"""Plan de ataque: el LLM decide vectores y redacta secuencias estilo Lapsus$.
Vectores disponibles: email, sms (envío manual desde un endpoint), phone (guion de llamada),
social (plantilla para contacto por mensajería), mfa_fatigue (guion para la organización).
Solo email y SMS viajan de verdad; los demás son guiones accionables.
"""
import json

from . import db, dossier as dossier_mod, llm

STRATEGY_PROMPT = """Eres un planificador de ingeniería social estilo Lapsus$: directo, creativo,
obsesivo con la verosimilitud y minimalista en tecnología. Solo vectores simples y humanos:
email, sms, phone (llamada), social (mensaje por mensajería), mfa_fatigue (bombardeo de
aprobaciones con cobertura telefónica).

Tácticas de tu repertorio, úsalas cuando encajen:
- Pon un gancho concreto: dato interno, proveedor real, fecha o proyecto del objetivo.
- Finge ser alguien con autoridad real y accesible: TI, finanzas, soporte de un proveedor.
- Urgencia que obliga a actuar ya (banco, cliente, incidente, corte de servicio).
- El punto débil del ecosistema: el empleado cansado, el tercero de confianza, el canal SMS.
- ATAQUES EN CADENA: el primer contacto habilita el siguiente (enlace → credenciales →
  MFA-fatigue → llamada de "soporte" que cierra). Máximo 4 pasos.
- El objetivo es que la persona HAGA algo (clicar, responder, aprobar, pagar, llamar).

Devuelve JSON:
{"vectors": [
  {"vector": "email|sms|phone|social|mfa_fatigue",
   "angle": "nombre corto del ángulo",
   "leverage": "que dato/hook del dossier lo hace creíble",
   "stance": "qué causa queda abierto si funciona",
   "steps": [
     {"actor": "ATACANTE|OBJETIVO|SISTEMA",
      "action": "descripción concreta",
      "script": "texto exacto a enviar/decir, en primera persona, en español; para phone/social/mfa_fatigue es un guion de 3-6 líneas; para email es el cuerpo completo del correo en texto plano con el marcador {tracking_url} donde va el enlace"
     }
   ]
 }
]}

Reglas: 2 a 3 vectores, encadenados cuando sea posible. Cada paso de OBJETIVO debe describir
la acción concreta que esperas. El campo script es obligatorio. Nada de tecnicismos de
seguridad; lenguaje cotidiano impecable en español.
"""


def build(conn, config, record, log=print):
    dos = dossier_mod.load(conn, record["id"]) or dossier_mod.build(conn, config, record, log)
    if not llm.available(config):
        raise SystemExit("El plan necesita LLM (configura ANDRAS_DEEPSEEK_API_KEY)")
    prompt = (f"Objetivo: {record['target_name']} | meta: {record['goal']}\n\n"
              f"Dossier:\n{dossier_mod.to_text(dos)}")
    log("  · planificando vectores (LLM)…")
    data = llm.chat_json(config, [{"role": "system", "content": STRATEGY_PROMPT},
                                  {"role": "user", "content": prompt}])
    attacks = []
    for vec in data.get("vectors", [])[:3]:
        vector = vec.get("vector", "email")
        if vector not in {"email", "sms", "phone", "social", "mfa_fatigue"}:
            continue
        steps = [s for s in vec.get("steps", []) if s.get("script") and s.get("action")]
        if not steps:
            continue
        payload = {
            "vector": vector,
            "angle": vec.get("angle", vector)[:80],
            "leverage": vec.get("leverage", "")[:500],
            "stance": vec.get("stance", "")[:500],
            "steps": steps,
        }
        attack_id = db_slug()
        conn.execute(
            "INSERT INTO attacks(id,mission_id,vector,angle,script,status,created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (attack_id, record["id"], vector, payload["angle"],
             json.dumps(payload, ensure_ascii=False), "draft", db.now()))
        conn.commit()
        attacks.append({**payload, "id": attack_id})
    if not attacks:
        raise SystemExit("El LLM no devolvió vectores válidos")
    return attacks


def load(conn, attack_id):
    row = conn.execute("SELECT * FROM attacks WHERE id=?", (attack_id,)).fetchone()
    if not row:
        return None
    data = json.loads(row["script"])
    data["id"] = row["id"]
    data["status"] = row["status"]
    data["mission_id"] = row["mission_id"]
    return data


def db_slug():
    import secrets
    return secrets.token_urlsafe(9)
