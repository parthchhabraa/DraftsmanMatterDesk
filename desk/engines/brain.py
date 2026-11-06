"""Client for brain-api on draftsmanbrain (see brain/brain_api.py).

Works with the v1 brain-api (only /status and /wol) and lights up the rest of the
features when it finds v2. The token never leaves the Pi: phones and the Mac talk
to the desk, the desk talks to the brain.
"""
from __future__ import annotations

import json
import math
import random
import time
from typing import Iterator

import httpx

from .base import Engine


class BrainEngine(Engine):
    name = "brain"

    def __init__(self, desk):
        super().__init__(desk)
        b = self.cfg.brain
        self.url = b.url.rstrip("/")
        self.version = 0
        self.client = httpx.Client(timeout=6, headers={"X-Brain-Token": b.token}) if self.url else None
        self._fails = 0
        self._demo_focus = False
        self._demo_loc = "India (direct)"
        self._demo_inbox = _demo_inbox()

    @property
    def configured(self) -> bool:
        return bool(self.url and self.cfg.brain.token) or self.demo

    def start(self):
        if not self.configured:
            self.hub.publish("brain", {"state": "unconfigured"})
            return
        self.every(self.cfg.brain.poll_s, self.poll_status)
        self.every(20, self.poll_tailnet, first_delay=1)
        self.every(60, self.poll_adguard, first_delay=2)
        self.every(15, self.poll_inbox, first_delay=3)

    # ---------- http ----------
    def _get(self, path: str, **kw):
        r = self.client.get(self.url + path, **kw)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict | None = None, timeout: float = 15):
        r = self.client.post(self.url + path, json=body or {}, timeout=timeout)
        if r.status_code == 404 and self.version < 2:
            raise RuntimeError("Needs brain-api v2 on draftsmanbrain (see brain/README.md)")
        r.raise_for_status()
        return r.json() if r.content else {}

    # ---------- polling ----------
    def poll_status(self):
        if self.demo:
            return self.hub.publish("brain", _demo_status())
        try:
            s = self._get("/status")
        except (httpx.HTTPError, ValueError) as e:
            self._fails += 1
            if self._fails >= 2:   # one dropped poll is not an outage
                prev = self.hub.get("brain") or {}
                self.hub.publish("brain", {**prev, "state": "unreachable", "error": type(e).__name__})
            return
        self._fails = 0
        self.version = int(s.get("version", 1))
        services = s.get("services", {})
        if isinstance(services, dict):   # v1 shape {"antara-ml.service": "active"}
            services = [{"name": k.removesuffix(".service"), "state": v} for k, v in services.items()]
        bad = [x for x in services if x.get("state") != "active"]
        bad += [c for c in s.get("containers", []) if c.get("state") != "running"]
        self.hub.publish("brain", {
            "state": "degraded" if bad else "online", "version": self.version,
            "host": {k: s.get(k) for k in ("cpu", "ram", "disk", "temp", "uptime_s", "load", "hostname")},
            "services": services, "containers": s.get("containers", []),
            "wol_targets": s.get("wol_targets") or self.cfg.brain.wol_targets,
            "ollama": s.get("ollama"), "last_ok": time.time(),
        })

    def poll_tailnet(self):
        if self.demo:
            return self.hub.publish("tailnet", _demo_tailnet(self._demo_loc))
        if self.version < 2:
            return
        self.hub.publish("tailnet", self._get("/tailnet"))

    def poll_adguard(self):
        if self.demo:
            return self.hub.publish("adguard", _demo_adguard(self._demo_focus))
        if self.version < 2:
            return
        try:
            self.hub.publish("adguard", self._get("/adguard"))
        except httpx.HTTPStatusError as e:
            self.hub.publish("adguard", {"error": f"AdGuard: {e.response.status_code}"})

    def poll_inbox(self):
        if self.demo:
            return self.hub.publish("inbox", self._demo_inbox)
        if self.version < 2:
            return
        ib = self._get("/inbox", params={"limit": 40})
        for it in ib.get("items", []):
            if it.get("kind") == "link" and "claude.ai/" in (it.get("text") or "") and self.desk.store.absorb_links(it["text"], it.get("source", "inbox")):
                self.hub.toast("Added a Claude artifact to the shelf")
        self.hub.publish("inbox", ib)

    # ---------- actions ----------
    def wol(self, target: str):
        if self.demo:
            return {"woke": target}
        return self._post(f"/wol/{target}")

    def restart_service(self, name: str):
        if self.demo:
            return {"restarted": name}
        out = self._post(f"/services/{name}/restart", timeout=40)
        self.spawn(self.poll_status)
        return out

    def set_exit(self, location: str | None = None, advertise: bool | None = None):
        if self.demo:
            if location:
                self._demo_loc = location
            self.poll_tailnet()
            return {}
        body = {k: v for k, v in (("location", location), ("advertise", advertise)) if v is not None}
        out = self._post("/exitnode", body, timeout=60)
        self.spawn(self.poll_tailnet)
        return out

    def adguard_protection(self, on: bool):
        if self.demo:
            return {}
        out = self._post("/adguard/protection", {"enabled": on})
        self.spawn(self.poll_adguard)
        return out

    def focus(self, on: bool, services: list[str]):
        if self.demo:
            self._demo_focus = on
            self.poll_adguard()
            return {}
        if not self.configured:
            return {}
        out = self._post("/focus", {"enabled": on, "services": services})
        self.spawn(self.poll_adguard)
        return out

    def inbox_delete(self, item_id: str):
        if self.demo:
            self._demo_inbox["items"] = [i for i in self._demo_inbox["items"] if i["id"] != item_id]
            return self.poll_inbox()
        self.client.delete(f"{self.url}/inbox/{item_id}").raise_for_status()
        self.spawn(self.poll_inbox)

    def inbox_file(self, item_id: str) -> tuple[bytes, str]:
        r = self.client.get(f"{self.url}/inbox/{item_id}/file", timeout=30)
        r.raise_for_status()
        return r.content, r.headers.get("content-type", "application/octet-stream")

    def inbox_upload(self, source: str, filename: str, content: bytes, ctype: str, text: str = "") -> dict:
        if self.demo:
            item = {"id": str(int(time.time())), "source": source, "kind": "text" if text else "file",
                    "name": filename, "text": text, "at": time.time(), "size": len(content)}
            self._demo_inbox["items"].insert(0, item)
            self.poll_inbox()
            return item
        r = self.client.post(f"{self.url}/inbox", data={"source": source, "text": text},
                             files={"file": (filename, content, ctype)} if content else None, timeout=60)
        r.raise_for_status()
        self.spawn(self.poll_inbox)
        return r.json()

    def ask(self, messages: list[dict], model: str | None = None) -> Iterator[str]:
        """Yields text chunks from the brain's local model."""
        if self.demo:
            reply = ("Short version: torque is the rotational twin of force. τ = r × F, so the same push does more "
                     "the further from the axis you apply it. For your JEE problems, pick the axis through the point "
                     "where the unknown forces act and those forces drop out of the torque equation.")
            for word in reply.split(" "):
                time.sleep(0.03)
                yield word + " "
            return
        body = {"messages": messages, **({"model": model} if model else {})}
        with self.client.stream("POST", f"{self.url}/ask", json=body, timeout=httpx.Timeout(120, connect=6)) as r:
            if r.status_code == 404:
                raise RuntimeError("Ask needs brain-api v2 on draftsmanbrain")
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                try:
                    j = json.loads(line)
                except ValueError:
                    continue
                if j.get("error"):
                    raise RuntimeError(j["error"])
                if j.get("text"):
                    yield j["text"]

    def models(self) -> list[str]:
        if self.demo:
            return ["qwen2.5:7b-instruct", "llama3.1:8b"]
        try:
            return self._get("/ask/models").get("models", [])
        except httpx.HTTPError:
            return []


# ---------- demo data ----------
def _demo_status():
    t = time.time()
    return {
        "state": "degraded", "version": 2,
        "host": {"cpu": round(9 + 6 * abs(math.sin(t / 13))), "ram": 61, "disk": 48, "temp": 52.0,
                 "uptime_s": 1_209_600 + int(t % 5000), "load": [0.42, 0.51, 0.47], "hostname": "draftsmanbrain"},
        "services": [{"name": "brain-api", "state": "active"}, {"name": "antara-ml", "state": "active"},
                     {"name": "antara-frontend", "state": "active"}, {"name": "antara-tunnel", "state": "failed"}],
        "containers": [{"name": n, "state": "running", "status": "Up 6 days"} for n in
                       ["ollama", "murmur", "adguardhome", "plex", "qbittorrent", "open-webui", "n8n"]],
        "wol_targets": ["desktop"], "ollama": {"up": True, "models": 3}, "last_ok": t,
    }


def _demo_tailnet(loc):
    peers = [("draftsmanbrain", "linux", True, "100.103.94.116", 0, 0),
             ("parths-macbook-air", "macOS", True, "100.88.12.4", 5.4e9, 1.2e9),
             ("iphone-15", "iOS", True, "100.71.30.9", 2.1e9, 0.3e9),
             ("ipad-pro", "iOS", False, "100.92.4.17", 0.4e9, 0.1e9),
             ("matterdesk", "linux", True, "100.66.2.40", 0.2e9, 0.1e9),
             ("desktop", "windows", False, "100.110.8.2", 0, 0)]
    return {
        "self": "draftsmanbrain",
        "peers": [{"name": n, "os": o, "online": on, "ip": ip, "exit": n in ("parths-macbook-air", "iphone-15"),
                   "rx": rx, "tx": tx, "last_seen": None if on else "3h ago"} for n, o, on, ip, rx, tx in peers],
        "exit": {"advertised": True, "location": loc,
                 "locations": ["India (direct)", "Netherlands", "Japan", "United States", "Switzerland"]},
    }


def _demo_adguard(focus):
    return {"queries": 48213, "blocked": 9120, "blocked_pct": 18.9, "protection": True, "focus": focus,
            "top_blocked": [["graph.instagram.com", 1840], ["app-measurement.com", 1312],
                            ["googleads.g.doubleclick.net", 990], ["mobile.events.data.microsoft.com", 610]],
            "clients": [["parths-macbook-air", 21003], ["iphone-15", 17320], ["ipad-pro", 4210]],
            "hourly": [random.Random(i).randint(800, 2600) for i in range(24)]}


def _demo_inbox():
    now = time.time()
    return {"items": [
        {"id": "a1", "source": "penotron", "kind": "image", "name": "notes_0931.jpg", "text": "", "at": now - 3200, "size": 812_000},
        {"id": "a2", "source": "anamnis", "kind": "audio", "name": "rec_1412.m4a",
         "text": "So the thing about the RYC venue is we need the final headcount by Friday, Daksh said he'd call them.",
         "at": now - 9100, "size": 2_400_000},
        {"id": "a3", "source": "iphone", "kind": "link", "name": "", "text": "https://ocw.mit.edu/courses/8-01sc-classical-mechanics-fall-2016/",
         "at": now - 20000, "size": 0},
    ]}
