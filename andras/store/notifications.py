"""Registro de avisos al operador."""
from __future__ import annotations

import sqlite3

from andras.store.db import now

LEVELS = ("info", "hit", "critical")


def add(conn: sqlite3.Connection, plan_id: str | None, level: str, channel: str,
        body: str, ok: bool, error: str = "") -> int:
    if level not in LEVELS:
        level = "info"
    cur = conn.execute(
        "INSERT INTO notifications(plan_id,level,channel,body,ok,error,created_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (plan_id, level, channel, body[:1200], int(ok), error[:300], now()))
    return int(cur.lastrowid)


def recent(conn: sqlite3.Connection, plan_id: str | None = None, limit: int = 20) -> list:
    if plan_id:
        return list(conn.execute(
            "SELECT * FROM notifications WHERE plan_id=? ORDER BY id DESC LIMIT ?",
            (plan_id, limit)))
    return list(conn.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,)))


def pending(conn: sqlite3.Connection, limit: int = 20) -> list:
    """Avisos que fallaron y se pueden reintentar."""
    return list(conn.execute(
        "SELECT * FROM notifications WHERE ok=0 AND error<>'definitivo' ORDER BY id LIMIT ?",
        (limit,)))
