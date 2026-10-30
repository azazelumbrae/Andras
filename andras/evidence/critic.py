"""Crítico adversarial sobre el dossier y el plan.

Aplica al objetivo el modelo mental de OPSEC del operador: brillo, volumen, discrepancia,
complejidad emergente, fachada y dato asesino.
"""
from __future__ import annotations

import json

from andras.brain import prompts, provider
from andras.store import db, evidence

MAX_ARTIFACTS = 60


def audit(conn, config, mission) -> dict:
    arts = evidence.list_for(conn, mission.id)[:MAX_ARTIFACTS]
    if not arts:
        return {"verdict": "roto", "contradictions": [], "gaps": ["sin artifacts"],
                "kill_switches": []}
    detalle = "\n".join(f"[{a.id}] ({a.kind}, {a.verification}, {a.confidence}) "
                        f"{a.value} <- {a.source}" for a in arts)
    message = [{"role": "system", "content": prompts.CRITIC},
               {"role": "user", "content": f"Objetivo: {mission.target_name}\nMeta: {mission.goal}"
                                           f"\n\n{detalle}"}]
    data = provider.complete_json(config, message, phase="critic", temperature=0.3)
    result = {
        "verdict": data.get("verdict", "flojo"),
        "contradictions": _list(data.get("contradictions")),
        "gaps": _list(data.get("gaps")),
        "kill_switches": _list(data.get("kill_switches")),
    }
    conn.execute("INSERT INTO critics(mission_id,verdict,kill_switches,gaps,contradictions,"
                 "created_at) VALUES(?,?,?,?,?,?)",
                 (mission.id, result["verdict"], json.dumps(result["kill_switches"]),
                  json.dumps(result["gaps"]), json.dumps(result["contradictions"]), db.now()))
    return result


def latest(conn, mission_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM critics WHERE mission_id=? ORDER BY id DESC",
                       (mission_id,)).fetchone()
    if not row:
        return None
    return {"verdict": row["verdict"], "created_at": row["created_at"],
            "kill_switches": json.loads(row["kill_switches"]),
            "gaps": json.loads(row["gaps"]), "contradictions": json.loads(row["contradictions"])}


def _list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v)[:300] for v in value][:12]
