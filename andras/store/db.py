"""Acceso a SQLite: ruta, conexión y migraciones."""
from __future__ import annotations

import json  # noqa: F401  (reexportado para logs)
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from andras.core import ROOT, load_config
from andras.store.migrations import MIGRATIONS


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def db_path(config=None) -> Path:
    config = config or load_config()
    return (ROOT / config.get("database", "data/andras.sqlite3")).resolve()


def connect(config=None) -> sqlite3.Connection:
    path = db_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for index, migration in enumerate(MIGRATIONS, start=1):
        if index <= version:
            continue
        if callable(migration):
            migration(conn)
            conn.commit()
        else:
            conn.executescript(migration)
        conn.execute(f"PRAGMA user_version={index}")
        conn.commit()


@contextmanager
def session(config=None):
    conn = connect(config)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def readonly(config=None):
    path = db_path(config)
    if not path.exists():
        raise SystemExit(f"No hay base de datos en {path}. Crea una misión primero.")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
