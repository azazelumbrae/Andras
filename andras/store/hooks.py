"""Ganchos: el dato del dossier que sostiene el pretexto."""
from __future__ import annotations

import json
import sqlite3

from andras.models import Hook
from andras.store.db import now


def add(conn: sqlite3.Connection, mission_id: str, *, title: str, rationale: str,
        artifact_ids: list[int], pain: int, verifiability: int) -> Hook:
    pain = max(0, min(100, pain))
    verifiability = max(0, min(100, verifiability))
    score = round(pain * 0.6 + verifiability * 0.4)
    cur = conn.execute(
        "INSERT INTO hooks(mission_id,title,rationale,artifact_ids,pain,verifiability,score,"
        "chosen,created_at) VALUES(?,?,?,?,?,?,?,0,?)",
        (mission_id, title[:160], rationale, json.dumps(artifact_ids), pain, verifiability, score, now()),
    )
    return Hook(id=int(cur.lastrowid), mission_id=mission_id, title=title, rationale=rationale,
                artifact_ids=artifact_ids, pain=pain, verifiability=verifiability, score=score)


def list_for(conn: sqlite3.Connection, mission_id: str, only_usable: bool = True) -> list[Hook]:
    sql = "SELECT * FROM hooks WHERE mission_id=?"
    if only_usable:
        sql += " AND pain > 0 AND json_array_length(artifact_ids) > 0"
    sql += " ORDER BY score DESC, id"
    return [_hook(r) for r in conn.execute(sql, (mission_id,))]


def choose(conn: sqlite3.Connection, mission_id: str, hook_id: int) -> None:
    conn.execute("UPDATE hooks SET chosen=0 WHERE mission_id=?", (mission_id,))
    conn.execute("UPDATE hooks SET chosen=1 WHERE id=? AND mission_id=?", (hook_id, mission_id))


def chosen(conn: sqlite3.Connection, mission_id: str) -> list[Hook]:
    return [_hook(r) for r in conn.execute(
        "SELECT * FROM hooks WHERE mission_id=? AND chosen=1", (mission_id,))]


def clear(conn: sqlite3.Connection, mission_id: str) -> None:
    conn.execute("DELETE FROM hooks WHERE mission_id=?", (mission_id,))


def _hook(row) -> Hook:
    return Hook(id=row["id"], mission_id=row["mission_id"], title=row["title"],
                rationale=row["rationale"], artifact_ids=json.loads(row["artifact_ids"]),
                pain=row["pain"], verifiability=row["verifiability"], score=row["score"],
                chosen=bool(row["chosen"]))
