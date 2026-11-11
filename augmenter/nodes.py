"""Ноды-агенты (ofnode в Docker, как remnanode): адрес, порт API, токен и
закреплённый TLS-сертификат ноды. Та же SQLite, что у store.py/accounts.py.

Добавление: create() → `ofnode secret` (токен + сертификат/ключ ноды) → compose()
с SECRET_KEY внутри; на ноде `docker compose up -d` — и аугментер ходит к ней по
HTTPS (nodeapi.py) вместо SSH. Канал помнит, на какой ноде он живёт
(channel_nodes), чтобы снять его там же.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass

_DB = os.getenv("STORE_PATH", "/data/links.db")
OFNODE = os.getenv("OFNODE_PATH", "/app/ofnode")
NODE_IMAGE = os.getenv("OPENFLUX_NODE_IMAGE", "openflux-node:local")
NODE_PORT_RANGE = os.getenv("OPENFLUX_NODE_PORT_RANGE", "20000-29999")
# Публичный IP панели — подставляется в строку файрвола compose («открыть API только ему»).
PANEL_IP = os.getenv("PANEL_IP", "").strip()
# как в provisioner.py: без direct нода не открывает портов под каналы
DIRECT = os.getenv("OPENFLUX_DIRECT", "off").strip().lower() in ("on", "1", "yes", "true")

_lock = threading.Lock()
_conn = sqlite3.connect(_DB, check_same_thread=False)
_conn.execute(
    """
    CREATE TABLE IF NOT EXISTS nodes (
        id         INTEGER PRIMARY KEY,
        name       TEXT NOT NULL,
        address    TEXT NOT NULL,
        port       INTEGER NOT NULL,
        token      TEXT NOT NULL,
        cert       TEXT NOT NULL,
        secret_key TEXT NOT NULL,
        created    INTEGER NOT NULL
    )
    """
)
_conn.execute(
    "CREATE TABLE IF NOT EXISTS channel_nodes "
    "(short_uuid TEXT PRIMARY KEY, node_id INTEGER NOT NULL)"
)
_conn.commit()


@dataclass
class Node:
    id: int
    name: str
    address: str
    port: int
    token: str
    cert: str
    secret_key: str
    created: int


_COLS = "id, name, address, port, token, cert, secret_key, created"
# хост или IPv4 без схемы и порта — то, что уйдёт и в URL API, и в ссылку (direct)
_ADDR = re.compile(r"[A-Za-z0-9.-]{1,253}")


def create(name: str, address: str, port: int = 2223) -> Node:
    """Завести ноду: новый секрет от ofnode → запись в базе."""
    address = address.strip()
    if not _ADDR.fullmatch(address):
        raise ValueError("address: хост или IP ноды, без https:// и порта")
    if not 1 <= int(port) <= 65535:
        raise ValueError("port: 1-65535")
    out = subprocess.run([OFNODE, "secret"], capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise RuntimeError(f"ofnode secret: {out.stderr.strip() or out.returncode}")
    sec = json.loads(out.stdout)
    with _lock:
        cur = _conn.execute(
            "INSERT INTO nodes(name, address, port, token, cert, secret_key, created) VALUES(?,?,?,?,?,?,?)",
            ((name or address).strip(), address, int(port), sec["token"], sec["cert"], sec["secret_key"], int(time.time())),
        )
        _conn.commit()
        node_id = cur.lastrowid
    return get(node_id)


def _row(r) -> Node:
    return Node(*r)


def get(node_id: int) -> Node | None:
    with _lock:
        r = _conn.execute(f"SELECT {_COLS} FROM nodes WHERE id=?", (node_id,)).fetchone()
    return _row(r) if r else None


def all() -> list[Node]:  # noqa: A001 — как accounts.all()
    with _lock:
        rows = _conn.execute(f"SELECT {_COLS} FROM nodes ORDER BY id").fetchall()
    return [_row(r) for r in rows]


def remove(node_id: int) -> None:
    with _lock:
        _conn.execute("DELETE FROM nodes WHERE id=?", (node_id,))
        _conn.commit()


def bind(short_uuid: str, node_id: int) -> None:
    with _lock:
        _conn.execute(
            "INSERT INTO channel_nodes(short_uuid, node_id) VALUES(?,?) "
            "ON CONFLICT(short_uuid) DO UPDATE SET node_id=excluded.node_id",
            (short_uuid, node_id),
        )
        _conn.commit()


def bound(short_uuid: str) -> int | None:
    with _lock:
        r = _conn.execute("SELECT node_id FROM channel_nodes WHERE short_uuid=?", (short_uuid,)).fetchone()
    return r[0] if r else None


def unbind(short_uuid: str) -> None:
    with _lock:
        _conn.execute("DELETE FROM channel_nodes WHERE short_uuid=?", (short_uuid,))
        _conn.commit()


def load() -> dict[int, int]:
    """Сколько каналов на каждой ноде (по привязкам) — для выбора ноды."""
    with _lock:
        rows = _conn.execute("SELECT node_id, COUNT(*) FROM channel_nodes GROUP BY node_id").fetchall()
    return {nid: n for nid, n in rows}


def compose(node: Node) -> str:
    """docker-compose.yml для ноды: положить на ноду и `docker compose up -d`."""
    lo, _, hi = NODE_PORT_RANGE.partition("-")
    panel = PANEL_IP or "<IP панели>"
    if DIRECT:
        firewall = (f"# Файрвол ноды: API только с IP панели, порты direct — клиентам:\n"
                    f"#   ufw allow from {panel} to any port {node.port} proto tcp\n"
                    f"#   ufw allow {lo}:{hi}/tcp")
    else:
        firewall = (f"# Файрвол ноды: открыть ТОЛЬКО API и только для IP панели (direct выключен —\n"
                    f"# каналы ничего не слушают, нода сама ходит к Яндексу; других портов не открывать):\n"
                    f"#   ufw allow from {panel} to any port {node.port} proto tcp")
    if "/" in NODE_IMAGE:  # из реестра (Docker Hub: <логин>/<имя>)
        image_note = ("# Обновить агента (редко: ядро аугментер обновляет сам):\n"
                      "#   docker compose pull && docker compose up -d")
    else:
        image_note = (f"# ⚠ Образ {NODE_IMAGE} локальный — из реестра он не скачается: собрать на ноде\n"
                      f"# из node-kit (docker build -f Dockerfile.bin -t {NODE_IMAGE} .) или выложить\n"
                      f"# в Docker Hub (node-kit/publish.sh) и задать OPENFLUX_NODE_IMAGE аугментеру.")
    return f"""# OpenFlux-нода «{node.name}» для AVACA augmenter (ofnode, как remnanode).
# На ноде: сохрани как /opt/openflux-node/docker-compose.yml и запусти
#   docker compose up -d
{image_note}
{firewall}
# SECRET_KEY — ключ этой ноды: никому не показывать.
services:
  openflux-node:
    image: {NODE_IMAGE}
    container_name: openflux-node
    restart: always
    network_mode: host
    cap_add: [NET_RAW, NET_ADMIN]
    environment:
      NODE_PORT: "{node.port}"
      PORT_RANGE: "{NODE_PORT_RANGE}"
      SECRET_KEY: "{node.secret_key}"
    volumes:
      - openflux-node-data:/var/lib/openflux-node

volumes:
  openflux-node-data:
    name: openflux-node-data
"""
