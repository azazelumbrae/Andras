"""Herramientas de operación: avisar al operador, ajustar presupuesto y cerrar la campaña."""
from __future__ import annotations

from andras import notify
from andras.agent import tools
from andras.store import budgets


@tools.tool("notify_operator", permission="send",
            description="Avisa al operador por sus canales (escritorio, telegram…). Niveles: "
                        "`info` para progreso, `hit` cuando el objetivo cae, `critical` si algo "
                        "se rompe. No lo uses para narrar cada paso.",
            schema={"type": "object",
                    "properties": {"body": {"type": "string"},
                                   "level": {"type": "string",
                                             "enum": list(notify.TITLES)}},
                    "required": ["body"]})
def notify_operator(ctx, body: str, level: str = "info") -> dict:
    sent = notify.send(ctx.conn, ctx.config, body=body, level=level,
                       plan_id=ctx.plan_id or None, log=ctx.log)
    if not sent:
        return {"text": "aviso registrado pero ningún canal configurado lo entregó",
                "data": {"channels": []}}
    return {"text": f"aviso enviado por {', '.join(sent)}", "data": {"channels": sent}}


@tools.tool("set_budget", permission="write",
            description="Cambia los topes de la campaña (pasos, tokens, dólares o cripto). "
                        "Súbelos sólo si el operador lo autoriza.",
            schema={"type": "object",
                    "properties": {"max_steps": {"type": "integer"},
                                   "max_tokens": {"type": "integer"},
                                   "max_usd": {"type": "number"},
                                   "max_crypto": {"type": "object"}}})
def set_budget(ctx, **fields) -> dict:
    updated = budgets.set_budget(ctx.conn, ctx.mission.id,
                                 **{k: v for k, v in fields.items() if v is not None})
    return {"text": budgets.summary(ctx.conn, ctx.mission.id), "data": updated}


@tools.tool("plan_status", permission="read",
            description="Estado del plan en curso: pasos, criterio de éxito y jobs.",
            schema={"type": "object", "properties": {}})
def plan_status(ctx) -> dict:
    if not ctx.plan_id:
        return {"text": "no hay plan en curso", "data": {}}
    steps = list(ctx.conn.execute(
        "SELECT position, channel, status FROM plan_steps WHERE plan_id=? ORDER BY position",
        (ctx.plan_id,)))
    jobs = list(ctx.conn.execute(
        "SELECT state, COUNT(*) AS n FROM jobs WHERE plan_id=? GROUP BY state", (ctx.plan_id,)))
    body = "\n".join(f"{s['position']}. {s['channel']} — {s['status']}" for s in steps)
    jobs_text = ", ".join(f"{j['state']}={j['n']}" for j in jobs) or "sin jobs"
    return {"text": f"{body}\njobs: {jobs_text}", "data": {"steps": len(steps)}}
