"""SMS y WhatsApp vía Twilio."""
from __future__ import annotations

import os

from andras.delivery.base import Result


def send(*, config: dict, target: str, subject: str, body: str,
         html_body: str | None = None) -> Result:
    sid = os.environ.get("ANDRAS_TWILIO_SID", "") or config.get("twilio_sid", "")
    token = os.environ.get("ANDRAS_TWILIO_TOKEN", "") or config.get("twilio_token", "")
    sender = config.get("twilio_from", "")
    if not (sid and token and sender):
        return Result.fail("faltan credenciales Twilio (SID, token, from)")
    channel = config.get("_channel", "sms")
    to = target if target.startswith("whatsapp:") or channel == "sms" else f"whatsapp:{target}"
    prefix = "whatsapp:" if channel == "whatsapp" else ""
    try:
        from twilio.rest import Client
    except ImportError:
        return Result.fail("instala el extra `sms` (twilio)")
    try:
        message = Client(sid, token).messages.create(body=body[:1500], from_=prefix + sender, to=to)
    except Exception as exc:
        return Result.fail(str(exc))
    return Result(ok=True, external_id=message.sid)
