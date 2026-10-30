"""Landing derivada de un ataque, sin depender de un escenario fijo."""
from __future__ import annotations

DEFAULT_SIGNALS = [
    "remitente inesperado",
    "urgencia o petición inusual",
    "destino del enlace",
]


def from_payload(payload: dict, capture: bool = True) -> dict:
    return {
        "title": payload.get("subject") or payload.get("angle") or "Ejercicio de seguridad",
        "message": payload.get("stance") or
                   "Esta notificación era una simulación. Comprueba siempre el remitente y el "
                   "destino del enlace por un canal conocido.",
        "signals": payload.get("signals") or DEFAULT_SIGNALS,
        "capture": capture,
    }
