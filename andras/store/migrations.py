"""Migraciones forward-only. Se aplican en orden y se registran en PRAGMA user_version."""
import sqlite3


def _ensure_columns(table, columns):
    """SQLite no tiene ADD COLUMN IF NOT EXISTS; se comprueba antes."""

    def apply(conn):
        have = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns.items():
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    return apply


def _notes_fts(conn):
    """Índice de texto completo; si el SQLite no trae FTS5 se busca con LIKE."""
    try:
        conn.executescript(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(title, body_md);
            CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
              INSERT INTO notes_fts(rowid, title, body_md) VALUES (new.id, new.title, new.body_md);
            END;
            CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
              DELETE FROM notes_fts WHERE rowid = old.id;
            END;
            CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
              DELETE FROM notes_fts WHERE rowid = old.id;
              INSERT INTO notes_fts(rowid, title, body_md) VALUES (new.id, new.title, new.body_md);
            END;
            INSERT INTO notes_fts(rowid, title, body_md)
              SELECT id, title, body_md FROM notes
              WHERE id NOT IN (SELECT rowid FROM notes_fts);
            """)
    except sqlite3.OperationalError:
        conn.execute("CREATE TABLE IF NOT EXISTS notes_fts(rowid INTEGER PRIMARY KEY,"
                     " title TEXT, body_md TEXT)")


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
    # 13 — memoria por campaña y personas/remitentes
    """
    CREATE TABLE IF NOT EXISTS notes (
      id INTEGER PRIMARY KEY,
      mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
      plan_id TEXT REFERENCES plans(id) ON DELETE CASCADE,
      attack_id TEXT,
      kind TEXT NOT NULL DEFAULT 'obs',
      title TEXT NOT NULL DEFAULT '',
      body_md TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_notes_mission ON notes(mission_id, created_at);
    CREATE TABLE IF NOT EXISTS personas (
      id TEXT PRIMARY KEY,
      mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
      kind TEXT NOT NULL DEFAULT 'email',
      sender_name TEXT NOT NULL DEFAULT '',
      domain TEXT NOT NULL DEFAULT '',
      address TEXT NOT NULL DEFAULT '',
      phone TEXT NOT NULL DEFAULT '',
      bio TEXT NOT NULL DEFAULT '',
      avatar_path TEXT,
      burned INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL
    );
    """,
    # 14 — planificador: trabajos, criterios de éxito y avisos
    """
    CREATE TABLE IF NOT EXISTS jobs (
      id INTEGER PRIMARY KEY,
      plan_id TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
      step_id INTEGER NOT NULL REFERENCES plan_steps(id) ON DELETE CASCADE,
      due_at TEXT NOT NULL,
      state TEXT NOT NULL DEFAULT 'queued',
      attempts INTEGER NOT NULL DEFAULT 0,
      lease_until TEXT,
      last_error TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL,
      UNIQUE (step_id)
    );
    CREATE INDEX IF NOT EXISTS idx_jobs_due ON jobs(state, due_at);
    CREATE TABLE IF NOT EXISTS success_criteria (
      id INTEGER PRIMARY KEY,
      plan_id TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
      kind TEXT NOT NULL,
      spec TEXT NOT NULL DEFAULT '{}',
      met_at TEXT,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS notifications (
      id INTEGER PRIMARY KEY,
      plan_id TEXT REFERENCES plans(id) ON DELETE CASCADE,
      level TEXT NOT NULL DEFAULT 'info',
      channel TEXT NOT NULL,
      body TEXT NOT NULL,
      ok INTEGER NOT NULL DEFAULT 0,
      error TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL
    );
    """,
    # 15 — wallets: burner, mixer y treasury por misión
    """
    CREATE TABLE IF NOT EXISTS wallets (
      id INTEGER PRIMARY KEY,
      mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
      role TEXT NOT NULL DEFAULT 'burner',
      chain TEXT NOT NULL,
      address TEXT NOT NULL,
      xpub TEXT NOT NULL DEFAULT '',
      fingerprint TEXT NOT NULL DEFAULT '',
      label TEXT NOT NULL DEFAULT '',
      path TEXT NOT NULL DEFAULT '',
      burner INTEGER NOT NULL DEFAULT 0,
      burned INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_wallets_mission ON wallets(mission_id, chain);
    CREATE TABLE IF NOT EXISTS wallet_txs (
      id INTEGER PRIMARY KEY,
      wallet_id INTEGER NOT NULL REFERENCES wallets(id) ON DELETE CASCADE,
      txid TEXT NOT NULL DEFAULT '',
      direction TEXT NOT NULL DEFAULT 'out',
      amount TEXT NOT NULL DEFAULT '0',
      fee TEXT NOT NULL DEFAULT '0',
      counterparty TEXT NOT NULL DEFAULT '',
      purpose TEXT NOT NULL DEFAULT '',
      state TEXT NOT NULL DEFAULT 'built',
      created_at TEXT NOT NULL
    );
    """,
    # 16 — perfiles de red
    """
    CREATE TABLE IF NOT EXISTS net_profiles (
      id TEXT PRIMARY KEY,
      mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
      mode TEXT NOT NULL DEFAULT 'direct',
      doh_url TEXT NOT NULL DEFAULT '',
      ua_pool TEXT NOT NULL DEFAULT '[]',
      jitter_ms INTEGER NOT NULL DEFAULT 0,
      proxy_url TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL
    );
    """,
    # 16b — detección de infra
    _ensure_columns("infra", {"detected_at": "TEXT"}),
    # 17 — auditoría de herramientas del agente
    """
    CREATE TABLE IF NOT EXISTS tool_runs (
      id INTEGER PRIMARY KEY,
      run_id TEXT NOT NULL,
      mission_id TEXT NOT NULL DEFAULT '',
      tool TEXT NOT NULL,
      args TEXT NOT NULL DEFAULT '{}',
      result TEXT NOT NULL DEFAULT '',
      permission TEXT NOT NULL DEFAULT 'read',
      cost_usd REAL NOT NULL DEFAULT 0,
      ms INTEGER NOT NULL DEFAULT 0,
      ok INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_tool_runs_run ON tool_runs(run_id);
    """,
    # 18 — presupuesto y consentimiento de la misión
    _ensure_columns("missions", {
        "intent": "TEXT NOT NULL DEFAULT '{}'",
        "budget": "TEXT NOT NULL DEFAULT '{}'",
        "spend_usd": "REAL NOT NULL DEFAULT 0",
        "spend_crypto": "TEXT NOT NULL DEFAULT '{}'",
    }),
    # 18b — índice de eventos por nombre
    "CREATE INDEX IF NOT EXISTS idx_events_name ON events(event);",
    # 19 — búsqueda de notas (FTS5 si el binario lo trae)
    _notes_fts,
    # 20 — semilla de las wallets burner (BIP39) y red
    _ensure_columns("wallets", {"mnemonic": "TEXT NOT NULL DEFAULT ''",
                                "network": "TEXT NOT NULL DEFAULT 'testnet'"}),
]
