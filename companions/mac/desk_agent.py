#!/usr/bin/env python3
"""MatterDesk agent for the Mac. Standard library only.

Every minute it tells the desk the battery, CPU, memory and front app.
In between it waits for commands from the desk: lock, display off, put text
on the clipboard, open a link, show a notification, keep awake.

Config: ~/Library/Application Support/MatterDesk/agent.json
  {"desk": "http://matterdesk:8420", "key": "<[devices] device_key>"}
a parthchhabra production
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

CONF = Path.home() / "Library/Application Support/MatterDesk/agent.json"
cfg = json.loads(CONF.read_text())
DESK = cfg["desk"].rstrip("/")
KEY = cfg["key"]
REPORT_EVERY = int(cfg.get("report_every", 60))


def run(*cmd, timeout=10) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def call(path: str, body: dict | None = None, timeout: float = 15):
    req = urllib.request.Request(DESK + path, headers={"X-Device-Key": KEY, "Content-Type": "application/json"},
                                 data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


# ---------------------------------------------------------------- readings
def battery():
    out = run("pmset", "-g", "batt")
    m = re.search(r"(\d+)%;\s*([a-zA-Z ]+);", out)
    if not m:
        return None, None
    return int(m.group(1)), "AC Power" in out and "discharging" not in m.group(2)


def cpu():
    out = run("top", "-l", "2", "-n", "0", "-s", "1")
    m = re.findall(r"CPU usage: ([\d.]+)% user, ([\d.]+)% sys", out)
    return round(float(m[-1][0]) + float(m[-1][1])) if m else None


def ram():
    total = int(run("sysctl", "-n", "hw.memsize").strip() or 0)
    vm = run("vm_stat")
    page = int((re.search(r"page size of (\d+)", vm) or [0, 16384])[1])
    get = lambda k: int((re.search(rf"{k}:\s+(\d+)", vm) or [0, 0])[1])
    used = (get("Pages active") + get("Pages wired down") + get("Pages occupied by compressor")) * page
    return round(100 * used / total) if total else None


def front_app():
    asn = run("lsappinfo", "front").strip()
    name = re.search(r'"(?:LSDisplayName|name)"="([^"]+)"', run("lsappinfo", "info", "-only", "name", asn)) if asn else None
    return name.group(1) if name else None


def uptime():
    m = re.search(r"sec = (\d+)", run("sysctl", "-n", "kern.boottime"))
    return int(time.time() - int(m.group(1))) if m else None


def report():
    b, charging = battery()
    app = front_app()
    call("/api/devices/report", {"device": "mac", "agent": True, "name": run("scutil", "--get", "ComputerName").strip() or "Mac",
                                 "battery": b, "charging": charging, "cpu": cpu(), "ram": ram(),
                                 "app": app, "locked": app == "loginwindow", "uptime_s": uptime()})


# ---------------------------------------------------------------- commands
def osa(script: str):
    run("osascript", "-e", script)


def notify(text: str, title: str = "MatterDesk"):
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
    osa(f'display notification "{esc(text)[:200]}" with title "{esc(title)}"')


def do(c: dict):
    cmd, arg = c.get("cmd"), c.get("arg")
    if cmd in ("lock", "sleep_display"):
        run("pmset", "displaysleepnow")   # locks too when "require password immediately" is on
    elif cmd == "clipboard" and arg:
        subprocess.run(["pbcopy"], input=str(arg), text=True)
        notify("Text from the desk is on your clipboard")
    elif cmd == "open" and str(arg).startswith(("http://", "https://")):
        run("open", str(arg))
    elif cmd == "notify" and arg:
        notify(str(arg))
    elif cmd == "say" and arg:
        run("say", str(arg)[:300], timeout=60)
    elif cmd == "caffeinate":
        subprocess.Popen(["caffeinate", "-d", "-t", str(int(arg or 3600))])
    elif cmd == "volume" and arg is not None:
        osa(f"set volume output volume {max(0, min(100, int(arg)))}")


def command_loop():
    while True:
        try:
            for c in call("/api/agent/mac/commands?wait=25", timeout=40).get("commands", []):
                do(c)
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(10)


def main():
    threading.Thread(target=command_loop, daemon=True).start()
    while True:
        try:
            report()
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(REPORT_EVERY)


if __name__ == "__main__":
    main()
