"""Campañas omnicanal: secuencia de pasos con canal, pack, espera y disparador."""
from __future__ import annotations

import sqlite3

from andras.store.db import now

TRIGGERS = ("always", "no_visit", "visited", "no_reply", "no_submit")


def create(conn: sqlite3.Connection, mission_id: str, title: str, narrative: str = "") -> str:
    import secrets

    plan_id = secrets.token_hex(5)
    conn.execute("INSERT INTO plans(id,mission_id,title,narrative,status,created_at)"
                 " VALUES(?,?,?,?,?,?)",
                 (plan_id, mission_id, title[:160], narrative, "draft", now()))
    return plan_id


def add_step(conn: sqlite3.Connection, plan_id: str, position: int, channel: str, *,
             pack_id: str = "", delay_hours: float = 0, trigger: str = "always",
             why: str = "") -> int:
    if trigger not in TRIGGERS:
        raise ValueError(f"disparador inválido: {trigger}")
    cur = conn.execute(
        "INSERT INTO plan_steps(plan_id,position,channel,pack_id,delay_hours,trigger,why,status)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (plan_id, position, channel, pack_id, max(0.0, float(delay_hours)), trigger,
         why[:400], "pending"))
    return int(cur.lastrowid)


def steps(conn: sqlite3.Connection, plan_id: str) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM plan_steps WHERE plan_id=? ORDER BY position",
                             (plan_id,)))


def get(conn: sqlite3.Connection, plan_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()


def for_mission(conn: sqlite3.Connection, mission_id: str) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM plans WHERE mission_id=? ORDER BY created_at DESC",
                             (mission_id,)))


def attach_attack(conn: sqlite3.Connection, step_id: int, attack_id: str) -> None:
    conn.execute("UPDATE plan_steps SET attack_id=? WHERE id=?", (attack_id, step_id))


def mark(conn: sqlite3.Connection, step_id: int, status: str) -> None:
    if status == "sending":
        conn.execute("UPDATE plan_steps SET status=?, started_at=? WHERE id=?",
                     (status, now(), step_id))
    elif status in {"done", "skipped", "failed"}:
        conn.execute("UPDATE plan_steps SET status=?, ended_at=? WHERE id=?",
                     (status, now(), step_id))
    else:
        conn.execute("UPDATE plan_steps SET status=? WHERE id=?", (status, step_id))


def set_status(conn: sqlite3.Connection, plan_id: str, status: str) -> None:
    conn.execute("UPDATE plans SET status=? WHERE id=?", (status, plan_id))


def event_counts(conn: sqlite3.Connection, attack_ids: list[str]) -> dict[str, set[str]]:
    """Eventos por campaña, para evaluar disparadores."""
    if not attack_ids:
        return {}
    marks = ",".join("?" * len(attack_ids))
    out: dict[str, set[str]] = {aid: set() for aid in attack_ids}
    for row in conn.execute(
            f"SELECT a.id AS aid, e.event FROM deliveries d"
            f" JOIN campaigns c ON c.id=d.campaign_id JOIN attacks a ON a.id=d.attack_id"
            f" JOIN events e ON e.campaign_id=c.id WHERE a.id IN ({marks})", attack_ids):
        out[row["aid"]].add(row["event"])
    return out


def fired(trigger: str, events: set[str]) -> bool:
    if trigger == "always":
        return True
    if trigger == "no_visit":
        return "visited" not in events
    if trigger == "visited":
        return "visited" in events
    if trigger == "no_reply":
        return "replied" not in events
    if trigger == "no_submit":
        return "submitted" not in events
    return True
