"""Time-driven things: the day plan, alarms, quick timers, and the ring.

Plan blocks, alarms and scores are stored by StoreEngine (desk.json). This engine
turns the plan into today's concrete blocks, fires alarms and timers, and owns
the one "ring" the desk can show at a time (alarm, timer or finished sprint).
"""
from __future__ import annotations

import datetime as dt
import time
import uuid

from .base import Engine

RING_TIMEOUT_S = 180


def _hm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    h, m = int(h), int(m)
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError("time must be HH:MM")
    return h, m


class ClockEngine(Engine):
    name = "clock"

    def __init__(self, desk):
        super().__init__(desk)
        self.timers: list[dict] = []
        self.ring_state: dict | None = None
        self._fired: set[str] = set()      # "2026-11-10|alarm|id" so nothing fires twice
        self._started = time.time()

    def start(self):
        self.hub.publish("ring", None)
        self.hub.publish("timers", [])
        self.every(1, self.tick)

    # ---------------- plan ----------------
    def today_blocks(self, now: dt.datetime | None = None) -> list[dict]:
        now = now or dt.datetime.now()
        day0 = dt.datetime.combine(now.date(), dt.time())
        out = []
        for b in self.desk.store.data.get("plan", []):
            days = b.get("days") or []
            if b.get("date"):
                if b["date"] != now.date().isoformat():
                    continue
            elif days and now.weekday() not in days:
                continue
            try:
                h, m = _hm(b["start"])
            except (ValueError, KeyError):
                continue
            start = day0 + dt.timedelta(hours=h, minutes=m)
            end = min(start + dt.timedelta(minutes=int(b.get("minutes", 60))), day0 + dt.timedelta(days=1))
            out.append({"id": b["id"], "label": b.get("label") or b.get("subject") or "Block",
                        "subject": b.get("subject"), "kind": b.get("kind", "study"),
                        "start": int(start.timestamp()), "end": int(end.timestamp())})
        return sorted(out, key=lambda x: x["start"])

    def start_block(self, block_id: str, lockin: bool = False) -> int:
        """Begin a sprint for a planned study block, for whatever is left of it."""
        now = time.time()
        b = next((x for x in self.today_blocks() if x["id"] == block_id), None)
        if not b or b["kind"] != "study":
            raise ValueError("That block is not a study block for today")
        left = int((b["end"] - max(now, b["start"])) // 60)
        if left < 5:
            raise ValueError("Less than 5 minutes left in that block")
        self.desk.study.begin(b["subject"] or b["label"], left, lockin)
        return left

    # ---------------- timers ----------------
    def add_timer(self, minutes: float, label: str = "") -> dict:
        if not (0 < minutes <= 24 * 60):
            raise ValueError("Timer must be between 1 minute and 24 hours")
        t = {"id": uuid.uuid4().hex[:8], "label": label.strip()[:60] or f"{int(minutes)} min timer",
             "ends": int(time.time() + minutes * 60), "total": int(minutes * 60)}
        self.timers.append(t)
        self._publish_timers()
        return t

    def cancel_timer(self, timer_id: str):
        self.timers = [t for t in self.timers if t["id"] != timer_id]
        self._publish_timers()

    def _publish_timers(self):
        self.hub.publish("timers", sorted(self.timers, key=lambda t: t["ends"]))

    # ---------------- ring ----------------
    def ring(self, kind: str, label: str, **extra):
        self.ring_state = {"id": uuid.uuid4().hex[:8], "kind": kind, "label": label, "since": int(time.time()), **extra}
        self.desk.system.hold_awake("ring", True)
        self.hub.publish("ring", self.ring_state)
        self.hub.note(f"Ring: {label}")
        if kind != "sprint" and not self.demo:
            try:
                self.desk.devices.command("mac", "notify", label)
            except Exception:  # noqa: BLE001 - the Mac being away must not stop an alarm
                pass

    def dismiss(self):
        self.ring_state = None
        self.desk.system.hold_awake("ring", False)
        self.hub.publish("ring", None)

    def snooze(self, minutes: int = 5):
        r = self.ring_state
        self.dismiss()
        if r:
            self.add_timer(minutes, r["label"])

    # ---------------- tick ----------------
    def tick(self):
        now = dt.datetime.now()
        ts = time.time()
        today = now.date().isoformat()
        blocks = self.today_blocks(now)
        self.hub.publish("plan", {"date": today, "blocks": blocks})

        # a planned block starting now: nudge, do not ring
        for b in blocks:
            key = f"{today}|block|{b['id']}|{b['start']}"
            if b["start"] <= ts < b["start"] + 60 and key not in self._fired and b["start"] > self._started:
                self._fired.add(key)
                self.hub.toast(f"{b['label']} starts now", "good")
                self.hub.event("chime", {"kind": "block"})
                self.desk.system.wake()

        # alarms
        hhmm = now.strftime("%H:%M")
        for a in list(self.desk.store.data.get("alarms", [])):
            if not a.get("enabled", True) or a.get("time") != hhmm:
                continue
            days = a.get("days") or []
            if days and now.weekday() not in days:
                continue
            key = f"{today}|alarm|{a['id']}|{hhmm}"
            if key in self._fired:
                continue
            self._fired.add(key)
            self.ring("alarm", a.get("label") or "Alarm")
            if not days:   # one-time alarm switches itself off
                self.desk.store.set_alarm_enabled(a["id"], False)

        # timers
        due = [t for t in self.timers if t["ends"] <= ts]
        if due:
            self.timers = [t for t in self.timers if t["ends"] > ts]
            self._publish_timers()
            self.ring("timer", due[0]["label"])

        if self.ring_state and ts - self.ring_state["since"] > RING_TIMEOUT_S:
            self.hub.note(f"Ring timed out: {self.ring_state['label']}", "warn")
            self.dismiss()
        if len(self._fired) > 500:
            self._fired = {k for k in self._fired if k.startswith(today)}
