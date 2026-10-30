"""Orquestación de las fases del agente: preparar, investigar, conversar."""
from __future__ import annotations

from andras.agent import loop, prompts
from andras.agent.tools import ToolContext
from andras.brain import provider
from andras.evidence import dossier
from andras.recon import run as recon_run
from andras.store import budgets, evidence, notes, plans


def draft_plan(conn, mission, title: str = "") -> str:
    return plans.create(conn, mission.id, title or f"Campaña para {mission.target_name}")


def seed(conn, config, mission, log=print) -> dict:
    """Recon determinista previo: da material al agente sin gastar tokens.

    El resultado se resume en una nota para que el agente no repita los mismos colectores.
    """
    try:
        status = recon_run.run(conn, config, mission, log=log, budget=90)
    except SystemExit:
        status = {"added": 0, "errors": ["sin datos suficientes"], "skipped": []}
    arts = evidence.usable(conn, mission.id)
    if arts or status.get("added"):
        body = "\n".join(f"[{a.id}] {a.kind}: {a.value} ({a.verification})" for a in arts[:30])
        notes.add(conn, mission.id,
                  f"Recon automático previo: {status.get('added', 0)} nuevos, "
                  f"{len(arts)} usables.\n{body or 'sin usables.'}", kind="hallazgo",
                  title="recon inicial")
    return status


def context_for(conn, mission, answers: dict | None) -> str:
    data = dossier.load(conn, mission.id) or {}
    text = dossier.to_text(data) if data else ""
    recent = "\n".join(f"- {n.created_at} {n.title}: {n.body_md[:200]}"
                       for n in notes.for_mission(conn, mission.id, limit=20))
    return prompts.context_block(mission, text, recent,
                                 budgets.summary(conn, mission.id), answers)


def recon(ctx: ToolContext, policy, answers: dict | None = None) -> loop.LoopResult:
    context = context_for(ctx.conn, ctx.mission, answers)
    if not evidence.list_for(ctx.conn, ctx.mission.id):
        ctx.log("  sin artefactos: el agente empezará por OSINT básico")
    return loop.run(ctx, policy, system=prompts.RECON, context=context,
                    status=lambda: plan_state(ctx.conn, ctx.plan_id))


def chat(ctx: ToolContext, policy, history: list[dict], message: str,
         answers: dict | None = None) -> loop.LoopResult:
    context = context_for(ctx.conn, ctx.mission, answers)
    system = prompts.CHAT
    if history:
        context += "\n\nCONVERSACIÓN PREVIA:\n" + "\n".join(
            f"{turn['role']}: {turn['content']}" for turn in history[-8:])
    context += f"\n\nMENSAJE DEL OPERADOR: {message}"
    allow = ("read", "write")
    return loop.run(ctx, policy, system=system, context=context, allow=allow,
                    stop_when="plan_submit")


def plan_state(conn, plan_id: str) -> str:
    rows = plans.steps(conn, plan_id)
    channels = ", ".join(r["channel"] for r in rows) or "ninguno"
    criterion = conn.execute("SELECT kind FROM success_criteria WHERE plan_id=?",
                             (plan_id,)).fetchone()
    return (f"pasos={len(rows)} ({channels}); éxito={'sí' if criterion else 'no'}; "
            f"estado del plan={plans.get(conn, plan_id)['status']}. Faltan al menos "
            f"{max(0, 3 - len(rows))} pasos.")


def review_summary(conn, plan_id: str) -> str:
    plan = plans.get(conn, plan_id)
    if not plan:
        return "plan inexistente"
    lines = [f"{plan['title']}\n{plan['narrative']}\n"]
    for step in plans.steps(conn, plan_id):
        lines.append(f"{step['position']}. [{step['channel']}] +{step['delay_hours']}h "
                     f"{step['trigger']} — {step['why']}")
    rows = conn.execute("SELECT kind, spec FROM success_criteria WHERE plan_id=?",
                        (plan_id,)).fetchall()
    lines.append("\nÉxito: " + (", ".join(f"{r['kind']} {r['spec']}" for r in rows) or "sin definir"))
    return "\n".join(lines)


def can_run(config) -> str:
    if not provider.available(config, "agent"):
        return "no hay proveedor LLM disponible para el agente"
    return ""
