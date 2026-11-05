"""AirPlay receiver (uxplay). The mirrored video opens fullscreen above the kiosk;
triple-tap anywhere (read straight from the touch device) stops it."""
from __future__ import annotations

import os
import shutil
import subprocess
import threading

from .base import Engine


class AirplayEngine(Engine):
    name = "airplay"

    def __init__(self, desk):
        super().__init__(desk)
        self.proc: subprocess.Popen | None = None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        self.publish("off")

    def publish(self, state: str):
        self.hub.publish("airplay", {"state": state, "installed": self.demo or bool(shutil.which("uxplay"))})

    def begin(self):
        if self.running:
            return
        if self.demo:
            self.publish("waiting")
            return
        if not shutil.which("uxplay"):
            raise RuntimeError("uxplay is not installed (sudo apt install uxplay)")
        env = {**os.environ, "WAYLAND_DISPLAY": os.environ.get("WAYLAND_DISPLAY", "wayland-1"),
               "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")}
        self.proc = subprocess.Popen(["stdbuf", "-oL", "uxplay", "-n", "MatterDesk", "-nh", "-p", "-fs", "-vs", "waylandsink"],
                                     env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.desk.system.hold_awake("airplay", True)
        self.publish("waiting")
        self.hub.note("AirPlay receiver up as MatterDesk")
        threading.Thread(target=self._watch, args=(self.proc,), daemon=True).start()

    def _watch(self, proc):
        for line in iter(proc.stdout.readline, ""):
            low = line.lower()
            if "begin streaming" in low or "starting mirroring" in low or "connection request" in low:
                self.publish("streaming")
            elif "connection closed" in low or "stopped mirroring" in low:
                self.publish("waiting")
        if proc is self.proc:
            self.proc = None
            self.desk.system.hold_awake("airplay", False)
            self.publish("off")

    def stop(self):
        p, self.proc = self.proc, None
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(3)
            except subprocess.TimeoutExpired:
                p.kill()
        self.desk.system.hold_awake("airplay", False)
        self.publish("off")
