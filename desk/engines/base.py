from __future__ import annotations

import subprocess
import threading
import time
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from ..config import Config
    from ..hub import Hub
    from ..core import Desk


class Engine:
    """One feature of the desk. Owns its threads, publishes its own topic."""

    name = "engine"

    def __init__(self, desk: "Desk"):
        self.desk = desk
        self.cfg: Config = desk.cfg
        self.hub: Hub = desk.hub
        self._stop = threading.Event()

    @property
    def demo(self) -> bool:
        return self.cfg.demo

    def start(self):
        pass

    def stop(self):
        self._stop.set()

    def every(self, seconds: float, fn: Callable[[], None], *, first_delay: float = 0.0, name: str | None = None):
        """Run fn every N seconds on a daemon thread; exceptions are logged, never fatal."""
        def run():
            if first_delay:
                self._stop.wait(first_delay)
            while not self._stop.is_set():
                t0 = time.monotonic()
                try:
                    fn()
                except Exception as e:  # noqa: BLE001 - a feature failing must not take the desk down
                    self.hub.note(f"{self.name}: {e}", "error")
                wait = seconds() if callable(seconds) else seconds
                self._stop.wait(max(0.05, wait - (time.monotonic() - t0)))
        threading.Thread(target=run, daemon=True, name=name or self.name).start()

    def spawn(self, fn: Callable, *args):
        def run():
            try:
                fn(*args)
            except Exception as e:  # noqa: BLE001
                self.hub.note(f"{self.name}: {e}", "error")
        threading.Thread(target=run, daemon=True).start()

    @staticmethod
    def sh(cmd: list[str], timeout: float = 20, check: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=check)

    @staticmethod
    def sudo(cmd: list[str], timeout: float = 20) -> subprocess.CompletedProcess:
        # -n: never hang waiting for a password on a kiosk with no keyboard
        return subprocess.run(["sudo", "-n", *cmd], capture_output=True, text=True, timeout=timeout)
