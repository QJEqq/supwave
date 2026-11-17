"""Создание/удаление канала OpenFlux под пользователя на ноде.

Провижн гоним через штатный deploy/node-install.sh по SSH (он ставит бинарь,
пишет node.conf + systemd openflux-node@<channel>, direct всегда как бэкап на
авто-порту; идемпотентно, с откатом). Ссылку собираем Go-CLI `oflink` через
provision.ShareLinkContext — она ГАРАНТИРОВАННО совпадает с node.conf по
приоритетам и encryption-context (иначе хендшейк падает).

  stub — имитация (без ноды, для разработки).
  real — SSH на ноду (root): upload node-install.sh → apply → oflink → ссылка.

Канал на ноде = u<sha1(shortUuid)[:16]> (node-install.sh требует имя
^[a-z0-9][a-z0-9-]{0,30}$ в нижнем регистре; base62-shortUuid туда не лезет).

"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
from asyncio.subprocess import PIPE

import accounts
import nodeapi
import nodes
import settings

STUB = os.getenv("PROVISION_MODE", "stub") == "stub"

# Ноды "user@host[:port]" через запятую. Фоллбэк на одиночную OPENFLUX_NODE.
_raw_nodes = os.getenv("OPENFLUX_NODES") or os.getenv("OPENFLUX_NODE", "")
NODES = [n.strip() for n in _raw_nodes.split(",") if n.strip()]
SSH_KEY = os.path.expanduser(os.getenv("SSH_KEY", "/keys/openflux"))
SSH_PORT = os.getenv("SSH_PORT", "22")

# бинарь oflink и node-install.sh лежат рядом в контейнере (см. Dockerfile).
OFLINK = os.getenv("OFLINK_PATH", "/app/oflink")
NODE_INSTALL = os.getenv("NODE_INSTALL_PATH", "/app/node-install.sh")
NODE_INSTALL_REMOTE = "/opt/openflux-node-install.sh"
# Ядро (openflux) кладём на ноду сами — ровно тот бинарь, что лежит в контейнере.
# Релиза node-v1.6.0 на GitHub нет, поэтому apply обязан принять НАШ файл без
# скачивания: install_core сверяет ядро с пином SHA_<arch> из node-install.sh и при
# расхождении идёт на GitHub → curl 404. Пин в файле руками больше НЕ правим: при
# каждой заливке провиженер сам вписывает в копию скрипта SHA реального бинаря
# (_pinned_installer). Пересобрал ядро → положил в контейнер → всё.
CORE_LOCAL = os.getenv("CORE_PATH", "/app/openflux-node-v1.6.0")
CORE_BIN_DIR = "/opt/openflux-node/bin"
# Визард создаёт доску/док через сеть (внутри у него свой таймаут на метод) — даём
# чуть больше и режем сами, чтобы провижн не завис навсегда.
WIZARD_TIMEOUT = int(os.getenv("WIZARD_TIMEOUT", "150"))
# Режим экзита на ноде. l3 — нативный стек ядра: быстрее и не теряет пакеты, как
# gVisor (node-install даёт каналу CAP_NET_RAW и, пока канал жив, режет iptables'ом
# исходящие RST ядра с адреса ноды — это касается всего адреса). l4 — gVisor в
# userspace: без всякой инфры, но медленнее.
NODE_MODE = os.getenv("OPENFLUX_NODE_MODE", "l3")

# Приоритеты носителей канала. Сессия шлёт весь трафик через ЖИВОЙ носитель с
# наивысшим приоритетом (скорость не учитывается), так что порядок решает, кто
# везёт: direct, пока доходит → доска → cups.online → Авито → волга. По замерам
# (2026-11-17): доска ~80 КБ/с, cups ~70 КБ/с (лимит cups.online — на адрес ноды,
# общий для её каналов), Авито ~24 КБ/с, волга 4–6 КБ/с. Одни и те же числа уходят
# И в node.conf экзита (priority_<тип>= в копии node-install.sh / агенту), И в
# ссылку клиента (oflink --priorities) — стороны совпадают.
PRIORITY_TYPES = ("direct", "boards", "cupsonline", "avito", "vyandex")  # что понимает копия node-install.sh
DEFAULT_PRIORITIES = {"direct": 100, "boards": 70, "cupsonline": 60, "avito": 55, "vyandex": 50}

# direct = прямой TCP на порт ноды. По умолчанию ВЫКЛЮЧЕН: на каждый канал — свой
# открытый нестандартный порт, а много таких портов сразу выдают ноду ТСПУ. Без
# direct нода ничего не слушает (только сама ходит к Яндексу), канал едет по доске и
# волге, а клиент не стучится на порт ноды. Такой канал умеет только нода-агент
# (ofnode): node-install.sh по SSH всегда открывает порт.
DIRECT = os.getenv("OPENFLUX_DIRECT", "off").strip().lower() in ("on", "1", "yes", "true")


def _priorities() -> dict:
    """DEFAULT_PRIORITIES поверх — OPENFLUX_PRIORITIES → {тип: число}. Тип, которого
    нет в env, берёт число отсюда (иначе ядро и oflink подставили бы свои умолчания,
    где Авито выше доски). Читаем при каждом провижне: кривое значение роняет только
    провижн (с внятной ошибкой), а не раздачу подписки."""
    raw = os.getenv("OPENFLUX_PRIORITIES", "")
    out = dict(DEFAULT_PRIORITIES)
    for part in raw.replace(" ", "").split(","):
        if not part:
            continue
        typ, _, num = part.partition(":")
        if typ not in PRIORITY_TYPES or not num.isdigit() or int(num) > 999:
            raise RuntimeError(f"OPENFLUX_PRIORITIES: {part!r} — нужно тип:число (0-999), типы {PRIORITY_TYPES}")
        out[typ] = int(num)
    return out


def _file_sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


_core_sha: tuple = (None, "")


def core_sha() -> str:
    """SHA ядра аугментера (CORE_PATH); пересчёт, только когда файл поменялся
    (веб-морда спрашивает его часто, а файл — 30 МБ). "" — ядра нет."""
    global _core_sha
    try:
        st = os.stat(CORE_LOCAL)
    except OSError:
        return ""
    key = (CORE_LOCAL, st.st_mtime_ns, st.st_size)
    if _core_sha[0] != key:
        _core_sha = (key, _file_sha(CORE_LOCAL))
    return _core_sha[1]


# Remnawave shortUuid = base64url (A-Za-z0-9 и _ -). В SSH-команды он НЕ попадает
# (имя канала = sha1-хэш), так что это просто sanity-гейт.
_SHORT = re.compile(r"[A-Za-z0-9_-]{1,32}")


def _channel(short_uuid: str) -> str:
    return "u" + hashlib.sha1(short_uuid.encode()).hexdigest()[:16]


# Канал = выбранные в морде носители (settings.carriers_for): boards + volga
# (vyandex) на аккаунте пула, комнаты cups.online и Авито (анонимно), + direct.
# Доску и док провиженер создаёт пер-юзер на аккаунтах пула; env ниже — фоллбэк,
# когда пул пуст (одна общая доска/док на все каналы). Читаем ЛЕНИВО (не при
# импорте): контейнер мог стартовать раньше, чем проставили env.
def _doc_transports() -> list:
    """Общие доска/volga-док из env: OPENFLUX_BOARDS_DOC / OPENFLUX_VOLGA_DOC."""
    out = []
    board = os.getenv("OPENFLUX_BOARDS_DOC", "").strip()
    if board:
        out.append({"type": "boards", "url": board})
    volga = _volga_url(os.getenv("OPENFLUX_VOLGA_DOC", "").strip())
    if volga:
        out.append({"type": "vyandex", "url": volga})
    return out


def _yandex_cookies() -> str:
    """base64 от cookie-store JSON ядра (вход в Яндекс). Пусто = без кук."""
    return os.getenv("OPENFLUX_YANDEX_COOKIES", "").strip()


async def provision(short_uuid: str) -> str:
    """Завести канал под shortUuid → openflux://-ссылка."""
    if not _SHORT.fullmatch(short_uuid):
        raise ValueError(f"плохой shortUuid: {short_uuid!r}")
    if STUB:
        await asyncio.sleep(2)
        return f"openflux://v1/DEMO-{short_uuid}"
    return await _provision_real(short_uuid)


async def deprovision(short_uuid: str) -> None:
    # Вернём ёмкость операторскому аккаунту канала (если он был из пула). Сами
    # доки на Диске оператора пока остаются — авто-чистку (mpfs delete) добавим
    # отдельно; release не зависит от доступности ноды.
    aid = accounts.bound_acc(short_uuid)
    if aid is not None:
        accounts.release(aid)
        accounts.unbind(short_uuid)
    if STUB:
        return
    channel = _channel(short_uuid)
    nid = nodes.bound(short_uuid)
    if nid is not None:  # канал живёт на ноде-агенте (ofnode)
        node = nodes.get(nid)
        if node is not None:  # ноду уже убрали из аугментера — снимать негде
            await nodeapi.remove(node, channel)
        nodes.unbind(short_uuid)
        return
    if NODES:  # старый путь: канал заведён по SSH через node-install.sh
        await _ssh(NODES[0], f"sh {NODE_INSTALL_REMOTE} remove {channel}")


# ---------------------------------------------------------------------------
# SSH: разбор "user@host[:port]" и выполнение команды (опц. со stdin) на ноде.
# ---------------------------------------------------------------------------
def _split(node: str) -> tuple[str, str]:
    if ":" in node.rsplit("@", 1)[-1]:
        target, port = node.rsplit(":", 1)
        return target, port
    return node, SSH_PORT


async def _ssh(node: str, command: str, stdin: bytes = b"") -> str:
    target, port = _split(node)
    args = [
        "ssh", "-i", SSH_KEY, "-p", port,
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=15",
        target, command,
    ]
    proc = await asyncio.create_subprocess_exec(*args, stdin=PIPE, stdout=PIPE, stderr=PIPE)
    out, err = await proc.communicate(stdin)
    if proc.returncode != 0:
        # node-install.sh пишет причину JSON-строкой в stdout ({"ok":false,"step",
        # "error"}), а в stderr — сырой вывод curl/systemctl. Показываем оба, иначе
        # видно только "curl: (22) … 404" без шага, на котором упало.
        last = (out.decode(errors="replace").strip().splitlines() or [""])[-1]
        detail = " | ".join(s for s in (err.decode(errors="replace").strip(), last) if s)
        raise RuntimeError(f"нода {node}: {detail}")
    return out.decode()


# ---------------------------------------------------------------------------
# Провижн: upload node-install.sh → apply (конфиг через stdin во временный
# файл) → читаем порт из JSON → oflink собирает ссылку.
# ---------------------------------------------------------------------------
# Архитектуры — те же имена, что у detect_arch в node-install.sh (по ним он
# выбирает пин SHA_<arch>). Ядро в контейнере собрано под одну арху: сверяем с
# нодой, а не льём amd64 на arm (юнит упал бы с exec format error).
_UNAME_ARCH = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64",
               "armv7l": "arm", "armv6l": "arm", "armhf": "arm"}
_ELF_ARCH = {62: "amd64", 183: "arm64", 40: "arm"}  # поле e_machine ELF-заголовка


def _core_arch(path: str) -> str:
    """Арха linux-бинаря ядра по его ELF-заголовку ("" — не ELF / неизвестная)."""
    with open(path, "rb") as f:
        head = f.read(20)
    if head[:4] != b"\x7fELF":
        return ""
    return _ELF_ARCH.get(int.from_bytes(head[18:20], "little"), "")


def _pinned_installer(core_sha: str, arch: str) -> tuple[bytes, str]:
    """node-install.sh с пином SHA_<arch> = SHA нашего ядра + куда класть ядро.

    Путь берём из CORE_VERSION самого скрипта (install_core ищет
    $BIN_DIR/openflux-$CORE_VERSION) — имя файла и версия не разъедутся.
    """
    with open(NODE_INSTALL, "rb") as f:
        script = f.read()
    m = re.search(rb'^CORE_VERSION="(node-v[0-9.]+)"$', script, re.M)
    if not m:
        raise RuntimeError(f"{NODE_INSTALL}: нет строки CORE_VERSION=")
    script, n = re.subn(rb'^SHA_' + arch.encode() + rb'="[0-9a-f]{64}"$',
                        f'SHA_{arch}="{core_sha}"'.encode(), script, count=1, flags=re.M)
    if n != 1:
        raise RuntimeError(f"{NODE_INSTALL}: нет строки SHA_{arch}=")
    return script, f"{CORE_BIN_DIR}/openflux-{m.group(1).decode()}"


async def _upload_installer(node: str) -> None:
    # SHA/арху ядра считаем ЗДЕСЬ, а не при импорте: контейнер мог стартовать
    # раньше, чем бинарь положили рядом (был баг: пустой SHA → upload пропускался).
    want = _file_sha(CORE_LOCAL)
    arch = _core_arch(CORE_LOCAL)
    node_arch = _UNAME_ARCH.get((await _ssh(node, "uname -m")).strip(), "")
    if not arch or arch != node_arch:
        raise RuntimeError(f"ядро {CORE_LOCAL} собрано под {arch or '?'}, а нода {node_arch or '?'}: пересобери с GOARCH ноды")
    # скрипт льём КАЖДЫЙ раз — уже с пином под текущий бинарь
    script, core_remote = _pinned_installer(want, arch)
    await _ssh(node, f"umask 077; cat > {NODE_INSTALL_REMOTE} && chmod 0755 {NODE_INSTALL_REMOTE}", script)
    # ядро — только если на ноде его ещё нет с нужной SHA (не 30МБ каждый раз)
    have = await _ssh(node, f'[ -x {core_remote} ] && sha256sum {core_remote} 2>/dev/null | cut -d" " -f1 || true')
    if have.strip() == want:
        return
    with open(CORE_LOCAL, "rb") as f:
        core = f.read()
    # Во временный файл + mv: перезапись файла, из которого запущены каналы, может
    # упасть с "Text file busy" (а mv их не трогает — дорабатывают на старом), и
    # обрыв SSH посреди заливки не оставит полфайла под именем ядра.
    await _ssh(node, f'mkdir -p {CORE_BIN_DIR} && t=$(mktemp {CORE_BIN_DIR}/.upload.XXXXXX) && '
                     f'{{ cat > "$t" && chmod 0755 "$t" && mv -f "$t" {core_remote}; }} || {{ rm -f "$t"; exit 1; }}', core)
    # убеждаемся, что ядро реально легло с нужной SHA (иначе apply пойдёт на GitHub)
    check = await _ssh(node, f'sha256sum {core_remote} 2>/dev/null | cut -d" " -f1 || true')
    if check.strip() != want:
        raise RuntimeError(f"ядро не загрузилось на ноду: sha {check.strip()!r} != {want!r}")


async def _plan_port(node: str, channel: str) -> int:
    # plan — read-only, конфиг со stdin, сам выбирает свободный порт для direct.
    # С mode=l3 он же проверяет, что нода тянет l3 (iptables, ip, systemd ≥ 231).
    cfg = f"channel={channel}\nmode={NODE_MODE}\n".encode()
    out = await _ssh(node, f"sh {NODE_INSTALL_REMOTE} plan", cfg)
    data = json.loads(out.strip().splitlines()[-1])
    if not data.get("ok"):
        raise RuntimeError(f"plan: {data.get('error')}")
    return int(data["port"])


async def _apply(node: str, channel: str, key: str, port: int, transports: list | None = None, cookies: str = "",
                 prios: dict | None = None) -> None:
    # apply — конфиг из файла (ключ + порт из плана); ставит ядро, node.conf, юнит.
    # Транспорты — отдельными строками: boards=<URL доски>, vyandex=<URL дока>.
    # direct не пишем — node-install.sh добавляет его бэкапом на порт из плана сам.
    # cookies= (base64 cookie-store) — вход в Яндекс для volga-экзита (node-install
    # отвергает его без vyandex-документа).
    cfg = f"channel={channel}\nkey={key}\nmode={NODE_MODE}\nport={port}\n"
    for t in transports or []:
        cfg += f"{t['type']}={t['url']}\n"
    if cookies:
        cfg += f"cookies={cookies}\n"
    for typ, n in (prios or {}).items():
        cfg += f"priority_{typ}={n}\n"
    out = await _ssh(node, f'umask 077; f=$(mktemp); cat > "$f"; sh {NODE_INSTALL_REMOTE} apply "$f"', cfg.encode())
    data = json.loads(out.strip().splitlines()[-1])
    if not data.get("ok"):
        raise RuntimeError(f"apply: {data.get('error')}")


def _volga_url(url: str) -> str:
    """URL volga-дока → https://docs.yandex.ru/edit/d/<id>?source=docs.

    ?source=docs ОБЯЗАТЕЛЕН: без него docs.yandex.ru открывает /edit/d/<id> в старом
    редакторе, на его странице нет officeActionData, и vyandex падает «action_url
    missing» (рабочий экзит из заметки «OpenFlux - Volga transport» — с ним).
    Остальной хвост адресной строки (&sk=…, #…) режем. Эту же форму сохраняет oflink
    (provision.CheckTransports) и принимает node-install.sh (valid_url) — node.conf,
    ссылка и ключ кук экзита (cookieKey = URL дока как есть) совпадают байт в байт.
    """
    if not url:
        return ""
    for sep in ("?", "#"):
        url = url.split(sep, 1)[0]
    return url.rstrip("/") + "?source=docs"


# Упакованный список комнат cups.online / Авито — как valid_rooms в node-install.sh.
_ROOMS_OK = re.compile(r"[A-Za-z0-9_-]{8,4096}")

# Те же регэкспы, что valid_boards / valid_url в node-install.sh.
_DOC_OK = {
    "boards": re.compile(r"https://boards\.yandex\.ru/whiteboard/\?hash=[0-9a-f]{32}"),
    "vyandex": re.compile(r"https://(docs|disk)\.yandex\.(ru|com|by|kz|uz)/edit/d/[A-Za-z0-9_-]{16,200}(\?source=docs)?"),
}


def _doc_ok(ttype: str, url: str) -> bool:
    """Доску/док берём в канал, только если node-install.sh примет URL.

    Кривой URL роняет apply ЦЕЛИКОМ (канал не встаёт даже на direct), а reconcile
    повторяет заход и каждый раз создаёт на аккаунте новую доску + док. Поэтому
    такой транспорт просто пропускаем (best-effort) и пишем в лог.
    """
    if not url:
        return False
    if _DOC_OK[ttype].fullmatch(url):
        return True
    print(f"[provision] {ttype}: node-install не примет URL — канал без него: {url}", flush=True)
    return False


def _rekey_cookies(store_b64: str, url: str) -> str:
    """Переложить операторские куки из складского блоба под КЛЮЧ созданного дока.

    Склад хранит куки аккаунта как base64 cookie-store ({любой_ключ:{name:value}}).
    Ядро на ноде ищет куки vyandex-экзита по URL дока, поэтому в node.conf cookies=
    кладём {doc_url:{name:value}}. Объединяем все jar'ы блоба в один (куки Яндекса
    доменные — одинаковы) и перекладываем под url.
    """
    raw = json.loads(base64.b64decode(store_b64))
    jar: dict = {}
    for d in raw.values():
        if isinstance(d, dict):
            jar.update(d)
    return base64.b64encode(json.dumps({url: jar}).encode()).decode()


async def _make_doc(method: str, cookies: str, name: str = "") -> str:
    """Создать boards-доску / volga-док на ОПЕРАТОРСКОМ аккаунте через core
    --node-wizard и вернуть её URL ("" на ошибке — best-effort, канал без неё).

    method: "createBoard" | "createVolgaDoc". cookies — base64 cookie-store ядра
    (вход оператора), уходит в визард ТОЛЬКО через stdin (не в argv/лог). Что
    создалось и почему не вышло — пишем в лог, иначе причину не поймать.
    """
    params: dict = {"cookies": cookies}
    if name:
        params["name"] = name
    return await _wizard(method, params, "url")


# Пар комнат Авито на канал (полос: tx + rx). Авито пускает 10 WebSocket-рукопожатий
# в минуту на адрес, и все каналы ноды делят этот лимит: 4 пары = 8 сокетов на
# конец — подъём за ~1 мин, а не за 2,5 (8 пар по умолчанию ядра).
def _avito_pairs() -> int:
    raw = os.getenv("OPENFLUX_AVITO_ROOMS", "").strip()
    return max(1, min(8, int(raw))) if raw.isdigit() else 4


AVITO_PAIRS = _avito_pairs()


async def _make_rooms(typ: str) -> str:
    """Комнаты cups.online / Авито под канал — анонимно, визардом ядра; ответ —
    упакованный список комнат (URL носителя в node.conf и ссылке). "" на ошибке."""
    if typ == "avito":
        return await _wizard("createAvitoRooms", {}, "rooms", {"AVITO_ROOMS": str(AVITO_PAIRS)})
    return await _wizard("createRooms", {}, "rooms")


async def _wizard(method: str, params: dict, field: str, env: dict | None = None) -> str:
    """Один запрос к core --node-wizard → значение поля field ответа ("" на ошибке).
    Секреты (куки) — только в params, через stdin."""
    req = (json.dumps({"id": 1, "method": method, "params": params}) + "\n").encode()
    proc = await asyncio.create_subprocess_exec(
        CORE_LOCAL, "--node-wizard", stdin=PIPE, stdout=PIPE, stderr=PIPE,
        env={**os.environ, **env} if env else None,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(req), timeout=WIZARD_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        print(f"[provision] {method}: визард не ответил за {WIZARD_TIMEOUT}с", flush=True)
        return ""
    # ответ — одна JSON-строка {"ok":…,"url"|"error":…}; идём с конца, чтобы не
    # споткнуться о возможную лог-строку перед ней.
    for raw in reversed(out.decode(errors="replace").splitlines()):
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        if data.get("ok") and data.get(field):
            got = data[field]
            # список комнат длинный (до 4 КБ) — в лог хватит начала
            print(f"[provision] {method}: {got if field == 'url' else got[:16] + f'… ({len(got)} симв.)'}", flush=True)
            return got
        print(f"[provision] {method}: не вышло — {data.get('error') or raw.strip()}", flush=True)
        return ""
    # ни одной JSON-строки: визард упал / не тот бинарь — покажем хвост stderr
    tail = " | ".join(err.decode(errors="replace").strip().splitlines()[-3:]) or "—"
    print(f"[provision] {method}: визард не ответил JSON (код {proc.returncode}); stderr: {tail}", flush=True)
    return ""


async def _make_link(name: str, key: str, host: str, port: int, transports: list | None = None,
                     prios: dict | None = None, no_direct: bool = False) -> str:
    args = [
        OFLINK, "--name", name, "--key", key,
        "--host", host, "--port", str(port),
        "--transports", json.dumps(transports or []),
    ]
    if prios:
        args += ["--priorities", ",".join(f"{t}:{n}" for t, n in prios.items())]
    if no_direct:
        args.append("--no-direct")  # в ссылке нет direct: клиент не стучится на порт ноды
    proc = await asyncio.create_subprocess_exec(*args, stdout=PIPE, stderr=PIPE)
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"oflink: {(err or out).decode().strip()}")
    return out.decode().strip()


async def _plan_fresh(node: str, channel: str) -> int:
    """plan → порт для direct; канал с тем же именем уже есть на ноде → снять и заново.

    Сюда попадаем, только когда ссылки в складе нет, значит такой канал на ноде —
    дрейф («склад почистили, а канал остался»): его ссылку никто не держит. plan сам
    отказывает на нём («уже существует»), поэтому ловим это здесь, а не на apply.
    """
    try:
        return await _plan_port(node, channel)
    except RuntimeError as error:
        if "уже существует" not in str(error):
            raise
    await _ssh(node, f"sh {NODE_INSTALL_REMOTE} remove {channel}")
    return await _plan_port(node, channel)


async def _pick_agent():
    """Нода-агент (ofnode) для нового канала: наименее загруженная из отвечающих.
    None — агентов не заведено, тогда старый путь по SSH (OPENFLUX_NODES)."""
    agents = nodes.all()
    if not agents:
        return None
    load = nodes.load()
    errors = []
    for n in sorted(agents, key=lambda n: (load.get(n.id, 0), n.id)):
        try:
            await nodeapi.health(n)
            return n
        except nodeapi.NodeError as error:
            errors.append(str(error))
    raise RuntimeError("ни одна нода-агент не отвечает: " + "; ".join(errors))


async def sync_cores(dry: bool = False) -> None:
    """Ядро на нодах-агентах = ядро аугментера (CORE_PATH). Агент отдаёт SHA своего
    в /health; разошлось — заливаем наше (PUT /core), агент перезапускает каналы на
    нём. Обновить ядро = обновить аугментер: на ноде ничего делать не надо. Зовёт
    reconcile — на старте и каждые RECONCILE_INTERVAL."""
    agents = nodes.all()
    if not agents or not os.path.exists(CORE_LOCAL):
        return
    want, arch = core_sha(), _core_arch(CORE_LOCAL)
    for n in agents:
        try:
            h = await nodeapi.health(n)
        except nodeapi.NodeError as error:
            print(f"[nodes] {error}", flush=True)
            continue
        have = h.get("core") or ""
        if have == want:
            continue
        if h.get("arch") != arch:
            print(f"[nodes] {n.name}: ядро аугментера под {arch or '?'}, а нода {h.get('arch') or '?'} — не заливаю", flush=True)
            continue
        if dry:
            print(f"[nodes] DRYRUN: залил бы на {n.name} ядро {want[:12]} (там {have[:12]})", flush=True)
            continue
        try:
            r = await nodeapi.push_core(n, CORE_LOCAL, want)
            print(f"[nodes] {n.name}: ядро {have[:12]} → {want[:12]}, каналов перезапущено: {r.get('restarted', 0)}", flush=True)
        except nodeapi.NodeError as error:
            if error.code in (404, 405):
                print(f"[nodes] {n.name}: агент {h.get('agent')} не умеет принимать ядро — обнови образ ноды", flush=True)
            else:
                print(f"[nodes] {n.name}: ядро {want[:12]} не залито: {error}", flush=True)


async def _provision_real(short_uuid: str) -> str:
    channel = _channel(short_uuid)
    key = secrets.token_hex(32)
    prios = _priorities()  # кривой OPENFLUX_PRIORITIES — падаем сразу, ничего не создав
    want = settings.carriers_for(short_uuid)  # носители из морды: свои у канала или по умолчанию

    # 1) Нода — ДО того, как создавать доску и док на аккаунте оператора (reconcile
    #    повторяет заход каждые RECONCILE_INTERVAL, и каждый провал на ноде оставлял
    #    бы на аккаунте осиротевшие доску + док). Нода-агент: выбрали ту, что
    #    отвечает. Старый путь (SSH): скрипт + ядро, затем пробный plan — он же
    #    проверяет, что нода тянет режим (l3), и снимает дрейфовый канал.
    agent = await _pick_agent()
    if agent is not None:
        host = agent.address
        where = f"нода-агент {agent.name}"
    else:
        if not DIRECT:
            raise RuntimeError("direct выключен (OPENFLUX_DIRECT=off), а старый путь по SSH всегда открывает "
                               "порт на ноде — добавь ноду-агент (POST /admin/nodes)")
        if not NODES:
            raise RuntimeError("нет ни одной ноды: добавь ноду-агент (POST /admin/nodes) или задай OPENFLUX_NODES")
        node = NODES[0]  # старый путь: одна нода по SSH
        host = node.rsplit("@", 1)[-1].split(":")[0]
        where = f"нода {node} (SSH)"
        await _upload_installer(node)
        await _plan_fresh(node, channel)

    # 2) Носители канала — что выбрано в морде (want); direct добавят агент /
    #    node-install.sh и oflink сами. Доску и док создаём на самом ненагруженном
    #    healthy-аккаунте пула (создание требует вход; аккаунт берём, только если
    #    выбран носитель Яндекса). Пул пуст → общие доска/док из env. Комнаты
    #    cups.online и Авито — анонимно, визардом ядра. Best-effort: что не
    #    создалось — в канал не идёт.
    transports: list = []
    cookies = ""
    acc = None
    if "boards" in want or "vyandex" in want:
        acc = accounts.pick()
        if acc is None:
            print("[provision] пул аккаунтов пуст (или все на потолке / нездоровы) — доску и волгу не создаю, беру env", flush=True)
        else:
            if "boards" in want:
                board_url = await _make_doc("createBoard", acc.cookies)
                if _doc_ok("boards", board_url):
                    transports.append({"type": "boards", "url": board_url})
            if "vyandex" in want:
                volga_url = _volga_url(await _make_doc("createVolgaDoc", acc.cookies))
                if _doc_ok("vyandex", volga_url):
                    transports.append({"type": "vyandex", "url": volga_url})
                    # куки нужны только volga-экзиту (входит по URL дока); boards — гостем
                    cookies = _rekey_cookies(acc.cookies, volga_url)
            if transports:
                accounts.bind(short_uuid, acc.id)
            else:
                accounts.release(acc.id)  # ничего не создалось — вернём ёмкость
                acc = None
        if acc is None:
            for t in _doc_transports():
                if t["type"] not in want or not _doc_ok(t["type"], t["url"]):
                    continue
                transports.append(t)
                if t["type"] == "vyandex" and _yandex_cookies():
                    try:
                        cookies = _rekey_cookies(_yandex_cookies(), t["url"])
                    except ValueError:
                        print("[provision] OPENFLUX_YANDEX_COOKIES — не base64 cookie-store, volga без входа", flush=True)
    for typ in ("cupsonline", "avito"):
        if typ in want:
            rooms = await _make_rooms(typ)
            if _ROOMS_OK.fullmatch(rooms):
                transports.append({"type": typ, "url": rooms})
            elif rooms:
                print(f"[provision] {typ}: визард вернул не список комнат — канал без него", flush=True)
    if not DIRECT and not transports:
        # без direct такой канал никуда не ведёт: ни один носитель не создался
        raise RuntimeError(f"без direct каналу нужен хоть один носитель, а не создался ни один из выбранных "
                           f"({', '.join(want) or 'ничего не выбрано'}; причина — в строках [provision] выше)")
    present = {t["type"] for t in transports} | ({"direct"} if DIRECT else set())
    prios = {t: n for t, n in prios.items() if t in present}  # в node.conf и ссылку — только свои
    mix = "+".join([t["type"] for t in transports] + (["direct"] if DIRECT else []))
    order = ",".join(f"{t}:{n}" for t, n in sorted(prios.items(), key=lambda kv: -kv[1]))
    print(f"[provision] {short_uuid}: канал {channel} = {mix}, режим {NODE_MODE}, приоритеты {order}, {where}", flush=True)

    try:
        if agent is not None:
            # агент пишет тот же node.conf, что node-install.sh, и сам берёт порт
            port = await nodeapi.apply(agent, {
                "channel": channel, "key": key, "mode": NODE_MODE,
                "transports": transports, "cookies": cookies, "priorities": prios,
                "no_direct": not DIRECT,
            })
            nodes.bind(short_uuid, agent.id)
        else:
            port = await _plan_fresh(node, channel)
            await _apply(node, channel, key, port, transports, cookies, prios)
        # те же транспорты и приоритеты → ссылка совпадёт с node.conf
        return await _make_link(channel, key, host, port, transports, prios, no_direct=not DIRECT)
    except Exception:
        # упали после резерва аккаунта — вернём ёмкость (reconcile повторит заход)
        if acc is not None:
            accounts.release(acc.id)
            accounts.unbind(short_uuid)
        raise
