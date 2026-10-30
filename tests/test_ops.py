import json
import threading
from datetime import UTC, datetime, timedelta
from http.client import HTTPConnection

import pytest

from andras import notify
from andras.ops import scheduler
from andras.store import jobs, notes, plans


@pytest.fixture(autouse=True)
def isolated_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(notes, "journal_path", lambda mission_id: tmp_path / f"{mission_id}.md")


@pytest.fixture
def config_notify(tmp_path):
    return {"database": str(tmp_path / "n.sqlite3"), "notify": {"channels": ["desktop"],
                                                                "levels": ["hit", "critical"]}}


def make_plan(conn, mission, channels=("email", "sms", "phone")):
    plan_id = plans.create(conn, mission.id, "prueba")
    for index, channel in enumerate(channels, start=1):
        plans.add_step(conn, plan_id, index, channel, why="x",
                       delay_hours=0 if index == 1 else 24, trigger="always")
    return plan_id


def test_jobs_materialize_one_per_pending_step(conn, mission):
    plan_id = make_plan(conn, mission)
    assert jobs.materialize(conn, plan_id) == 3
    assert jobs.materialize(conn, plan_id) == 0
    assert jobs.counts(conn, plan_id)["queued"] == 3


def test_jobs_backoff_gives_up(conn, mission):
    plan_id = make_plan(conn, mission, channels=("email",))
    jobs.materialize(conn, plan_id)
    job = jobs.due(conn, plan_id)[0]
    for _ in range(4):
        assert jobs.retry(conn, job["id"], "fallo")
    assert not jobs.retry(conn, job["id"], "último")
    assert conn.execute("SELECT state FROM jobs WHERE id=?", (job["id"],)).fetchone()["state"] == "failed"


def test_jobs_pause_and_resume(conn, mission):
    plan_id = make_plan(conn, mission)
    jobs.materialize(conn, plan_id)
    assert jobs.pause_all(conn, plan_id) == 3
    assert jobs.resume_all(conn, plan_id) == 3


def test_tick_delivers_due_step(conn, config, mission, monkeypatch):
    plan_id = make_plan(conn, mission)
    plans.set_status(conn, plan_id, "confirmed")
    monkeypatch.setattr(scheduler.executor, "run_step",
                        lambda *a, **k: type("O", (), {"ok": True, "text": "enviado", "error": ""})())
    monkeypatch.setattr(notify, "send", lambda *a, **k: ["desktop"])
    report = scheduler.tick(conn, config, plan_id, log=lambda *_: None)
    assert [e["position"] for e in report.executed] == [1]
    assert plans.get(conn, plan_id)["status"] == "running"
    assert conn.execute("SELECT status FROM plan_steps WHERE plan_id=? ORDER BY position",
                        (plan_id,)).fetchone()["status"] == "done"


def test_tick_waits_when_trigger_not_met(conn, config, mission, monkeypatch):
    plan_id = plans.create(conn, mission.id, "espera")
    plans.add_step(conn, plan_id, 1, "email", why="x", delay_hours=0, trigger="visited")
    plans.set_status(conn, plan_id, "confirmed")
    monkeypatch.setattr(notify, "send", lambda *a, **k: [])
    report = scheduler.tick(conn, config, plan_id, log=lambda *_: None)
    assert report.waiting == [1]
    assert report.executed == []


def test_tick_gives_up_on_stale_trigger(conn, config, mission, monkeypatch):
    plan_id = plans.create(conn, mission.id, "viejo")
    plans.add_step(conn, plan_id, 1, "email", why="x", delay_hours=0, trigger="visited")
    plans.set_status(conn, plan_id, "confirmed")
    jobs.materialize(conn, plan_id, from_now=datetime.now(UTC) - timedelta(hours=120))
    monkeypatch.setattr(notify, "send", lambda *a, **k: [])
    report = scheduler.tick(conn, config, plan_id, log=lambda *_: None)
    assert report.skipped == [1]


def test_tick_detects_captured_credentials(conn, config, mission, monkeypatch):
    plan_id = make_plan(conn, mission)
    plans.set_status(conn, plan_id, "confirmed")
    attack_id = "atk1"
    step = conn.execute("SELECT id FROM plan_steps WHERE plan_id=? ORDER BY position",
                        (plan_id,)).fetchone()
    plans.attach_attack(conn, step["id"], attack_id)
    step2 = conn.execute("SELECT id FROM plan_steps WHERE plan_id=? ORDER BY position DESC",
                         (plan_id,)).fetchone()
    conn.execute("UPDATE plan_steps SET attack_id=? WHERE id=?", (attack_id, step2["id"]))
    conn.execute("INSERT INTO attacks(id,mission_id,vector,angle,created_at)"
                 " VALUES(?,?,?,?,?)", (attack_id, mission.id, "email", "x", "2026-01-01"))
    conn.execute("INSERT INTO campaigns(id,scenario,recipient_hash,created_at)"
                 " VALUES('c1','s','h','2026-01-01')")
    conn.execute("INSERT INTO deliveries(attack_id,campaign_id,channel,target)"
                 " VALUES(?,?,?,?)", (attack_id, "c1", "email", "a@b.c"))
    conn.execute("INSERT INTO credentials(campaign_id,username,secret,captured_at)"
                 " VALUES('c1','ana','x','2026-01-01')")
    conn.execute("INSERT INTO success_criteria(plan_id,kind,spec,created_at)"
                 " VALUES(?,?,?,?)", (plan_id, "credential_captured", "{}", "2026-01-01"))
    monkeypatch.setattr(notify, "send", lambda *a, **k: ["desktop"])
    report = scheduler.tick(conn, config, plan_id, log=lambda *_: None)
    assert report.achieved
    assert plans.get(conn, plan_id)["status"] == "achieved"


def test_notify_skips_level_not_allowed(conn, config_notify, monkeypatch):
    monkeypatch.setattr(notify, "_dispatch", lambda *a, **k: None)
    assert notify.send(conn, config_notify, body="info", level="info") == []
    assert notify.send(conn, config_notify, body="hit", level="hit") == ["desktop"]


def test_notify_records_channel_failure(conn, config_notify, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("sin token")

    monkeypatch.setattr(notify, "_dispatch", boom)
    assert notify.send(conn, config_notify, body="x", level="hit") == []
    row = conn.execute("SELECT ok, error FROM notifications").fetchone()
    assert row["ok"] == 0 and "sin token" in row["error"]


def test_webhook_and_pixel(conn, tmp_path, monkeypatch):
    from http.server import HTTPServer

    from andras import server

    conn.execute("INSERT INTO campaigns(id,scenario,recipient_hash,created_at)"
                 " VALUES('tok','s','h','2026-01-01')")
    handler = server.handler_for(conn, capture=False, secret="k")
    httpd = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        port = httpd.server_address[1]
        client = HTTPConnection("127.0.0.1", port, timeout=5)
        client.request("GET", "/px/tok")
        assert client.getresponse().read().startswith(b"\x89PNG")
        assert conn.execute("SELECT event FROM events").fetchone()["event"] == "opened"

        body = json.dumps({"detail": "abierto"}).encode()
        signature = __import__("hmac").new(b"k", body, __import__("hashlib").sha256).hexdigest()
        client.request("POST", "/hook/tok/replied", body=body,
                       headers={"X-Andras-Signature": signature})
        assert client.getresponse().status == 204
        assert conn.execute("SELECT event FROM events ORDER BY id DESC").fetchone()[0] == "replied"

        client.request("POST", "/hook/tok/replied", body=b"{}",
                       headers={"X-Andras-Signature": "mala"})
        assert client.getresponse().status == 401
        client.request("GET", "/hook/tok/raro")
        assert client.getresponse().status == 400
        client.request("GET", "/hook/otro/replied")
        assert client.getresponse().status == 404
        client.close()
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_scheduler_active_plans(conn, mission):
    plan_id = make_plan(conn, mission, channels=("email",))
    plans.set_status(conn, plan_id, "confirmed")
    assert scheduler.active_plans(conn) == [plan_id]
    plans.set_status(conn, plan_id, "aborted")
    assert scheduler.active_plans(conn) == []


def test_daemon_pause_resume_abort(conn, config, mission, monkeypatch):
    from andras.ops import daemon

    monkeypatch.setattr(daemon, "load_config", lambda: config)
    plan_id = make_plan(conn, mission)
    plans.set_status(conn, plan_id, "confirmed")
    jobs.materialize(conn, plan_id)
    conn.commit()
    assert daemon.pause(plan_id) == 3
    assert plans.get(conn, plan_id)["status"] == "paused"
    conn.commit()
    assert daemon.resume(plan_id) == 3
    daemon.abort(plan_id)
    assert plans.get(conn, plan_id)["status"] == "aborted"


def test_webhook_captures_credentials(conn, tmp_path):
    from http.server import HTTPServer

    from andras import server

    conn.execute("INSERT INTO campaigns(id,scenario,recipient_hash,created_at)"
                 " VALUES('tok','s','h','2026-01-01')")
    httpd = HTTPServer(("127.0.0.1", 0), server.handler_for(conn, capture=True))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        client = HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5)
        body = b"username=ana&secret=pw&action=submitted"
        client.request("POST", "/tok", body=body,
                       headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert client.getresponse().status == 303
        row = conn.execute("SELECT username, secret FROM credentials").fetchone()
        assert (row["username"], row["secret"]) == ("ana", "pw")
        client.close()
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_notes_export_by_attack_isolates(conn, mission, tmp_path, monkeypatch):
    monkeypatch.setattr(notes, "journal_path", lambda mission_id: tmp_path / "j.md")
    notes.add(conn, mission.id, "uno", attack_id="atk1")
    notes.add(conn, mission.id, "dos", attack_id="atk2")
    path = notes.export_html(conn, mission.id, "atk1")
    assert "uno" in path.read_text() and "dos" not in path.read_text()
    assert path.name == "attack-atk1.html"


def test_pixel_added_to_html():
    from andras.delivery import pipeline

    html = pipeline._with_pixel("<body>x</body>", {"base_url": "https://a.b/"}, "tok")
    assert "https://a.b/px/tok" in html
    assert html.endswith("</body>")
    assert pipeline._with_pixel("<p>x</p>", {}, "tok") == "<p>x</p>"


def test_preflight_warns_without_hook_secret(config):
    from andras import preflight

    names = {check.name: check.level for check in preflight.run(config)}
    assert names["firma webhooks"] == preflight.WARN
    assert names["base_url"] == preflight.FAIL
    assert "entorno" in names
