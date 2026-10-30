"""Dossier: agregación directa + destilación por LLM, siempre anclada a artifact ids."""
from __future__ import annotations

import json

from andras.brain import prompts, provider
from andras.store import db, evidence

FIELDS = ("identidad", "cargos", "empresas", "dominios", "emails", "telefonos", "perfiles",
          "filtraciones", "documentos", "infra", "repos", "coartadas", "ganchos",
          "puntos_debil", "ambiguedades")

KIND_TO_FIELD = {
    "person": "identidad", "company": "empresas", "domain": "dominios", "email": "emails",
    "phone": "telefonos", "social": "perfiles", "leak": "filtraciones", "breach": "filtraciones",
    "doc": "documentos", "infra": "infra", "repo": "repos", "recovery_fact": "coartadas",
}


def fallback(conn, mission_id: str) -> dict:
    out = {field: [] for field in FIELDS}
    out["resumen"] = ""
    for art in evidence.list_for(conn, mission_id):
        field = KIND_TO_FIELD.get(art.kind)
        if field and len(out[field]) < 40:
            out[field].append({"texto": art.value, "artifacts": [art.id]})
    return out


def build(conn, config, mission, log=print) -> dict:
    arts = evidence.usable(conn, mission.id, min_confidence=30)
    dossier = fallback(conn, mission.id)
    if not provider.available(config, "dossier") or not arts:
        _save(conn, mission.id, dossier)
        return dossier

    detalle = "\n".join(f"[{a.id}] ({a.kind}, {a.verification}, {a.confidence}) {a.value}"
                        for a in arts[:120])
    message = [{"role": "system", "content": prompts.DOSSIER},
               {"role": "user", "content": f"Objetivo: {mission.target_name} | cargo "
                                           f"{mission.target_role} | empresa {mission.target_company}"
                                           f" | dominio {mission.domain} | meta {mission.goal}\n\n"
                                           f"Artifacts:\n{detalle}"}]
    try:
        data = provider.complete_json(config, message, phase="dossier", temperature=0.2)
    except provider.LLMError as exc:
        log(f"  ! dossier por LLM falló ({exc}); uso agregación directa")
        _save(conn, mission.id, dossier)
        return dossier

    valid_ids = {a.id for a in arts}
    for field in FIELDS:
        value = data.get(field)
        if not isinstance(value, list):
            continue
        items = []
        for entry in value:
            text, ids = _entry(entry)
            ids = [i for i in ids if i in valid_ids]
            if text:
                items.append({"texto": text, "artifacts": ids})
        if items:
            dossier[field] = items[:40]
    if isinstance(data.get("resumen"), str):
        dossier["resumen"] = data["resumen"][:1500]
    _save(conn, mission.id, dossier)
    return dossier


def load(conn, mission_id: str) -> dict | None:
    row = conn.execute("SELECT json FROM dossiers WHERE mission_id=?", (mission_id,)).fetchone()
    return json.loads(row["json"]) if row else None


def to_text(dossier: dict, max_items: int = 15) -> str:
    lines = [f"Resumen: {dossier.get('resumen', '')}"]
    for field in FIELDS:
        values = [item["texto"] if isinstance(item, dict) else str(item)
                  for item in dossier.get(field) or []]
        if values:
            lines.append(f"{field.upper()}: " + "; ".join(values[:max_items]))
    return "\n".join(lines)


def artifact_ids(dossier: dict) -> set[int]:
    ids = set()
    for field in FIELDS:
        for item in dossier.get(field) or []:
            if isinstance(item, dict):
                ids.update(i for i in item.get("artifacts", []) if isinstance(i, int))
    return ids


def _entry(entry) -> tuple[str, list[int]]:
    if isinstance(entry, str):
        return entry[:300], []
    if isinstance(entry, dict):
        ids = [i for i in entry.get("artifacts", []) if isinstance(i, int)]
        return str(entry.get("texto", ""))[:300], ids
    return str(entry)[:300], []


def _save(conn, mission_id: str, dossier: dict) -> None:
    conn.execute("INSERT INTO dossiers(mission_id,json,updated_at) VALUES(?,?,?) "
                 "ON CONFLICT(mission_id) DO UPDATE SET json=excluded.json, "
                 "updated_at=excluded.updated_at",
                 (mission_id, json.dumps(dossier, ensure_ascii=False), db.now()))
