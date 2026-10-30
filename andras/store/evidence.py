"""Persistencia de artifacts y recálculo de verificación."""
from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path

from andras.evidence import score
from andras.models import ARTIFACT_KINDS, Artifact, Finding
from andras.store.db import now

NORMALIZE_KINDS = {"email", "domain", "username"}


def clean(kind: str, value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip().strip(",;.")
    if kind in NORMALIZE_KINDS:
        value = value.lower().rstrip("/")
    return value[:500]


def add(conn: sqlite3.Connection, mission_id: str, finding: Finding) -> tuple[int, bool]:
    """Guarda un hallazgo. Devuelve (artifact_id, es_nuevo). Nunca lanza por duplicado."""
    kind = finding.kind
    if kind not in ARTIFACT_KINDS:
        raise ValueError(f"kind de artifact desconocido: {kind}")
    value = clean(kind, finding.value)
    if not value:
        raise ValueError("artifact vacío")

    row = conn.execute(
        "SELECT id, confidence, verification FROM artifacts WHERE mission_id=? AND kind=? AND value=?",
        (mission_id, kind, value),
    ).fetchone()

    is_new = row is None
    if is_new:
        cur = conn.execute(
            "INSERT INTO artifacts(mission_id,kind,key,value,source,source_domain,snapshot_path,"
            "content_hash,fetched_at,created_at,confidence,verification)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (mission_id, kind, "", value, finding.source, finding.source_domain or score.source_domain(finding.source),
             finding.snapshot, _hash(finding.snapshot), now(), now(),
             score.base_confidence(_source_kind(finding.source), finding.confidence), "single_source"),
        )
        artifact_id = int(cur.lastrowid)
    else:
        artifact_id = int(row["id"])

    conn.execute(
        "INSERT OR IGNORE INTO artifact_sources(artifact_id,source,source_domain,fetched_at)"
        " VALUES(?,?,?,?)",
        (artifact_id, finding.source, finding.source_domain or score.source_domain(finding.source), now()),
    )
    recompute(conn, artifact_id)
    return artifact_id, is_new


def recompute(conn: sqlite3.Connection, artifact_id: int) -> None:
    row = conn.execute("SELECT mission_id, kind, source, confidence FROM artifacts WHERE id=?",
                       (artifact_id,)).fetchone()
    if not row:
        return
    sources = [r["source"] for r in conn.execute(
        "SELECT source FROM artifact_sources WHERE artifact_id=?", (artifact_id,))]
    verification = score.verification_for(sources, _source_kind(row["source"]))
    confidence = score.boosted(row["confidence"], verification)
    conn.execute("UPDATE artifacts SET verification=?, confidence=? WHERE id=?",
                 (verification, confidence, artifact_id))


def list_for(conn: sqlite3.Connection, mission_id: str, kinds: set[str] | None = None) -> list[Artifact]:
    sql = "SELECT * FROM artifacts WHERE mission_id=?"
    params: list = [mission_id]
    if kinds:
        sql += f" AND kind IN ({','.join('?' * len(kinds))})"
        params.extend(sorted(kinds))
    sql += " ORDER BY confidence DESC, id"
    return [_artifact(r) for r in conn.execute(sql, params)]


def usable(conn, mission_id: str, min_confidence: int = 55) -> list[Artifact]:
    return [a for a in list_for(conn, mission_id)
            if a.verification != "inferred" and a.confidence >= min_confidence]


def by_ids(conn, ids: list[int]) -> list[Artifact]:
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    return [_artifact(r) for r in conn.execute(f"SELECT * FROM artifacts WHERE id IN ({marks})", ids)]


def _artifact(row) -> Artifact:
    return Artifact(id=row["id"], mission_id=row["mission_id"], kind=row["kind"], value=row["value"],
                    source=row["source"], source_domain=row["source_domain"],
                    confidence=row["confidence"], verification=row["verification"],
                    fetched_at=row["fetched_at"], snapshot_path=row["snapshot_path"],
                    content_hash=row["content_hash"])


def _source_kind(source: str) -> str:
    return source.split(":", 1)[0] if ":" in source else "web"


def _hash(path: str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()
