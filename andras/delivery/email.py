"""Entrega SMTP."""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

from andras.delivery.base import Result


def send(*, config: dict, target: str, subject: str, body: str,
         html_body: str | None = None) -> Result:
    user = os.environ.get(config.get("smtp_user_env", "ANDRAS_SMTP_USER"), "") or \
        config.get("smtp_user", "")
    password = os.environ.get(config.get("smtp_password_env", "ANDRAS_SMTP_PASSWORD"), "") or \
        config.get("smtp_password", "")
    needs_auth = config.get("smtp_auth", True)
    if needs_auth and (not user or not password):
        return Result.fail("faltan credenciales SMTP en el entorno")

    msg = EmailMessage()
    msg["From"] = f"{config['from_name']} <{config['from_address']}>"
    msg["To"] = target
    msg["Subject"] = subject
    msg.set_content(body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    security = config.get("smtp_security", "starttls")
    try:
        if security == "ssl":
            smtp = smtplib.SMTP_SSL(config["smtp_host"], int(config["smtp_port"]),
                                    context=ssl.create_default_context(), timeout=20)
        else:
            smtp = smtplib.SMTP(config["smtp_host"], int(config["smtp_port"]), timeout=20)
            smtp.ehlo()
            if security != "plain":
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
        with smtp:
            if needs_auth:
                smtp.login(user, password)
            smtp.send_message(msg)
    except Exception as exc:
        return Result.fail(str(exc))
    return Result(ok=True)
