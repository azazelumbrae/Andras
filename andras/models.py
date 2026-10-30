"""Tipos del dominio. Sin dependencias externas."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Mode = Literal["passive", "tracked", "interactive"]
Verification = Literal["single_source", "corroborated", "inferred", "stale"]
Channel = Literal["email", "landing", "phone", "telegram", "sms", "whatsapp", "social"]

ARTIFACT_KINDS = {
    "person", "email", "phone", "username", "domain", "social", "company",
    "infra", "doc", "repo", "leak", "breach", "credential", "recovery_fact", "objetivo",
}


@dataclass(slots=True)
class Mission:
    id: str
    target_name: str
    goal: str
    target_role: str = ""
    target_company: str = ""
    domain: str = ""
    mode: Mode = "passive"
    channels: list[str] = field(default_factory=list)
    status: str = "intake"
    notes: str = ""
    created_at: str = ""


@dataclass(slots=True)
class Finding:
    """Un dato crudo que un colector cree haber encontrado."""

    kind: str
    value: str
    source: str
    source_domain: str = ""
    confidence: int = 40
    snapshot: str | None = None


@dataclass(slots=True)
class Artifact:
    id: int
    mission_id: str
    kind: str
    value: str
    source: str
    source_domain: str
    confidence: int
    verification: Verification
    fetched_at: str
    snapshot_path: str | None = None
    content_hash: str | None = None


@dataclass(slots=True)
class Hook:
    id: int
    mission_id: str
    title: str
    rationale: str
    artifact_ids: list[int]
    pain: int
    verifiability: int
    score: int
    chosen: bool = False


@dataclass
class Step:
    actor: Literal["ATACANTE", "OBJETIVO", "SISTEMA"]
    action: str
    script: str


@dataclass
class Vector:
    vector: str
    channel: Channel
    angle: str
    leverage: str
    stance: str
    hook_ids: list[int] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    subject: str = ""
