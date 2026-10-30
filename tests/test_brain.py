import pytest

from andras.brain import planner, provider
from andras.evidence import critic, dossier
from andras.models import Finding
from andras.store import evidence, hooks


@pytest.fixture
def con_config(conn, config):
    return conn, config


def _llm(monkeypatch, payload):
    monkeypatch.setattr(provider, "available", lambda *a, **k: True)
    monkeypatch.setattr(provider, "complete_json", lambda *a, **k: payload)


def test_hooks_keep_only_valid_artifact_ids(conn, config, mission, monkeypatch):
    aid, _ = evidence.add(conn, mission.id, Finding(kind="email", value="a@acme.com", source="x", confidence=90))
    _llm(monkeypatch, {"hooks": [
        {"title": "válido", "rationale": "r", "artifacts": [aid], "pain": 90, "verifiability": 80},
        {"title": "inventado", "rationale": "r", "artifacts": [999], "pain": 90, "verifiability": 90},
    ]})
    created = planner.generate_hooks(conn, config, mission)
    assert [h.title for h in created] == ["válido"]
    assert created[0].score == 86


def test_hooks_without_artifacts_fails(conn, config, mission):
    with pytest.raises(SystemExit):
        planner.generate_hooks(conn, config, mission)


def test_plan_builds_vector(conn, config, mission, monkeypatch):
    aid, _ = evidence.add(conn, mission.id, Finding(kind="email", value="a@acme.com", source="x", confidence=90))
    hook = hooks.add(conn, mission.id, title="proveedor", rationale="r",
                     artifact_ids=[aid], pain=80, verifiability=70)
    hooks.choose(conn, mission.id, hook.id)
    _llm(monkeypatch, {"vector": "email", "angle": "factura", "leverage": "proveedor real",
                       "stance": "cobro",
                       "steps": [{"actor": "ATACANTE", "action": "enviar", "script": "Hola {tracking_url}"}]})
    built = planner.build_attacks(conn, config, mission, count=1)
    assert built and built[0].vector == "email"
    row = conn.execute("SELECT payload FROM attacks").fetchone()
    assert "weak_evidence" in row["payload"]


def test_plan_drops_invalid_vector(conn, config, mission, monkeypatch):
    aid, _ = evidence.add(conn, mission.id, Finding(kind="email", value="a@acme.com", source="x", confidence=90))
    hook = hooks.add(conn, mission.id, title="t", rationale="r", artifact_ids=[aid],
                     pain=80, verifiability=70)
    hooks.choose(conn, mission.id, hook.id)
    _llm(monkeypatch, {"vector": "fax", "angle": "a", "steps": [
        {"actor": "ATACANTE", "action": "x", "script": "y"}]})
    with pytest.raises(SystemExit):
        planner.build_attacks(conn, config, mission, count=1)


def test_dossier_merges_only_existing_ids(conn, config, mission, monkeypatch):
    aid, _ = evidence.add(conn, mission.id, Finding(kind="email", value="a@acme.com", source="x", confidence=90))
    _llm(monkeypatch, {"resumen": "ok", "emails": [
        {"texto": "a@acme.com", "artifacts": [aid]},
        {"texto": "falso@x.co", "artifacts": [404]},
    ]})
    data = dossier.build(conn, config, mission, log=lambda *_: None)
    assert data["emails"][0]["texto"] == "a@acme.com"
    assert data["emails"][1]["artifacts"] == []


def test_critic_persists(conn, config, mission, monkeypatch):
    evidence.add(conn, mission.id, Finding(kind="email", value="a@acme.com", source="x", confidence=90))
    _llm(monkeypatch, {"verdict": "flojo", "kill_switches": ["el dominio expiró"],
                       "gaps": ["sin teléfono"], "contradictions": []})
    result = critic.audit(conn, config, mission)
    assert result["verdict"] == "flojo"
    assert critic.latest(conn, mission.id)["kill_switches"] == ["el dominio expiró"]
