"""Bot de respuesta: contesta por Telegram como la persona del guion.

Se apoya en la campaña que ya existe: cada mensaje entrante se cruza con la entrega
cuyo destino es ese chat y se responde con el contexto de su ataque. Sin token o sin
entregas no hace nada y lo dice.

Un operador humano puede dejar el bucle con ctrl+c y escribir a mano en cualquier momento.
"""
from __future__ import annotations

import json
import time

import httpx

from andras.brain import provider
from andras.core import ROOT, record
from andras.store import db, notes

OFFSET = ROOT / "data" / "bot_offset.json"
DEFAULT_INTERVAL = 8

SYSTEM = """Eres la persona que firma el último mensaje de esta campaña de ingeniería social.
Respondes por chat, en español, en 1-3 frases cortas y naturales, como en una conversación
real. No expliques que eres un modelo. Mantén el pretexto y el nombre del departamento.

Reglas:
- Si piden un dato que ya está en el guion, dáselo tal cual.
- Si piden algo que no sabes, improvisa lo mínimo y ofrece comprobarlo.
- Si el objetivo sospecha, no te justifiques de más: confirma con un dato concreto.
- Si piden un enlace, repite el que ya se envió.
- Nunca pidas contraseña ni código salvo que el guion lo haga."""


def _offset() -> int:
    try:
        return int(json.loads(OFFSET.read_text()).get("offset", 0))
    except (OSError, json.JSONDecodeError, ValueError):
        return 0


def _save_offset(value: int) -> None:
    OFFSET.parent.mkdir(parents=True, exist_ok=True)
    OFFSET.write_text(json.dumps({"offset": value}))


def _campaign_for(conn, config: dict, chat_id: str):
    """Encuentra la entrega de Telegram que corresponde a ese chat, la más reciente.

    Primero se cruza por destino; si el bot atiende un único chat configurado, vale la
    última entrega de Telegram aunque el destino se anotara con otro formato.
    """
    row = conn.execute(
        "SELECT d.campaign_id, d.attack_id, a.mission_id, a.script, a.angle"
        " FROM deliveries d JOIN attacks a ON a.id=d.attack_id"
        " WHERE d.channel='telegram' AND d.target=? ORDER BY d.id DESC LIMIT 1",
        (chat_id,)).fetchone()
    if row:
        return row
    if str(config.get("telegram_chat_id", "")) == chat_id:
        return conn.execute(
            "SELECT d.campaign_id, d.attack_id, a.mission_id, a.script, a.angle"
            " FROM deliveries d JOIN attacks a ON a.id=d.attack_id"
            " WHERE d.channel='telegram' ORDER BY d.id DESC LIMIT 1").fetchone()
    return None


def answer(conn, config: dict, chat_id: str, text: str, log=print) -> str:
    """Responde a un mensaje. Devuelve el texto enviado o cadena vacía."""
    token = config.get("telegram_token", "")
    if not token:
        raise RuntimeError("falta `telegram_token` en config.json")
    target = _campaign_for(conn, config, chat_id)
    if not target:
        log(f"  · chat {chat_id} sin campaña asociada: no respondo")
        return ""
    history = conn.execute(
        "SELECT direction, body FROM bot_messages WHERE chat_id=? ORDER BY id DESC LIMIT 6",
        (chat_id,)).fetchall()
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": "GUION ENVIADO:\n" + (target["script"] or "")[:3000]}]
    for row in reversed(history):
        messages.append({"role": "assistant" if row["direction"] == "out" else "user",
                         "content": row["body"][:800]})
    messages.append({"role": "user", "content": text})
    try:
        reply = provider.complete(config, messages, temperature=0.6, max_tokens=400).strip()
    except provider.LLMError as exc:
        log(f"  · sin modelo para responder: {exc}")
        return ""
    _store(conn, chat_id, target, "in", text)
    _store(conn, chat_id, target, "out", reply)
    resp = httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat_id, "text": reply[:4000]}, timeout=20)
    if not resp.json().get("ok"):
        log(f"  · Telegram rechazó la respuesta: {resp.text[:120]}")
    record(conn, target["campaign_id"], "replied", chat_id)
    notes.add(conn, target["mission_id"], f"respuesta del objetivo por Telegram: {text[:300]}\n\n"
              f"contestado: {reply[:400]}", kind="obs", attack_id=target["attack_id"])
    return reply


def _store(conn, chat_id: str, target, direction: str, body: str) -> None:
    conn.execute(
        "INSERT INTO bot_messages(chat_id,campaign_id,attack_id,direction,body,created_at)"
        " VALUES(?,?,?,?,?,?)",
        (chat_id, target["campaign_id"], target["attack_id"], direction, body, db.now()))
    conn.commit()


def poll_once(conn, config: dict, log=print) -> int:
    """Una pasada de getUpdates. Devuelve cuántos mensajes contestó."""
    token = config.get("telegram_token", "")
    if not token:
        log("falta `telegram_token`: bot parado")
        return 0
    offset = _offset()
    resp = httpx.get(f"https://api.telegram.org/bot{token}/getUpdates",
                     params={"offset": offset, "timeout": 0}, timeout=20)
    data = resp.json()
    if not data.get("ok"):
        log(f"getUpdates falló: {data.get('description', '')}")
        return 0
    answered = 0
    for update in data.get("result", []):
        offset = update["update_id"] + 1
        message = update.get("message") or {}
        chat_id = str((message.get("chat") or {}).get("id", ""))
        text = (message.get("text") or "").strip()
        if not chat_id or not text:
            continue
        log(f"  · mensaje de {chat_id}: {text[:80]}")
        if answer(conn, config, chat_id, text, log=log):
            answered += 1
    _save_offset(offset)
    return answered


def loop(interval: int = DEFAULT_INTERVAL, once: bool = False) -> int:
    from andras.core import load_config

    config = load_config()
    while True:
        with db.session(config) as conn:
            try:
                poll_once(conn, config)
            except (httpx.HTTPError, RuntimeError) as exc:
                print(f"  · error de bot: {exc}")
        if once:
            return 0
        time.sleep(max(2, interval))
