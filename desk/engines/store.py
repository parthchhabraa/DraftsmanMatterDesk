"""Desk data: notes, tasks, flashcards, countdowns. One JSON file, atomic writes.

On first run it imports the v5 files (data/notes.json, tasks.json, flashcards.json,
countdown.json) so nothing written on the old desk is lost.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import random
import re
import threading
import time
import uuid

from .base import Engine


ARTIFACT_RE = re.compile(r"https://claude\.ai/(?:code/)?artifact/[A-Za-z0-9_-]+")


def _id() -> str:
    return uuid.uuid4().hex[:10]


class StoreEngine(Engine):
    name = "store"

    def __init__(self, desk):
        super().__init__(desk)
        self.path = self.cfg.data_dir / "desk.json"
        self._lock = threading.Lock()
        self.data = {"notes": [], "tasks": [], "cards": [], "countdowns": [], "artifacts": []}
        if self.path.exists():
            self.data.update(json.loads(self.path.read_text()))
            self.data.setdefault("artifacts", [])
        else:
            try:
                self._import_v5()
            except Exception as e:  # noqa: BLE001 - odd v5 data must not stop the desk
                self.hub.note(f"v5 import skipped: {e}", "warn")
            if self.demo and not any(self.data.values()):
                self._seed_demo()
            self._save()

    def start(self):
        self.publish()

    def publish(self):
        d = self.data
        today = dt.date.today()
        cds = []
        for c in d["countdowns"]:
            try:
                days = (dt.date.fromisoformat(c["date"]) - today).days
            except ValueError:
                continue
            cds.append({**c, "days": days})
        cds.sort(key=lambda c: (c["days"] < 0, c["days"]))
        self.hub.publish("desk", {
            "notes": sorted(d["notes"], key=lambda n: -n.get("updated", 0)),
            "tasks": d["tasks"], "cards": d["cards"], "countdowns": cds,
            "artifacts": sorted(d["artifacts"], key=lambda a: -max(a.get("opened") or 0, a.get("added") or 0)),
        })

    def _save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, ensure_ascii=False))
        os.replace(tmp, self.path)

    def mutate(self, fn):
        with self._lock:
            out = fn(self.data)
            self._save()
        self.publish()
        return out

    # ---------- notes ----------
    def save_note(self, note_id: str | None, body: str, pinned: bool | None = None) -> str:
        def f(d):
            nid = note_id or _id()
            for n in d["notes"]:
                if n["id"] == nid:
                    n["body"], n["updated"] = body, time.time()
                    if pinned is not None:
                        n["pinned"] = pinned
                    return nid
            d["notes"].append({"id": nid, "body": body, "updated": time.time(), "pinned": bool(pinned)})
            return nid
        return self.mutate(f)

    def delete(self, kind: str, item_id: str):
        self.mutate(lambda d: d.__setitem__(kind, [x for x in d[kind] if x["id"] != item_id]))

    # ---------- tasks ----------
    def add_task(self, text: str, due: str | None = None, subject: str | None = None):
        self.mutate(lambda d: d["tasks"].append({"id": _id(), "text": text.strip(), "done": False,
                                                 "due": due, "subject": subject, "created": time.time()}))

    def toggle_task(self, task_id: str):
        def f(d):
            for t in d["tasks"]:
                if t["id"] == task_id:
                    t["done"] = not t["done"]
                    t["done_at"] = time.time() if t["done"] else None
        self.mutate(f)

    def clear_done(self):
        self.mutate(lambda d: d.__setitem__("tasks", [t for t in d["tasks"] if not t["done"]]))

    # ---------- flashcards (light spaced repetition: box 1..5) ----------
    def add_card(self, subject: str, front: str, back: str):
        self.mutate(lambda d: d["cards"].append({"id": _id(), "subject": subject, "front": front.strip(),
                                                 "back": back.strip(), "box": 1, "due": 0}))

    def grade_card(self, card_id: str, knew: bool):
        gaps = {1: 0, 2: 1, 3: 3, 4: 7, 5: 16}

        def f(d):
            for c in d["cards"]:
                if c["id"] == card_id:
                    c["box"] = min(5, c.get("box", 1) + 1) if knew else 1
                    c["due"] = time.time() + gaps[c["box"]] * 86400
        self.mutate(f)

    # ---------- countdowns ----------
    def set_countdown(self, label: str, date: str, cd_id: str | None = None):
        dt.date.fromisoformat(date)

        def f(d):
            for c in d["countdowns"]:
                if c["id"] == cd_id:
                    c["label"], c["date"] = label, date
                    return
            d["countdowns"].append({"id": _id(), "label": label, "date": date})
        self.mutate(f)

    # ---------- Claude artifacts shelf ----------
    def add_artifact(self, url: str, title: str = "", source: str = "desk") -> bool:
        url = url.strip().split("?")[0].split("#")[0]
        if not url.startswith("https://"):
            raise ValueError("Paste a full https link")

        def f(d):
            if any(a["url"] == url for a in d["artifacts"]):
                return False
            d["artifacts"].append({"id": _id(), "url": url, "title": title.strip()[:120], "source": source,
                                   "added": time.time(), "opened": None})
            return True
        return self.mutate(f)

    def absorb_links(self, text: str, source: str) -> int:
        """Pick claude.ai artifact links out of shared text (iPhone share sheet, inbox)."""
        return sum(self.add_artifact(u, source=source) for u in ARTIFACT_RE.findall(text or ""))

    def artifact_opened(self, url: str):
        def f(d):
            for a in d["artifacts"]:
                if url.startswith(a["url"]):
                    a["opened"] = time.time()
        self.mutate(f)

    def artifact_title(self, url: str, title: str):
        title = re.sub(r"\s*[|\u2013-]\s*Claude$", "", title).strip()
        if not title or title.lower() in ("claude", "sign in"):
            return

        def f(d):
            for a in d["artifacts"]:
                if url.startswith(a["url"]) and not a.get("title"):
                    a["title"] = title[:120]
        self.mutate(f)

    def rename_artifact(self, aid: str, title: str):
        def f(d):
            for a in d["artifacts"]:
                if a["id"] == aid:
                    a["title"] = title.strip()[:120]
        self.mutate(f)

    # ---------- migration ----------
    def _import_v5(self):
        dd = self.cfg.data_dir

        def load(name):
            try:
                return json.loads((dd / name).read_text())
            except (OSError, ValueError):
                return None

        notes = load("notes.json") or {}
        for key, n in notes.items():
            self.data["notes"].append({"id": _id(), "body": n.get("body", ""), "updated": int(key) / 1000 if key.isdigit() else time.time(), "pinned": False})
        for t in load("tasks.json") or []:
            self.data["tasks"].append({"id": _id(), "text": t.get("text", ""), "done": t.get("done", False), "due": None, "subject": None, "created": time.time()})
        for subj, cards in (load("flashcards.json") or {}).items():
            for c in cards:
                self.data["cards"].append({"id": _id(), "subject": subj, "front": c["front"], "back": c["back"], "box": 1, "due": 0})
        cd = load("countdown.json")
        if cd and cd.get("date"):
            self.data["countdowns"].append({"id": _id(), "label": cd.get("label", "Target"), "date": cd["date"]})
        if any(self.data.values()):
            self.hub.note("Imported notes, tasks, flashcards and countdown from v5")

    def _seed_demo(self):
        today = dt.date.today()
        self.data["countdowns"] = [
            {"id": _id(), "label": "JEE Main S1", "date": (today + dt.timedelta(days=74)).isoformat()},
            {"id": _id(), "label": "Boards: Physics", "date": (today + dt.timedelta(days=118)).isoformat()},
            {"id": _id(), "label": "UCAS deadline", "date": (today + dt.timedelta(days=69)).isoformat()},
        ]
        for text, subj, done in [("Rotational motion PYQs, 2019 to 2024", "Physics", False),
                                 ("Redo Aldehydes worksheet mistakes", "O Chem", True),
                                 ("Integration by parts drill, 40 Qs", "Maths", False),
                                 ("Send RYC vendor quotes to Daksh", None, False)]:
            self.data["tasks"].append({"id": _id(), "text": text, "done": done, "due": None, "subject": subj, "created": time.time()})
        for body in ["Moment of inertia of a hollow cone about its axis: MR²/2. Same as a disc, because every mass element sits at the same r spread.",
                     "Ask Uniity sir about the Q14 sign convention in yesterday's test."]:
            self.data["notes"].append({"id": _id(), "body": body, "updated": time.time() - random.randint(0, 90000), "pinned": False})
        for s, f, b in [("Physics", "Escape velocity from Earth", "11.2 km/s, √(2GM/R)"),
                        ("O Chem", "Reagent for aldehyde vs ketone", "Tollens' gives a silver mirror with aldehydes only"),
                        ("Maths", "∫ ln x dx", "x ln x − x + C")]:
            self.data["cards"].append({"id": _id(), "subject": s, "front": f, "back": b, "box": 1, "due": 0})
