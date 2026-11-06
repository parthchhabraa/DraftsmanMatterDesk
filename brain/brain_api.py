"""brain-api v2, runs on draftsmanbrain (port 8010, behind `tailscale serve`).

Drop-in for v1: GET /status and POST /wol/{target} keep their shape, same
X-Brain-Token header, same BRAIN_API_TOKEN env var. New in v2:

  POST /services/{name}/restart   restart an allow-listed systemd unit or a docker container
  GET  /tailnet                   tailnet devices + exit node state
  POST /exitnode                  advertise exit node on/off, switch exit location (Proton WireGuard)
  GET  /adguard                   AdGuard Home stats
  POST /adguard/protection        AdGuard protection on/off
  POST /focus                     lock-in: block distracting services in AdGuard, restore after
  POST /ask   GET /ask/models     chat with the local Ollama model, streamed as NDJSON
  POST /inbox  GET /inbox  GET /inbox/{id}/file  DELETE /inbox/{id}
                                  drop box for Penotron photos, Anamnis audio, iPhone shares

a parthchhabra production
"""
from __future__ import annotations

from typing import Optional, Union

import json
import mimetypes
import os
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
from pathlib import Path

import httpx
import psutil
from fastapi import Body, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

VERSION = 2


def env_list(name: str, default: str = "") -> list[str]:
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


TOKEN = os.environ.get("BRAIN_API_TOKEN", "")
SERVICES = env_list("BRAIN_SERVICES", "brain-api,antara-ml,antara-frontend,antara-tunnel")
WOL = dict(x.split("=", 1) for x in env_list("BRAIN_WOL"))          # desktop=AA:BB:CC:DD:EE:FF
OLLAMA = os.environ.get("BRAIN_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
ASK_MODEL = os.environ.get("BRAIN_ASK_MODEL", "qwen2.5:7b-instruct")
ASK_SYSTEM = os.environ.get("BRAIN_ASK_SYSTEM", (
    "You are the brain of Parth's study desk. Parth is a Class 12 CBSE student preparing for JEE Main and "
    "applying to UK engineering degrees. Answer directly and briefly, as a sharp tutor would. Use plain text "
    "that reads well on a small screen: short paragraphs, no markdown tables, write maths inline like a = v²/r."))
ADGUARD = os.environ.get("BRAIN_ADGUARD_URL", "").rstrip("/")
ADGUARD_AUTH = (os.environ.get("BRAIN_ADGUARD_USER", ""), os.environ.get("BRAIN_ADGUARD_PASS", ""))
MURMUR = os.environ.get("BRAIN_MURMUR_URL", "").rstrip("/")
MURMUR_TOKEN = os.environ.get("BRAIN_MURMUR_TOKEN", "")
EXIT_DIR = Path(os.environ.get("BRAIN_EXIT_DIR", "/etc/wireguard/proton"))
EXIT_HELPER = os.environ.get("BRAIN_EXIT_HELPER", "/usr/local/bin/brain-exit-location")
STATE_DIR = Path(os.environ.get("BRAIN_STATE_DIR", Path.home() / ".local/share/brain-api"))
INBOX_DIR = Path(os.environ.get("BRAIN_INBOX_DIR", Path.home() / "brain-inbox"))
INBOX_MAX = int(os.environ.get("BRAIN_INBOX_MAX_MB", "40")) * 1024 * 1024
NAME_RE = re.compile(r"^[A-Za-z0-9_.@-]{1,64}$")

STATE_DIR.mkdir(parents=True, exist_ok=True)
INBOX_DIR.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="brain-api", version=str(VERSION), docs_url=None, redoc_url=None)
http = httpx.Client(timeout=8)


def auth(x_brain_token: str = Header("")):
    if not TOKEN or not secrets.compare_digest(x_brain_token.encode(), TOKEN.encode()):
        raise HTTPException(401, "bad token")


A = [Depends(auth)]


def sh(cmd: list[str], timeout: float = 20) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# ---------------------------------------------------------------- status
def _containers() -> list[dict]:
    if not shutil.which("docker"):
        return []
    r = sh(["docker", "ps", "-a", "--format", "{{json .}}"], timeout=10)
    out = []
    for line in r.stdout.splitlines():
        try:
            c = json.loads(line)
        except ValueError:
            continue
        out.append({"name": c.get("Names"), "state": c.get("State"), "status": c.get("Status"), "image": c.get("Image")})
    return sorted(out, key=lambda c: (c["state"] == "running", c["name"]))


def _temp() -> float | None:
    try:
        temps = psutil.sensors_temperatures()
    except (AttributeError, OSError):
        return None
    for key in ("coretemp", "k10temp", "cpu_thermal", "acpitz"):
        if temps.get(key):
            return round(max(t.current for t in temps[key]), 1)
    return None


def _ollama() -> dict:
    try:
        tags = http.get(f"{OLLAMA}/api/tags", timeout=2).json().get("models", [])
        return {"up": True, "models": len(tags)}
    except httpx.HTTPError:
        return {"up": False, "models": 0}


@app.get("/status", dependencies=A)
def status():
    return {
        "version": VERSION, "hostname": socket.gethostname(),
        "cpu": psutil.cpu_percent(interval=0.2), "ram": psutil.virtual_memory().percent,
        "disk": psutil.disk_usage("/").percent, "temp": _temp(),
        "uptime_s": int(time.time() - psutil.boot_time()), "load": [round(x, 2) for x in os.getloadavg()],
        # v1 shape kept on purpose: {"unit-name.service": "active"}
        "services": {f"{s}.service": sh(["systemctl", "is-active", f"{s}.service"]).stdout.strip() for s in SERVICES},
        "containers": _containers(), "ollama": _ollama(), "wol_targets": sorted(WOL),
    }


# ---------------------------------------------------------------- wake on lan
def magic_packet(mac: str):
    hexmac = re.sub(r"[^0-9a-fA-F]", "", mac)
    if len(hexmac) != 12:
        raise HTTPException(500, f"bad MAC configured: {mac}")
    payload = bytes.fromhex("FF" * 6 + hexmac * 16)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for port in (9, 7):
            s.sendto(payload, ("255.255.255.255", port))


@app.post("/wol/{target}", dependencies=A)
def wol(target: str):
    mac = WOL.get(target)
    if not mac:
        raise HTTPException(404, "unknown target")
    magic_packet(mac)
    return {"woke": target}


# ---------------------------------------------------------------- restart
@app.post("/services/{name}/restart", dependencies=A)
def restart(name: str):
    if not NAME_RE.match(name):
        raise HTTPException(400, "bad name")
    if name in SERVICES:
        r = sh(["sudo", "-n", "systemctl", "restart", f"{name}.service"], timeout=40)
    elif any(c["name"] == name for c in _containers()):
        r = sh(["docker", "restart", name], timeout=60)
    else:
        raise HTTPException(404, "not an allow-listed service or a container")
    if r.returncode:
        raise HTTPException(500, (r.stderr or r.stdout).strip()[-300:])
    return {"restarted": name}


# ---------------------------------------------------------------- tailnet + exit node
def _exit_locations() -> list[str]:
    names = sorted(p.stem for p in EXIT_DIR.glob("*.conf")) if EXIT_DIR.is_dir() else []
    return ["direct", *names]


def _exit_state() -> str:
    try:
        return (STATE_DIR / "exit-location").read_text().strip() or "direct"
    except OSError:
        return "direct"


@app.get("/tailnet", dependencies=A)
def tailnet():
    r = sh(["tailscale", "status", "--json"], timeout=10)
    if r.returncode:
        raise HTTPException(500, r.stderr.strip()[-200:])
    st = json.loads(r.stdout)
    me = st.get("Self", {})
    peers = []
    for p in [me, *st.get("Peer", {}).values()]:
        last = p.get("LastSeen") or ""
        peers.append({
            "name": p.get("HostName") or p.get("DNSName", "").split(".")[0], "os": p.get("OS"),
            "online": bool(p.get("Online")) or p is me, "ip": (p.get("TailscaleIPs") or [""])[0],
            "rx": p.get("RxBytes", 0), "tx": p.get("TxBytes", 0), "self": p is me,
            "last_seen": None if p.get("Online") or p is me or last.startswith("0001") else last[:16].replace("T", " "),
            # Peers sending lots through us are using us as their exit node.
            "exit": p is not me and p.get("RxBytes", 0) > 50_000_000,
        })
    prefs = sh(["tailscale", "debug", "prefs"], timeout=10)
    advertised = False
    try:
        advertised = "0.0.0.0/0" in (json.loads(prefs.stdout).get("AdvertiseRoutes") or [])
    except ValueError:
        pass
    return {"self": me.get("HostName"), "peers": peers,
            "exit": {"advertised": advertised, "location": _exit_state(), "locations": _exit_locations()}}


@app.post("/exitnode", dependencies=A)
def exitnode(location: Optional[str] = Body(None), advertise: Optional[bool] = Body(None)):
    if advertise is not None:
        r = sh(["sudo", "-n", "tailscale", "set", f"--advertise-exit-node={'true' if advertise else 'false'}"])
        if r.returncode:
            raise HTTPException(500, r.stderr.strip()[-200:])
    if location is not None:
        if location not in _exit_locations():
            raise HTTPException(404, "unknown location")
        r = sh(["sudo", "-n", EXIT_HELPER, location], timeout=60)
        if r.returncode:
            raise HTTPException(500, (r.stderr or r.stdout).strip()[-300:])
        (STATE_DIR / "exit-location").write_text(location)
    return {"location": _exit_state()}


# ---------------------------------------------------------------- adguard
def ag(method: str, path: str, **kw):
    if not ADGUARD:
        raise HTTPException(501, "BRAIN_ADGUARD_URL not set")
    r = http.request(method, f"{ADGUARD}/control/{path}", auth=ADGUARD_AUTH, **kw)
    if r.status_code >= 400:
        raise HTTPException(502, f"AdGuard {path}: {r.status_code}")
    return r.json() if r.content and r.headers.get("content-type", "").startswith("application/json") else {}


def _blocked_services() -> tuple[list[str], dict | None]:
    try:
        j = ag("GET", "blocked_services/get")          # v0.107.37+
        return list(j.get("ids") or []), j.get("schedule")
    except HTTPException:
        return list(ag("GET", "blocked_services/list") or []), None


def _set_blocked(ids: list[str], schedule):
    try:
        ag("PUT", "blocked_services/update", json={"ids": ids, "schedule": schedule or {"time_zone": "Local"}})
    except HTTPException:
        ag("POST", "blocked_services/set", json=ids)


def _focus_state() -> dict | None:
    try:
        return json.loads((STATE_DIR / "focus.json").read_text())
    except (OSError, ValueError):
        return None


@app.get("/adguard", dependencies=A)
def adguard():
    s = ag("GET", "stats")
    st = ag("GET", "status")
    q, b = s.get("num_dns_queries", 0), s.get("num_blocked_filtering", 0)
    flat = lambda rows: [[k, v] for row in rows or [] for k, v in row.items()]   # [{"x.com": 12}] -> [["x.com", 12]]
    return {"queries": q, "blocked": b, "blocked_pct": round(100 * b / q, 1) if q else 0,
            "protection": st.get("protection_enabled", True), "focus": _focus_state() is not None,
            "top_blocked": flat(s.get("top_blocked_domains"))[:6], "clients": flat(s.get("top_clients"))[:6],
            "hourly": (s.get("dns_queries") or [])[-24:]}


@app.post("/adguard/protection", dependencies=A)
def adguard_protection(enabled: bool = Body(..., embed=True)):
    try:
        ag("POST", "protection", json={"enabled": enabled})
    except HTTPException:
        ag("POST", "dns_config", json={"protection_enabled": enabled})
    return {"protection": enabled}


_focus_lock = threading.Lock()


@app.post("/focus", dependencies=A)
def focus(enabled: bool = Body(...), services: list[str] = Body(default_factory=list)):
    with _focus_lock:
        path = STATE_DIR / "focus.json"
        ids, schedule = _blocked_services()
        saved = _focus_state()
        if enabled:
            if saved is None:   # remember what was blocked before, once
                path.write_text(json.dumps({"before": ids, "since": time.time()}))
            _set_blocked(sorted(set(ids) | set(services)), schedule)
        else:
            _set_blocked(saved["before"] if saved else [i for i in ids if i not in services], schedule)
            path.unlink(missing_ok=True)
    return {"focus": enabled}


# ---------------------------------------------------------------- ask
@app.get("/ask/models", dependencies=A)
def ask_models():
    try:
        return {"models": [m["name"] for m in http.get(f"{OLLAMA}/api/tags").json().get("models", [])], "default": ASK_MODEL}
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Ollama: {e}") from e


@app.post("/ask", dependencies=A)
def ask(messages: list[dict] = Body(...), model: Optional[str] = Body(None)):
    body = {"model": model or ASK_MODEL, "stream": True,
            "messages": [{"role": "system", "content": ASK_SYSTEM}] + [
                {"role": m.get("role", "user"), "content": str(m.get("content", ""))} for m in messages[-20:]]}

    def gen():
        try:
            with httpx.stream("POST", f"{OLLAMA}/api/chat", json=body, timeout=httpx.Timeout(300, connect=5)) as r:
                if r.status_code >= 400:
                    yield json.dumps({"error": f"Ollama {r.status_code}: {r.read().decode()[:200]}"}) + "\n"
                    return
                for line in r.iter_lines():
                    if not line:
                        continue
                    j = json.loads(line)
                    if j.get("message", {}).get("content"):
                        yield json.dumps({"text": j["message"]["content"]}) + "\n"
                    if j.get("done"):
                        yield json.dumps({"done": True, "model": body["model"]}) + "\n"
        except httpx.HTTPError as e:
            yield json.dumps({"error": f"Ollama unreachable: {e}"}) + "\n"
    return StreamingResponse(gen(), media_type="application/x-ndjson")


# ---------------------------------------------------------------- inbox
def db():
    c = sqlite3.connect(INBOX_DIR / "inbox.sqlite3", timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY, source TEXT, kind TEXT, name TEXT,
                 path TEXT, ctype TEXT, text TEXT, at REAL, size INTEGER)""")
    return c


def _kind(ctype: str, text: str) -> str:
    if ctype.startswith("image/"):
        return "image"
    if ctype.startswith("audio/") or ctype.startswith("video/"):
        return "audio"
    if not ctype and re.match(r"^https?://\S+$", text.strip()):
        return "link"
    return "text" if not ctype else "file"


def _transcribe(item_id: str, path: str, ctype: str):
    """Audio from Anamnis gets a transcript via Murmur, in the background."""
    try:
        with open(path, "rb") as fh:
            r = httpx.post(f"{MURMUR}/v1/dictate", headers={"Authorization": f"Bearer {MURMUR_TOKEN}"},
                           files={"file": (Path(path).name, fh, ctype)}, data={"client_id": "brain-inbox"}, timeout=600)
        text = r.json().get("text", "") if r.status_code < 400 else ""
        if text:
            with db() as c:
                c.execute("UPDATE items SET text=? WHERE id=?", (text, item_id))
    except (httpx.HTTPError, OSError, ValueError):
        pass


@app.post("/inbox", dependencies=A)
def inbox_add(source: str = Form("unknown"), text: str = Form(""), file: Optional[UploadFile] = File(None)):
    item_id = f"{int(time.time())}-{secrets.token_hex(3)}"
    path, ctype, name, size = "", "", "", 0
    if file is not None and file.filename:
        ctype = file.content_type or mimetypes.guess_type(file.filename)[0] or "application/octet-stream"
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", file.filename)[-80:]
        day = INBOX_DIR / time.strftime("%Y-%m")
        day.mkdir(exist_ok=True)
        dest = day / f"{item_id}_{name}"
        with open(dest, "wb") as out:
            while chunk := file.file.read(1 << 20):
                size += len(chunk)
                if size > INBOX_MAX:
                    out.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(413, "file too large")
                out.write(chunk)
        path = str(dest)
    elif not text.strip():
        raise HTTPException(400, "send a file or text")
    kind = _kind(ctype, text)
    with db() as c:
        c.execute("INSERT INTO items VALUES(?,?,?,?,?,?,?,?,?)",
                  (item_id, source[:24], kind, name, path, ctype, text[:20000], time.time(), size))
    if kind == "audio" and MURMUR:
        threading.Thread(target=_transcribe, args=(item_id, path, ctype), daemon=True).start()
    return {"id": item_id, "kind": kind}


@app.get("/inbox", dependencies=A)
def inbox_list(limit: int = 40, source: Optional[str] = None):
    q = "SELECT id, source, kind, name, text, at, size FROM items"
    args: list = []
    if source:
        q += " WHERE source=?"
        args.append(source)
    q += " ORDER BY at DESC LIMIT ?"
    args.append(min(limit, 200))
    with db() as c:
        return {"items": [dict(r) for r in c.execute(q, args)]}


@app.get("/inbox/{item_id}/file", dependencies=A)
def inbox_file(item_id: str):
    with db() as c:
        r = c.execute("SELECT path, ctype, name FROM items WHERE id=?", (item_id,)).fetchone()
    if not r or not r["path"] or not Path(r["path"]).exists():
        raise HTTPException(404)
    return FileResponse(r["path"], media_type=r["ctype"], filename=r["name"])


@app.delete("/inbox/{item_id}", dependencies=A)
def inbox_delete(item_id: str):
    with db() as c:
        r = c.execute("SELECT path FROM items WHERE id=?", (item_id,)).fetchone()
        c.execute("DELETE FROM items WHERE id=?", (item_id,))
    if r and r["path"]:
        Path(r["path"]).unlink(missing_ok=True)
    return {"deleted": item_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.environ.get("BRAIN_HOST", "127.0.0.1"), port=int(os.environ.get("BRAIN_PORT", "8010")))
