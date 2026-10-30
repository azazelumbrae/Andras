"""Herramientas de canal: auditoría de correo, DKIM, respuestas y simulaciones.

Todo lo que aquí se toca es infraestructura del atacante: SPF/DKIM/DMARC de un dominio
propio, respuestas que llegan por IMAP o Telegram, y el runbook de sim swap.
"""
from __future__ import annotations

import imaplib
import json
import re
import subprocess
from datetime import UTC, datetime
from email import message_from_bytes
from email.utils import parseaddr
from pathlib import Path

from andras.agent import tools
from andras.core import ROOT, record
from andras.store import db

SELECTORS = ("default", "mail", "dkim", "s1", "google", "selector1", "selector2")


def _dig(name: str, kind: str) -> list[str]:
    try:
        out = subprocess.run(["dig", "+short", kind, name], check=False, timeout=10,
                             capture_output=True, text=True).stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return []
    return [line.strip().strip('"') for line in out.splitlines() if line.strip()]


@tools.tool("dns_audit_spf_dkim_dmarc", permission="read",
            description="Audita el correo de un dominio: MX, SPF, DMARC y selectores DKIM "
                        "habituales. Devuelve hallazgos y qué falta para no caer en spam.",
            schema={"type": "object", "properties": {"domain": {"type": "string"}},
                    "required": ["domain"]})
def dns_audit_spf_dkim_dmarc(ctx, domain: str) -> dict:
    domain = domain.strip().lower()
    mx = _dig(domain, "MX")
    txt = _dig(domain, "TXT")
    spf = [t for t in txt if t.lower().startswith("v=spf1")]
    dmarc = [t for t in _dig(f"_dmarc.{domain}", "TXT") if "v=dmarc1" in t.lower()]
    dkim = {}
    for selector in SELECTORS:
        found = _dig(f"{selector}._domainkey.{domain}", "TXT")
        if found:
            dkim[selector] = found[0][:80]
    problems = []
    if not mx:
        problems.append("sin MX: no puede recibir respuestas")
    if not spf:
        problems.append("sin SPF: los correos caerán en spam")
    elif "?all" in spf[0] or "~all" in spf[0]:
        problems.append("SPF blando (~all/?all): declara `-all` cuando el dominio esté cerrado")
    if not dmarc:
        problems.append("sin DMARC: sin política de rechazo ni informes")
    if not dkim:
        problems.append("sin DKIM en selectores habituales: genera uno con "
                        "`generate_dkim_zone`")
    summary = (f"MX={len(mx)} SPF={'sí' if spf else 'no'} DMARC={'sí' if dmarc else 'no'} "
               f"DKIM={','.join(dkim) or 'no'}")
    body = summary + ("\n- " + "\n- ".join(problems) if problems else "\ncorreo bien configurado")
    return {"text": body, "data": {"mx": mx, "spf": spf, "dmarc": dmarc,
                                   "dkim": list(dkim), "problems": problems}}


@tools.tool("generate_dkim_zone", permission="write",
            description="Genera un par de claves DKIM (RSA 2048), guarda la privada y devuelve "
                        "el registro TXT público para publicar en el DNS del dominio.",
            schema={"type": "object",
                    "properties": {"domain": {"type": "string"},
                                   "selector": {"type": "string"}},
                    "required": ["domain"]})
def generate_dkim_zone(ctx, domain: str, selector: str = "andras") -> dict:
    domain, selector = domain.strip().lower(), re.sub(r"[^a-z0-9]", "", selector.lower()) or "andras"
    folder = ROOT / "data" / "dkim" / domain
    folder.mkdir(parents=True, exist_ok=True)
    private, public = folder / f"{selector}.key", folder / f"{selector}.pub"
    if not private.exists():
        subprocess.run(["openssl", "genrsa", "-out", str(private), "2048"], check=True,
                       capture_output=True, timeout=60)
        subprocess.run(["openssl", "rsa", "-in", str(private), "-pubout", "-out", str(public)],
                       check=True, capture_output=True, timeout=60)
    key = "".join(public.read_text().splitlines()[1:-1])
    name = f"{selector}._domainkey.{domain}"
    record_txt = f"v=DKIM1; k=rsa; p={key}"
    (folder / f"{selector}.zone").write_text(f"{name}. 3600 IN TXT \"{record_txt}\"\n")
    return {"text": f"clave privada: {private}\npublica este TXT en {name}:\n{record_txt[:400]}…",
            "data": {"selector": selector, "record": record_txt, "name": name}}


def _mark_replied(conn, mission_id: str, sender: str) -> int:
    """Marca `replied` en las campañas cuyo destino es ese remitente."""
    marked = 0
    rows = conn.execute(
        "SELECT DISTINCT d.campaign_id FROM deliveries d JOIN attacks a ON a.id=d.attack_id"
        " WHERE a.mission_id=? AND lower(d.target)=?", (mission_id, sender.lower())).fetchall()
    for row in rows:
        record(conn, row["campaign_id"], "replied", sender)
        marked += 1
    return marked


@tools.tool("check_inbox", permission="read",
            description="Lee respuestas nuevas por IMAP y marca `replied` en las campañas cuyo "
                        "destino coincide con el remitente. Sin IMAP configurado, falla claro.",
            schema={"type": "object",
                    "properties": {"minutes": {"type": "integer"},
                                   "limit": {"type": "integer"}}})
def check_inbox(ctx, minutes: int = 720, limit: int = 10) -> dict:
    host = ctx.config.get("imap_host", "")
    if not host:
        raise tools.ToolError("falta `imap_host` en config.json")
    import os

    user = os.environ.get(ctx.config.get("imap_user_env", "ANDRAS_IMAP_USER"), "") \
        or ctx.config.get("imap_user", "")
    password = os.environ.get(ctx.config.get("imap_password_env", "ANDRAS_IMAP_PASSWORD"), "")
    if not (user and password):
        raise tools.ToolError("faltan credenciales IMAP en el entorno")
    client = imaplib.IMAP4_SSL(host, int(ctx.config.get("imap_port", 993)))
    try:
        client.login(user, password)
        client.select(ctx.config.get("imap_folder", "INBOX"))
        since = datetime.now(UTC).strftime("%d-%b-%Y")
        _, data = client.search(None, f'(SINCE "{since}")')
        messages = []
        for number in data[0].split()[-limit:]:
            _, raw = client.fetch(number, "(RFC822)")
            mail = message_from_bytes(raw[0][1])
            sender = parseaddr(mail.get("From", ""))[1]
            subject = str(mail.get("Subject", ""))[:160]
            hit = _mark_replied(ctx.conn, ctx.mission.id, sender)
            messages.append({"from": sender, "subject": subject, "matched": bool(hit)})
    finally:
        try:
            client.logout()
        except imaplib.IMAP4.error:
            pass
    if not messages:
        return {"text": "sin correos nuevos", "data": []}
    lines = [f"{'✔' if m['matched'] else '·'} {m['from']} — {m['subject']}"
             for m in messages]
    return {"text": "\n".join(lines), "data": messages}


@tools.tool("telegram_updates", permission="read",
            description="Recoge respuestas del bot de Telegram y las marca como `replied`. "
                        "Guarda el offset para no repetirlas.",
            schema={"type": "object", "properties": {}})
def telegram_updates(ctx) -> dict:
    import httpx

    token = ctx.config.get("telegram_token", "")
    if not token:
        raise tools.ToolError("falta `telegram_token` en config.json")
    path = ROOT / "data" / "telegram_offset.json"
    offset = 0
    if path.exists():
        try:
            offset = int(json.loads(path.read_text()).get("offset", 0))
        except (json.JSONDecodeError, ValueError):
            offset = 0
    resp = httpx.get(f"https://api.telegram.org/bot{token}/getUpdates",
                     params={"offset": offset, "timeout": 0}, timeout=20)
    data = resp.json()
    if not data.get("ok"):
        raise tools.ToolError(str(data.get("description", "getUpdates falló")))
    out = []
    for update in data.get("result", []):
        offset = update["update_id"] + 1
        message = update.get("message") or {}
        sender = (message.get("from") or {}).get("username", "")
        text = message.get("text", "")[:300]
        matched = _mark_replied(ctx.conn, ctx.mission.id, sender) if sender else 0
        out.append({"from": sender, "text": text, "matched": bool(matched)})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"offset": offset}))
    if not out:
        return {"text": "sin mensajes nuevos", "data": []}
    return {"text": "\n".join(f"@{m['from']}: {m['text']}" for m in out), "data": out}


@tools.tool("sim_swap_runbook", permission="read",
            description="Devuelve el runbook de sim swap para un operador y un objetivo: qué "
                        "pedir, qué excusa usar y qué comprobar al portar el número.",
            schema={"type": "object",
                    "properties": {"operator": {"type": "string"},
                                   "target_phone": {"type": "string"}},
                    "required": ["operator"]})
def sim_swap_runbook(ctx, operator: str, target_phone: str = "") -> dict:
    number = target_phone or (ctx.mission.notes or "")[:40] or "<número del objetivo>"
    body = f"""# Sim swap · {operator}

1. Comprueba la cobertura de {operator} en la zona del objetivo y que el número
   {number} sea de ese operador (portabilidad previa incluida).
2. Consigue una SIM virgen del mismo operador (kiosco o prepago) y un teléfono
   barato dedicado. Nunca uses tu terminal personal.
3. Llama al servicio de atención con la persona de la campaña ya creada: nombre,
   DNI inventado coherente, dirección y fecha de alta.
4. Excusa: «he perdido el móvil, necesito conservar el número para el banco».
   Pide duplicado de SIM y activación inmediata.
5. En cuanto haya señal, verifica recepción de SMS y que WhatsApp/Telegram del
   número siguen vivos. Si el objetivo tiene 2FA por SMS, ya lo controlas.
6. Anota hora, agente, referencia del ticket y caducidad del duplicado.
   El original sigue funcionando hasta que el operador corte: hay ventana.

Riesgo: si el titular denuncia la pérdida antes, el operador puede revertir la
portabilidad. La ventana útil suele ser de horas, no de días."""
    return {"text": body, "data": {"operator": operator, "target_phone": target_phone}}


@tools.tool("pickup_runbook", permission="read",
            description="Runbook corto de recuperación de voz (callback phishing) para cuando el "
                        "objetivo ya llama a un número controlado.",
            schema={"type": "object", "properties": {}})
def pickup_runbook(ctx) -> dict:
    db.now()
    return {"text": (
        "# Guion de llamada entrante\n\n"
        "1. Identifícate como el departamento que figura en el correo (nunca improvises otro).\n"
        "2. Pide ticket o referencia; si no la tiene, «no pasa nada, lo busco por su correo».\n"
        "3. Confirma identidad con dos datos del dossier, no con el DNI completo.\n"
        "4. Guía al objetivo al portal paso a paso y quédate en línea hasta que termine.\n"
        "5. Si se atasca, pide captura de pantalla o código de error; nunca pidas la contraseña.\n"
        "6. Cierra con número de incidencia inventado y plazo de resolución."),
        "data": {}}


def _status() -> Path:
    return ROOT / "data" / "channels.json"


@tools.tool("spoof_advice", permission="read",
            description="Explica qué suplantación permite el dominio de envío: nombre visible, "
                        "dominio parecido, reply-to y límites de SPF/DMARC. Úsalo antes de "
                        "elegir remitente.",
            schema={"type": "object",
                    "properties": {"domain": {"type": "string"},
                                   "display_name": {"type": "string"}},
                    "required": ["domain"]})
def spoof_advice(ctx, domain: str, display_name: str = "") -> dict:
    domain = domain.strip().lower()
    name = display_name or ctx.mission.target_company or domain
    dmarc = [t for t in _dig(f"_dmarc.{domain}", "TXT") if "v=dmarc1" in t.lower()]
    policy = "reject" if dmarc and "p=reject" in dmarc[0].lower() else (
        "quarantine" if dmarc and "p=quarantine" in dmarc[0].lower() else "none")
    options = [
        f"Nombre visible «{name}» <{domain}>: sólo cambia lo que se lee, no la dirección.",
        "Reply-To a un buzón propio: la respuesta llega a ti aunque el From suene ajeno.",
        ("Subdominio propio parecido (acme-soporte.tudominio.com): no hace falta tocar el "
         "dominio real, pero cambia el dominio visible."),
    ]
    if policy == "none":
        options.append("DMARC en `p=none`: puedes poner el dominio real en el From aunque "
                       "no esté autorizado; caerá en spam si no alineas SPF/DKIM.")
    else:
        options.append(f"DMARC en `p={policy}`: con el dominio real en el From necesitas "
                       "enviar por un servidor autorizado en su SPF o firmar con su DKIM.")
    return {"text": "# Suplantación\n\n- " + "\n- ".join(options),
            "data": {"dmarc": policy}}


@tools.tool("landing_check", permission="read",
            description="Comprueba que la landing de la campaña responde, tiene formulario y "
                        "no filtra el token en el HTML. Antes de mandar el enlace.",
            schema={"type": "object", "properties": {"url": {"type": "string"}},
                    "required": ["url"]})
def landing_check(ctx, url: str) -> dict:
    import httpx

    problems = []
    try:
        resp = httpx.get(url, timeout=20, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise tools.ToolError(f"la landing no responde: {exc}") from exc
    text = resp.text
    if resp.status_code != 200:
        problems.append(f"HTTP {resp.status_code}")
    if "password" not in text.lower():
        problems.append("sin campo de contraseña: no captura credenciales")
    if "form" not in text.lower():
        problems.append("sin formulario")
    if "http://" in url and ctx.config.get("base_url", "").startswith("https"):
        problems.append("enlace en claro con dominio https configurado")
    summary = f"HTTP {resp.status_code} · {len(text)} bytes"
    body = summary + ("\n- " + "\n- ".join(problems) if problems else "\nlanding correcta")
    return {"text": body, "data": {"problems": problems, "status": resp.status_code}}
