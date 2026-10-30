"""Selección de ganchos y generación de vectores de ataque."""
from __future__ import annotations

import json
import secrets

from andras.brain import packs, prompts, provider
from andras.models import Step, Vector
from andras.store import db, evidence, hooks

VALID_VECTORS = {"email", "sms", "phone", "social", "telegram", "whatsapp"}


def generate_hooks(conn, config, mission, limit: int = 5) -> list[hooks.Hook]:
    arts = evidence.usable(conn, mission.id, min_confidence=40)
    if not arts:
        raise SystemExit("No hay artifacts utilizables. Ejecuta `andras recon` primero.")
    detalle = "\n".join(f"[{a.id}] ({a.kind}, {a.verification}, {a.confidence}) {a.value}"
                        for a in arts[:80])
    message = [{"role": "system", "content": prompts.HOOK},
               {"role": "user", "content": f"Objetivo: {mission.target_name} "
                                           f"({mission.target_role} en {mission.target_company})\n"
                                           f"Meta: {mission.goal}\n\nArtifacts:\n{detalle}"}]
    data = provider.complete_json(config, message, phase="hooks", temperature=0.5)

    valid = {a.id for a in arts}
    hooks.clear(conn, mission.id)
    created = []
    for entry in data.get("hooks", [])[:limit]:
        ids = [i for i in entry.get("artifacts", []) if i in valid]
        if not ids or not entry.get("title"):
            continue
        created.append(hooks.add(conn, mission.id, title=str(entry["title"]),
                                 rationale=str(entry.get("rationale", ""))[:600],
                                 artifact_ids=ids, pain=_int(entry.get("pain")),
                                 verifiability=_int(entry.get("verifiability"))))
    return created


def build_attacks(conn, config, mission, channel: str | None = None,
                  count: int = 2) -> list[Vector]:
    chosen = hooks.chosen(conn, mission.id) or hooks.list_for(conn, mission.id)[:2]
    if not chosen:
        raise SystemExit("No hay ganchos. Ejecuta `andras hooks` primero.")
    has = {a.kind for a in evidence.usable(conn, mission.id, min_confidence=40)}
    built = []
    for pack in packs.choose(channel=channel, has=has, limit=count):
        vector = build_one(conn, config, mission, pack, chosen[0])
        if vector:
            built.append(vector)
    if not built:
        raise SystemExit("El LLM no devolvió vectores válidos")
    return built


def build_one(conn, config, mission, pack, hook, channel: str | None = None) -> Vector | None:
    """Genera y guarda un vector concreto para un pack y un gancho."""
    channel = channel or pack.channel
    arts = evidence.usable(conn, mission.id, min_confidence=40)
    by_id = {a.id: a for a in arts}
    weak = [a for i in hook.artifact_ids if (a := by_id.get(i))
            and a.verification != "corroborated"]
    soporte = "\n".join(f"[{a.id}] {a.kind}: {a.value}"
                        for i in hook.artifact_ids if (a := by_id.get(i)))
    message = [{"role": "system", "content": prompts.PLAN + provider.COMPLETENESS},
               {"role": "user", "content":
                f"Meta: {mission.goal}\nObjetivo: {mission.target_name}, "
                f"{mission.target_role} en {mission.target_company}\nCanal: {channel}\n\n"
                f"{pack.as_prompt()}\n\nGANCHO: {hook.title}\n"
                f"Por qué funciona: {hook.rationale}\nSoporte:\n{soporte}"}]
    data = provider.complete_json(config, message, phase="plan", temperature=0.7,
                                  max_tokens=4000)
    vector = _vector(data, channel, {hook.id})
    if not vector:
        return None
    vector.channel = channel
    attack_id = secrets.token_urlsafe(9)
    payload = json.dumps(_payload(vector, weak), ensure_ascii=False)
    conn.execute("INSERT INTO attacks(id,mission_id,vector,channel,angle,leverage,stance,"
                 "payload,script,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                 (attack_id, mission.id, vector.vector, vector.channel, vector.angle,
                  vector.leverage, vector.stance, payload, payload, "draft", db.now()))
    vector.id = attack_id  # type: ignore[attr-defined]
    return vector


def _vector(data: dict, channel: str, hook_ids: set[int]) -> Vector | None:
    vector = str(data.get("vector", channel))
    if vector not in VALID_VECTORS:
        return None
    steps = [Step(actor=s.get("actor", "ATACANTE"), action=str(s.get("action", "")),
                  script=str(s.get("script", "")))
             for s in data.get("steps", []) if s.get("script") and s.get("action")]
    if not steps:
        return None
    return Vector(vector=vector, channel=vector, angle=str(data.get("angle", vector))[:120],
                  leverage=str(data.get("leverage", ""))[:600],
                  stance=str(data.get("stance", ""))[:600],
                  hook_ids=sorted(hook_ids), steps=steps,
                  subject=str(data.get("subject", ""))[:160])


def _payload(vector: Vector, weak: list) -> dict:
    return {
        "angle": vector.angle, "leverage": vector.leverage, "stance": vector.stance,
        "subject": vector.subject,
        "steps": [{"actor": s.actor, "action": s.action, "script": s.script}
                  for s in vector.steps],
        "hook_ids": vector.hook_ids,
        "weak_evidence": [{"id": a.id, "kind": a.kind, "verification": a.verification}
                          for a in weak],
    }


def _int(value) -> int:
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return 50


def load(conn, attack_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM attacks WHERE id=?", (attack_id,)).fetchone()
    if not row:
        return None
    return {**json.loads(row["payload"]), "id": row["id"], "mission_id": row["mission_id"],
            "vector": row["vector"], "channel": row["channel"], "status": row["status"],
            "angle": row["angle"]}
