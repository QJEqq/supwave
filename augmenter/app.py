"""AVACA openflux companion.

- GET /{shortUuid} — проксирует подписку Remnawave и, если юзер ПРОВЕДЁН (есть
  запись в складе), дописывает ЕГО персональную openflux://-строку. Нет записи →
  чистый vless (не тот сквад / не проведён). Это и есть squad-гейтинг.
- фон: reconcile — склад = eligible-юзеры (по целевому скваду), см. reconcile.py.

Зеро-вмешательство: Caddy шлёт сюда ВСЕ запросы на subs, а UA различаем ЗДЕСЬ —
openflux дописываем ТОЛЬКО если UA содержит одну из меток клиентов (settings.ua_markers:
AVACA-Pod, Rawline… — правятся в морде). Голый Happ/браузер/боты получают тело апстрима
байт-в-байт. Гейт живёт в коде (в гите), а не в правке
Caddyfile — опечаткой в nano его не сломать, и openflux не утечёт чужим клиентам.

На время перехода, пока reconcile не наполнил склад, OPENFLUX_LINE работает как
общий фоллбэк (поведение MVP). Для строгого пер-юзер squad-гейтинга — очисти его.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import secrets
import time
import zlib
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request, Response

import accounts
import admin_ui
import journal
import nodeapi
import nodes
import provisioner
import reconcile
import remnawave
import settings
import store

journal.install()  # хвост наших строк журнала — для веб-морды (/admin/log)

UPSTREAM = os.getenv("SUB_UPSTREAM", "http://remnawave-subscription-page:3010").rstrip("/")
FALLBACK = os.getenv("OPENFLUX_LINE", "").strip()  # общий лег, пока склад пуст (MVP)
# UA нашего Pod — только ему дописываем openflux (та же метка, что матчил Caddy-форк).
# Токен админ-эндпоинтов (заливка операторских кук в пул). ПУСТО = эндпоинты
# выключены (никакой открытой заливки кук). Требуем Authorization: Bearer <TOKEN>.
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()
# Префикс админки — и API, и веб-морды (страница на {ADMIN_PREFIX}/). На домене панели
# его отдаёт Caddy (handle /augmenter* → augmenter:8080), поэтому свой префикс, чтобы не
# пересекаться с путями самой Remnawave.
ADMIN_PREFIX = "/" + (os.getenv("ADMIN_PREFIX", "/admin").strip().strip("/") or "admin")
# Домены, на которых админка вообще отвечает (через запятую), например
# panel.example.com. Пусто — на любом. Задано — на прочих (subs) её «нет» (404).
# Запросы на сам аугментер (curl 127.0.0.1:8080 с панели) пускаются всегда.
ADMIN_HOSTS = {h.strip().lower() for h in os.getenv("ADMIN_HOSTS", "").split(",") if h.strip()}
_LOOPBACK = {"127.0.0.1", "localhost", "[::1]"}

# заголовки ОТВЕТА, которые не отдаём как есть (длину/кодировку пересчитает сервер).
_DROP = {"content-length", "content-encoding", "transfer-encoding", "connection", "content-type"}
# заголовки ЗАПРОСА наверх: UA решает формат в Remnawave, x-forwarded-* — для IP-логов.
_FWD = ("user-agent", "accept", "x-forwarded-for", "x-real-ip", "x-forwarded-proto", "x-forwarded-host")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(reconcile.loop())  # сверка в фоне (no-op при RECONCILE_MODE=off)
    yield
    task.cancel()


# Без /docs, /redoc и /openapi.json: домен подписки публичный, а схема API выдавала
# бы и название, и все админ-ручки.
app = FastAPI(title="AVACA openflux companion", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "provisioned": len(store.keys())}


# ── админ: пул операторских аккаунтов (Ф5) ──────────────────────────────────
# Объявлено ДО catch-all /{path:path} — иначе GET /admin/* уйдёт в него.
def _host_ok(request: Request) -> bool:
    if not ADMIN_HOSTS:
        return True
    host = (request.headers.get("host") or "").strip().lower()
    host = host[: host.find("]") + 1] if host.startswith("[") else host.split(":", 1)[0]
    return host in ADMIN_HOSTS or host in _LOOPBACK


def _admin_ok(request: Request) -> bool:
    if not ADMIN_TOKEN or not _host_ok(request):
        return False  # выключены (нет ADMIN_TOKEN) или чужой домен (ADMIN_HOSTS)
    auth = request.headers.get("authorization", "")
    tok = auth[7:] if auth[:7].lower() == "bearer " else ""
    return bool(tok) and secrets.compare_digest(tok, ADMIN_TOKEN)


def _netscape_to_jar(text: str) -> dict:
    """Netscape cookies.txt → {name: value} — ТОЛЬКО куки yandex.ru.

    Экспорт бывает полным (все сайты браузера, тысячи кук). Без фильтра в пул
    уехали бы сессии чужих сайтов (а нода слала бы их Яндексу), и одноимённые
    куки склеились бы как попало: Session_id есть и у .ya.ru, и у .yandex.cloud,
    с другими значениями. Поэтому: только домен yandex.ru и его поддомены,
    просроченные — мимо, при совпадении имён доменная .yandex.ru важнее
    поддоменной. Терпим к #HttpOnly_-строкам.
    """
    now = time.time()
    jar: dict = {}
    wide: set = set()  # имена, уже взятые с самого .yandex.ru
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        elif not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7 or not parts[5]:
            continue
        domain, expires, name, value = parts[0].lower(), parts[4], parts[5], parts[6]
        is_wide = domain.lstrip(".") == "yandex.ru"
        if not (is_wide or domain.endswith(".yandex.ru")):
            continue
        if expires.isdigit() and 0 < int(expires) < now:
            continue
        if name in wide and not is_wide:
            continue
        jar[name] = value
        if is_wide:
            wide.add(name)
    return jar


@app.get(ADMIN_PREFIX + "/accounts")
async def admin_list(request: Request):
    if not _admin_ok(request):
        return Response(status_code=404)
    return {
        "stats": accounts.stats(),
        "accounts": [
            {"id": a.id, "label": a.label, "active_docs": a.active_docs,
             "created_docs": a.created_docs, "healthy": a.healthy, "last_used": a.last_used}
            for a in accounts.all()
        ],
    }


@app.post(ADMIN_PREFIX + "/accounts")
async def admin_add(request: Request, label: str = ""):
    """Залить операторский аккаунт в пул. Тело запроса = Netscape cookies.txt
    (живой вход в Яндекс; годится и полный экспорт браузера — берём только
    yandex.ru), label — метка в query (по умолчанию = yandex_login). Куки кладём
    как base64 cookie-store {"_":{name:value}} — формат, который читают и ядро
    (cookiesUnion), и провиженер (_rekey_cookies)."""
    if not _admin_ok(request):
        return Response(status_code=404)
    raw = (await request.body()).decode("utf-8", "ignore")
    jar = _netscape_to_jar(raw)
    if "Session_id" not in jar:
        raise HTTPException(status_code=400, detail="в куках yandex.ru нет живого Session_id (не залогиненная/просроченная сессия Яндекса)")
    label = label or jar.get("yandex_login", "")
    cookies_b64 = base64.b64encode(json.dumps({"_": jar}).encode()).decode()
    acc_id = accounts.add(cookies_b64, label)
    print(f"[admin] + аккаунт #{acc_id} «{label}» в пул: кук yandex.ru {len(jar)}", flush=True)
    return {"ok": True, "id": acc_id, "label": label, "cookies": len(jar),
            "sessionid2": "sessionid2" in jar}


@app.delete(ADMIN_PREFIX + "/accounts/{acc_id}")
async def admin_delete(acc_id: int, request: Request):
    if not _admin_ok(request):
        return Response(status_code=404)
    accounts.remove(acc_id)
    print(f"[admin] - аккаунт #{acc_id} убран из пула", flush=True)
    return {"ok": True, "id": acc_id}


@app.post(ADMIN_PREFIX + "/accounts/{acc_id}/healthy")
async def admin_healthy(acc_id: int, request: Request):
    """Вернуть аккаунт в ротацию после того, как его прижали (капча/бан)."""
    if not _admin_ok(request):
        return Response(status_code=404)
    accounts.mark_healthy(acc_id)
    print(f"[admin] аккаунт #{acc_id} снова в ротации", flush=True)
    return {"ok": True, "id": acc_id}


# ── админ: ноды-агенты (ofnode в Docker, как remnanode) ───────────────────────
@app.post(ADMIN_PREFIX + "/nodes")
async def admin_node_add(request: Request, address: str = "", name: str = "", port: int = 2223):
    """Завести ноду → compose для неё (SECRET_KEY внутри). На ноде
    `docker compose up -d`, дальше аугментер сам ходит к ней по HTTPS."""
    if not _admin_ok(request):
        return Response(status_code=404)
    try:
        node = nodes.create(name, address, port)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    print(f"[admin] + нода {node.name} ({node.address}:{node.port}) — выдан compose", flush=True)
    return {"ok": True, "id": node.id, "name": node.name, "address": node.address,
            "port": node.port, "compose": nodes.compose(node)}


@app.get(ADMIN_PREFIX + "/nodes")
async def admin_node_list(request: Request):
    """Ноды со статусом: отвечает ли агент, версия, ядро, сколько каналов."""
    if not _admin_ok(request):
        return Response(status_code=404)
    load = nodes.load()
    all_nodes = nodes.all()
    core = await asyncio.to_thread(provisioner.core_sha)  # на нодах должно быть оно (заливает reconcile)

    async def state(n):
        try:
            h = await nodeapi.health(n, timeout=4)
            return {"connected": True, "agent": h.get("agent"), "core": (h.get("core") or "")[:12],
                    "core_from": h.get("core_from", "image"), "core_current": h.get("core") == core,
                    "channels_on_node": h.get("channels")}
        except nodeapi.NodeError as error:
            return {"connected": False, "error": str(error)}

    states = await asyncio.gather(*(state(n) for n in all_nodes))
    return {"nodes": [{"id": n.id, "name": n.name, "address": n.address, "port": n.port, "created": n.created,
                       "channels": load.get(n.id, 0), "status": _node_status(st, n.created), **st}
                      for n, st in zip(all_nodes, states)]}


@app.get(ADMIN_PREFIX + "/nodes/{node_id}/compose")
async def admin_node_compose(node_id: int, request: Request):
    if not _admin_ok(request):
        return Response(status_code=404)
    node = nodes.get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="нет такой ноды")
    return Response(content=nodes.compose(node), media_type="text/yaml")


@app.delete(ADMIN_PREFIX + "/nodes/{node_id}")
async def admin_node_delete(node_id: int, request: Request):
    """Убрать ноду из аугментера (каналы на ней сначала снять: reset_channels)."""
    if not _admin_ok(request):
        return Response(status_code=404)
    busy = nodes.load().get(node_id, 0)
    if busy:
        raise HTTPException(status_code=409, detail=f"на ноде {busy} канал(ов) — сначала сними их")
    nodes.remove(node_id)
    print(f"[admin] - нода #{node_id} убрана из аугментера", flush=True)
    return {"ok": True, "id": node_id}


# ── админ: сводка, каналы, сверка, журнал (для веб-морды) ────────────────────
_REPROVISIONING: set[str] = set()  # каналы, которые пересоздаются прямо сейчас
_TASKS: set[asyncio.Task] = set()  # держим ссылки, чтобы фоновые задачи не собрал GC


def _spawn(coro, what: str) -> None:
    async def run():
        try:
            await coro
        except Exception as error:  # noqa: BLE001 — фон не должен падать молча
            print(f"[admin] {what}: {error}", flush=True)
    task = asyncio.create_task(run())
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


NODE_FRESH = 15 * 60  # нода, заведённая так недавно, ещё «поднимается», а не offline


def _node_status(st: dict, created: int) -> str:
    """online — агент отвечает и ядро на нём наше; processing — поднимается (ядро
    ещё обновится на сверке, или ноду только завели и compose пока не запущен);
    offline — не отвечает."""
    if st.get("connected"):
        return "online" if st.get("core_current") else "processing"
    return "processing" if time.time() - created < NODE_FRESH else "offline"


def _channel_status(state, busy: bool, stats) -> str:
    """online — ядро канала работает и хоть один носитель поднят; processing —
    поднимается (пересоздаётся, перезапускается, носители ещё заходят);
    offline — канала нет на ноде, он остановлен или нода не отвечает."""
    if busy:
        return "processing"
    if state == "restarting":
        return "processing"
    if state != "running":
        return "offline"
    carriers = (stats or {}).get("carriers") or []
    if carriers and not any(c.get("up") for c in carriers):
        return "processing"
    return "online"


@app.get(ADMIN_PREFIX + "/summary")
async def admin_summary(request: Request):
    """Режимы и счётчики — шапка веб-морды."""
    if not _admin_ok(request):
        return Response(status_code=404)
    try:
        prios = provisioner._priorities()
        if not provisioner.DIRECT:
            prios.pop("direct", None)
    except RuntimeError as error:
        prios = {"error": str(error)}
    return {
        "reconcile": {"mode": reconcile.MODE, "interval": reconcile.INTERVAL, **reconcile.STATE},
        "provision_mode": "stub" if provisioner.STUB else "real",
        "node_mode": provisioner.NODE_MODE, "direct": provisioner.DIRECT, "priorities": prios,
        "node_image": nodes.NODE_IMAGE, "panel_ip": nodes.PANEL_IP,
        "squads": settings.squads(), "link_name": settings.link_name(), "ua_markers": settings.ua_markers(),
        "pool": accounts.stats(), "pool_max_docs": accounts.MAX_DOCS_PER_ACCOUNT,
        "nodes": len(nodes.all()), "channels": len(store.keys()),
        "core": (await asyncio.to_thread(provisioner.core_sha))[:12],
    }


@app.get(ADMIN_PREFIX + "/channels")
async def admin_channels(request: Request):
    """Каналы юзеров: где живут (нода, аккаунт пула) и что с ядром канала на ноде."""
    if not _admin_ok(request):
        return Response(status_code=404)
    node_by_id = {n.id: n for n in nodes.all()}
    acc_by_id = {a.id: a for a in accounts.all()}

    async def on_node(n):
        try:
            return n.id, {c["channel"]: c for c in await nodeapi.channels(n, timeout=5)}
        except nodeapi.NodeError:
            return n.id, None  # нода не ответила: состояние неизвестно

    live = dict(await asyncio.gather(*(on_node(n) for n in node_by_id.values())))
    rows = []
    # пересоздаваемый на миг пропадает из склада — показываем его всё равно (busy)
    for su in sorted(store.keys() | _REPROVISIONING):
        ch = provisioner._channel(su)
        nid, aid = nodes.bound(su), accounts.bound_acc(su)
        node, acc = node_by_id.get(nid), acc_by_id.get(aid)
        st, state = None, None
        if node is not None:
            if live.get(nid) is None:
                state = "unknown"
            else:
                st = live[nid].get(ch)
                state = st["state"] if st else "missing"
        rows.append({
            "short_uuid": su, "channel": ch,
            "node_id": nid, "node": node.name if node else None,
            "account_id": aid, "account": (acc.label or f"#{acc.id}") if acc else None,
            "state": state, "restarts": (st or {}).get("restarts", 0), "last_exit": (st or {}).get("last_exit"),
            "busy": su in _REPROVISIONING,
            "status": _channel_status(state, su in _REPROVISIONING, (st or {}).get("stats")),
            # агент ≥ 0.3.0: снимок ядра канала (носители, трафик, клиент), вход
            # оператора на документах, CPU/память ядра, когда оно запущено
            "stats": (st or {}).get("stats"), "signin": (st or {}).get("signin") or [],
            "cpu": (st or {}).get("cpu"), "rss": (st or {}).get("rss"), "since": (st or {}).get("since"),
        })
    return {"channels": rows}


@app.get(ADMIN_PREFIX + "/channels/{short_uuid}/log")
async def admin_channel_log(short_uuid: str, request: Request):
    """Последние строки ядра канала (с агента ноды, ≥ 0.3.0)."""
    if not _admin_ok(request):
        return Response(status_code=404)
    node = nodes.get(nodes.bound(short_uuid) or 0)
    if node is None:
        raise HTTPException(status_code=404, detail="канал не на ноде-агенте")
    try:
        return {"lines": await nodeapi.channel_log(node, provisioner._channel(short_uuid))}
    except nodeapi.NodeError as error:
        if error.code in (404, 405) and "такого канала" not in str(error):
            raise HTTPException(status_code=409, detail="агент ноды старый — обнови образ ноды (docker compose pull)")
        raise HTTPException(status_code=502, detail=str(error))


@app.get(ADMIN_PREFIX + "/channels/{short_uuid}/link")
async def admin_channel_link(short_uuid: str, request: Request):
    if not _admin_ok(request):
        return Response(status_code=404)
    link = store.get(short_uuid)
    if not link:
        raise HTTPException(status_code=404, detail="нет такого канала")
    return {"link": link}


async def _reprovision(su: str) -> None:
    try:
        async with reconcile.LOCK:
            print(f"[admin] {su}: пересоздаю канал", flush=True)
            await provisioner.deprovision(su)
            store.delete(su)
            link = await provisioner.provision(su)
            store.put(su, link)
            print(f"[admin] {su}: канал пересоздан", flush=True)
    finally:
        _REPROVISIONING.discard(su)


@app.post(ADMIN_PREFIX + "/channels/{short_uuid}/reprovision")
async def admin_channel_reprovision(short_uuid: str, request: Request):
    """Снять канал и завести заново (новые доска/док, новый ключ — ссылка у юзера
    обновится со следующей подпиской). Не вышло — следующая сверка заведёт сама."""
    if not _admin_ok(request):
        return Response(status_code=404)
    if short_uuid not in store.keys():
        raise HTTPException(status_code=404, detail="нет такого канала")
    if short_uuid not in _REPROVISIONING:
        _REPROVISIONING.add(short_uuid)
        _spawn(_reprovision(short_uuid), f"{short_uuid}: не пересоздался")
    return {"ok": True, "busy": reconcile.LOCK.locked()}


@app.post(ADMIN_PREFIX + "/reconcile")
async def admin_reconcile(request: Request):
    """Сверить сейчас, не дожидаясь RECONCILE_INTERVAL."""
    if not _admin_ok(request):
        return Response(status_code=404)
    if reconcile.MODE == "off":
        raise HTTPException(status_code=409, detail="сверка выключена (RECONCILE_MODE=off)")
    if reconcile.LOCK.locked():
        return {"ok": True, "busy": True}
    _spawn(reconcile.reconcile_once(), "сверка")
    return {"ok": True, "started": True}


@app.get(ADMIN_PREFIX + "/settings")
async def admin_settings(request: Request):
    """Настройки из морды (поверх .env): кому openflux, имя ссылки, клиенты."""
    if not _admin_ok(request):
        return Response(status_code=404)
    return {"squads": settings.squads(), "link_name": settings.link_name(), "ua_markers": settings.ua_markers(),
            "env": {"squads": settings.ENV_SQUADS, "link_name": settings.ENV_LINK_NAME, "ua_markers": settings.ENV_UA}}


_PRINTABLE = re.compile(r"[^\x00-\x1f\x7f]+")


def _text(v, what: str, lo: int, hi: int) -> str:
    s = str(v if v is not None else "").strip()
    if not (lo <= len(s) <= hi) or (s and not _PRINTABLE.fullmatch(s)):
        raise HTTPException(status_code=400, detail=f"{what}: от {lo} до {hi} символов, без управляющих")
    return s


@app.put(ADMIN_PREFIX + "/settings")
async def admin_settings_put(request: Request):
    """Сохранить, что пришло: squads {mode: all|squads, squads: [uuid], names: [имя]},
    link_name (шаблон, {node} — имя ноды), ua_markers [метка]."""
    if not _admin_ok(request):
        return Response(status_code=404)
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="тело — JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="тело — JSON-объект")
    done = []
    if "squads" in body:
        sq = body["squads"] if isinstance(body["squads"], dict) else {}
        mode = sq.get("mode")
        if mode not in ("all", "squads"):
            raise HTTPException(status_code=400, detail="squads.mode: all или squads")
        uuids = [_text(u, "сквад", 1, 100) for u in (sq.get("squads") or [])][:100]
        names = [_text(n, "имя сквада", 1, 100) for n in (sq.get("names") or [])][:100]
        settings.set_squads(mode, uuids, names)
        done.append("openflux — всем активным" if mode == "all" else "openflux — сквадам: " + (", ".join(names or uuids) or "никому"))
    if "link_name" in body:
        name = _text(body["link_name"], "имя ссылки", 0, 64)
        settings.set_link_name(name)
        done.append(f"имя ссылки «{name or 'как завёл провиженер'}»")
    if "ua_markers" in body:
        raw = body["ua_markers"] if isinstance(body["ua_markers"], list) else []
        markers = list(dict.fromkeys(_text(m, "метка клиента", 2, 64) for m in raw))[:20]
        settings.set_ua_markers(markers)
        done.append("клиенты: " + (", ".join(markers) or "никто"))
    if done:
        print("[admin] настройки: " + "; ".join(done), flush=True)
    return await admin_settings(request)


@app.get(ADMIN_PREFIX + "/squads")
async def admin_squads(request: Request):
    """Сквады из Remnawave — выбирать в морде, кому openflux."""
    if not _admin_ok(request):
        return Response(status_code=404)
    try:
        return {"squads": await remnawave.squads(), "selected": settings.squads()}
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail=f"Remnawave не отдал список: {error}")


@app.get(ADMIN_PREFIX + "/log")
async def admin_log(request: Request, n: int = 300):
    if not _admin_ok(request):
        return Response(status_code=404)
    return {"lines": [{"t": t, "line": line} for t, line in journal.tail(max(1, min(n, 500)))]}


# ── веб-морда: одна страница; данные она берёт из {ADMIN_PREFIX}/* по токену ──────
# Страница без данных и без токена внутри: токен вводится на ней и живёт только в
# браузере. Адрес — {ADMIN_PREFIX}/, API рядом под тем же префиксом (страница сама
# берёт его из своего адреса). Нет ADMIN_TOKEN — нет и её; чужой домен — 404.
_UI_PATH = ADMIN_PREFIX + "/"
_UI_HEADERS = {
    "Content-Security-Policy": ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                                "connect-src 'self'; img-src data:; base-uri 'none'; form-action 'none'; "
                                "frame-ancestors 'none'"),
    "Referrer-Policy": "no-referrer", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
}

if ADMIN_TOKEN:
    @app.get(_UI_PATH, include_in_schema=False)
    async def admin_ui_page(request: Request):
        if not _host_ok(request):
            return Response(status_code=404)
        return Response(content=admin_ui.PAGE, media_type="text/html; charset=utf-8", headers=_UI_HEADERS)

    @app.get(ADMIN_PREFIX, include_in_schema=False)
    async def admin_ui_redirect(request: Request):
        if not _host_ok(request):
            return Response(status_code=404)
        return Response(status_code=307, headers={"Location": _UI_PATH})


@app.get("/{path:path}")
async def serve(path: str, request: Request):
    short_uuid = path.split("/", 1)[0]
    # Боты постоянно долбят /.git/config, /wp-login.php, /favicon.ico и т.п. —
    # настоящий путь подписки это shortUuid (base64url). Что на него не похоже —
    # сразу 404: не ходим к апстриму и не плодим 500+трейсбек в логах.
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", short_uuid):
        return Response(status_code=404)
    # UA-гейт ЗДЕСЬ, а не в Caddy: openflux дописываем только Pod'у, прочим —
    # тело апстрима как есть (зеро-вмешательство для чужих клиентов).
    ua = request.headers.get("user-agent", "")
    is_pod = any(m in ua for m in settings.ua_markers())

    headers = {h: request.headers[h] for h in _FWD if h in request.headers}
    headers["accept-encoding"] = "identity"  # без gzip — чтобы не разжимать тело
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            up = await client.get(
                f"{UPSTREAM}/{path}",
                params=dict(request.query_params),
                headers=headers,
                follow_redirects=True,
            )
    except httpx.TransportError:
        # апстрим (sub-page) оборвал соединение / не ответил — чистый 502 без трейсбека
        return Response(content=b"upstream unavailable", status_code=502)

    body = up.content
    if is_pod and up.status_code == 200:
        link = store.get(short_uuid) or FALLBACK  # пер-юзер из склада, иначе общий (MVP)
        link = _named(link, short_uuid) if link else link
        if link:
            body = _inject(body, link)

    out = {k: v for k, v in up.headers.items() if k.lower() not in _DROP}
    return Response(content=body, status_code=up.status_code, headers=out,
                    media_type=up.headers.get("content-type"))


_LINK_PREFIX = "openflux://v1/"


def _rename_link(link: str, name: str) -> str:
    """Имя профиля в openflux-ссылке. Ссылка — openflux://v1/ + base64url(raw
    DEFLATE(JSON конфига)), имя — поле "name" внутри; остальное (ключ, носители,
    контекст) не трогаем. Не разобралось — отдаём как было."""
    if not name or not link.startswith(_LINK_PREFIX):
        return link
    body = link[len(_LINK_PREFIX):]
    try:
        cfg = json.loads(zlib.decompress(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)), -15))
    except (ValueError, zlib.error):
        return link
    if not isinstance(cfg, dict) or cfg.get("name") == name:
        return link
    cfg["name"] = name
    z = zlib.compressobj(9, zlib.DEFLATED, -15)
    packed = z.compress(json.dumps(cfg, ensure_ascii=False, separators=(",", ":")).encode()) + z.flush()
    return _LINK_PREFIX + base64.urlsafe_b64encode(packed).decode().rstrip("=")


def _named(link: str, short_uuid: str) -> str:
    """Имя из настроек ({node} — имя ноды канала) — сразу у всех, без пересоздания каналов."""
    tmpl = settings.link_name()
    if not tmpl:
        return link
    node = nodes.get(nodes.bound(short_uuid) or 0)
    return _rename_link(link, tmpl.replace("{node}", node.name if node else "").strip())


def _inject(body: bytes, line: str) -> bytes:
    """Дописать openflux-строку. Remnawave для клиентских UA отдаёт base64(список
    ссылок). Другой формат / не наш — отдаём как есть, ничего не ломаем."""
    text = body.decode("utf-8", "ignore").strip()
    if "://" in text:
        return (text + "\n" + line).encode()
    try:
        decoded = base64.b64decode(text).decode("utf-8", "ignore")
    except Exception:
        return body
    if "://" not in decoded:
        return body
    decoded = decoded.rstrip("\n") + "\n" + line + "\n"
    return base64.b64encode(decoded.encode()).decode().encode()
