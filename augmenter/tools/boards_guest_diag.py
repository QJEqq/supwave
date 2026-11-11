"""Диагностика гостевого доступа к доске: что видит владелец, включение guest_mode
через update-dashboard-presentation, проверка анонимным гостем. Значения кук и
токенов не печатает. Запуск в контейнере аугментера (куки — из пула):
    docker exec -i augmenter python - <hash> < tools/boards_guest_diag.py
Без пула (только гостевая проверка): python3 boards_guest_diag.py <hash> --guest-only
"""
import base64
import http.cookiejar
import json
import secrets
import sys
import urllib.request

H = sys.argv[1]
GUEST_ONLY = "--guest-only" in sys.argv
UA = "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Mobile Safari/537.36"
BOARD = f"https://boards.yandex.ru/whiteboard/?hash={H}"


def api(action, content, cookie=None, opener=None, referer="https://boards.yandex.ru/cabinet/"):
    body = json.dumps({"action": action, "content": base64.b64encode(json.dumps(content).encode()).decode()}).encode()
    req = urllib.request.Request("https://boards.yandex.ru/api", data=body, method="POST", headers={
        "User-Agent": UA, "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01", "Origin": "https://boards.yandex.ru",
        "Referer": referer})
    if cookie:
        req.add_header("Cookie", cookie)
    with (opener or urllib.request.build_opener()).open(req, timeout=20) as r:
        return json.loads(r.read() or b"{}")


def guest_can_join():
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    op.open(urllib.request.Request(BOARD, headers={"User-Agent": UA}), timeout=20).read()
    ans = api("request-guest-token", {"name": "guest_" + secrets.token_hex(3), "hash": H},
              opener=op, referer=f"https://boards.yandex.ru/guest/?hash={H}")
    return any(c.name == "token_" + H for c in jar), ans


if not GUEST_ONLY:
    import accounts  # пул аугментера
    jar = {}
    for d in json.loads(base64.b64decode(accounts.all()[0].cookies)).values():
        jar.update(d)
    owner = "; ".join(f"{k}={v}" for k, v in jar.items())

    csrf = api("init-csrf", {}, owner).get("csrf")
    print("1) владелец: csrf получен:", bool(csrf))
    info = api("get-whiteboard-info", {"hash": H, "csrf": csrf}, owner, referer=BOARD)
    csrf = info.get("csrf") or csrf
    p = info.get("presentation") or {}
    print("2) владелец видит: access_type =", p.get("access_type"), "| status =", p.get("status"),
          "| guest-свойства =", {k: v for k, v in (p.get("properties") or {}).items() if k.startswith("guest")},
          "| error =", info.get("error"))
    ok, ans = guest_can_join()
    print("3) гость ДО:", "токен выдан" if ok else f"не пускает, ответ {ans}")
    upd = api("update-dashboard-presentation", {
        "media": H, "csrf": csrf,
        "properties": {"guest_mode": True, "guest_role": 1, "guest_password": None, "guest_password_expiration_date": None},
    }, owner)  # тот же Referer /cabinet/, что шлёт ядро (boardsCabinetRequest)
    print("4) update-dashboard-presentation(guest_mode) →", {k: v for k, v in upd.items() if k != "csrf"})

# guest_mode вступает в силу через несколько секунд после update — опрашиваем,
# а не судим по первому ответу (иначе ложный «не пускает»).
import time
for attempt in range(1 if GUEST_ONLY else 8):
    if attempt:
        time.sleep(2)
    ok, ans = guest_can_join()
    if ok:
        break
label = "гость:" if GUEST_ONLY else f"5) гость ПОСЛЕ (попытка {attempt + 1}):"
print(label, "ТОКЕН ВЫДАН — доска открыта" if ok else f"не пускает, ответ {ans}")
