"""Проверка аккаунтов пула: живой ли вход в Яндекс для досок. Для каждого аккаунта —
какие ключевые куки есть (только имена) и что отвечает boards.yandex.ru на init-csrf
(с него начинается создание доски). Ничего не создаёт, значений кук не печатает.
Запуск в контейнере аугментера (из папки репозитория на панели):
    docker exec -i augmenter python - < tools/pool_check.py

init-csrf «код 201» = Яндекс не видит в этих куках вход: сессия протухла или в выгрузке
нет кук домена .yandex.ru (вход был через ya.ru) — выгрузить заново (см. README, пул).
"""
import base64
import json
import urllib.request

import accounts

KEY = ("Session_id", "sessionid2", "L", "yandex_login", "yandexuid")


def init_csrf(jar: dict) -> str:
    body = json.dumps({"action": "init-csrf", "content": "e30="}).encode()
    req = urllib.request.Request("https://boards.yandex.ru/api", data=body, method="POST", headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36",
        "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Origin": "https://boards.yandex.ru", "Referer": "https://boards.yandex.ru/cabinet/",
        "Cookie": "; ".join(f"{k}={v}" for k, v in jar.items())})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            ans = json.loads(r.read() or b"{}")
    except Exception as e:  # noqa: BLE001 — диагностика: показать и идти дальше
        return f"не ответил: {e}"
    if ans.get("csrf"):
        return "ок, вход живой"
    err = ans.get("error") or {}
    if err.get("code") == 201:
        return "код 201 — вход не виден (протухла сессия или нет кук .yandex.ru)"
    return f"ошибка {err or ans}"


for a in accounts.all():
    jar: dict = {}
    try:
        for d in json.loads(base64.b64decode(a.cookies)).values():
            if isinstance(d, dict):
                jar.update(d)
    except ValueError:
        print(f"#{a.id} {a.label}: куки в базе не читаются")
        continue
    have = [k for k in KEY if k in jar]
    lack = [k for k in KEY if k not in jar]
    print(f"#{a.id} {a.label or '—'} ({'здоров' if a.healthy else 'нездоров'}, досок {a.active_docs}): "
          f"кук {len(jar)}, есть {', '.join(have) or '—'}" + (f", НЕТ {', '.join(lack)}" if lack else "")
          + f" → init-csrf: {init_csrf(jar)}")
