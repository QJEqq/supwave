"""Клиент API ноды-агента (ofnode): HTTPS с ЗАКРЕПЛЁННЫМ сертификатом ноды
(он у нас в базе с момента добавления — свой CA, имя хоста не проверяем) +
Bearer-токен. На стандартной библиотеке (urllib в потоке), без новых зависимостей.
"""
from __future__ import annotations

import asyncio
import json
import os
import ssl
import urllib.error
import urllib.request


class NodeError(RuntimeError):
    def __init__(self, msg: str, code: int = 0):
        super().__init__(msg)
        self.code = code


def _ctx(cert: str) -> ssl.SSLContext:
    ctx = ssl.create_default_context(cadata=cert)
    ctx.check_hostname = False  # закреплён сам сертификат: адрес ноды не важен
    return ctx


def _call(node, method: str, path: str, body: dict | None, timeout: float) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    return _send(node, method, path, data, {"Content-Type": "application/json"}, timeout)


def _send(node, method: str, path: str, data, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        f"https://{node.address}:{node.port}{path}", data=data, method=method,
        headers={"Authorization": f"Bearer {node.token}", **headers},
    )
    try:
        with urllib.request.urlopen(req, context=_ctx(node.cert), timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e).get("error") or str(e)
        except ValueError:
            msg = str(e)
        raise NodeError(f"нода {node.name}: {msg}", e.code) from None
    except (urllib.error.URLError, OSError) as e:
        raise NodeError(f"нода {node.name} ({node.address}:{node.port}) не отвечает: {getattr(e, 'reason', e)}") from None


async def health(node, timeout: float = 5) -> dict:
    return await asyncio.to_thread(_call, node, "GET", "/health", None, timeout)


async def channels(node, timeout: float = 15) -> list[dict]:
    r = await asyncio.to_thread(_call, node, "GET", "/channels", None, timeout)
    return r.get("channels") or []


async def apply(node, spec: dict) -> int:
    """Завести (или заменить) канал на ноде → порт его direct."""
    r = await asyncio.to_thread(_call, node, "POST", "/channels", spec, 60)
    return int(r["port"])


def _put_core(node, path: str, sha: str, timeout: float) -> dict:
    with open(path, "rb") as f:
        return _send(node, "PUT", "/core", f, {
            "Content-Type": "application/octet-stream", "Content-Length": str(os.path.getsize(path)),
            "X-Core-SHA256": sha}, timeout)


async def push_core(node, path: str, sha: str) -> dict:
    """Залить ядро на ноду (агент ≥ 0.2.0): агент сверит SHA, проверит, что ядро
    запускается, и перезапустит каналы на нём; не поднялись — вернёт прежнее и
    ответит ошибкой. → {"core", "was", "restarted"}"""
    return await asyncio.to_thread(_put_core, node, path, sha, 300)


async def channel_log(node, channel: str) -> list[str]:
    """Последние строки ядра канала (агент ≥ 0.3.0)."""
    r = await asyncio.to_thread(_call, node, "GET", f"/channels/{channel}/log", None, 10)
    return r.get("lines") or []


async def remove(node, channel: str) -> None:
    """Снять канал; «такого нет» — тоже успех (снимать нечего)."""
    try:
        await asyncio.to_thread(_call, node, "DELETE", f"/channels/{channel}", None, 30)
    except NodeError as e:
        if e.code != 404:
            raise
