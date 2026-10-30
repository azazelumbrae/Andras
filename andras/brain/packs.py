"""Carga de packs de técnicas. Los packs son datos YAML versionados, no código."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from andras.core import ROOT

PACK_DIR = ROOT / "prompts" / "packs"
VALID_CHANNELS = {"email", "phone", "social", "telegram", "sms", "whatsapp", "landing"}
REQUIRED = {"id", "name", "channel", "purpose", "turns"}


@dataclass(slots=True)
class Turn:
    role: str
    goal: str
    success: str


@dataclass(slots=True)
class Pack:
    id: str
    name: str
    channel: str
    purpose: str
    turn_budget: int
    turns: list[Turn]
    strength: str = "B"
    leverage_requires: list[str] = field(default_factory=list)
    mappings: list[str] = field(default_factory=list)
    path: str = ""

    def as_prompt(self) -> str:
        lines = [f"TÉCNICA: {self.name}", f"OBJETIVO: {self.purpose}", "SECUENCIA:"]
        for index, turn in enumerate(self.turns, start=1):
            lines.append(f"{index}. [{turn.role}] {turn.goal} → señal de éxito: {turn.success}")
        return "\n".join(lines)


class PackError(ValueError):
    pass


def load_all(directory: Path | None = None) -> tuple[list[Pack], list[str]]:
    base = Path(directory) if directory else PACK_DIR
    packs, errors = [], []
    if not base.exists():
        return packs, [f"no existe {base}"]
    for path in sorted(base.rglob("*.yaml")):
        try:
            packs.append(_parse(path))
        except PackError as exc:
            errors.append(f"{path.relative_to(base)}: {exc}")
    return packs, errors


def _parse(path: Path) -> Pack:
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise PackError(f"YAML inválido: {exc}") from exc
    if not isinstance(data, dict):
        raise PackError("el pack no es un mapa")
    missing = REQUIRED - data.keys()
    if missing:
        raise PackError(f"faltan campos: {', '.join(sorted(missing))}")
    if data["channel"] not in VALID_CHANNELS:
        raise PackError(f"canal inválido: {data['channel']}")
    turns = []
    for turn in data["turns"]:
        if not {"role", "goal", "success"} <= set(turn):
            raise PackError("cada turno necesita role, goal y success")
        turns.append(Turn(**turn))
    if not turns:
        raise PackError("sin turnos")
    return Pack(id=str(data["id"]), name=str(data["name"]), channel=str(data["channel"]),
                purpose=str(data["purpose"]), turn_budget=int(data.get("turn_budget", len(turns))),
                turns=turns, strength=str(data.get("strength", "B")),
                leverage_requires=list(data.get("leverage_requires", [])),
                mappings=list(data.get("mappings", [])), path=str(path))


CHANNEL_ALIAS = {"sms": "phone", "telegram": "social", "whatsapp": "social",
                 "landing": "email"}


def choose(channel: str | None = None, has: set[str] | None = None,
           limit: int = 3) -> list[Pack]:
    packs, _ = load_all()
    if channel:
        matching = [p for p in packs if p.channel == channel]
        if not matching:
            channel = CHANNEL_ALIAS.get(channel, channel)
    has = has or set()
    scored = []
    for pack in packs:
        if channel and pack.channel != channel:
            continue
        missing = set(pack.leverage_requires) - has
        penalty = len(missing) * 20
        strength = {"S": 3, "A": 2, "B": 1}.get(pack.strength, 0)
        scored.append((penalty - strength, pack))
    scored.sort(key=lambda pair: pair[0])
    return [pack for _, pack in scored[:limit]]
