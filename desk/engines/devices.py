"""Mac, iPhone and iPad.

The Mac runs companions/mac/desk_agent.py: it reports battery/CPU/front app and
long-polls this engine for commands (lock, sleep the display, put text on the
clipboard, open a link, show a notification).

The iPhone and iPad report through Shortcuts automations (companions/iphone).
An iPhone Focus named like cfg.study.focus_name starts and ends a lock-in sprint.
"""
from __future__ import annotations

import json
import threading
import time
import uuid

from .base import Engine

MAC_COMMANDS = {"lock", "sleep_display", "clipboard", "open", "notify", "say", "caffeinate", "volume"}


class DevicesEngine(Engine):
    name = "devices"

    def __init__(self, desk):
        super().__init__(desk)
        self.path = self.cfg.data_dir / "devices.json"
        self.state: dict[str, dict] = {}
        try:
            self.state = json.loads(self.path.read_text())
        except (OSError, ValueError):
            pass
        self.queues: dict[str, list[dict]] = {}
        self.cv = threading.Condition()
        if self.demo:
            now = time.time()
            self.state = {
                "mac": {"name": "MacBook Air", "battery": 82, "charging": True, "cpu": 14, "ram": 71,
                        "app": "Cursor", "locked": False, "seen": now, "agent": True, "uptime_s": 302_000},
                "iphone": {"name": "iPhone", "battery": 54, "charging": False, "focus": None, "seen": now - 420},
                "ipad": {"name": "iPad", "battery": 23, "charging": False, "seen": now - 7200},
            }

    def start(self):
        self.publish()
        self.every(30, self.publish, first_delay=30)
        if self.desk.firebase.ready:
            self.every(60, self._firebase_batteries)

    def publish(self):
        stale = self.cfg.devices.stale_after_s
        now = time.time()
        out = {}
        for key, d in self.state.items():
            out[key] = {**d, "stale": now - d.get("seen", 0) > stale, "ago_s": int(now - d.get("seen", 0))}
        self.hub.publish("devices", out)

    def report(self, payload: dict):
        dev = str(payload.get("device", "")).lower().strip()
        if dev not in ("mac", "iphone", "ipad"):
            raise ValueError("device must be mac, iphone or ipad")
        prev = self.state.get(dev, {})
        cur = dict(prev)
        for k in ("name", "battery", "charging", "cpu", "ram", "app", "locked", "focus", "uptime_s", "wifi", "volume"):
            if k in payload:
                cur[k] = payload[k]
        if "battery" in cur and cur["battery"] is not None:
            b = float(cur["battery"])
            cur["battery"] = round(b * 100 if b <= 1 else b)   # Shortcuts sends 0.54 on some iOS versions
        cur["seen"] = time.time()
        cur["agent"] = dev == "mac" and payload.get("agent", False)
        self.state[dev] = cur
        self.path.write_text(json.dumps(self.state))
        self.publish()
        if dev == "iphone" and "focus" in payload:
            self._focus_changed(prev.get("focus"), payload.get("focus"))

    def _focus_changed(self, old, new):
        st = self.cfg.study
        if not st.focus_starts_sprint or old == new:
            return
        name = st.focus_name.lower()
        study = self.desk.study
        if new and name in str(new).lower() and not study.active:
            study.begin(st.subjects[0] if st.subjects else "Study", None, lockin=True)
            self.hub.toast(f"{new} Focus on. Lock-in started.", "good")
        elif old and name in str(old).lower() and study.active:
            mins = study.end() // 60
            self.hub.toast(f"Focus off. {mins} min logged.")

    # ---------- commands for the Mac agent ----------
    def command(self, dev: str, cmd: str, arg=None) -> dict:
        if dev != "mac" or cmd not in MAC_COMMANDS:
            raise ValueError("unknown command")
        item = {"id": uuid.uuid4().hex[:8], "cmd": cmd, "arg": arg, "at": time.time()}
        if self.demo:
            self.hub.toast(f"Demo: Mac would {cmd}")
            return item
        with self.cv:
            q = self.queues.setdefault(dev, [])
            q[:] = [c for c in q if time.time() - c["at"] < 120] + [item]
            self.cv.notify_all()
        return item

    def wait_commands(self, dev: str, timeout: float = 25) -> list[dict]:
        """Long poll for the agent. Returns and clears the queue."""
        deadline = time.time() + timeout
        with self.cv:
            while not self.queues.get(dev):
                left = deadline - time.time()
                if left <= 0:
                    return []
                self.cv.wait(left)
            out, self.queues[dev] = self.queues[dev], []
            return out

    def _firebase_batteries(self):
        """Old desk read batteries from Firebase; keep it as a fallback source."""
        data = self.desk.firebase.batteries()
        changed = False
        for key, fb in (("iphone", "iphone"), ("mac", "mac"), ("ipad", "ipad")):
            val = data.get(fb)
            cur = self.state.get(key, {})
            if val is None or (time.time() - cur.get("seen", 0)) < 600:
                continue
            self.state[key] = {**cur, "battery": int(val), "seen": time.time(), "via": "firebase"}
            changed = True
        if changed:
            self.publish()
