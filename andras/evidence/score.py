"""Confianza y verificación de evidencia.

Regla de oro: un dato inferido por el LLM nunca sube de `inferred`; un dato solo es
`corroborated` con dos dominios de origen independientes.
"""
from __future__ import annotations

from urllib.parse import urlparse

from andras.models import Finding

BASE_BY_SOURCE = {
    "input": 95,
    "official": 80,
    "registry": 75,
    "whois": 65,
    "dns": 60,
    "harvest": 55,
    "web": 45,
    "dork": 40,
    "social": 45,
    "pattern": 45,
    "llm": 30,
}

CORROBORATION_BONUS = 15
MAX_CONFIDENCE = 100


def source_domain(source: str) -> str:
    if source.startswith(("http://", "https://")):
        host = urlparse(source).hostname or ""
        return host.removeprefix("www.")
    return ""


def base_confidence(source_kind: str, explicit: int | None = None) -> int:
    if explicit is not None:
        return max(1, min(MAX_CONFIDENCE, explicit))
    return BASE_BY_SOURCE.get(source_kind, 40)


def verification_for(sources: list[str], source_kind: str) -> str:
    if source_kind == "llm" or all(s.startswith("llm") for s in sources):
        return "inferred"
    domains = {d for d in (source_domain(s) for s in sources) if d}
    return "corroborated" if len(domains) >= 2 else "single_source"


def boosted(confidence: int, verification: str) -> int:
    if verification == "corroborated":
        return min(MAX_CONFIDENCE, confidence + CORROBORATION_BONUS)
    return confidence


def finding_from_llm(value: str, kind: str, source: str, confidence: int = 30) -> Finding:
    return Finding(kind=kind, value=value.strip(), source=f"llm:{source}",
                   confidence=base_confidence("llm", confidence))
