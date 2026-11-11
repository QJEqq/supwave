"""Хвост журнала аугментера для веб-морды: последние строки, которые печатает он
сам ([reconcile], [provision], [nodes], [admin] …) — вместо `docker logs | grep`.

stdout подменяется тройником: всё по-прежнему уходит в docker logs, а строки с
нашими метками (начинаются с «[») ещё и кладутся в кольцевой буфер. Access-лог
uvicorn сюда не попадает: его обработчик держит исходный поток со своего старта.
"""
from __future__ import annotations

import collections
import sys
import threading
import time

_lines: collections.deque = collections.deque(maxlen=500)
_lock = threading.Lock()


class _Tee:
    def __init__(self, stream):
        self._stream = stream
        self._buf = ""

    def write(self, s: str) -> int:
        n = self._stream.write(s)
        with _lock:
            self._buf += s
            *done, self._buf = self._buf.split("\n")
            for line in done:
                if line.startswith("["):
                    _lines.append((time.time(), line))
        return n

    def flush(self) -> None:
        self._stream.flush()

    def __getattr__(self, name):  # isatty, fileno, encoding …
        return getattr(self._stream, name)


def install() -> None:
    if not isinstance(sys.stdout, _Tee):
        sys.stdout = _Tee(sys.stdout)


def tail(n: int = 300) -> list[tuple[float, str]]:
    with _lock:
        return list(_lines)[-n:]
