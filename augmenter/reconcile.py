"""Сверка: склад = eligible-юзеры (по целевому скваду). Декларативно.

Бэкбон пер-юзера (вебхук — быстрый добор сверху, добавим позже). Заводит канал
недостающим eligible-юзерам, снимает у тех, кто больше не eligible (сквад убрали,
подписка истекла, юзера удалили). cups-провижн медленный (~150c), поэтому делаем
это заранее в фоне, а не в момент запроса подписки.

RECONCILE_MODE:  off (по умолчанию, безопасно) | dryrun (только печать) | on
"""
from __future__ import annotations

import asyncio
import os
import time

import provisioner
import remnawave
import store

MODE = os.getenv("RECONCILE_MODE", "off")
INTERVAL = int(os.getenv("RECONCILE_INTERVAL", "600"))  # секунд между проверками

# Одна сверка или перезаведение канала за раз: фоновый цикл, «Сверить сейчас» и
# «Пересоздать» из веб-морды не должны заводить один и тот же канал параллельно.
LOCK = asyncio.Lock()
# Что было на последней сверке — для веб-морды.
STATE: dict = {"running": False, "started": None, "finished": None, "error": None, "note": None,
               "added": 0, "removed": 0, "failed": 0}


async def reconcile_once() -> None:
    if MODE == "off":
        return
    async with LOCK:
        STATE.update(running=True, started=time.time(), error=None, note=None, added=0, removed=0, failed=0)
        try:
            await _reconcile()
        except Exception as error:
            STATE["error"] = str(error)
            raise
        finally:
            STATE.update(running=False, finished=time.time())


async def _reconcile() -> None:
    # Сначала ядро на нодах (новые каналы заведутся уже на нём). Сбой тут — не повод
    # пропускать сверку юзеров.
    try:
        await provisioner.sync_cores(dry=MODE == "dryrun")
    except Exception as error:  # noqa: BLE001
        print(f"[nodes] сверка ядра: {error}", flush=True)
    desired, seen = await remnawave.eligible_short_uuids()
    provisioned = store.keys()

    # Предохранитель: панель не вернула НИ ОДНОГО юзера, а склад не пуст — почти
    # всегда сбой API/токена/фильтра, не выпиливаем всё разом. Если юзеры есть, но
    # никто не положен (истёк последний, сквад сняли со всех) — снимаем как обычно:
    # раньше здесь проверялось «никто не положен», и канал последнего истёкшего
    # юзера не снимался никогда.
    if not seen and provisioned:
        STATE["note"] = "панель не вернула ни одного юзера — пропущено"
        print("[reconcile] панель не вернула ни одного юзера, а склад не пуст — пропускаю (похоже на сбой)", flush=True)
        return

    for su in desired - provisioned:
        if MODE == "dryrun":
            print(f"[reconcile] DRYRUN: завёл бы {su}", flush=True)
            continue
        try:
            link = await provisioner.provision(su)
            store.put(su, link)
            STATE["added"] += 1
            print(f"[reconcile] + {su}", flush=True)
        except Exception as error:  # noqa: BLE001 — один юзер не должен ронять круг
            STATE["failed"] += 1
            print(f"[reconcile] ошибка провижина {su}: {error}", flush=True)

    for su in provisioned - desired:
        if MODE == "dryrun":
            print(f"[reconcile] DRYRUN: снял бы {su}", flush=True)
            continue
        try:
            await provisioner.deprovision(su)
            store.delete(su)
            STATE["removed"] += 1
            print(f"[reconcile] - {su}", flush=True)
        except Exception as error:  # noqa: BLE001
            STATE["failed"] += 1
            print(f"[reconcile] ошибка снятия {su}: {error}", flush=True)


async def loop() -> None:
    while True:
        try:
            await reconcile_once()
        except Exception as error:  # noqa: BLE001 — крон не должен падать
            print(f"[reconcile] loop error: {error}", flush=True)
        await asyncio.sleep(INTERVAL)
