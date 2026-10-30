"""Entrega por bot de Telegram."""
from __future__ import annotations

import os

import httpx

from andras.delivery.base import Result


def send(*, config: dict, target: str, subject: str, body: str,
         html_body: str | None = None) -> Result:
    # token en config o en ANDRAS_TELEGRAM_TOKEN; target = chat_id
    token = os.environ.get("ANDRAS_TELEGRAM_TOKEN", "") or config.get("telegram_token", "")
    if not token:
        return Result.fail("falta ANDRAS_TELEGRAM_TOKEN")
    text = f"{subject}\n\n{body}" if subject else body
    try:
        resp = httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": target, "text": text[:4000],
                                "disable_web_page_preview": False}, timeout=20)
    except httpx.HTTPError as exc:
        return Result.fail(str(exc))
    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if not data.get("ok"):
        return Result.fail(str(data.get("description") or resp.text[:200]))
    return Result(ok=True, external_id=str(data["result"]["message_id"]))
