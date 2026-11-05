"""HTTP + websocket surface of the desk.

The Pi's own Chromium talks to 127.0.0.1 and needs no key. Anything else (your
phone or Mac over Tailscale) needs [server] remote_key once, via /?key=..., which
sets a cookie. Mac agent and iPhone Shortcuts use [devices] device_key in the
X-Device-Key header and can only reach the device endpoints.
"""
from __future__ import annotations

import asyncio
import contextlib
import hmac

import httpx
from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import ROOT, Config
from .core import VERSION, Desk

UI = ROOT / "ui"
LOCAL = {"127.0.0.1", "::1", "localhost", "testclient"}


def _eq(a: str, b: str) -> bool:
    return bool(a and b) and hmac.compare_digest(a.encode(), b.encode())


def create_app(cfg: Config, desk: Desk | None = None) -> FastAPI:
    desk = desk or Desk(cfg)
    hub = desk.hub

    @contextlib.asynccontextmanager
    async def lifespan(app):
        hub.bind_loop(asyncio.get_running_loop())
        desk.start()
        yield
        desk.stop()

    app = FastAPI(title="MatterDesk", version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.desk = desk

    # ---------------- auth ----------------
    def is_local(req) -> bool:
        return (req.client.host if req.client else "") in LOCAL

    def ui_key_ok(req) -> bool:
        k = cfg.server.remote_key
        got = req.cookies.get("mdk") or req.headers.get("x-desk-key") or req.query_params.get("key") or ""
        return _eq(got, k)

    def device_key_ok(req) -> bool:
        return _eq(req.headers.get("x-device-key", ""), cfg.devices.device_key)

    def user(req: Request):
        if not (is_local(req) or ui_key_ok(req)):
            raise HTTPException(401, "Open the desk once with /?key=<remote_key>")

    def device(req: Request):
        if not (is_local(req) or ui_key_ok(req) or device_key_ok(req)):
            raise HTTPException(401, "Bad X-Device-Key")

    U = [Depends(user)]
    D = [Depends(device)]

    def run(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except (ValueError, RuntimeError, httpx.HTTPError) as e:
            raise HTTPException(400 if isinstance(e, ValueError) else 502, str(e)) from e

    # ---------------- pages ----------------
    @app.get("/", include_in_schema=False)
    def index(req: Request):
        if not is_local(req) and not ui_key_ok(req):
            return Response("MatterDesk: add ?key=<remote_key> to the address once.", status_code=401)
        resp = FileResponse(UI / "index.html", headers={"Cache-Control": "no-cache"})
        if req.query_params.get("key") and ui_key_ok(req):
            resp = RedirectResponse("/")
            resp.set_cookie("mdk", req.query_params["key"], max_age=3600 * 24 * 365, httponly=True, samesite="strict")
        return resp

    app.mount("/ui", StaticFiles(directory=UI), name="ui")

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": VERSION, "demo": cfg.demo}

    # ---------------- live state ----------------
    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        ok = (sock.client.host if sock.client else "") in LOCAL or _eq(sock.cookies.get("mdk", ""), cfg.server.remote_key)
        if not ok:
            await sock.close(code=4401)
            return
        await sock.accept()
        q = hub.attach()
        try:
            await sock.send_json({"snapshot": hub.snapshot(), "logs": list(hub.logs)[:80]})

            async def pump():
                while True:
                    await sock.send_text(await q.get())

            async def listen():
                while True:   # any message = the screen is being used
                    msg = await sock.receive_text()
                    if msg == "activity":
                        desk.system.activity()

            done, pending = await asyncio.wait([asyncio.create_task(pump()), asyncio.create_task(listen())],
                                               return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            for t in done:   # a closed socket ends one side; that is the normal exit
                t.exception()
        except WebSocketDisconnect:
            pass
        finally:
            hub.detach(q)

    # ---------------- system ----------------
    @app.post("/api/display/{action}", dependencies=U)
    def display(action: str):
        {"sleep": desk.system.sleep, "wake": desk.system.wake}.get(action, desk.system.activity)()
        return {"ok": True}

    @app.post("/api/power/{action}", dependencies=U)
    def power(action: str):
        if action not in ("reboot", "poweroff", "restart-desk"):
            raise HTTPException(400, "unknown action")
        desk.system.power(action)
        return {"ok": True}

    @app.get("/api/wifi", dependencies=U)
    def wifi():
        return {"networks": run(desk.system.wifi_scan)}

    @app.post("/api/wifi", dependencies=U)
    def wifi_connect(ssid: str = Body(...), password: str = Body("")):
        ok, msg = desk.system.wifi_connect(ssid, password)
        return {"ok": ok, "message": msg}

    @app.post("/api/ota", dependencies=U)
    def ota():
        desk.system.ota()
        return {"ok": True}

    @app.get("/api/diag/{test}", dependencies=U)
    def diag(test: str):
        return desk.system.diagnose(test)

    @app.get("/api/logs", dependencies=U)
    def logs():
        return {"logs": list(hub.logs)}

    # ---------------- music ----------------
    @app.post("/api/music/{action}", dependencies=U)
    def music(action: str, value: str | int | None = Body(None, embed=True)):
        run(desk.spotify.control, action, value)
        return {"ok": True}

    @app.get("/api/music/devices", dependencies=U)
    def music_devices():
        return {"devices": run(desk.spotify.devices)}

    # ---------------- study ----------------
    @app.post("/api/study/start", dependencies=U)
    def study_start(subject: str = Body(...), target_min: int | None = Body(None), lockin: bool = Body(False)):
        desk.study.begin(subject, target_min, lockin)
        return {"ok": True}

    @app.post("/api/study/pause", dependencies=U)
    def study_pause():
        desk.study.pause()
        return {"ok": True}

    @app.post("/api/study/stop", dependencies=U)
    def study_stop():
        return {"seconds": desk.study.end()}

    # ---------------- desk data ----------------
    s = desk.store

    @app.post("/api/notes", dependencies=U)
    def note(id: str | None = Body(None), body: str = Body(...), pinned: bool | None = Body(None)):
        return {"id": s.save_note(id, body, pinned)}

    @app.post("/api/tasks", dependencies=U)
    def task(text: str = Body(...), subject: str | None = Body(None)):
        if not text.strip():
            raise HTTPException(400, "empty task")
        s.add_task(text, subject=subject)
        return {"ok": True}

    @app.post("/api/tasks/{tid}/toggle", dependencies=U)
    def task_toggle(tid: str):
        s.toggle_task(tid)
        return {"ok": True}

    @app.post("/api/tasks/clear-done", dependencies=U)
    def task_clear():
        s.clear_done()
        return {"ok": True}

    @app.post("/api/cards", dependencies=U)
    def card(subject: str = Body(...), front: str = Body(...), back: str = Body(...)):
        s.add_card(subject, front, back)
        return {"ok": True}

    @app.post("/api/cards/{cid}/grade", dependencies=U)
    def card_grade(cid: str, knew: bool = Body(..., embed=True)):
        s.grade_card(cid, knew)
        return {"ok": True}

    @app.post("/api/countdowns", dependencies=U)
    def countdown(label: str = Body(...), date: str = Body(...), id: str | None = Body(None)):
        run(s.set_countdown, label, date, id)
        return {"ok": True}

    @app.delete("/api/{kind}/{item_id}", dependencies=U)
    def delete(kind: str, item_id: str):
        if kind == "inbox":
            run(desk.brain.inbox_delete, item_id)
            return {"ok": True}
        table = {"notes": "notes", "tasks": "tasks", "cards": "cards", "countdowns": "countdowns"}.get(kind)
        if not table:
            raise HTTPException(404)
        s.delete(table, item_id)
        return {"ok": True}

    # ---------------- brain ----------------
    b = desk.brain

    @app.post("/api/brain/wol/{target}", dependencies=U)
    def wol(target: str):
        out = run(b.wol, target)
        hub.note(f"Wake-on-LAN sent to {target}")
        return out

    @app.post("/api/brain/services/{name}/restart", dependencies=U)
    def restart(name: str):
        return run(b.restart_service, name)

    @app.post("/api/brain/exit", dependencies=U)
    def exit_node(location: str | None = Body(None), advertise: bool | None = Body(None)):
        return run(b.set_exit, location, advertise)

    @app.post("/api/brain/adguard", dependencies=U)
    def adguard(enabled: bool = Body(..., embed=True)):
        return run(b.adguard_protection, enabled)

    @app.post("/api/brain/focus", dependencies=U)
    def focus(enabled: bool = Body(..., embed=True)):
        return run(b.focus, enabled, cfg.study.lockin_block)

    @app.get("/api/ask/models", dependencies=U)
    def ask_models():
        return {"models": b.models()}

    @app.post("/api/ask", dependencies=U)
    def ask(messages: list[dict] = Body(...), model: str | None = Body(None)):
        if not b.configured:
            raise HTTPException(400, "Brain is not configured")
        msgs = [{"role": m.get("role", "user"), "content": str(m.get("content", ""))[:8000]} for m in messages[-20:]]

        def gen():
            try:
                yield from b.ask(msgs, model)
            except (RuntimeError, httpx.HTTPError) as e:
                yield f"\n\n[brain error: {e}]"
        return StreamingResponse(gen(), media_type="text/plain; charset=utf-8")

    @app.post("/api/dictate", dependencies=U)
    def dictate(file: UploadFile = File(...)):
        m = cfg.murmur
        if cfg.demo:
            return {"text": "Explain why the normal force on a banked curve has a horizontal part."}
        if not m.url:
            raise HTTPException(400, "Murmur is not configured")
        r = httpx.post(m.url.rstrip("/") + "/v1/dictate", headers={"Authorization": f"Bearer {m.token}"},
                       files={"file": (file.filename or "desk.webm", file.file.read(), file.content_type or "audio/webm")},
                       data={"client_id": "matterdesk"}, timeout=60)
        if r.status_code >= 400:
            raise HTTPException(502, f"Murmur: {r.text[:200]}")
        return {"text": r.json().get("text", "")}

    @app.get("/api/inbox/{item_id}/file", dependencies=U)
    def inbox_file(item_id: str):
        if cfg.demo:
            raise HTTPException(404, "demo")
        data, ctype = run(b.inbox_file, item_id)
        return Response(data, media_type=ctype, headers={"Cache-Control": "private, max-age=3600"})

    @app.post("/api/inbox/{item_id}/to-mac", dependencies=U)
    def inbox_to_mac(item_id: str):
        items = (hub.get("inbox") or {}).get("items", [])
        it = next((i for i in items if i["id"] == item_id), None)
        if not it:
            raise HTTPException(404)
        text = it.get("text") or ""
        if text.startswith("http"):
            return desk.devices.command("mac", "open", text)
        return desk.devices.command("mac", "clipboard", text or it.get("name", ""))

    # ---------------- devices (Mac agent, iPhone Shortcuts) ----------------
    @app.post("/api/devices/report", dependencies=D)
    async def report(req: Request):
        try:
            payload = await req.json()
        except ValueError:
            raise HTTPException(400, "send JSON") from None
        run(desk.devices.report, payload)
        return {"ok": True, "timer": hub.get("timer")}

    @app.get("/api/agent/{dev}/commands", dependencies=D)
    def agent_commands(dev: str, wait: float = 25):
        return {"commands": desk.devices.wait_commands(dev, min(wait, 50))}

    @app.post("/api/devices/{dev}/{cmd}", dependencies=U)
    def device_cmd(dev: str, cmd: str, arg: str | int | None = Body(None, embed=True)):
        return run(desk.devices.command, dev, cmd, arg)

    @app.post("/api/inbox", dependencies=D)
    def inbox_upload(source: str = Form("iphone"), text: str = Form(""), file: UploadFile | None = File(None)):
        content = file.file.read() if file else b""
        if not content and not text.strip():
            raise HTTPException(400, "send a file or text")
        item = run(b.inbox_upload, source[:24], (file.filename if file else "") or "note.txt", content,
                   (file.content_type if file else "") or "text/plain", text)
        hub.toast(f"New in inbox from {source}")
        return item

    # ---------------- network ----------------
    @app.post("/api/lan/scan", dependencies=U)
    def lan_scan(deep: bool = Body(False, embed=True)):
        desk.network.spawn(desk.network.scan, deep)
        return {"ok": True}

    @app.post("/api/lan/block", dependencies=U)
    def lan_block(mac: str = Body(...), on: bool = Body(...)):
        run(desk.network.block, mac, on)
        return {"ok": True}

    @app.post("/api/dpn", dependencies=U)
    def dpn(on: bool | None = Body(None), force_vpn: bool | None = Body(None), adblock: bool | None = Body(None),
            ssid: str | None = Body(None)):
        desk.network.dpn_set(on, force_vpn, adblock, ssid)
        return {"ok": True}

    @app.post("/api/airplay/{action}", dependencies=U)
    def airplay(action: str):
        run(desk.airplay.begin if action == "start" else desk.airplay.stop)
        return {"ok": True}

    @app.get("/api/bookmarks/{device_name}", dependencies=U)
    def bookmarks(device_name: str):
        if not desk.firebase.ready:
            return {"items": [], "note": "Firebase not configured"}
        return {"items": desk.firebase.bookmarks(device_name)}

    @app.exception_handler(HTTPException)
    async def http_err(req, exc):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    return app
