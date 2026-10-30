import json

import pytest

from andras.agent import gates, tools
from andras.store import budgets, notes, personas


@pytest.fixture(autouse=True)
def isolated_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(notes, "journal_path", lambda mission_id: tmp_path / f"{mission_id}.md")


@pytest.fixture
def ctx(conn, config, mission):
    return tools.ToolContext(conn=conn, config=config, mission=mission, run_id="run-test")


def test_migrations_create_new_tables(conn):
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version >= 19
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"notes", "personas", "jobs", "success_criteria", "notifications",
            "wallets", "wallet_txs", "net_profiles", "tool_runs"} <= names


def test_register_rejects_duplicates():
    @tools.tool("duplicada", description="x")
    def one(ctx):
        return {"text": "1"}

    with pytest.raises(ValueError):
        @tools.tool("duplicada", description="y")
        def two(ctx):
            return {"text": "2"}


def test_validate_types_and_required():
    spec = tools.get("note_write")
    with pytest.raises(tools.ToolError):
        tools.validate(spec, {})
    with pytest.raises(tools.ToolError):
        tools.validate(spec, {"body": 5})
    assert tools.validate(spec, {"body": " texto "})["body"] == "texto"
    assert "desconocido" not in tools.validate(spec, {"body": "x", "otro": 1})


def test_unknown_tool():
    with pytest.raises(tools.ToolError):
        tools.get("no_existe")


def test_invoke_writes_note_and_audits(ctx):
    result = tools.invoke(ctx, "note_write", {"body": "hallazgo: usa proveedor X", "kind": "hallazgo"})
    assert result["ok"]
    assert ctx.conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 1
    audit = ctx.conn.execute("SELECT tool, ok FROM tool_runs").fetchone()
    assert (audit["tool"], audit["ok"]) == ("note_write", 1)


def test_invoke_is_idempotent_without_repeat(ctx):
    args = {"body": "misma nota"}
    tools.invoke(ctx, "note_write", args)
    again = tools.invoke(ctx, "note_write", args)
    assert again.get("cached")
    tools.invoke(ctx, "note_write", args, repeat=True)
    assert ctx.conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 2


def test_invoke_dry_run_has_no_effect(ctx):
    ctx.dry_run = True
    result = tools.invoke(ctx, "note_write", {"body": "borrador"})
    assert result["ok"]
    assert ctx.conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 0


def test_invoke_captures_tool_failure(ctx):
    from andras.agent import tools as registry

    @registry.tool("revienta", description="x")
    def boom(ctx):
        raise RuntimeError("kaboom")

    result = registry.invoke(ctx, "revienta", {})
    assert not result["ok"]
    assert "kaboom" in result["text"]


def test_invoke_blocks_when_steps_exhausted(ctx):
    budgets.set_budget(ctx.conn, ctx.mission.id, max_steps=1)
    tools.invoke(ctx, "current_time", {})
    with pytest.raises(budgets.BudgetExceeded):
        tools.invoke(ctx, "current_time", {})


def test_gates_read_and_write_are_free():
    policy = gates.Policy()
    gates.authorize(policy, tools.get("current_time"), {})
    gates.authorize(policy, tools.get("note_write"), {"body": "x"})


def test_gates_send_needs_approval_unless_plan_confirmed():
    seen = []

    def deny(question, payload):
        seen.append(question)
        return False

    policy = gates.Policy(approver=deny)
    spec = tools.get("note_write")
    spec.permission = "send"
    try:
        with pytest.raises(tools.PermissionDenied):
            gates.authorize(policy, spec, {})
        policy.plan_confirmed = True
        gates.authorize(policy, spec, {})
    finally:
        spec.permission = "write"
    assert seen


def test_gates_spend_threshold():
    asked = []
    policy = gates.Policy(spend_threshold_usd=1.0, approver=lambda q, p: asked.append(q) or True)
    spec = tools.get("note_write")
    spec.permission = "spend"
    try:
        gates.authorize(policy, spec, {"amount": 0.5})
        assert not asked
        gates.authorize(policy, spec, {"amount": 5})
        assert asked
    finally:
        spec.permission = "write"


def test_notes_search(conn, mission):
    notes.add(conn, mission.id, "usa Microsoft 365 como proveedor")
    notes.add(conn, mission.id, "el telefono es de Madrid")
    hits = notes.search(conn, mission.id, "proveedor")
    assert len(hits) == 1
    assert "Microsoft" in hits[0].body_md


def test_notes_journal_is_append_only(conn, mission):
    notes.add(conn, mission.id, "primera")
    notes.add(conn, mission.id, "segunda")
    body = notes.journal_path(mission.id).read_text()
    assert body.index("primera") < body.index("segunda")


def test_notes_reject_empty(conn, mission):
    with pytest.raises(ValueError):
        notes.add(conn, mission.id, "   ")
    with pytest.raises(ValueError):
        notes.add(conn, mission.id, "x", kind="raro")


def test_personas_derive_and_burn(conn, mission):
    persona = personas.create(conn, mission.id, sender_name="Íñigo Peña", domain="Acme.COM")
    assert persona.address == "inigo.pena@acme.com"
    assert personas.burn(conn, mission.id) == 1


def test_budget_defaults_and_caps(conn, mission):
    budget = budgets.get(conn, mission.id)
    assert budget["max_steps"] == 40
    budgets.check_usd(conn, mission.id, 0.5)
    with pytest.raises(budgets.BudgetExceeded):
        budgets.check_usd(conn, mission.id, 99)
    budgets.charge_crypto(conn, mission.id, "btc", 0.0005)
    assert budgets.get(conn, mission.id)["spent_crypto"]["btc"] == 0.0005


def test_complete_tools_shapes_tool_calls(config, monkeypatch):
    from andras.brain import provider

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {
                "content": "", "tool_calls": [
                    {"id": "call_1", "type": "function",
                     "function": {"name": "dns_lookup", "arguments": "{\"domain\":\"x.com\"}"}}]}}],
                "usage": {"total_tokens": 21}}

    monkeypatch.setattr(provider.httpx, "post", lambda *a, **k: FakeResponse())
    monkeypatch.setattr(provider, "resolve",
                        lambda *a, **k: [provider.Target("ollama", "http://x", "m", "k")])
    result = provider.complete_tools(config, [{"role": "user", "content": "hola"}], [])
    assert result["tool_calls"][0]["name"] == "dns_lookup"
    assert json.loads(result["tool_calls"][0]["arguments"])["domain"] == "x.com"
    assert result["usage"]["total_tokens"] == 21


def test_preflight_marks_missing_models(tmp_path):
    from andras import preflight

    checks = preflight.run({"database": str(tmp_path / "p.sqlite3")})
    names = [c.name for c in checks]
    assert "modelos" in names and "tor" in names
    assert any(c.level == preflight.FAIL for c in checks)
