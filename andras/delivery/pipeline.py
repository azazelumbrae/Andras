"""Envío de un vector: render, QA, campaña con token y registro de la entrega."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from andras.artifacts import render
from andras.brain import planner
from andras.delivery import send as deliver_fn
from andras.store import db


@dataclass(slots=True)
class Outcome:
    ok: bool
    url: str = ""
    error: str = ""
    problems: list[str] | None = None
    text: str = ""


def hash_target(address: str) -> str:
    return hashlib.sha256(address.lower().encode()).hexdigest()


def _fill_url(text: str, url: str) -> str:
    """Sustituye el marcador sin dejar esquemas duplicados si el LLM ya puso uno."""
    return (text.replace("https://" + render.TRACKING, url)
                .replace("http://" + render.TRACKING, url)
                .replace(render.TRACKING, url))


def deliver(conn, config, attack_id: str, to: str, *, force: bool = False) -> Outcome:
    """Renderiza, valida y entrega el ataque. No confirma con el humano."""
    attack = planner.load(conn, attack_id)
    if not attack:
        return Outcome(ok=False, error=f"vector inexistente: {attack_id}")
    rendered = render.build(attack["channel"], attack)
    if rendered.problems and not force:
        return Outcome(ok=False, error="QA con problemas", problems=rendered.problems)

    campaign_id = secrets.token_urlsafe(18)
    conn.execute(
        "INSERT INTO campaigns(id,scenario,recipient_hash,created_at) VALUES(?,?,?,?)",
        (campaign_id, attack["angle"][:120], hash_target(to), db.now()))
    conn.execute("UPDATE campaigns SET mission_id=?, attack_id=?, channel=? WHERE id=?",
                 (attack["mission_id"], attack_id, attack["channel"], campaign_id))
    url = config["base_url"].rstrip("/") + "/" + campaign_id
    text = _fill_url(rendered.text, url)
    text = text.replace("[Nombre del remitente]", config.get("from_name", "Soporte"))
    html_body = _fill_url(rendered.html, url) if rendered.html else None

    result = deliver_fn(attack["channel"], config, to, rendered.subject, text, html_body)
    conn.execute(
        "INSERT INTO deliveries(attack_id,campaign_id,channel,target,status,external_id,error,"
        "sent_at) VALUES(?,?,?,?,?,?,?,?)",
        (attack_id, campaign_id, attack["channel"], to, "sent" if result.ok else "failed",
         result.external_id, result.error, None if not result.ok else db.now()))
    if result.ok:
        conn.execute("INSERT INTO events(campaign_id,event,occurred_at) VALUES(?,?,?)",
                     (campaign_id, "sent", db.now()))
    return Outcome(ok=result.ok, url=url, error=result.error, text=text)
