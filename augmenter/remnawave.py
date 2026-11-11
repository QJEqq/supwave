"""Клиент к Remnawave API: кто eligible под обход (по выбранным сквадам).

В вебхуке Remnawave activeInternalSquads «для производительности» часто пуст, так
что истину берём из API. Список юзеров уже несёт shortUuid + activeInternalSquads
+ status + expireAt (проверено на панели: {response:{total,users:[...]}}).
Авторизация — Bearer-токен из Settings → API Tokens.

Кому положен openflux — settings.squads(): выбранные в веб-морде сквады (юзер
хотя бы в одном из них) или «всем активным»; пока в морде не задано — TARGET_SQUADS
из .env (имя ИЛИ uuid через запятую; * — всем активным; пусто — никому).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx

import settings

API_URL = os.getenv("REMNAWAVE_API_URL", "http://remnawave:3000").rstrip("/")
API_TOKEN = os.getenv("REMNAWAVE_API_TOKEN", "")
PAGE = 500


def _headers() -> dict:
    return {"Authorization": f"Bearer {API_TOKEN}"}


def _active(user: dict) -> bool:
    if user.get("status") != "ACTIVE":
        return False
    raw = user.get("expireAt")
    if not raw:
        return True
    end = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return end > datetime.now(timezone.utc)


def _in_target(user: dict) -> bool:
    cfg = settings.squads()
    if cfg["mode"] == "all":
        return True
    want = set(cfg["squads"])
    squads = user.get("activeInternalSquads") or []
    have = {s.get("name") for s in squads} | {s.get("uuid") for s in squads}
    return bool(want & have)  # хотя бы в одном из выбранных (пустой выбор — никому)


def eligible(user: dict) -> bool:
    return _active(user) and _in_target(user)


async def _all_users() -> list[dict]:
    users: list[dict] = []
    start = 0
    async with httpx.AsyncClient(timeout=20) as client:
        while True:
            r = await client.get(f"{API_URL}/api/users", params={"size": PAGE, "start": start}, headers=_headers())
            r.raise_for_status()
            body = r.json()["response"]
            page = body.get("users") or []
            users += page
            total = int(body.get("total", len(page)))
            start += PAGE
            if start >= total or not page:
                return users


async def eligible_short_uuids() -> tuple[set[str], int]:
    """shortUuid всех юзеров, которым положен обход (бэкбон reconcile), и сколько
    юзеров панель вернула всего — reconcile отличает «никто не положен» (все
    истекли — снимать) от «панель не вернула никого» (сбой — не трогать)."""
    users = await _all_users()
    return {u["shortUuid"] for u in users if u.get("shortUuid") and eligible(u)}, len(users)


async def squads() -> list[dict]:
    """Сквады панели для выбора в морде: [{uuid, name, members}]. Из
    /api/internal-squads; если этого эндпоинта нет (другая версия Remnawave) —
    собираем из того, в каких сквадах состоят юзеры (members — сколько их там)."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{API_URL}/api/internal-squads", headers=_headers())
            r.raise_for_status()
            body = r.json().get("response")
        items = body.get("internalSquads") if isinstance(body, dict) else None
        if isinstance(items, list):
            out = [{"uuid": s["uuid"], "name": s.get("name") or s["uuid"], "members": (s.get("info") or {}).get("membersCount")}
                   for s in items if isinstance(s, dict) and s.get("uuid")]
            return sorted(out, key=lambda s: str(s["name"]).lower())
    except (httpx.HTTPError, ValueError, AttributeError, KeyError):
        pass
    found: dict[str, dict] = {}
    for u in await _all_users():
        for s in u.get("activeInternalSquads") or []:
            if s.get("uuid"):
                f = found.setdefault(s["uuid"], {"uuid": s["uuid"], "name": s.get("name") or s["uuid"], "members": 0})
                f["members"] += 1
    return sorted(found.values(), key=lambda s: str(s["name"]).lower())
