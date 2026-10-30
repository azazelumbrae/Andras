"""Avisos al operador: escritorio macOS, Telegram, correo y webhook.

Un aviso que falla se registra y no rompe el daemon. Nunca bloquea: todo con timeout corto.
"""
from __future__ import annotations

import json
import subprocess

import httpx

from andras.store import notifications

TITLES = {"info": "ANDRAS · aviso", "hit": "ANDRAS · objetivo conseguido",
          "critical": "ANDRAS · crítico"}


def send(conn, config: dict, *, body: str, level: str = "info", plan_id: str | None = None,
         log=print) -> list[str]:
    """Envía por los canales configurados para ese nivel. Devuelve los que funcionaron."""
    settings = config.get("notify") or {}
    allowed_levels = settings.get("levels") or ["hit", "critical"]
    if level not in allowed_levels and level != "critical":
        return []
    channels = settings.get("channels") or ["desktop"]
    done = []
    for channel in channels:
        try:
            _dispatch(config, channel, body, level)
        except Exception as exc:  # un canal roto no debe tumbar el bucle
            notifications.add(conn, plan_id, level, channel, body, False, str(exc))
            log(f"  ! aviso por {channel} falló: {exc}")
            continue
        notifications.add(conn, plan_id, level, channel, body, True)
        done.append(channel)
    return done


def _dispatch(config: dict, channel: str, body: str, level: str) -> None:
    if channel == "desktop":
        title = TITLES.get(level, "ANDRAS")
        script = f'display notification {json.dumps(body[:200])} with title {json.dumps(title)}'
        subprocess.run(["osascript", "-e", script], check=True, timeout=10,
                       capture_output=True)
        audio = "/System/Library/Sounds/Glass.aiff"
        subprocess.run(["afplay", audio], check=False, timeout=10, capture_output=True)
        return
    if channel == "telegram":
        token = config.get("telegram_token") or ""
        chat = config.get("telegram_chat_id") or ""
        if not token or not chat:
            raise RuntimeError("falta telegram_token o telegram_chat_id")
        httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
                   json={"chat_id": chat, "text": f"{TITLES.get(level, '')}\n{body}",
                         "disable_web_page_preview": True}, timeout=15).raise_for_status()
        return
    if channel == "email":
        from andras.delivery import send as mail

        to = config.get("notify_email") or config.get("from_address")
        if not to:
            raise RuntimeError("falta notify_email")
        result = mail.send("email", config, to, f"ANDRAS: {TITLES.get(level, 'aviso')}",
                           body, None)
        if not result.ok:
            raise RuntimeError(result.error)
        return
    if channel == "webhook":
        url = config.get("notify_webhook") or ""
        if not url:
            raise RuntimeError("falta notify_webhook")
        httpx.post(url, json={"level": level, "text": body}, timeout=15).raise_for_status()
        return
    raise RuntimeError(f"canal de aviso desconocido: {channel}")


def describe(config: dict) -> str:
    settings = config.get("notify") or {}
    return f"canales {', '.join(settings.get('channels') or []) or 'ninguno'} · " \
           f"niveles {', '.join(settings.get('levels') or []) or 'ninguno'}"
