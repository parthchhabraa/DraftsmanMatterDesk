"""Study timer, session log, heatmap, and Lock-in mode.

Lock-in = timer + AdGuard blocks distracting services on every device on the tailnet
+ optional playlist + optional Mac lock. It is undone when the sprint ends, even if the
desk restarts mid-sprint (the active sprint is stored on disk).
"""
from __future__ import annotations

import datetime as dt
import json
import random
import sqlite3
import threading
import time

from .base import Engine


class StudyEngine(Engine):
    name = "study"

    def __init__(self, desk):
        super().__init__(desk)
        self.db_path = self.cfg.data_dir / "study.sqlite3"
        self.active_path = self.cfg.data_dir / "study_active.json"
        self._db_lock = threading.Lock()
        self.active: dict | None = None
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS sessions(
                id INTEGER PRIMARY KEY, subject TEXT NOT NULL, started REAL NOT NULL,
                seconds INTEGER NOT NULL, lockin INTEGER DEFAULT 0, note TEXT DEFAULT '')""")
        if self.demo and not self._count():
            self._seed_demo()

    def _conn(self):
        return sqlite3.connect(self.db_path, timeout=10)

    def _count(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]

    def start(self):
        if self.active_path.exists():
            try:
                self.active = json.loads(self.active_path.read_text())
                self.desk.system.hold_awake("study", True)
            except (OSError, ValueError):
                self.active = None
        self.publish_stats()
        self.every(1, self._tick)
        self.every(300, self.publish_stats, first_delay=300)
        if self.desk.firebase.ready and not self._count():
            self.spawn(self._import_firebase)

    # ---------- timer ----------
    def begin(self, subject: str, target_min: int | None, lockin: bool):
        if self.active:
            self.end()
        self.active = {"subject": subject, "target_s": (target_min or 0) * 60, "started": time.time(),
                       "lockin": bool(lockin), "paused_s": 0, "paused_at": None}
        self.active_path.write_text(json.dumps(self.active))
        self.desk.system.hold_awake("study", True)
        self.hub.note(f"Sprint started: {subject}{' (lock-in)' if lockin else ''}")
        if lockin:
            self.spawn(self._lockin, True)
        self._tick()

    def pause(self):
        a = self.active
        if not a:
            return
        if a["paused_at"]:
            a["paused_s"] += time.time() - a["paused_at"]
            a["paused_at"] = None
        else:
            a["paused_at"] = time.time()
        self.active_path.write_text(json.dumps(a))
        self._tick()

    def elapsed(self) -> int:
        a = self.active
        if not a:
            return 0
        end = a["paused_at"] or time.time()
        return int(end - a["started"] - a["paused_s"])

    def end(self, note: str = "") -> int:
        a = self.active
        if not a:
            return 0
        secs = self.elapsed()
        if a["target_s"]:
            secs = min(secs, a["target_s"])
        self.active = None
        self.active_path.unlink(missing_ok=True)
        self.desk.system.hold_awake("study", False)
        if secs >= 60:
            with self._db_lock, self._conn() as c:
                c.execute("INSERT INTO sessions(subject, started, seconds, lockin, note) VALUES(?,?,?,?,?)",
                          (a["subject"], a["started"], secs, int(a["lockin"]), note))
            self.desk.firebase.push_session(a["subject"], secs, int(a["started"]))
        if a["lockin"]:
            self.spawn(self._lockin, False)
        self.hub.note(f"Sprint ended: {a['subject']} {secs // 60} min")
        self.hub.publish("timer", None)
        self.publish_stats()
        return secs

    def _tick(self):
        a = self.active
        if not a:
            if self.hub.get("timer") is not None:
                self.hub.publish("timer", None)
            return
        el = self.elapsed()
        remaining = max(0, a["target_s"] - el) if a["target_s"] else None
        self.hub.publish("timer", {"subject": a["subject"], "elapsed": el, "started": int(a["started"]), "target_s": a["target_s"],
                                   "remaining": remaining, "lockin": a["lockin"], "paused": bool(a["paused_at"])})
        if remaining == 0:
            self.end()
            self.desk.clock.ring("sprint", f"{a['subject']} sprint done", minutes=a["target_s"] // 60, subject=a["subject"])

    def _lockin(self, on: bool):
        st = self.cfg.study
        brain = self.desk.brain
        try:
            brain.focus(on, st.lockin_block)
        except Exception as e:  # noqa: BLE001
            self.hub.note(f"lock-in blocking: {e}", "warn")
        if on and st.lockin_playlist:
            try:
                self.desk.spotify.control("playlist", st.lockin_playlist)
            except Exception as e:  # noqa: BLE001
                self.hub.note(f"lock-in playlist: {e}", "warn")
        if on and st.lockin_lock_mac:
            self.desk.devices.command("mac", "lock")

    # ---------- stats ----------
    def publish_stats(self):
        now = dt.datetime.now()
        today0 = dt.datetime.combine(now.date(), dt.time()).timestamp()
        since = today0 - 139 * 86400
        with self._conn() as c:
            rows = c.execute("SELECT subject, started, seconds FROM sessions WHERE started >= ? ORDER BY started",
                             (since,)).fetchall()
            recent = c.execute("SELECT subject, started, seconds, lockin FROM sessions ORDER BY started DESC LIMIT 6").fetchall()
        days: dict[str, int] = {}
        subj_today: dict[str, int] = {}
        blocks: list[list] = []
        week = 0
        for subj, started, secs in rows:
            d = dt.date.fromtimestamp(started)
            days[d.isoformat()] = days.get(d.isoformat(), 0) + secs
            if started >= today0:
                subj_today[subj] = subj_today.get(subj, 0) + secs
                blocks.append([int(started), int(secs), subj])
            if started >= today0 - 6 * 86400:
                week += secs
        streak, d = 0, now.date()
        if days.get(d.isoformat(), 0) < 1800:
            d -= dt.timedelta(days=1)   # today not done yet does not break the streak
        while days.get(d.isoformat(), 0) >= 1800:
            streak += 1
            d -= dt.timedelta(days=1)
        # last 14 days for the bar chart, 30-day split by subject
        days14 = []
        for i in range(13, -1, -1):
            d14 = now.date() - dt.timedelta(days=i)
            days14.append({"date": d14.isoformat(), "wd": d14.strftime("%a"), "min": days.get(d14.isoformat(), 0) // 60})
        split: dict[str, int] = {}
        for subj, started, secs in rows:
            if started >= today0 - 29 * 86400:
                split[subj] = split.get(subj, 0) + secs
        last7 = [x["min"] for x in days14[-8:-1]]   # the 7 full days before today
        heat = []
        for i in range(139, -1, -1):
            day = (now.date() - dt.timedelta(days=i)).isoformat()
            heat.append(days.get(day, 0) // 60)
        self.hub.publish("study", {
            "today_min": sum(subj_today.values()) // 60,
            "goal_min": self.cfg.study.daily_goal_min,
            "by_subject": sorted(([k, v // 60] for k, v in subj_today.items()), key=lambda x: -x[1]),
            "week_min": week // 60, "streak": streak, "heat": heat, "today_blocks": blocks,
            "recent": [{"subject": s, "at": dt.datetime.fromtimestamp(t).strftime("%d %b %H:%M"),
                        "min": sec // 60, "lockin": bool(li)} for s, t, sec, li in recent],
            "subjects": self.cfg.study.subjects,
            "days14": days14, "split30": sorted(([k, v // 60] for k, v in split.items()), key=lambda x: -x[1]),
            "avg7": round(sum(last7) / 7) if last7 else 0, "best14": max((x["min"] for x in days14), default=0),
            "score_target": self.cfg.study.score_target, "score_out_of": self.cfg.study.score_out_of,
        })

    def _import_firebase(self):
        n = 0
        for s in self.desk.firebase.sessions():
            with self._db_lock, self._conn() as c:
                c.execute("INSERT INTO sessions(subject, started, seconds) VALUES(?,?,?)",
                          (s.get("subject", "Other"), s.get("timestamp", 0), s.get("duration_seconds", 0)))
            n += 1
        if n:
            self.hub.note(f"Imported {n} study sessions from Firebase")
            self.publish_stats()

    def _seed_demo(self):
        rnd = random.Random(7)
        subs = ["Maths", "Physics", "P Chem", "O Chem", "English"]
        now = time.time()
        with self._conn() as c:
            for day in range(1, 120):
                if rnd.random() < 0.2:
                    continue
                for _ in range(rnd.randint(1, 4)):
                    c.execute("INSERT INTO sessions(subject, started, seconds, lockin) VALUES(?,?,?,?)",
                              (rnd.choice(subs), now - day * 86400 + rnd.randint(0, 40000),
                               rnd.randint(20, 95) * 60, int(rnd.random() < 0.3)))
            day0 = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))
            for subj, h, mins in [("Physics", 6.5, 72), ("Maths", 9.0, 55), ("O Chem", 13.25, 41)]:
                if day0 + h * 3600 + mins * 60 < now:
                    c.execute("INSERT INTO sessions(subject, started, seconds) VALUES(?,?,?)",
                              (subj, day0 + h * 3600, mins * 60))
