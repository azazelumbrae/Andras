"""Trabajos del planificador: un job por paso, con vencimiento, intentos y alquiler."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from andras.store.db import now

STATES = ("queued", "ready", "running", "done", "failed", "paused")

MAX_ATTEMPTS = 5
BASE_BACKOFF_MIN = 5


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def materialize(conn: sqlite3.Connection, plan_id: str, *, from_now: datetime | None = None) -> int:
    """Crea los jobs que falten para los pasos pendientes del plan."""
    base = from_now or datetime.now(UTC)
    created = 0
    for step in conn.execute(
            "SELECT s.id, s.delay_hours, j.id AS job FROM plan_steps s"
            " LEFT JOIN jobs j ON j.step_id=s.id WHERE s.plan_id=? AND s.status='pending'"
            " ORDER BY s.position", (plan_id,)):
        if step["job"]:
            continue
        due = base + timedelta(hours=float(step["delay_hours"] or 0))
        conn.execute("INSERT INTO jobs(plan_id,step_id,due_at,state,created_at)"
                     " VALUES(?,?,?,?,?)", (plan_id, step["id"], iso(due), "queued", now()))
        created += 1
    return created


def due(conn: sqlite3.Connection, plan_id: str, *, at: datetime | None = None) -> list[sqlite3.Row]:
    moment = iso(at or datetime.now(UTC))
    return list(conn.execute(
        "SELECT j.*, s.position, s.channel, s.attack_id, s.trigger, s.status AS step_status"
        " FROM jobs j JOIN plan_steps s ON s.id=j.step_id"
        " WHERE j.plan_id=? AND j.state IN ('queued','ready') AND j.due_at<=?"
        " AND (j.lease_until IS NULL OR j.lease_until<?)"
        " ORDER BY j.due_at, s.position", (plan_id, moment, moment)))


def lease(conn: sqlite3.Connection, job_id: int, seconds: int = 300) -> None:
    until = iso(datetime.now(UTC) + timedelta(seconds=seconds))
    conn.execute("UPDATE jobs SET state='running', lease_until=? WHERE id=?", (until, job_id))


def finish(conn: sqlite3.Connection, job_id: int, state: str, error: str = "") -> None:
    if state not in STATES:
        raise ValueError(f"estado de job inválido: {state}")
    conn.execute("UPDATE jobs SET state=?, last_error=?, lease_until=NULL WHERE id=?",
                 (state, error[:400], job_id))


def retry(conn: sqlite3.Connection, job_id: int, error: str) -> bool:
    """Reencola con backoff. Devuelve False cuando se agotan los intentos."""
    row = conn.execute("SELECT attempts FROM jobs WHERE id=?", (job_id,)).fetchone()
    attempts = int(row["attempts"] or 0) + 1 if row else MAX_ATTEMPTS
    if attempts >= MAX_ATTEMPTS:
        finish(conn, job_id, "failed", error)
        return False
    delay = timedelta(minutes=BASE_BACKOFF_MIN * 2 ** (attempts - 1))
    conn.execute("UPDATE jobs SET attempts=?, state='queued', last_error=?, lease_until=NULL,"
                 " due_at=? WHERE id=?",
                 (attempts, error[:400], iso(datetime.now(UTC) + delay), job_id))
    return True


def pause_all(conn: sqlite3.Connection, plan_id: str) -> int:
    cur = conn.execute("UPDATE jobs SET state='paused' WHERE plan_id=? AND state IN"
                       " ('queued','ready')", (plan_id,))
    return cur.rowcount


def resume_all(conn: sqlite3.Connection, plan_id: str) -> int:
    cur = conn.execute("UPDATE jobs SET state='queued' WHERE plan_id=? AND state='paused'",
                       (plan_id,))
    return cur.rowcount


def for_plan(conn: sqlite3.Connection, plan_id: str) -> list[sqlite3.Row]:
    return list(conn.execute(
        "SELECT j.*, s.position, s.channel FROM jobs j JOIN plan_steps s ON s.id=j.step_id"
        " WHERE j.plan_id=? ORDER BY s.position", (plan_id,)))


def counts(conn: sqlite3.Connection, plan_id: str) -> dict[str, int]:
    out = {state: 0 for state in STATES}
    for row in conn.execute("SELECT state, COUNT(*) AS n FROM jobs WHERE plan_id=?"
                            " GROUP BY state", (plan_id,)):
        out[row["state"]] = row["n"]
    return out
