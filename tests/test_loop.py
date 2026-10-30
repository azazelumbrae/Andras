import pytest

from andras.agent import clarify, gates, loop, plan_tools
from andras.agent.tools import ToolContext
from andras.brain import provider
from andras.models import Finding
from andras.store import budgets, evidence, notes, plans


@pytest.fixture(autouse=True)
def isolated_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(notes, "journal_path", lambda mission_id: tmp_path / f"{mission_id}.md")


@pytest.fixture
def ctx(conn, config, mission):
    plan_id = plans.create(conn, mission.id, "borrador")
    return ToolContext(conn=conn, config=config, mission=mission, run_id="r", plan_id=plan_id,
                       log=lambda *_: None)


def script(monkeypatch, turns):
    """Devuelve los turnos en orden y falla si se pide uno de más."""
    queue = list(turns)

    def fake(config, messages, tools_, **kwargs):
        if not queue:
            raise provider.LLMError("guion agotado")
        turn = queue.pop(0)
        return {"content": turn.get("content", ""), "tool_calls": turn.get("calls", []),
                "usage": {"total_tokens": turn.get("tokens", 100)},
                "provider": "fake", "model": "fake"}

    monkeypatch.setattr(provider, "complete_tools", fake)


def call(name, **args):
    import json

    return {"id": f"c_{name}", "name": name, "arguments": json.dumps(args)}


def test_loop_runs_tools_and_stops_on_submit(ctx, monkeypatch):
    evidence.add(ctx.conn, ctx.mission.id, Finding(
        kind="email", value="ana@acme.com", source="https://a.com", source_domain="a.com",
        confidence=90))
    for index, channel in enumerate(["email", "sms", "phone"], start=1):
        plan_tools.plan_add_step(ctx, channel=channel, why=f"paso {index}",
                                 delay_hours=0 if index == 1 else 24)
    plan_tools.plan_set_success(ctx, kind="credential_captured")
    monkeypatch.setattr(provider, "complete_json",
                        lambda *a, **k: {"verdict": "solido", "contradictions": [],
                                         "gaps": [], "kill_switches": []})
    script(monkeypatch, [
        {"calls": [call("note_write", body="hola")]},
        {"calls": [call("plan_submit", narrative="historia completa")]},
    ])
    result = loop.run(ctx, gates.Policy(), system="s", context="c")
    assert result.reason == "submitted"
    assert plans.get(ctx.conn, ctx.plan_id)["status"] == "proposed"


def test_loop_records_tool_messages(ctx, monkeypatch):
    seen = {}

    def fake(config, messages, tools_, **kwargs):
        if not seen:
            seen["first"] = list(messages)
            return {"content": "", "tool_calls": [call("current_time")],
                    "usage": {"total_tokens": 10}, "provider": "f", "model": "f"}
        seen["second"] = list(messages)
        return {"content": "listo", "tool_calls": [], "usage": {"total_tokens": 10},
                "provider": "f", "model": "f"}

    monkeypatch.setattr(provider, "complete_tools", fake)
    result = loop.run(ctx, gates.Policy(), system="s", context="c",
                      status=lambda: "estado del plan=proposed")
    assert result.reason == "done"
    roles = [m["role"] for m in seen["second"]]
    assert "tool" in roles
    assert seen["second"][-1]["tool_call_id"] == "c_current_time"


def test_loop_stops_at_step_cap(ctx, monkeypatch):
    budgets.set_budget(ctx.conn, ctx.mission.id, max_steps=2)
    script(monkeypatch, [
        {"calls": [call("note_write", body="a"), call("note_write", body="b")]},
        {"calls": [call("note_write", body="c")]}])
    result = loop.run(ctx, gates.Policy(), system="s", context="c")
    assert result.reason in {"steps", "budget"}
    assert result.steps <= 4


def test_loop_honours_should_stop(ctx, monkeypatch):
    script(monkeypatch, [{"calls": [call("current_time")]}] * 2)
    result = loop.run(ctx, gates.Policy(), system="s", context="c",
                      should_stop=lambda: True)
    assert result.reason == "stopped"
    assert result.steps == 0


def test_loop_reports_llm_failure(ctx, monkeypatch):
    monkeypatch.setattr(provider, "complete_tools",
                        lambda *a, **k: (_ for _ in ()).throw(provider.LLMError("caído")))
    result = loop.run(ctx, gates.Policy(), system="s", context="c")
    assert result.reason == "llm_error"
    assert "caído" in result.message


def test_loop_denies_send_without_confirmation(ctx, monkeypatch):
    spec = __import__("andras.agent.tools", fromlist=["get"]).get("current_time")
    spec.permission = "send"
    try:
        script(monkeypatch, [{"calls": [call("current_time")]},
                             {"content": "fin", "calls": []}])
        result = loop.run(ctx, gates.Policy(approver=lambda q, p: False), system="s",
                          context="c", status=lambda: "estado del plan=proposed")
        assert result.reason == "done"
        assert "denegado" in (result.tool_trace or [""])[0]
    finally:
        spec.permission = "read"


def test_loop_writes_transcript(ctx):
    assert loop.transcript_path(ctx.run_id).name == "r.jsonl"


def test_plan_tools_edit_move_remove(ctx):
    for channel in ["email", "sms", "phone"]:
        plan_tools.plan_add_step(ctx, channel=channel, why="x")
    plan_tools.plan_edit_step(ctx, position=2, channel="telegram", delay_hours=3)
    steps = plans.steps(ctx.conn, ctx.plan_id)
    assert steps[1]["channel"] == "telegram" and steps[1]["delay_hours"] == 3
    plan_tools.plan_move_step(ctx, position=3, new_position=1)
    assert plans.steps(ctx.conn, ctx.plan_id)[0]["channel"] == "phone"
    plan_tools.plan_remove_step(ctx, position=1)
    assert [s["position"] for s in plans.steps(ctx.conn, ctx.plan_id)] == [1, 2]


def test_plan_add_rejects_unknown_channel(ctx):
    from andras.agent import tools

    with pytest.raises(tools.ToolError):
        tools.validate(tools.get("plan_add_step"), {"channel": "fax", "why": "x"})


def test_plan_submit_requires_three_steps(ctx):
    plan_tools.plan_add_step(ctx, channel="email", why="x")
    result = plan_tools.plan_submit(ctx, "narrativa")
    assert "incompleto" in result["text"]


def test_plan_submit_sets_default_criterion(ctx, monkeypatch):
    evidence.add(ctx.conn, ctx.mission.id, Finding(
        kind="email", value="ana@acme.com", source="https://a.com", source_domain="a.com",
        confidence=90))
    for channel in ["email", "sms", "phone"]:
        plan_tools.plan_add_step(ctx, channel=channel, why="x")
    result = plan_tools.plan_submit(ctx, "narrativa")
    assert not result["data"].get("problems")
    row = ctx.conn.execute("SELECT kind FROM success_criteria").fetchone()
    assert row["kind"] == "credential_captured"


def test_clarify_rejects_garbage_and_falls_back(config, mission, monkeypatch):
    monkeypatch.setattr(provider, "complete_json", lambda *a, **k: {"questions": "nada"})
    questions = clarify.generate(config, mission)
    assert len(questions) >= 4
    assert all(q["options"] for q in questions)


def test_clarify_accepts_valid_payload(config, mission, monkeypatch):
    payload = {"questions": [
        {"id": f"q{i}", "question": f"¿pregunta {i}?", "options": ["a", "b"]}
        for i in range(7)]}
    monkeypatch.setattr(provider, "complete_json", lambda *a, **k: payload)
    assert len(clarify.generate(config, mission)) == 6


def test_loop_pushes_model_that_stops_early(ctx, monkeypatch):
    notes_script = [{"content": "ya veremos", "calls": []},
                    {"calls": [call("note_write", body="sigo")]},
                    {"content": "fin", "calls": []}]
    script(monkeypatch, notes_script)
    result = loop.run(ctx, gates.Policy(), system="s", context="c",
                      status=lambda: "pasos=0; estado del plan=draft")
    assert result.steps >= 1
    assert result.reason in {"done", "llm_error"}


def test_trim_keeps_budget_and_marks_history():
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "encargo"}]
    for index in range(40):
        messages.append({"role": "assistant", "content": "x" * 500})
        messages.append({"role": "tool", "tool_call_id": str(index), "content": "y" * 3000})
    loop._trim(messages)
    size = len(__import__("json").dumps(messages))
    assert size <= loop.MAX_CONTEXT
    assert messages[0]["role"] == "system"
    assert messages[1]["content"] == "encargo"
    assert messages[2]["content"].startswith("(ya hecho:")


def test_trim_handles_openai_tool_call_shape():
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "e"}]
    for index in range(30):
        messages.append({"role": "assistant", "content": "", "tool_calls": [
            {"id": str(index), "type": "function",
             "function": {"name": "current_time", "arguments": "{}"}}]})
        messages.append({"role": "tool", "tool_call_id": str(index), "content": "z" * 3000})
    loop._trim(messages)
    assert loop._sane(messages)[0]["role"] == "system"
    assert all(m["role"] != "tool" or messages[i - 1]["role"] == "assistant"
               for i, m in enumerate(messages[1:], start=1))


def test_finalize_completes_plan(conn, config, mission):
    from andras.agent import runner
    from andras.store import plans

    plan_id = plans.create(conn, mission.id, "a medias")
    plans.add_step(conn, plan_id, 1, "email", why="x", delay_hours=0, trigger="always")
    note = runner.finalize(conn, plan_id, mission)
    assert "cerrado por el sistema" in note
    assert len(plans.steps(conn, plan_id)) == 3
    assert plans.get(conn, plan_id)["status"] == "proposed"
    assert conn.execute("SELECT 1 FROM success_criteria WHERE plan_id=?",
                        (plan_id,)).fetchone()


def test_finalize_ignores_confirmed_plan(conn, mission):
    from andras.agent import runner
    from andras.store import plans

    plan_id = plans.create(conn, mission.id, "hecho")
    plans.set_status(conn, plan_id, "confirmed")
    assert runner.finalize(conn, plan_id, mission) == ""


def test_ask_operator_without_tty_picks_first(monkeypatch):
    import sys

    from andras import cli

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    assert cli._ask_operator("¿seguir?", ("Sí", "No")) == "Sí"
    assert cli._ask_operator("¿seguir?") == ""


def test_spoof_advice_mentions_dmarc(conn, ctx, monkeypatch):
    from andras.agent import channel_tools

    monkeypatch.setattr(channel_tools, "_dig",
                        lambda name, kind: ["v=DMARC1; p=reject"] if "_dmarc" in name else [])
    result = channel_tools.spoof_advice(ctx, "acme.com", "Acme")
    assert "p=reject" in result["text"]
    assert result["data"]["dmarc"] == "reject"
