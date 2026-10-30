"""Dossier estructurado del objetivo, construido a partir de artifacts."""
import json

from . import db, llm

FALLBACK_KEYS = {
    "identidad": ("person", "nombre"),
    "cargos": ("person", "cargo"),
    "empresas": ("company",),
    "dominios": ("domain",),
    "emails": ("email",),
    "telefonos": ("phone",),
    "perfiles": ("social",),
    "filtraciones": ("leak", "breach"),
    "documentos": ("doc",),
    "infra": ("infra",),
    "repos": ("repo",),
}

DISTILL_PROMPT = """Eres analista de inteligencia. Con los datos crudos del objetivo, escribe un dossier.
Devuelve JSON estricto con estas claves:
{"resumen": "...", "identidad": [...], "cargos": [...], "empresas": [...], "dominios": [...],
 "emails": [...], "telefonos": [...], "perfiles": [...], "filtraciones": [...],
 "documentos": [...], "infra": [...], "repos": [...], "coartadas": [...],
 "ganchos": [...], "puntos_debil": [...], "ambiguedades": [...]}
Reglas:
- Copia solo datos presentes en la entrada; no inventes. Lo dudoso va en `ambiguedades`.
- `ganchos`: hechos concretos que un atacante usaría (proveedor, cliente, proyecto, jerga interna).
- `puntos_debil`: sobrecarga, viaje, rotación, equipo pequeño, exposición pública, dependencia de proveedores.
- `coartadas`: la excusa de verosimilitud que hará creíble un primer contacto.
- Español, frases cortas.
"""


def fallback(conn, mission_id):
    out = {}
    for field, kinds in FALLBACK_KEYS.items():
        values, seen = [], set()
        for art in db.artifacts(conn, mission_id):
            if art["kind"] in kinds and art["value"] not in seen:
                seen.add(art["value"])
                values.append(art["value"])
        out[field] = values[:40]
    out.update({"resumen": "", "coartadas": [], "ganchos": [], "puntos_debil": [],
                "ambiguedades": []})
    return out


def build(conn, config, record, log=print):
    raw = [dict(a) for a in db.artifacts(conn, record["id"])]
    dossier = fallback(conn, record["id"])
    if llm.available(config) and raw:
        prompt = (f"Objetivo: {record['target_name']} (cargo {record['target_role']}, "
                  f"empresa {record['target_company']}, dominio {record['domain']})\n"
                  f"Meta del ejercicio: {record['goal']}\n\n"
                  f"Datos crudos:\n{json.dumps(raw, ensure_ascii=False)[:18000]}")
        try:
            data = llm.chat_json(config, [{"role": "system", "content": DISTILL_PROMPT},
                                          {"role": "user", "content": prompt}])
            for key, value in data.items():
                if isinstance(value, list) and key in dossier:
                    dossier[key] = [str(v)[:300] for v in value] or dossier[key]
                elif isinstance(value, str):
                    dossier[key] = value
        except llm.LLMError as exc:
            log(f"  ! dossier por LLM falló ({exc}); uso agregación directa")
    dossier["mission_id"] = record["id"]
    db.save_dossier(conn, record["id"], json.dumps(dossier, ensure_ascii=False))
    return dossier


def load(conn, mission_id):
    row = conn.execute("SELECT json FROM dossiers WHERE mission_id=?", (mission_id,)).fetchone()
    return json.loads(row["json"]) if row else None


def to_text(dossier):
    lines = [f"Resumen: {dossier.get('resumen', '')}"]
    for field in ("identidad", "cargos", "empresas", "dominios", "emails", "telefonos",
                  "perfiles", "filtraciones", "documentos", "infra", "repos",
                  "coartadas", "ganchos", "puntos_debil", "ambiguedades"):
        values = dossier.get(field) or []
        if values:
            lines.append(f"{field.upper()}: " + "; ".join(values[:12]))
    return "\n".join(lines)
