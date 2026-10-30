"""Ejecución de un paso del plan: resuelve el destino, entrega y anota."""
from __future__ import annotations

import json

from andras.delivery import pipeline
from andras.models import Mission
from andras.store import evidence, notes

SENDABLE = {"email", "sms", "whatsapp", "telegram"}
PLACEHOLDER = {"phone": "voz", "social": "social"}


class MissingTarget(RuntimeError):
    pass


def intent(conn, mission) -> dict:
    row = conn.execute("SELECT intent FROM missions WHERE id=?", (mission.id,)).fetchone()
    return json.loads(row["intent"] or "{}") if row else {}


def resolve_target(conn, mission, channel: str) -> str:
    known = intent(conn, mission)
    if channel == "email":
        address = known.get("target_email")
        if address:
            return address
        for artifact in evidence.list_for(conn, mission.id, {"email"}):
            if artifact.verification != "inferred":
                return artifact.value
        raise MissingTarget("sin correo del objetivo")
    if channel in {"sms", "whatsapp", "telegram"}:
        phone = known.get("target_phone")
        if phone:
            return phone
        for artifact in evidence.list_for(conn, mission.id, {"phone", "username"}):
            return artifact.value
        raise MissingTarget(f"sin destino {channel}")
    return mission.target_name


def run_step(conn, config, step, *, force: bool = False) -> pipeline.Outcome:
    """Entrega un paso. Los pasos de voz y social devuelven la hoja para llamar."""
    mission_row = conn.execute("SELECT * FROM missions WHERE id=(SELECT mission_id FROM"
                               " plans WHERE id=?)", (step["plan_id"],)).fetchone()
    if not mission_row:
        raise MissingTarget("plan sin misión")
    mission = Mission(id=mission_row["id"], target_name=mission_row["target_name"],
                      goal=mission_row["goal"], target_role=mission_row["target_role"],
                      target_company=mission_row["target_company"], domain=mission_row["domain"])

    if step["channel"] in PLACEHOLDER:
        from andras.artifacts import render
        from andras.brain import planner

        attack = planner.load(conn, step["attack_id"]) if step["attack_id"] else None
        if not attack:
            return pipeline.Outcome(ok=False, error="paso sin guion")
        sheet = render.call_sheet(attack) if step["channel"] == "phone" else attack.get(
            "script", "")
        notes.add(conn, mission.id, f"guion del paso {step['position']} ({step['channel']}):\n"
                  f"{sheet}", kind="obs", plan_id=step["plan_id"], attack_id=step["attack_id"])
        return pipeline.Outcome(ok=True, text=sheet)

    if not step["attack_id"]:
        return pipeline.Outcome(ok=False, error="paso sin guion generado")
    try:
        target = resolve_target(conn, mission, step["channel"])
    except MissingTarget as exc:
        return pipeline.Outcome(ok=False, error=str(exc))
    outcome = pipeline.deliver(conn, config, step["attack_id"], target, force=force)
    notes.add(conn, mission.id,
              f"paso {step['position']} por {step['channel']} a {target}: "
              + ("enviado" if outcome.ok else f"fallo ({outcome.error})"),
              kind="obs" if outcome.ok else "incidencia",
              plan_id=step["plan_id"], attack_id=step["attack_id"])
    return outcome
