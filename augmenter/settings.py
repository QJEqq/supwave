"""Настройки, которые меняются из веб-морды (без правки .env и пересборки): кому
положен openflux (сквады Remnawave), имя openflux-ссылки в подписке, клиенты
(метки User-Agent), которым её дописывать, и носители каналов (по умолчанию и свои
у отдельного канала). Лежат в той же SQLite, что и склад (/data/links.db). Пока в
морде не заданы — берутся из .env.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading

_DB = os.getenv("STORE_PATH", "/data/links.db")
_lock = threading.Lock()
_conn = sqlite3.connect(_DB, check_same_thread=False)
_conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
# свои носители отдельного канала (поверх носителей по умолчанию)
_conn.execute("CREATE TABLE IF NOT EXISTS channel_carriers (short_uuid TEXT PRIMARY KEY, carriers TEXT NOT NULL)")
_conn.commit()
_cache: dict = {}  # пишет только этот процесс — кэш не протухает

# Значения из .env — пока в морде ничего не сохранено.
ENV_SQUADS = [s.strip() for s in os.getenv("TARGET_SQUADS", "").split(",") if s.strip()]
ENV_LINK_NAME = os.getenv("OPENFLUX_LINK_NAME", "").strip()
# Метки клиентов: openflux дописывается, только если User-Agent содержит одну из них.
# По умолчанию — Avaca: её User-Agent «Avaca/… (Android …) AVACA-Pod».
ENV_UA = [m.strip() for m in os.getenv("POD_UA_MARKER", "AVACA-Pod").split(",") if m.strip()]

# Носители, которые канал может везти (direct — отдельно, OPENFLUX_DIRECT). Доска и
# волга — на аккаунте Яндекса из пула; комнаты cups.online и Авито — анонимные,
# аккаунт им не нужен. Порядок здесь — порядок показа и записи.
CARRIERS = ("boards", "vyandex", "cupsonline", "avito")


def clean_carriers(raw) -> list[str]:
    """Известные носители из raw — в порядке CARRIERS, без повторов."""
    got = set(raw or [])
    return [c for c in CARRIERS if c in got]


# Носители новых каналов, пока в морде не выбраны: OPENFLUX_CARRIERS (по умолчанию —
# доска + волга, как было до cups и Авито).
ENV_CARRIERS = clean_carriers(c.strip() for c in os.getenv("OPENFLUX_CARRIERS", "boards,vyandex").split(",")) \
    or ["boards", "vyandex"]


def _get(key: str):
    if key not in _cache:
        with _lock:
            row = _conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        _cache[key] = json.loads(row[0]) if row else None
    return _cache[key]


def _put(key: str, value) -> None:
    with _lock:
        _conn.execute("INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (key, json.dumps(value, ensure_ascii=False)))
        _conn.commit()
    _cache[key] = value


def squads() -> dict:
    """Кому openflux: {"mode": "all"} — всем активным юзерам; {"mode": "squads",
    "squads": [uuid или имя, …]} — юзерам хотя бы одного из сквадов (пустой список —
    никому). "names" — имена для показа, "from" — откуда: panel (морда) или env."""
    v = _get("squads")
    if isinstance(v, dict) and v.get("mode") in ("all", "squads"):
        return {"mode": v["mode"], "squads": list(v.get("squads") or []), "names": list(v.get("names") or []), "from": "panel"}
    if ENV_SQUADS == ["*"]:  # явно «всем активным»
        return {"mode": "all", "squads": [], "names": [], "from": "env"}
    # Пусто — никому: свежая установка не заводит каналы всем юзерам панели разом
    # (масса досок и доков — и Яндекс прижмёт аккаунт), пока сквады не выбраны.
    return {"mode": "squads", "squads": ENV_SQUADS, "names": ENV_SQUADS, "from": "env"}


def set_squads(mode: str, uuids: list[str], names: list[str]) -> None:
    _put("squads", {"mode": mode, "squads": uuids if mode == "squads" else [], "names": names if mode == "squads" else []})


def link_name() -> str:
    """Имя openflux-ссылки в подписке ({node} — имя ноды канала). "" — как завёл
    провиженер (имя канала)."""
    v = _get("link_name")
    return v if isinstance(v, str) else ENV_LINK_NAME


def set_link_name(name: str) -> None:
    _put("link_name", name)


def ua_markers() -> list[str]:
    v = _get("ua_markers")
    return list(v) if isinstance(v, list) else ENV_UA


def set_ua_markers(markers: list[str]) -> None:
    _put("ua_markers", markers)


def carriers() -> dict:
    """Носители канала по умолчанию: {"carriers": [...], "from": panel | env}."""
    v = _get("carriers")
    if isinstance(v, list):
        return {"carriers": clean_carriers(v), "from": "panel"}
    return {"carriers": list(ENV_CARRIERS), "from": "env"}


def set_carriers(carriers_: list[str]) -> None:
    _put("carriers", clean_carriers(carriers_))


def channel_carriers(short_uuid: str) -> list[str] | None:
    """Свои носители канала; None — канал берёт носители по умолчанию."""
    with _lock:
        row = _conn.execute("SELECT carriers FROM channel_carriers WHERE short_uuid=?", (short_uuid,)).fetchone()
    return clean_carriers(json.loads(row[0])) if row else None


def set_channel_carriers(short_uuid: str, carriers_: list[str] | None) -> None:
    """Задать каналу свои носители; None — вернуть ему носители по умолчанию."""
    with _lock:
        if carriers_ is None:
            _conn.execute("DELETE FROM channel_carriers WHERE short_uuid=?", (short_uuid,))
        else:
            _conn.execute("INSERT INTO channel_carriers(short_uuid, carriers) VALUES(?,?) "
                          "ON CONFLICT(short_uuid) DO UPDATE SET carriers=excluded.carriers",
                          (short_uuid, json.dumps(clean_carriers(carriers_))))
        _conn.commit()


def channel_overrides() -> dict[str, list[str]]:
    """{shortUuid: носители} — каналы со своими носителями."""
    with _lock:
        rows = _conn.execute("SELECT short_uuid, carriers FROM channel_carriers").fetchall()
    return {su: clean_carriers(json.loads(v)) for su, v in rows}


def carriers_for(short_uuid: str) -> list[str]:
    """Что заводить каналу: свои носители, иначе — по умолчанию."""
    own = channel_carriers(short_uuid)
    return own if own is not None else carriers()["carriers"]
