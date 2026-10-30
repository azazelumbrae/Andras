"""Herramientas de plan: el agente construye y valida la secuencia, sin enviar nada."""
from __future__ import annotations

import json

from andras.agent import tools
from andras.brain import campaign as campaign_mod
from andras.evidence import critic
from andras.store import evidence, hooks, plans

MAX_STEPS = 6


def _plan(ctx):
    if not ctx.plan_id:
        raise tools.ToolError("no hay plan en curso")
    plan = plans.get(ctx.conn, ctx.plan_id)
    if not plan:
        raise tools.ToolError("plan inexistente")
    if plan["status"] not in {"draft", "proposed"}:
        raise tools.ToolError(f"plan en estado {plan['status']}, no editable")
    return plan


@tools.tool("plan_set_title", permission="write",
            description="Pone título y narrativa al plan. La narrativa explica en 3-6 frases la "
                        "historia completa que se le va a contar al objetivo.",
            schema={"type": "object",
                    "properties": {"title": {"type": "string"},
                                   "narrative": {"type": "string"}},
                    "required": ["title", "narrative"]})
def plan_set_title(ctx, title: str, narrative: str) -> dict:
    _plan(ctx)
    ctx.conn.execute("UPDATE plans SET title=?, narrative=? WHERE id=?",
                     (title[:160], narrative, ctx.plan_id))
    return {"text": "título y narrativa guardados", "data": {"title": title}}


@tools.tool("plan_add_step", permission="write",
            description="Añade un paso al final del plan. Máximo 6. El primer paso no debe "
                        "llevar espera; los siguientes, sí.",
            schema={"type": "object",
                    "properties": {
                        "channel": {"type": "string", "enum": list(campaign_mod.SUPPORTED)},
                        "why": {"type": "string",
                                "description": "qué consigue este paso y con qué soporte"},
                        "delay_hours": {"type": "number"},
                        "trigger": {"type": "string", "enum": list(plans.TRIGGERS)},
                        "pack_id": {"type": "string"}},
                    "required": ["channel", "why"]})
def plan_add_step(ctx, channel: str, why: str, delay_hours: float = 0, trigger: str = "always",
                  pack_id: str = "") -> dict:
    _plan(ctx)
    current = plans.steps(ctx.conn, ctx.plan_id)
    if len(current) >= MAX_STEPS:
        raise tools.ToolError(f"el plan ya tiene {MAX_STEPS} pasos")
    step_id = plans.add_step(ctx.conn, ctx.plan_id, len(current) + 1, channel,
                             pack_id=pack_id, delay_hours=delay_hours, trigger=trigger, why=why)
    return {"text": f"paso {len(current) + 1} añadido: {channel} (+{delay_hours}h, "
                    f"{trigger}) · {_checklist(ctx)}", "data": {"step_id": step_id}}


def _checklist(ctx) -> str:
    rows = plans.steps(ctx.conn, ctx.plan_id)
    criterion = ctx.conn.execute("SELECT kind FROM success_criteria WHERE plan_id=?",
                                 (ctx.plan_id,)).fetchone()
    used = {r["channel"] for r in rows}
    missing = [c for c in ("email", "phone", "sms", "telegram", "whatsapp")
               if c not in used and c != (rows[-1]["channel"] if rows else "")]
    need = []
    if len(rows) < 3:
        need.append(f"añade {3 - len(rows)} paso(s)")
    if not criterion and len(rows) < 3:
        need.append("al llegar a 3 pasos el éxito se fija solo")
    if len(rows) >= 3:
        need.append("llama a plan_submit")
    return ("CHECKLIST: " + ("; ".join(need) if need else "plan completo")
            + (" · canales sin usar: " + ", ".join(missing[:3]) if missing else ""))


def _step(ctx, position: int):
    for step in plans.steps(ctx.conn, ctx.plan_id):
        if step["position"] == position:
            return step
    raise tools.ToolError(f"no hay paso {position}")


@tools.tool("plan_edit_step", permission="write",
            description="Cambia canal, espera, disparador o motivo de un paso existente.",
            schema={"type": "object",
                    "properties": {
                        "position": {"type": "integer"},
                        "channel": {"type": "string", "enum": list(campaign_mod.SUPPORTED)},
                        "why": {"type": "string"},
                        "delay_hours": {"type": "number"},
                        "trigger": {"type": "string", "enum": list(plans.TRIGGERS)},
                        "pack_id": {"type": "string"}},
                    "required": ["position"]})
def plan_edit_step(ctx, position: int, **fields) -> dict:
    _plan(ctx)
    step = _step(ctx, position)
    pairs = {k: v for k, v in fields.items() if v is not None and k in
             {"channel", "why", "delay_hours", "trigger", "pack_id"}}
    if not pairs:
        return {"text": "nada que cambiar", "data": {}}
    if "trigger" in pairs and pairs["trigger"] not in plans.TRIGGERS:
        raise tools.ToolError("disparador inválido")
    ctx.conn.execute(f"UPDATE plan_steps SET {', '.join(f'{k}=?' for k in pairs)} WHERE id=?",
                     (*pairs.values(), step["id"]))
    return {"text": f"paso {position} actualizado: {', '.join(pairs)} · {_checklist(ctx)}",
            "data": pairs}


@tools.tool("plan_move_step", permission="write",
            description="Mueve un paso a otra posición (1..6), reordenando el resto.",
            schema={"type": "object",
                    "properties": {"position": {"type": "integer"},
                                   "new_position": {"type": "integer"}},
                    "required": ["position", "new_position"]})
def plan_move_step(ctx, position: int, new_position: int) -> dict:
    _plan(ctx)
    rows = plans.steps(ctx.conn, ctx.plan_id)
    new_position = max(1, min(len(rows), new_position))
    order = [r["id"] for r in rows]
    try:
        moved = order.pop(position - 1)
    except IndexError as exc:
        raise tools.ToolError(f"no hay paso {position}") from exc
    order.insert(new_position - 1, moved)
    ctx.conn.execute("UPDATE plan_steps SET position=-position WHERE plan_id=?", (ctx.plan_id,))
    for index, step_id in enumerate(order, start=1):
        ctx.conn.execute("UPDATE plan_steps SET position=? WHERE id=?", (index, step_id))
    return {"text": f"paso {position} movido a {new_position}", "data": {}}


@tools.tool("plan_remove_step", permission="write",
            description="Elimina un paso y recompacta las posiciones.",
            schema={"type": "object", "properties": {"position": {"type": "integer"}},
                    "required": ["position"]})
def plan_remove_step(ctx, position: int) -> dict:
    _plan(ctx)
    step = _step(ctx, position)
    ctx.conn.execute("DELETE FROM plan_steps WHERE id=?", (step["id"],))
    for index, row in enumerate(plans.steps(ctx.conn, ctx.plan_id), start=1):
        ctx.conn.execute("UPDATE plan_steps SET position=? WHERE id=?", (index, row["id"]))
    return {"text": f"paso {position} eliminado · {_checklist(ctx)}", "data": {}}


@tools.tool("plan_set_success", permission="write",
            description="Define qué demuestra que el objetivo cayó. Tipos: `credential_captured` "
                        "(credenciales en la landing), `event` (un evento concreto), `manual`.",
            schema={"type": "object",
                    "properties": {"kind": {"type": "string",
                                            "enum": ["credential_captured", "event", "manual"]},
                                   "spec": {"type": "object"}},
                    "required": ["kind"]})
def plan_set_success(ctx, kind: str, spec: dict | None = None) -> dict:
    _plan(ctx)
    ctx.conn.execute("DELETE FROM success_criteria WHERE plan_id=?", (ctx.plan_id,))
    from andras.store.db import now

    ctx.conn.execute("INSERT INTO success_criteria(plan_id,kind,spec,created_at) VALUES(?,?,?,?)",
                     (ctx.plan_id, kind, json.dumps(spec or {}), now()))
    return {"text": f"criterio de éxito definido: {kind} · {_checklist(ctx)}",
            "data": spec or {}}


@tools.tool("plan_submit", permission="write",
            description="Cierra el plan y lo pasa al crítico. Si el crítico devuelve problemas, "
                        "corrige y vuelve a enviarlo. No envía nada al objetivo.",
            schema={"type": "object",
                    "properties": {"narrative": {"type": "string"}},
                    "required": ["narrative"]})
def plan_submit(ctx, narrative: str) -> dict:
    _plan(ctx)
    rows = plans.steps(ctx.conn, ctx.plan_id)
    problems = []
    if len(rows) < 3:
        problems.append(f"sólo {len(rows)} pasos (mínimo 3)")
    if len(rows) > MAX_STEPS:
        problems.append(f"{len(rows)} pasos (máximo {MAX_STEPS})")
    if problems:
        return {"text": "plan incompleto: " + "; ".join(problems), "data": {"problems": problems}}

    if not ctx.conn.execute("SELECT 1 FROM success_criteria WHERE plan_id=?",
                            (ctx.plan_id,)).fetchone():
        from andras.store.db import now

        ctx.conn.execute("INSERT INTO success_criteria(plan_id,kind,spec,created_at)"
                         " VALUES(?,?,?,?)",
                         (ctx.plan_id, "credential_captured", '{"origen": "defecto"}', now()))

    if not hooks.chosen(ctx.conn, ctx.mission.id):
        usable = evidence.usable(ctx.conn, ctx.mission.id)
        if not usable:
            return {"text": "no hay artefactos usables: el pretexto no tendría soporte",
                    "data": {"problems": ["sin evidencia"]}}
        first = usable[0]
        hook = hooks.add(ctx.conn, ctx.mission.id, title=f"soporte: {first.value}",
                         rationale="gancho automático desde el artefacto más creíble",
                         artifact_ids=[first.id], pain=60, verifiability=first.confidence)
        hooks.choose(ctx.conn, ctx.mission.id, hook.id)

    ctx.conn.execute("UPDATE plans SET narrative=? WHERE id=?", (narrative, ctx.plan_id))
    try:
        verdict = critic.audit(ctx.conn, ctx.config, ctx.mission)
    except Exception as exc:  # sin LLM el plan no se bloquea
        verdict = {"verdict": "sin crítico", "gaps": [str(exc)], "contradictions": [],
                   "kill_switches": []}
    blockers = verdict.get("contradictions", []) + verdict.get("kill_switches", [])
    if blockers and verdict.get("verdict") in {"roto", "flojo"}:
        return {"text": "el crítico pide correcciones antes de seguir:\n- "
                        + "\n- ".join(blockers[:6]),
                "data": {"problems": blockers, "verdict": verdict.get("verdict")}}
    plans.set_status(ctx.conn, ctx.plan_id, "proposed")
    return {"text": f"plan presentado al humano (crítico: {verdict.get('verdict')}). "
                    f"Ya puedes responder o cerrar.",
            "data": {"verdict": verdict.get("verdict"), "submitted": True}}
