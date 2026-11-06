"""Run: python -m pytest tests -q   (no Pi hardware needed, runs in demo mode)"""
import time

import pytest
from fastapi.testclient import TestClient

from desk.config import load_config
from desk.server import create_app


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("MATTERDESK_DEMO", "1")
    monkeypatch.setenv("MATTERDESK__SERVER__DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MATTERDESK__SERVER__REMOTE_KEY", "remote-secret")
    monkeypatch.setenv("MATTERDESK__DEVICES__DEVICE_KEY", "device-secret")
    return create_app(load_config(tmp_path / "none.toml"))


def test_snapshot_has_every_topic(app):
    with TestClient(app) as c:
        time.sleep(1.5)
        with c.websocket_connect("/ws") as ws:
            snap = ws.receive_json()["snapshot"]
    for t in ("meta", "pi", "brain", "study", "desk", "devices", "music", "weather", "dpn", "lan"):
        assert t in snap, t


def test_remote_needs_key(app):
    with TestClient(app, client=("100.64.1.9", 5000)) as c:
        assert c.get("/").status_code == 401
        assert c.post("/api/tasks", json={"text": "x"}).status_code == 401
        r = c.get("/?key=remote-secret", follow_redirects=False)
        assert r.status_code in (302, 307) and "mdk" in r.cookies
        assert c.post("/api/tasks", json={"text": "x"}).status_code == 200


def test_device_key_only_reaches_device_endpoints(app):
    with TestClient(app, client=("100.64.1.9", 5000)) as c:
        h = {"X-Device-Key": "device-secret"}
        assert c.post("/api/devices/report", json={"device": "iphone", "battery": 0.41}, headers=h).status_code == 200
        assert app.state.desk.hub.get("devices")["iphone"]["battery"] == 41
        assert c.post("/api/tasks", json={"text": "x"}, headers=h).status_code == 401
        assert c.post("/api/devices/report", json={"device": "fridge"}, headers=h).status_code == 400


def test_sprint_logs_and_focus_trigger(app):
    with TestClient(app) as c:
        d = app.state.desk
        c.post("/api/devices/report", json={"device": "iphone", "focus": "Study"})
        assert d.study.active and d.study.active["lockin"]
        assert d.hub.get("adguard")["focus"] is True
        d.study.active["started"] -= 120          # pretend two minutes passed
        c.post("/api/devices/report", json={"device": "iphone", "focus": None})
        assert d.study.active is None
        assert d.hub.get("adguard")["focus"] is False
        assert d.hub.get("study")["today_min"] >= 2


def test_desk_data_roundtrip(app):
    with TestClient(app) as c:
        c.post("/api/tasks", json={"text": "Redo Q14"})
        t = next(x for x in app.state.desk.hub.get("desk")["tasks"] if x["text"] == "Redo Q14")
        c.post(f"/api/tasks/{t['id']}/toggle")
        assert next(x for x in app.state.desk.hub.get("desk")["tasks"] if x["id"] == t["id"])["done"]
        assert c.post("/api/countdowns", json={"label": "JEE", "date": "not-a-date"}).status_code == 400
        c.post("/api/countdowns", json={"label": "JEE", "date": "2027-01-22"})
        assert any(x["label"] == "JEE" for x in app.state.desk.hub.get("desk")["countdowns"])


def test_ask_streams(app):
    with TestClient(app) as c:
        r = c.post("/api/ask", json={"messages": [{"role": "user", "content": "torque?"}]})
        assert r.status_code == 200 and "torque" in r.text


def test_mac_command_queue(app, monkeypatch):
    with TestClient(app) as c:
        d = app.state.desk
        monkeypatch.setattr(d.cfg, "demo", False)
        c.post("/api/devices/mac/clipboard", json={"arg": "hello"})
        cmds = c.get("/api/agent/mac/commands?wait=1").json()["commands"]
        assert cmds and cmds[0]["cmd"] == "clipboard" and cmds[0]["arg"] == "hello"
        assert c.post("/api/devices/mac/rm-rf", json={"arg": None}).status_code == 400
