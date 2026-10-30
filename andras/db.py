"""Esquema SQLite de ANDRAS v2 (misiones OSINT -> ataques)."""
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .core import database

SCHEMA = """
CREATE TABLE IF NOT EXISTS missions (
  id TEXT PRIMARY KEY,
  target_name TEXT NOT NULL,
  target_role TEXT DEFAULT '',
  target_company TEXT DEFAULT '',
  domain TEXT DEFAULT '',
  goal TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
  id INTEGER PRIMARY KEY,
  mission_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  source TEXT NOT NULL,
  confidence INTEGER DEFAULT 50,
  created_at TEXT NOT NULL,
  UNIQUE(mission_id, kind, value)
);
CREATE TABLE IF NOT EXISTS dossiers (
  mission_id TEXT PRIMARY KEY,
  json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attacks (
  id TEXT PRIMARY KEY,
  mission_id TEXT NOT NULL,
  vector TEXT NOT NULL,
  angle TEXT NOT NULL,
  script TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaigns (
  id TEXT PRIMARY KEY,
  scenario TEXT NOT NULL,
  recipient_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  mission_id TEXT,
  attack_id TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  event TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id)
);
"""

MIGRATIONS = {
    "campaigns": {
        "mission_id": "TEXT",
        "attack_id": "TEXT",
    },
}


def connect(config):
    conn = database(config)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    for table, cols in MIGRATIONS.items():
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col, typ in cols.items():
            if col not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    return conn


def now():
    return datetime.now(UTC).isoformat(timespec="seconds")


def add_artifact(conn, mission_id, kind, key, value, source, confidence=50):
    conn.execute(
        "INSERT OR IGNORE INTO artifacts(mission_id,kind,key,value,source,confidence,created_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (mission_id, kind, key, value, source, confidence, now()),
    )
    conn.commit()


def artifacts(conn, mission_id):
    return conn.execute(
        "SELECT * FROM artifacts WHERE mission_id=? ORDER BY confidence DESC, id",
        (mission_id,),
    ).fetchall()


def save_dossier(conn, mission_id, payload):
    conn.execute(
        "INSERT INTO dossiers(mission_id,json,updated_at) VALUES(?,?,?)"
        " ON CONFLICT(mission_id) DO UPDATE SET json=excluded.json, updated_at=excluded.updated_at",
        (mission_id, payload, now()),
    )
    conn.commit()


def mission(conn, mission_id=None, name=None):
    if mission_id:
        return conn.execute("SELECT * FROM missions WHERE id=?", (mission_id,)).fetchone()
    if name:
        return conn.execute(
            "SELECT * FROM missions WHERE lower(target_name)=lower(?) ORDER BY created_at DESC",
            (name,),
        ).fetchone()
    return None


def db_path(config):
    return Path(config.get("database", "data/andras.sqlite3"))
