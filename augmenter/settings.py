"""Настройки, которые меняются из веб-морды (без правки .env и пересборки): кому
положен openflux (сквады Remnawave), имя openflux-ссылки в подписке и клиенты
(метки User-Agent), которым её дописывать. Лежат в той же SQLite, что и склад
(/data/links.db). Пока в морде не заданы — берутся из .env.
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
_conn.commit()
_cache: dict = {}  # пишет только этот процесс — кэш не протухает

# Значения из .env — пока в морде ничего не сохранено.
ENV_SQUADS = [s.strip() for s in os.getenv("TARGET_SQUADS", "").split(",") if s.strip()]
ENV_LINK_NAME = os.getenv("OPENFLUX_LINK_NAME", "").strip()
# Метки клиентов: openflux дописывается, только если User-Agent содержит одну из них.
# По умолчанию — Avaca: её User-Agent «Avaca/… (Android …) AVACA-Pod».
ENV_UA = [m.strip() for m in os.getenv("POD_UA_MARKER", "AVACA-Pod").split(",") if m.strip()]


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
