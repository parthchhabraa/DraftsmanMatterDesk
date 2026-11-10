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


def test_artifact_shelf_from_share_sheet(app):
    with TestClient(app, client=("100.64.1.9", 5000)) as c:
        h = {"X-Device-Key": "device-secret"}
        shared = "Look at this https://claude.ai/artifact/15jeh2kKfXtk9tG3jtgLRQ?x=1 nice"
        r = c.post("/api/inbox", data={"source": "iphone", "text": shared}, headers=h)
        assert r.json()["kind"] == "artifact"
        c.post("/api/inbox", data={"source": "iphone", "text": shared}, headers=h)   # duplicate ignored
        shelf = app.state.desk.hub.get("desk")["artifacts"]
        assert [a["url"] for a in shelf] == ["https://claude.ai/artifact/15jeh2kKfXtk9tG3jtgLRQ"]
        d = app.state.desk
        d.store.artifact_title(shelf[0]["url"], "JEE 150 - Claude")
        assert d.hub.get("desk")["artifacts"][0]["title"] == "JEE 150"


def test_viewer_only_opens_https(app):
    with TestClient(app) as c:
        assert c.post("/api/viewer/open", json={"url": "http://evil.example"}).status_code == 400
        assert c.post("/api/viewer/open", json={"url": "https://claude.ai/artifact/abc"}).status_code == 200


def test_plan_block_and_one_tap_start(app):
    import datetime as dt
    with TestClient(app) as c:
        d = app.state.desk
        start = (dt.datetime.now() - dt.timedelta(minutes=10)).strftime("%H:%M")
        if start > "23:00":
            pytest.skip("too close to midnight for a 40 minute block")
        bid = c.post("/api/plan", json={"block": {"kind": "study", "subject": "Maths", "start": start, "minutes": 40, "days": []}}).json()["id"]
        blocks = d.clock.today_blocks()
        mine = next(b for b in blocks if b["id"] == bid)
        assert mine["end"] - mine["start"] == 40 * 60
        left = c.post(f"/api/plan/{bid}/start", json={"lockin": False}).json()["minutes"]
        assert 28 <= left <= 30 and d.study.active["subject"] == "Maths"
        d.study.end()
        assert c.post("/api/plan", json={"block": {"start": "25:00", "minutes": 30}}).status_code == 400
        # a block for another weekday is not in today's list
        other = (dt.date.today().weekday() + 1) % 7
        oid = c.post("/api/plan", json={"block": {"kind": "fixed", "label": "X", "start": "10:00", "minutes": 30, "days": [other]}}).json()["id"]
        assert all(b["id"] != oid for b in d.clock.today_blocks())


def test_timer_rings_snoozes_and_alarm_fires(app):
    import datetime as dt
    with TestClient(app) as c:
        d = app.state.desk
        t = c.post("/api/timers", json={"minutes": 1, "label": "Tea"}).json()
        d.clock.timers[0]["ends"] = 0
        d.clock.tick()
        assert d.hub.get("ring")["label"] == "Tea" and d.hub.get("timers") == []
        assert "ring" in d.system.wake_lock
        c.post("/api/ring/snooze", json={"minutes": 5})
        assert d.hub.get("ring") is None and d.hub.get("timers")[0]["label"] == "Tea"
        c.delete(f"/api/timers/{d.clock.timers[0]['id']}")
        assert d.hub.get("timers") == [] and t["id"]
        # one-time alarm for this minute fires once and switches itself off
        now = dt.datetime.now().strftime("%H:%M")
        aid = c.post("/api/alarms", json={"alarm": {"time": now, "label": "Up", "days": []}}).json()["id"]
        d.clock.tick(); d.clock.tick()
        assert d.hub.get("ring")["kind"] == "alarm"
        c.post("/api/ring/dismiss")
        d.clock.tick()
        assert d.hub.get("ring") is None
        assert next(a for a in d.hub.get("desk")["alarms"] if a["id"] == aid)["enabled"] is False


def test_sprint_end_rings_and_scores(app):
    with TestClient(app) as c:
        d = app.state.desk
        d.study.begin("Physics", 1, False)
        d.study.active["started"] -= 61
        d.study._tick()
        r = d.hub.get("ring")
        assert r["kind"] == "sprint" and r["subject"] == "Physics"
        c.post("/api/ring/dismiss")
        n = len(d.hub.get("desk")["scores"])
        assert c.post("/api/scores", json={"name": "AITS 5", "score": 141}).status_code == 200
        assert len(d.hub.get("desk")["scores"]) == n + 1
        assert c.post("/api/scores", json={"name": "bad", "score": 900}).status_code == 400
        st = d.hub.get("study")
        assert len(st["days14"]) == 14 and st["score_target"] == 150
