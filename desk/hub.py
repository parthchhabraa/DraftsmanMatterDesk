"""Live state hub.

Engines run in their own threads and call hub.publish(topic, data). Every
connected screen (the Pi kiosk, a phone, the Mac) holds a websocket and gets the
full snapshot on connect, then one message per change. Only changed topics are
sent, so a 1 s telemetry tick costs one small frame.
"""
from __future__ import annotations

import asyncio
import collections
import datetime as dt
import json
import logging
import threading
from typing import Any

log = logging.getLogger("desk")


class Hub:
    def __init__(self):
        self._state: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._clients: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self.logs: collections.deque = collections.deque(maxlen=300)

    def bind_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    # ---- state ----
    def get(self, topic: str, default=None):
        with self._lock:
            return self._state.get(topic, default)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._state)

    def publish(self, topic: str, data: Any):
        with self._lock:
            if self._state.get(topic) == data:
                return
            self._state[topic] = data
        self._send({"t": topic, "d": data})

    def patch(self, topic: str, **changes):
        with self._lock:
            cur = dict(self._state.get(topic) or {})
            cur.update(changes)
        self.publish(topic, cur)

    def event(self, kind: str, data: Any = None):
        """One-off message that is not kept in state (toasts, chat tokens)."""
        self._send({"e": kind, "d": data})

    def toast(self, text: str, level: str = "info"):
        self.event("toast", {"text": text, "level": level})

    def note(self, msg: str, level: str = "info"):
        ts = dt.datetime.now().strftime("%H:%M:%S")
        self.logs.appendleft({"ts": ts, "level": level, "msg": msg})
        getattr(log, "warning" if level == "warn" else level if level in ("info", "error") else "info")(msg)
        self._send({"e": "log", "d": {"ts": ts, "level": level, "msg": msg}})

    # ---- clients ----
    def attach(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._clients.add(q)
        return q

    def detach(self, q: asyncio.Queue):
        self._clients.discard(q)

    def _send(self, msg: dict):
        if not self._loop or not self._clients:
            return
        frame = json.dumps(msg, default=str, separators=(",", ":"))

        def push():
            for q in list(self._clients):
                if q.full():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(frame)

        try:
            self._loop.call_soon_threadsafe(push)
        except RuntimeError:
            pass
