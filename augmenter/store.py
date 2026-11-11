"""Склад shortUuid → openflux-ссылка (SQLite).

Пишет провиженер (через reconcile), читает аугментер (по shortUuid из пути
подписки). Нет записи для юзера → аугментер отдаёт ЧИСТЫЙ vless, т.е. «нет
доступа к обходу» (не тот сквад / не проведён). Это и есть squad-гейтинг:
доступ = наличие строки в складе.
"""
from __future__ import annotations

import os
import sqlite3
import threading

_DB = os.getenv("STORE_PATH", "/data/links.db")
_lock = threading.Lock()

_conn = sqlite3.connect(_DB, check_same_thread=False)
_conn.execute("CREATE TABLE IF NOT EXISTS links (short_uuid TEXT PRIMARY KEY, link TEXT NOT NULL)")
_conn.commit()


def get(short_uuid: str) -> str | None:
    with _lock:
        row = _conn.execute("SELECT link FROM links WHERE short_uuid=?", (short_uuid,)).fetchone()
    return row[0] if row else None


def put(short_uuid: str, link: str) -> None:
    with _lock:
        _conn.execute(
            "INSERT INTO links(short_uuid, link) VALUES(?,?) "
            "ON CONFLICT(short_uuid) DO UPDATE SET link=excluded.link",
            (short_uuid, link),
        )
        _conn.commit()


def delete(short_uuid: str) -> None:
    with _lock:
        _conn.execute("DELETE FROM links WHERE short_uuid=?", (short_uuid,))
        _conn.commit()


def keys() -> set[str]:
    with _lock:
        rows = _conn.execute("SELECT short_uuid FROM links").fetchall()
    return {r[0] for r in rows}
