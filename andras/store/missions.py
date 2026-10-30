"""Misiones."""
from __future__ import annotations

import json
import secrets
import sqlite3

from andras.models import Mission
from andras.store.db import now

STATUSES = ("intake", "recon", "dossier", "hook", "plan", "built", "sent", "closed")


def create(conn: sqlite3.Connection, *, target_name: str, goal: str, target_role: str = "",
           target_company: str = "", domain: str = "", mode: str = "passive",
           channels: list[str] | None = None, notes: str = "") -> Mission:
    if not target_name.strip():
        raise ValueError("target_name obligatorio")
    if not goal.strip():
        raise ValueError("goal obligatorio: qué debe hacer la persona")
    mission = Mission(id=secrets.token_hex(6), target_name=target_name.strip(), goal=goal.strip(),
                      target_role=target_role.strip(), target_company=target_company.strip(),
                      domain=domain.strip().lower(), mode=mode, channels=channels or [],
                      notes=notes, created_at=now())
    conn.execute(
        "INSERT INTO missions(id,target_name,target_role,target_company,domain,goal,mode,"
        "channels,status,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (mission.id, mission.target_name, mission.target_role, mission.target_company, mission.domain,
         mission.goal, mission.mode, json.dumps(mission.channels), mission.status,
         mission.notes, mission.created_at),
    )
    return mission


def get(conn: sqlite3.Connection, mission_id: str) -> Mission | None:
    row = conn.execute("SELECT * FROM missions WHERE id=?", (mission_id,)).fetchone()
    return _mission(row) if row else None


def latest(conn: sqlite3.Connection) -> Mission | None:
    row = conn.execute("SELECT * FROM missions ORDER BY created_at DESC").fetchone()
    return _mission(row) if row else None


def all_missions(conn: sqlite3.Connection) -> list[Mission]:
    return [_mission(r) for r in conn.execute("SELECT * FROM missions ORDER BY created_at DESC")]


def set_status(conn: sqlite3.Connection, mission_id: str, status: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"estado inválido: {status}")
    conn.execute("UPDATE missions SET status=? WHERE id=?", (status, mission_id))


def counts(conn: sqlite3.Connection, mission_id: str) -> dict[str, int]:
    out = {}
    for table in ("artifacts", "hooks", "attacks", "deliveries"):
        out[table] = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE mission_id=?" if table != "deliveries" else
            "SELECT COUNT(*) FROM deliveries d JOIN attacks a ON a.id=d.attack_id"
            " WHERE a.mission_id=?", (mission_id,)).fetchone()[0]
    return out


def _mission(row) -> Mission:
    return Mission(id=row["id"], target_name=row["target_name"], goal=row["goal"],
                   target_role=row["target_role"], target_company=row["target_company"],
                   domain=row["domain"], mode=row["mode"], channels=json.loads(row["channels"]),
                   status=row["status"], notes=row["notes"], created_at=row["created_at"])
