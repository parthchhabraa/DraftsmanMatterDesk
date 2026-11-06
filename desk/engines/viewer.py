"""Opens web pages (Claude artifacts) full screen on the Pi and brings you back.

The kiosk Chromium runs with --remote-debugging-port=9222 (bound to localhost).
This engine keeps a DevTools session on the kiosk tab and:
  - adds a "Back to desk" button to every page that is not the desk,
  - notices when the tab leaves the desk (keeps the screen awake, captures the
    page title for the shelf),
  - navigates back to the desk on the button, on a triple-tap, or from a phone.
"""
from __future__ import annotations

import json
import threading
import time

import httpx

from .base import Engine

CDP = "http://127.0.0.1:9222"
DESK_ORIGIN = "http://127.0.0.1:8420"
DESK_URL = f"{DESK_ORIGIN}/?kiosk#claude"
MARKER = "__matterdesk_back__"

BUTTON_JS = """
(() => {
  if (window.top !== window || location.origin === "%(origin)s" || location.protocol === "devtools:") return;
  const add = () => {
    if (document.getElementById("__md_back")) return;
    const b = document.createElement("button");
    b.id = "__md_back";
    b.textContent = "Back to desk";
    b.style.cssText = "position:fixed;left:12px;bottom:12px;z-index:2147483647;height:48px;padding:0 18px;" +
      "border:0;border-radius:2px;background:#d49a4a;color:#1a1206;font:700 15px system-ui,sans-serif;";
    b.addEventListener("click", (e) => {
      e.preventDefault(); e.stopPropagation();
      console.debug("%(marker)s");
      setTimeout(() => { location.href = "%(desk)s"; }, 900);
    }, true);
    (document.body || document.documentElement).appendChild(b);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", add); else add();
  setInterval(add, 2000);
})();
""" % {"origin": DESK_ORIGIN, "marker": MARKER, "desk": DESK_URL}


class ViewerEngine(Engine):
    name = "viewer"

    def __init__(self, desk):
        super().__init__(desk)
        self.ws = None
        self._send_lock = threading.Lock()
        self._next = 0
        self._pending: dict[int, callable] = {}
        self.url = None

    @property
    def open(self) -> bool:
        return self.url is not None

    def start(self):
        self._publish(False)
        if not self.demo:
            threading.Thread(target=self._run, daemon=True, name="viewer").start()

    def _publish(self, available: bool):
        self.hub.publish("viewer", {"available": available or self.demo, "open": self.open, "url": self.url})

    # ---------------- devtools session ----------------
    def _run(self):
        while not self._stop.is_set():
            try:
                self._session()
            except Exception:  # noqa: BLE001 - kiosk restarting, no debug port yet, etc.
                pass
            self.ws = None
            self._publish(False)
            self._stop.wait(5)

    def _session(self):
        from websockets.sync.client import connect
        pages = [t for t in httpx.get(f"{CDP}/json/list", timeout=2).json() if t.get("type") == "page"]
        if not pages:
            return
        target = next((t for t in pages if t["url"].startswith(DESK_ORIGIN)), pages[0])
        with connect(target["webSocketDebuggerUrl"], max_size=None, open_timeout=5) as ws:
            self.ws = ws
            self._call("Page.enable")
            self._call("Runtime.enable")
            self._call("Page.addScriptToEvaluateOnNewDocument", source=BUTTON_JS)
            self._navigated(target["url"])
            if self.open:   # already on a page when the desk restarted: add the button now
                self._call("Runtime.evaluate", expression=BUTTON_JS)
            self._publish(True)
            for raw in ws:
                self._handle(json.loads(raw))

    def _call(self, method: str, cb=None, **params):
        ws = self.ws
        if ws is None:
            raise RuntimeError("Viewer is only available on the Pi's own screen")
        with self._send_lock:
            self._next += 1
            if cb:
                self._pending[self._next] = cb
            ws.send(json.dumps({"id": self._next, "method": method, "params": params}))

    def _handle(self, m: dict):
        if "id" in m:
            cb = self._pending.pop(m["id"], None)
            if cb:
                cb(m.get("result") or {})
            return
        meth, p = m.get("method"), m.get("params") or {}
        if meth == "Page.frameNavigated" and not p.get("frame", {}).get("parentId"):
            self._navigated(p["frame"].get("url", ""))
        elif meth == "Page.loadEventFired" and self.open:
            self._call("Runtime.evaluate", cb=self._got_title, expression="document.title", returnByValue=True)
        elif meth == "Runtime.consoleAPICalled":
            args = p.get("args") or []
            if args and args[0].get("value") == MARKER:
                self.back()

    def _navigated(self, url: str):
        was = self.open
        self.url = None if url.startswith(DESK_ORIGIN) or not url.startswith("http") else url
        if self.open != was:
            self.desk.system.hold_awake("viewer", self.open)
            if self.open:
                self.desk.store.artifact_opened(self.url)
        self._publish(self.ws is not None)

    def _got_title(self, result: dict):
        title = ((result.get("result") or {}).get("value") or "").strip()
        if self.url and title:
            self.desk.store.artifact_title(self.url, title)

    # ---------------- actions ----------------
    def show(self, url: str):
        if not url.startswith("https://"):
            raise ValueError("Only https links can be opened")
        if self.demo:
            self.hub.toast("Demo: the Pi would open this full screen")
            return
        self._call("Page.navigate", url=url)

    def back(self):
        if self.ws is not None:
            try:
                self._call("Page.navigate", url=DESK_URL)
                return
            except Exception:  # noqa: BLE001
                pass
        # No devtools session: restart the kiosk browser; kiosk.sh reopens the desk.
        self.sh(["pkill", "-f", "matterdesk-kiosk"])
        time.sleep(0.2)
