import pytest

from andras.artifacts import render
from andras.brain import campaign, planner, provider
from andras.delivery import pipeline
from andras.models import Finding
from andras.store import evidence, hooks, plans


@pytest.fixture
def chosen_hook(conn, mission):
    aid, _ = evidence.add(conn, mission.id, Finding(
        kind="email", value="ana@acme.com", source="https://a.com", source_domain="a.com",
        confidence=90))
    hook = hooks.add(conn, mission.id, title="proveedor real", rationale="r",
                     artifact_ids=[aid], pain=80, verifiability=70)
    hooks.choose(conn, mission.id, hook.id)
    return hook


def test_triggers():
    assert plans.fired("always", set())
    assert plans.fired("no_visit", set())
    assert not plans.fired("no_visit", {"visited"})
    assert plans.fired("visited", {"visited"})
    assert plans.fired("no_submit", {"visited"})
    assert not plans.fired("no_submit", {"visited", "submitted"})
    assert plans.fired("no_reply", {"sent"})


def test_add_step_rejects_bad_trigger(conn, mission):
    plan_id = plans.create(conn, mission.id, "x")
    with pytest.raises(ValueError):
        plans.add_step(conn, plan_id, 1, "email", trigger="quizas")


def test_steps_are_ordered(conn, mission):
    plan_id = plans.create(conn, mission.id, "x")
    plans.add_step(conn, plan_id, 2, "phone")
    plans.add_step(conn, plan_id, 1, "email")
    assert [s["position"] for s in plans.steps(conn, plan_id)] == [1, 2]


def test_fill_url_does_not_duplicate_scheme():
    assert pipeline._fill_url("https://{tracking_url}", "http://x/1") == "http://x/1"
    assert pipeline._fill_url("{tracking_url}", "http://x/1") == "http://x/1"


def test_campaign_validate_drops_unknown_channels():
    steps = campaign._validate({"steps": [
        {"channel": "email", "trigger": "always"},
        {"channel": "fax"},
        {"channel": "sms", "trigger": "no_visit", "delay_hours": "3"},
        {"channel": "phone", "trigger": "no_reply"},
    ]}, ["email", "sms", "phone"])
    assert [s["channel"] for s in steps] == ["email", "sms", "phone"]
    assert steps[1]["delay_hours"] == 3
    assert steps[1]["trigger"] == "no_visit"


def test_campaign_validate_rejects_short_sequence():
    with pytest.raises(SystemExit):
        campaign._validate({"steps": [{"channel": "email"}]}, ["email"])


def test_template_is_safe_without_llm():
    steps = campaign._template(["email", "phone"], 4)
    assert len(steps) == 4
    assert steps[0]["delay_hours"] == 0
    assert steps[0]["trigger"] == "always"


def test_compose_falls_back_to_template(conn, config, mission, chosen_hook, monkeypatch):
    monkeypatch.setattr(provider, "complete_json", lambda *a, **k: {
        "vector": "email", "angle": "a", "subject": "s",
        "steps": [{"actor": "ATACANTE", "action": "x", "script": "y {tracking_url}"}]})
    plan_id = campaign.compose(conn, config, mission, channels=["email"], length=3,
                               log=lambda *_: None)
    assert len(plans.steps(conn, plan_id)) == 3


def test_run_skips_undelivered_steps(conn, config, mission, chosen_hook):
    plan_id = plans.create(conn, mission.id, "x")
    plans.add_step(conn, plan_id, 1, "email", trigger="visited")
    result = campaign.run(conn, config, plan_id, target="a@b.co", skip_wait=True,
                          log=lambda *_: None)
    assert result[0]["status"] == "sin_guion" or result[0]["status"] == "no_disparado"


def test_email_body_joins_attacker_steps():
    payload = {"subject": "x", "steps": [
        {"actor": "ATACANTE", "action": "a", "script": "uno"},
        {"actor": "OBJETIVO", "action": "b", "script": "dos"},
        {"actor": "ATACANTE", "action": "c", "script": "tres"},
    ]}
    assert render._body(payload, "email") == "uno\n\ntres"
    assert render._body(payload, "sms") == "tres"


def test_planner_keeps_forced_channel(conn, config, mission, chosen_hook, monkeypatch):
    monkeypatch.setattr(provider, "complete_json", lambda *a, **k: {
        "vector": "phone", "angle": "a", "subject": "s",
        "steps": [{"actor": "ATACANTE", "action": "x", "script": "y"}]})
    from andras.brain import packs

    pack = packs.choose(channel="phone", limit=1)[0]
    vector = planner.build_one(conn, config, mission, pack, chosen_hook, channel="sms")
    assert vector.channel == "sms"
    row = conn.execute("SELECT channel FROM attacks").fetchone()
    assert row["channel"] == "sms"
