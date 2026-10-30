import json
import secrets
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_config():
    path = ROOT / "config.json"
    if not path.exists():
        raise SystemExit("Falta config.json. Ejecuta `python3 -m andras.cli init` y edita la configuración.")
    config = json.loads(path.read_text())
    if config.get("smtp_security") not in {"starttls", "ssl", "plain"}:
        raise SystemExit("smtp_security debe ser starttls o ssl")
    return config


def database(config):
    path = ROOT / config.get("database", "data/andras.sqlite3")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS campaigns (
        id TEXT PRIMARY KEY, scenario TEXT NOT NULL, recipient_hash TEXT NOT NULL,
        created_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY, campaign_id TEXT NOT NULL, event TEXT NOT NULL,
        occurred_at TEXT NOT NULL, FOREIGN KEY(campaign_id) REFERENCES campaigns(id))""")
    conn.commit()
    return conn


def record(conn, campaign_id, event):
    conn.execute("INSERT INTO events(campaign_id,event,occurred_at) VALUES(?,?,?)",
                 (campaign_id, event, datetime.now(UTC).isoformat()))
    conn.commit()


def new_campaign(conn, scenario, recipient_hash):
    campaign = secrets.token_urlsafe(24)
    conn.execute("INSERT INTO campaigns(id,scenario,recipient_hash,created_at) VALUES(?,?,?,?)",
                 (campaign, scenario, recipient_hash, datetime.now(UTC).isoformat()))
    conn.commit()
    return campaign


def load_scenario(name):
    path = ROOT / "scenarios" / f"{name}.json"
    if not path.exists():
        raise SystemExit(f"Escenario no encontrado: {name}")
    return json.loads(path.read_text())
