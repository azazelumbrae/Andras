"""Herramientas base: memoria, reloj, DNS y presupuesto.

Recon, canales y wallets van en módulos aparte y se registran igual, importando ese módulo.
"""
from __future__ import annotations

import socket
import subprocess
from datetime import UTC, datetime

from andras.agent import tools
from andras.store import budgets, notes


@tools.tool("note_write", permission="write", cost_usd=0.0,
            description="Apunta un hallazgo, hipótesis o decisión en el diario de la campaña. "
                        "Escribe en markdown y con precisión; el diario es tu memoria.",
            schema={"type": "object",
                    "properties": {
                        "body": {"type": "string", "description": "la nota en markdown"},
                        "title": {"type": "string", "description": "título corto"},
                        "kind": {"type": "string", "enum": list(notes.KINDS)}},
                    "required": ["body"]})
def note_write(ctx, body: str, title: str = "", kind: str = "obs",
               attack_id: str = "") -> dict:
    note = notes.add(ctx.conn, ctx.mission.id, body, title=title, kind=kind,
                     attack_id=attack_id or None)
    return {"text": f"nota #{note.id} guardada", "data": {"id": note.id}}


@tools.tool("note_search", permission="read",
            description="Busca en el diario de la campaña antes de repetir trabajo.",
            schema={"type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"]})
def note_search(ctx, query: str) -> dict:
    found = notes.search(ctx.conn, ctx.mission.id, query)
    if not found:
        return {"text": "sin coincidencias en el diario", "data": []}
    body = "\n".join(f"[{n.id}] {n.created_at} {n.kind} {n.title}: {n.body_md[:300]}"
                     for n in found)
    return {"text": body, "data": [n.id for n in found]}


@tools.tool("current_time", permission="read",
            description="Fecha y hora UTC actuales. Úsalo antes de calcular esperas.",
            schema={"type": "object", "properties": {}})
def current_time(ctx) -> dict:
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    return {"text": stamp, "data": {"utc": stamp}}


@tools.tool("dns_lookup", permission="read",
            description="Resuelve registros A/AAAA/MX/TXT/NS de un dominio. Sin coste, "
                        "sirve para comprobar si existe y qué correo usa.",
            schema={"type": "object",
                    "properties": {"domain": {"type": "string"},
                                   "kind": {"type": "string",
                                            "enum": ["A", "AAAA", "MX", "TXT", "NS"]}},
                    "required": ["domain"]})
def dns_lookup(ctx, domain: str, kind: str = "A") -> dict:
    domain = domain.strip().lower()
    if kind in {"A", "AAAA"}:
        family = socket.AF_INET if kind == "A" else socket.AF_INET6
        values = [info[4][0] for info in socket.getaddrinfo(domain, None, family)]
        text = f"{domain} {kind}: " + (", ".join(sorted(set(values))) or "sin registros")
        return {"text": text, "data": sorted(set(values))}
    try:
        proc = subprocess.run(["dig", "+short", kind, domain], check=False, timeout=15,
                              capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"text": f"{domain} {kind}: fallo de dig ({exc})", "data": []}
    values = [line.strip().strip('"') for line in proc.stdout.splitlines() if line.strip()]
    if not values:
        return {"text": f"{domain} {kind}: sin registros", "data": []}
    return {"text": f"{domain} {kind}: " + " · ".join(values[:12]), "data": values[:12]}


@tools.tool("budget_status", permission="read",
            description="Presupuesto restante de la campaña: pasos, tokens, dólares y cripto.",
            schema={"type": "object", "properties": {}})
def budget_status(ctx) -> dict:
    return {"text": budgets.summary(ctx.conn, ctx.mission.id), "data": budgets.get(
        ctx.conn, ctx.mission.id)}


@tools.tool("ask_operator", permission="write",
            description="Pregunta al humano y espera su respuesta. Úsalo sólo cuando la duda "
                        "no se resuelve investigando.",
            schema={"type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "options": {"type": "array",
                                    "description": "opciones de respuesta, si las hay"}},
                    "required": ["question"]})
def ask_operator(ctx, question: str, options: list | None = None) -> dict:
    if ctx.ask is None:
        return {"text": f"pregunta sin canal: {question}", "data": {"answer": ""}}
    answer = ctx.ask(question, options or [])
    return {"text": f"respuesta del operador: {answer}", "data": {"answer": answer}}
