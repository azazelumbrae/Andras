"""Migraciones forward-only. Se aplican en orden y se registran en PRAGMA user_version."""


def _ensure_columns(table, columns):
    """SQLite no tiene ADD COLUMN IF NOT EXISTS; se comprueba antes."""

    def apply(conn):
        have = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns.items():
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    return apply


MIGRATIONS = [
    # 1 — esquema base v3
    """
    CREATE TABLE IF NOT EXISTS missions (
      id TEXT PRIMARY KEY,
      target_name TEXT NOT NULL,
      target_role TEXT NOT NULL DEFAULT '',
      target_company TEXT NOT NULL DEFAULT '',
      domain TEXT NOT NULL DEFAULT '',
      goal TEXT NOT NULL,
      mode TEXT NOT NULL DEFAULT 'passive',
      channels TEXT NOT NULL DEFAULT '[]',
      status TEXT NOT NULL DEFAULT 'intake',
      notes TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS artifacts (
      id INTEGER PRIMARY KEY,
      mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
      kind TEXT NOT NULL,
      key TEXT NOT NULL DEFAULT '',
      value TEXT NOT NULL,
      source TEXT NOT NULL,
      source_domain TEXT NOT NULL DEFAULT '',
      snapshot_path TEXT,
      content_hash TEXT,
      fetched_at TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT '',
      confidence INTEGER NOT NULL DEFAULT 40,
      verification TEXT NOT NULL DEFAULT 'single_source',
      UNIQUE (mission_id, kind, value)
    );

    CREATE TABLE IF NOT EXISTS dossiers (
      mission_id TEXT PRIMARY KEY REFERENCES missions(id) ON DELETE CASCADE,
      json TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS hooks (
      id INTEGER PRIMARY KEY,
      mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
      title TEXT NOT NULL,
      rationale TEXT NOT NULL,
      artifact_ids TEXT NOT NULL DEFAULT '[]',
      pain INTEGER NOT NULL DEFAULT 0,
      verifiability INTEGER NOT NULL DEFAULT 0,
      score INTEGER NOT NULL DEFAULT 0,
      chosen INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS attacks (
      id TEXT PRIMARY KEY,
      mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
      vector TEXT NOT NULL,
      channel TEXT NOT NULL DEFAULT 'email',
      angle TEXT NOT NULL,
      leverage TEXT NOT NULL DEFAULT '',
      stance TEXT NOT NULL DEFAULT '',
      payload TEXT NOT NULL DEFAULT '{}',
      script TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'draft',
      created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS deliveries (
      id INTEGER PRIMARY KEY,
      attack_id TEXT NOT NULL REFERENCES attacks(id) ON DELETE CASCADE,
      campaign_id TEXT NOT NULL,
      channel TEXT NOT NULL,
      target TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending',
      external_id TEXT NOT NULL DEFAULT '',
      error TEXT NOT NULL DEFAULT '',
      sent_at TEXT
    );

    CREATE TABLE IF NOT EXISTS runs (
      id INTEGER PRIMARY KEY,
      mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
      phase TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'running',
      log TEXT NOT NULL DEFAULT '',
      started_at TEXT NOT NULL,
      ended_at TEXT
    );

    CREATE TABLE IF NOT EXISTS infra (
      id INTEGER PRIMARY KEY,
      mission_id TEXT REFERENCES missions(id) ON DELETE SET NULL,
      kind TEXT NOT NULL,
      value TEXT NOT NULL,
      purpose TEXT NOT NULL DEFAULT '',
      burned INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL,
      UNIQUE (kind, value)
    );

    CREATE TABLE IF NOT EXISTS critics (
      id INTEGER PRIMARY KEY,
      mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
      verdict TEXT NOT NULL,
      kill_switches TEXT NOT NULL DEFAULT '[]',
      gaps TEXT NOT NULL DEFAULT '[]',
      contradictions TEXT NOT NULL DEFAULT '[]',
      created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS credentials (
      id INTEGER PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      username TEXT NOT NULL DEFAULT '',
      secret TEXT NOT NULL DEFAULT '',
      captured_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS campaigns (
      id TEXT PRIMARY KEY,
      scenario TEXT NOT NULL,
      recipient_hash TEXT NOT NULL,
      created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS events (
      id INTEGER PRIMARY KEY,
      campaign_id TEXT NOT NULL,
      event TEXT NOT NULL,
      occurred_at TEXT NOT NULL,
      meta TEXT NOT NULL DEFAULT '{}'
    );
    """,
    # 2 — índices
    """
    CREATE INDEX IF NOT EXISTS idx_artifacts_mission ON artifacts(mission_id, kind);
    CREATE INDEX IF NOT EXISTS idx_attacks_mission ON attacks(mission_id, status);
    CREATE INDEX IF NOT EXISTS idx_events_campaign ON events(campaign_id);
    CREATE INDEX IF NOT EXISTS idx_runs_mission ON runs(mission_id, phase);
    """,
    # 3 — columnas v1 que falten
    _ensure_columns("campaigns", {"mission_id": "TEXT", "attack_id": "TEXT", "channel": "TEXT"}),
    _ensure_columns("events", {"meta": "TEXT NOT NULL DEFAULT '{}'"}),
    # 4-7 — columnas que faltan en tablas creadas por versiones anteriores
    _ensure_columns("artifacts", {"created_at": "TEXT NOT NULL DEFAULT ''",
                                  "source_domain": "TEXT NOT NULL DEFAULT ''",
                                  "snapshot_path": "TEXT", "content_hash": "TEXT",
                                  "fetched_at": "TEXT NOT NULL DEFAULT ''",
                                  "verification": "TEXT NOT NULL DEFAULT 'single_source'"}),
    _ensure_columns("missions", {"mode": "TEXT NOT NULL DEFAULT 'passive'",
                                 "channels": "TEXT NOT NULL DEFAULT '[]'",
                                 "notes": "TEXT NOT NULL DEFAULT ''",
                                 "status": "TEXT NOT NULL DEFAULT 'intake'"}),
    # 7 — columnas del esquema v3 sobre bases antiguas
    _ensure_columns("artifacts", {"created_at": "TEXT NOT NULL DEFAULT ''",
                                  "key": "TEXT NOT NULL DEFAULT ''",
                                  "fetched_at": "TEXT NOT NULL DEFAULT ''"}),
    # 8 — fuentes múltiples por artifact (base de la corroboración)
    """
    CREATE TABLE IF NOT EXISTS artifact_sources (
      id INTEGER PRIMARY KEY,
      artifact_id INTEGER NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
      source TEXT NOT NULL,
      source_domain TEXT NOT NULL DEFAULT '',
      fetched_at TEXT NOT NULL,
      UNIQUE (artifact_id, source)
    );
    INSERT OR IGNORE INTO artifact_sources(artifact_id, source, source_domain, fetched_at)
      SELECT id, source, source_domain, fetched_at FROM artifacts;
    CREATE INDEX IF NOT EXISTS idx_artifact_sources ON artifact_sources(artifact_id);
    """,
    # 9 — índice que depende de la columna añadida antes
    "CREATE INDEX IF NOT EXISTS idx_artifacts_verification ON artifacts(mission_id, verification);",
    # 10 — created_at en bases antiguas
    _ensure_columns("artifacts", {"created_at": "TEXT NOT NULL DEFAULT ''"}),
    # 11 — attacks de v2 sin columnas de payload
    _ensure_columns("attacks", {"channel": "TEXT NOT NULL DEFAULT 'email'",
                                "leverage": "TEXT NOT NULL DEFAULT ''",
                                "stance": "TEXT NOT NULL DEFAULT ''",
                                "payload": "TEXT NOT NULL DEFAULT '{}'",
                                "script": "TEXT NOT NULL DEFAULT ''"}),
    # 12 — campañas omnicanal
    """
    CREATE TABLE IF NOT EXISTS plans (
      id TEXT PRIMARY KEY,
      mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
      title TEXT NOT NULL,
      narrative TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'draft',
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS plan_steps (
      id INTEGER PRIMARY KEY,
      plan_id TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
      position INTEGER NOT NULL,
      channel TEXT NOT NULL,
      pack_id TEXT NOT NULL DEFAULT '',
      attack_id TEXT,
      delay_hours REAL NOT NULL DEFAULT 0,
      trigger TEXT NOT NULL DEFAULT 'always',
      why TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'pending',
      started_at TEXT,
      ended_at TEXT,
      UNIQUE (plan_id, position)
    );
    CREATE INDEX IF NOT EXISTS idx_plan_steps ON plan_steps(plan_id, position);
    """,
]
