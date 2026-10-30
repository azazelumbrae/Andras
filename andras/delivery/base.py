"""Interfaz común de entrega y registro de resultados."""
from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass

from andras.core import load_config


@dataclass(slots=True)
class Result:
    ok: bool
    external_id: str = ""
    error: str = ""

    @classmethod
    def fail(cls, error: str) -> Result:
        return cls(ok=False, error=error[:400])


Handler = Callable[[dict, str, str, dict], Result]

HANDLERS: dict[str, str] = {
    "email": "andras.delivery.email",
    "telegram": "andras.delivery.telegram",
    "sms": "andras.delivery.twilio",
    "whatsapp": "andras.delivery.twilio",
    "phone": "andras.delivery.manual",
    "social": "andras.delivery.manual",
}


def send(channel: str, config: dict, target: str, subject: str, body: str,
         html_body: str | None = None) -> Result:
    module_name = HANDLERS.get(channel)
    if not module_name:
        return Result.fail(f"canal sin adaptador: {channel}")
    module = importlib.import_module(module_name)
    kwargs = {"config": {**(config or load_config()), "_channel": channel}, "target": target,
              "subject": subject, "body": body, "html_body": html_body}
    return module.send(**kwargs)
