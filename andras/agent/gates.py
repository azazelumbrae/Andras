"""Puerta de permisos del agente.

Reglas, en este orden: `read` y `write` corren solas; `send` corre sola si el plan está
confirmado (ese es el consentimiento que dio el humano) y si no, pregunta; `spend` pregunta
salvo que esté por debajo del umbral; `admin` pregunta siempre.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from andras.agent import tools

MODES = ("asistido", "autonomo")


@dataclass(slots=True)
class Policy:
    mode: str = "asistido"
    plan_confirmed: bool = False
    spend_threshold_usd: float = 0.25
    approver: Callable[[str, dict], bool] | None = None

    def ask(self, question: str, payload: dict) -> bool:
        if self.mode == "autonomo" and self.plan_confirmed:
            return True
        if self.approver is None:
            return True
        return bool(self.approver(question, payload))


def authorize(policy: Policy, spec: tools.ToolSpec, args: dict) -> None:
    if spec.permission in {"read", "write"}:
        return
    if spec.permission == "send":
        if policy.plan_confirmed:
            return
        if not policy.ask(f"¿enviar con {spec.name}?", args):
            raise tools.PermissionDenied(f"envío cancelado: {spec.name}")
        return
    if spec.permission == "spend":
        amount = _amount(args)
        if amount <= policy.spend_threshold_usd:
            return
        if not policy.ask(f"¿gastar {amount:.6f} con {spec.name}?", args):
            raise tools.PermissionDenied(f"gasto cancelado: {spec.name}")
        return
    if not policy.ask(f"acción administrativa `{spec.name}`", args):
        raise tools.PermissionDenied(f"acción cancelada: {spec.name}")


def _amount(args: dict) -> float:
    for key in ("amount_usd", "usd", "amount"):
        if key not in args:
            continue
        try:
            return float(args.get(key) or 0)
        except (TypeError, ValueError):
            continue
    return 0.0
