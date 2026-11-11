"""Пул операторских Яндекс-аккаунтов для авто-создания доков/досок (SQLite).

Идея: «1 мульти-транспорт-канал = 1 юзер», и под каждый канал надо создать
boards-доску и volga-док НА ОПЕРАТОРСКОМ аккаунте (создание требует вход). Один
аккаунт на сотни доков Яндекс прижмёт → держим ПУЛ залитых аккаунтов и
размазываем нагрузку: `pick()` отдаёт самый ненагруженный здоровый аккаунт и
резервирует его (active_docs += 1), `release()` возвращает при deprovision/ошибке,
`mark_unhealthy()` выводит из ротации прижатый (капча/бан).

Хранилище — та же SQLite, что у [store.py] (STORE_PATH, общий /data-том), но своя
таблица `accounts`. Оператор заливает куки (Ф5 admin-endpoint конвертит его
cookies.txt → base64 cookie-store ядра и кладёт сюда через `add()`); здесь —
только хранение и выбор, формат кук не трогаем.

cookies — base64 cookie-store JSON ядра ({docURL:{name:value}}), ровно то, что
принимают node.conf `cookies=` и `CreateBoard` в ядре.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import dataclass

_DB = os.getenv("STORE_PATH", "/data/links.db")
_lock = threading.Lock()

# Потолок живых доков на один аккаунт — чтобы не спалить его массовым созданием.
# 0 = без лимита.
MAX_DOCS_PER_ACCOUNT = int(os.getenv("POOL_MAX_DOCS_PER_ACCOUNT", "40"))

_conn = sqlite3.connect(_DB, check_same_thread=False)
_conn.execute(
    """
    CREATE TABLE IF NOT EXISTS accounts (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        label        TEXT,
        cookies      TEXT NOT NULL,
        active_docs  INTEGER NOT NULL DEFAULT 0,
        created_docs INTEGER NOT NULL DEFAULT 0,
        healthy      INTEGER NOT NULL DEFAULT 1,
        last_used    INTEGER NOT NULL DEFAULT 0
    )
    """
)
# Привязка канала к аккаунту, на котором созданы его boards/volga-доки — чтобы
# при deprovision вернуть аккаунту ёмкость (release). Отдельная таблица, чтобы не
# трогать store.py (links) и сигнатуры provision/deprovision.
_conn.execute(
    "CREATE TABLE IF NOT EXISTS channel_accounts "
    "(short_uuid TEXT PRIMARY KEY, acc_id INTEGER NOT NULL)"
)
_conn.commit()


@dataclass
class Account:
    id: int
    label: str
    cookies: str
    active_docs: int
    created_docs: int
    healthy: bool
    last_used: int


def _row(r) -> Account:
    return Account(
        id=r[0], label=r[1] or "", cookies=r[2],
        active_docs=r[3], created_docs=r[4], healthy=bool(r[5]), last_used=r[6],
    )


_COLS = "id, label, cookies, active_docs, created_docs, healthy, last_used"


def add(cookies: str, label: str = "") -> int:
    """Залить аккаунт в пул (cookies = base64 cookie-store). → id строки."""
    if not cookies:
        raise ValueError("пустые cookies")
    with _lock:
        cur = _conn.execute(
            "INSERT INTO accounts(label, cookies) VALUES(?,?)", (label, cookies)
        )
        _conn.commit()
        return int(cur.lastrowid)


def pick() -> Account | None:
    """Зарезервировать самый ненагруженный ЗДОРОВЫЙ аккаунт под новый канал.

    Выбор: healthy=1 и (лимит выключен или active_docs < лимита), сортировка по
    active_docs ASC, затем last_used ASC (честная ротация). Атомарно (под _lock)
    инкрементит active_docs/created_docs и ставит last_used=now, чтобы
    параллельные провижны не сели на один аккаунт. Нет свободных → None (провижн
    падёт на direct-бэкап / env-доки).
    """
    now = int(time.time())
    with _lock:
        if MAX_DOCS_PER_ACCOUNT > 0:
            row = _conn.execute(
                f"SELECT {_COLS} FROM accounts WHERE healthy=1 AND active_docs < ? "
                "ORDER BY active_docs ASC, last_used ASC LIMIT 1",
                (MAX_DOCS_PER_ACCOUNT,),
            ).fetchone()
        else:
            row = _conn.execute(
                f"SELECT {_COLS} FROM accounts WHERE healthy=1 "
                "ORDER BY active_docs ASC, last_used ASC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        acc = _row(row)
        _conn.execute(
            "UPDATE accounts SET active_docs=active_docs+1, created_docs=created_docs+1, "
            "last_used=? WHERE id=?",
            (now, acc.id),
        )
        _conn.commit()
    # Возвращаем уже с учётом резерва.
    acc.active_docs += 1
    acc.created_docs += 1
    acc.last_used = now
    return acc


def release(acc_id: int) -> None:
    """Вернуть аккаунт (канал снят / создание не удалось): active_docs -= 1."""
    with _lock:
        _conn.execute(
            "UPDATE accounts SET active_docs = MAX(active_docs-1, 0) WHERE id=?",
            (acc_id,),
        )
        _conn.commit()


def mark_unhealthy(acc_id: int) -> None:
    """Вывести аккаунт из ротации (капча/бан). pick() его больше не отдаёт."""
    with _lock:
        _conn.execute("UPDATE accounts SET healthy=0 WHERE id=?", (acc_id,))
        _conn.commit()


def mark_healthy(acc_id: int) -> None:
    """Вернуть аккаунт в ротацию (восстановился / ручной reset)."""
    with _lock:
        _conn.execute("UPDATE accounts SET healthy=1 WHERE id=?", (acc_id,))
        _conn.commit()


def get(acc_id: int) -> Account | None:
    with _lock:
        row = _conn.execute(
            f"SELECT {_COLS} FROM accounts WHERE id=?", (acc_id,)
        ).fetchone()
    return _row(row) if row else None


def all() -> list[Account]:
    """Все аккаунты (для админ-листинга)."""
    with _lock:
        rows = _conn.execute(
            f"SELECT {_COLS} FROM accounts ORDER BY id"
        ).fetchall()
    return [_row(r) for r in rows]


def remove(acc_id: int) -> None:
    with _lock:
        _conn.execute("DELETE FROM accounts WHERE id=?", (acc_id,))
        _conn.commit()


def stats() -> dict:
    """Сводка пула для /admin и health-checks."""
    with _lock:
        total, healthy, active = _conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(healthy),0), COALESCE(SUM(active_docs),0) FROM accounts"
        ).fetchone()
    return {"total": total, "healthy": healthy, "active_docs": active}


# ── привязка канал ↔ аккаунт (для release при deprovision) ──────────────────
def bind(short_uuid: str, acc_id: int) -> None:
    with _lock:
        _conn.execute(
            "INSERT INTO channel_accounts(short_uuid, acc_id) VALUES(?,?) "
            "ON CONFLICT(short_uuid) DO UPDATE SET acc_id=excluded.acc_id",
            (short_uuid, acc_id),
        )
        _conn.commit()


def bound_acc(short_uuid: str) -> int | None:
    with _lock:
        row = _conn.execute(
            "SELECT acc_id FROM channel_accounts WHERE short_uuid=?", (short_uuid,)
        ).fetchone()
    return row[0] if row else None


def unbind(short_uuid: str) -> None:
    with _lock:
        _conn.execute("DELETE FROM channel_accounts WHERE short_uuid=?", (short_uuid,))
        _conn.commit()
