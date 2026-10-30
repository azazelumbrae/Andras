"""Canales manuales: la hoja de llamada y el mensaje social se copian a mano."""
from __future__ import annotations

from andras.delivery.base import Result


def send(*, config: dict, target: str, subject: str, body: str,
         html_body: str | None = None) -> Result:
    return Result(ok=True, external_id="manual")
