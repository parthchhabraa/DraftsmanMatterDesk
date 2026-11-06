"""The Pi itself: telemetry, screen sleep, touch wake, power, Wi-Fi, OTA, diagnostics."""
from __future__ import annotations

import math
import os
import random
import threading
import time
from pathlib import Path

import psutil

from ..config import ROOT
from .base import Engine

THERMAL = "/sys/class/thermal/thermal_zone0/temp"
PANIC_C = 82.0


class SystemEngine(Engine):
    name = "system"

    def __init__(self, desk):
        super().__init__(desk)
        self.last_activity = time.time()
        self.asleep = False
        self.wake_lock = set()   # reasons the screen must stay on (study timer, airplay)
        n = psutil.net_io_counters()
        self._net = (n.bytes_sent, n.bytes_recv, time.monotonic())
        self.net_hist = [[0.0, 0.0] for _ in range(60)]
        self.panic = False

    def start(self):
        self.publish_display()
        self.every(1, self._tick)
        if not self.demo:
            threading.Thread(target=self._touch_listener, daemon=True).start()

    # ---------- telemetry ----------
    def _read_temp(self) -> float:
        if self.demo:
            return 47 + 4 * math.sin(time.time() / 40)
        try:
            return float(Path(THERMAL).read_text()) / 1000.0
        except OSError:
            return 0.0

    def _tick(self):
        now = time.monotonic()
        n = psutil.net_io_counters()
        tx0, rx0, t0 = self._net
        dt = max(0.001, now - t0)
        tx, rx = (n.bytes_sent - tx0) / dt / 1024, (n.bytes_recv - rx0) / dt / 1024
        self._net = (n.bytes_sent, n.bytes_recv, now)
        if self.demo:
            tx, rx = abs(random.gauss(14, 8)), abs(random.gauss(60, 30))
        self.net_hist = self.net_hist[1:] + [[round(tx, 1), round(rx, 1)]]
        temp = self._read_temp()
        cpu = psutil.cpu_percent() if not self.demo else round(18 + 10 * abs(math.sin(time.time() / 9)), 1)
        ram = psutil.virtual_memory().percent
        idle_left = max(0, self.cfg.display.idle_timeout_s - (time.time() - self.last_activity))
        self.hub.publish("pi", {
            "cpu": round(cpu), "ram": round(ram), "temp": round(temp, 1),
            "disk": round(psutil.disk_usage("/").percent),
            "uptime_s": int(time.time() - psutil.boot_time()),
            "net": self.net_hist[-30:],
            "sleep_in": None if (self.wake_lock or self.asleep) else int(idle_left),
            "wake_lock": sorted(self.wake_lock),
            "panic": self.panic,
        })
        if temp >= PANIC_C and not self.panic:
            self.panic = True
            self.hub.note(f"Thermal panic at {temp:.1f}°C", "error")
            self.hub.toast(f"Pi at {temp:.0f}°C. Ease off or it will throttle.", "danger")
        elif self.panic and temp < PANIC_C - 6:
            self.panic = False
        if not self.asleep and not self.wake_lock and idle_left <= 0:
            self.sleep()

    # ---------- screen ----------
    def publish_display(self):
        self.hub.publish("display", {"asleep": self.asleep})

    def activity(self):
        self.last_activity = time.time()
        if self.asleep:
            self.wake()

    def _backlight(self, on: bool):
        if self.demo:
            return
        path = self.cfg.display.backlight_power
        if os.path.exists(path):
            r = self.sudo(["sh", "-c", f"echo {0 if on else 1} > {path}"])
            if r.returncode != 0:
                self.hub.note(f"backlight: {r.stderr.strip() or 'sudo refused'}", "warn")

    def sleep(self):
        if self.asleep:
            return
        self.asleep = True
        self.publish_display()
        # give the standby clock a moment to render before the light goes
        threading.Timer(0.4, lambda: self._backlight(False)).start()
        self.hub.note("Screen asleep")

    def wake(self):
        self.last_activity = time.time()
        if not self.asleep:
            return
        self._backlight(True)
        self.asleep = False
        self.publish_display()
        self.hub.note("Screen awake")

    def hold_awake(self, reason: str, on: bool):
        (self.wake_lock.add if on else self.wake_lock.discard)(reason)
        if on:
            self.wake()

    def _touch_listener(self):
        """Raw touch events keep working while the backlight is off and while
        a fullscreen AirPlay window covers the browser."""
        try:
            import evdev
        except ImportError:
            self.hub.note("evdev missing, touch-to-wake off", "warn")
            return
        while not self._stop.is_set():
            try:
                dev = evdev.InputDevice(self.cfg.display.touch_device)
                taps: list[float] = []
                for ev in dev.read_loop():
                    if ev.type != evdev.ecodes.EV_KEY or ev.value != 1:
                        continue
                    now = time.time()
                    taps = [t for t in taps if now - t < 0.9] + [now]
                    if self.asleep:
                        self.desk.call_ui(self.wake)
                        continue
                    self.last_activity = now
                    if len(taps) >= 3 and (self.desk.airplay.running or self.desk.viewer.open):
                        taps.clear()
                        if self.desk.airplay.running:
                            self.desk.call_ui(self.desk.airplay.stop)
                        else:
                            self.desk.call_ui(self.desk.viewer.back)
            except OSError as e:
                self.hub.note(f"touch device: {e}", "warn")
                self._stop.wait(10)

    # ---------- power ----------
    def power(self, action: str):
        self.hub.note(f"Power: {action}")
        if self.demo:
            self.hub.toast(f"Demo mode: would {action} now")
            return
        self.desk.airplay.stop()
        cmd = {"reboot": ["systemctl", "reboot"], "poweroff": ["systemctl", "poweroff"],
               "restart-desk": ["systemctl", "restart", "matterdesk.service"]}.get(action)
        if cmd:
            self.sudo(cmd)

    # ---------- wifi ----------
    def wifi_scan(self) -> list[dict]:
        if self.demo:
            return [{"ssid": s, "signal": g, "secure": True, "active": a}
                    for s, g, a in [("Chhabra 5G", 82, True), ("Chhabra", 74, False), ("DPS-Staff", 31, False)]]
        r = self.sh(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "--rescan", "yes"], timeout=25)
        seen, out = set(), []
        for line in r.stdout.splitlines():
            parts = line.replace("\\:", "\x00").split(":")
            if len(parts) < 4:
                continue
            use, ssid, sig, sec = [p.replace("\x00", ":") for p in parts[:4]]
            if not ssid or ssid in seen:
                continue
            seen.add(ssid)
            out.append({"ssid": ssid, "signal": int(sig or 0), "secure": bool(sec and sec != "--"), "active": use == "*"})
        return sorted(out, key=lambda x: (-x["active"], -x["signal"]))

    def wifi_connect(self, ssid: str, password: str) -> tuple[bool, str]:
        if self.demo:
            return True, f"Connected to {ssid}"
        cmd = ["nmcli", "dev", "wifi", "connect", ssid] + (["password", password] if password else [])
        r = self.sudo(cmd, timeout=45)
        ok = r.returncode == 0
        self.hub.note(f"Wi-Fi {ssid}: {'connected' if ok else r.stderr.strip()}", "info" if ok else "error")
        return ok, (r.stdout or r.stderr).strip()

    # ---------- OTA ----------
    def ota(self):
        self.spawn(self._ota)

    def _ota(self):
        step = lambda pct, label: self.hub.publish("ota", {"pct": pct, "label": label, "error": None})
        step(5, "Contacting GitHub")
        if self.demo:
            for p, l in [(30, "Fetching"), (70, "Applying"), (100, "Restarting")]:
                time.sleep(0.8)
                step(p, l)
            time.sleep(1)
            self.hub.publish("ota", None)
            return
        cwd, branch = str(ROOT), self.cfg.ota.branch
        try:
            self.sh(["git", "config", "--global", "--add", "safe.directory", cwd])
            r = self.sh(["git", "-C", cwd, "fetch", self.cfg.ota.repo_url, branch], timeout=120)
            if r.returncode:
                raise RuntimeError(r.stderr.strip()[-200:])
            step(55, "Applying update")
            r = self.sh(["git", "-C", cwd, "reset", "--hard", "FETCH_HEAD"])
            if r.returncode:
                raise RuntimeError(r.stderr.strip()[-200:])
            step(75, "Checking dependencies")
            self.sh([str(ROOT / ".venv" / "bin" / "pip"), "install", "-q", "-r", str(ROOT / "requirements.txt")], timeout=300)
            step(100, "Restarting")
            self.hub.note(f"OTA applied from {branch}")
            time.sleep(1.2)
            self.sudo(["systemctl", "restart", "matterdesk.service"])
        except Exception as e:  # noqa: BLE001
            self.hub.note(f"OTA failed: {e}", "error")
            self.hub.publish("ota", {"pct": 0, "label": "Update failed", "error": str(e)})

    # ---------- diagnostics ----------
    def diagnose(self, test: str) -> dict:
        if test == "network":
            if self.demo:
                return {"ok": True, "detail": "3/3 replies, 24 ms"}
            r = self.sh(["ping", "-c", "3", "-W", "2", "1.1.1.1"], timeout=15)
            last = (r.stdout.strip().splitlines() or [""])[-1]
            return {"ok": r.returncode == 0, "detail": last or r.stderr.strip()}
        if test == "github":
            r = self.sh(["git", "ls-remote", "--heads", self.cfg.ota.repo_url], timeout=15) if not self.demo else None
            ok = self.demo or r.returncode == 0
            return {"ok": ok, "detail": "Origin reachable, OTA ready" if ok else r.stderr.strip()[-160:]}
        if test == "thermal":
            t = self._read_temp()
            thr = "not available"
            if not self.demo:
                r = self.sh(["vcgencmd", "get_throttled"])
                thr = r.stdout.strip() or thr
            return {"ok": t < 75, "detail": f"{t:.1f}°C, {thr}"}
        if test == "brain":
            b = self.hub.get("brain") or {}
            return {"ok": b.get("state") == "online", "detail": b.get("state", "unknown")}
        return {"ok": False, "detail": "unknown test"}
