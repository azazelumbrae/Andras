"""Memoria de campaña: notas en markdown, buscables y exportables."""
from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from andras.core import ROOT
from andras.store.db import now

KINDS = ("obs", "hallazgo", "hipotesis", "decision", "incidencia", "credito")


@dataclass(slots=True)
class Note:
    id: int
    mission_id: str
    plan_id: str | None
    attack_id: str | None
    kind: str
    title: str
    body_md: str
    created_at: str


def _fts(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT sql FROM sqlite_master WHERE name='notes_fts'").fetchone()
    return bool(row and row["sql"] and "fts5" in row["sql"].lower())


def journal_path(mission_id: str) -> Path:
    path = ROOT / "data" / "missions" / mission_id
    path.mkdir(parents=True, exist_ok=True)
    return path / "journal.md"


def add(conn: sqlite3.Connection, mission_id: str, body_md: str, *, title: str = "",
        kind: str = "obs", plan_id: str | None = None, attack_id: str | None = None) -> Note:
    if kind not in KINDS:
        raise ValueError(f"tipo de nota inválido: {kind}")
    body_md = body_md.strip()
    if not body_md:
        raise ValueError("la nota está vacía")
    created = now()
    cur = conn.execute(
        "INSERT INTO notes(mission_id,plan_id,attack_id,kind,title,body_md,created_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (mission_id, plan_id, attack_id, kind, title[:160], body_md, created))
    note = Note(id=int(cur.lastrowid), mission_id=mission_id, plan_id=plan_id,
                attack_id=attack_id, kind=kind, title=title, body_md=body_md,
                created_at=created)
    _append_journal(note)
    return note


def _append_journal(note: Note) -> None:
    path = journal_path(note.mission_id)
    header = f"\n## {note.created_at} · {note.kind}" + (f" · {note.title}" if note.title else "")
    meta = []
    if note.plan_id:
        meta.append(f"plan: {note.plan_id}")
    if note.attack_id:
        meta.append(f"ataque: {note.attack_id}")
    block = header + "\n" + (f"_{' · '.join(meta)}_\n" if meta else "") + note.body_md + "\n"
    if not path.exists():
        path.write_text(f"# Diario de la misión {note.mission_id}\n"
                        "Registro cronológico del agente. Sólo se añade, nunca se reescribe.\n")
    with path.open("a") as handle:
        handle.write(block)


def search(conn: sqlite3.Connection, mission_id: str, query: str, limit: int = 10) -> list[Note]:
    query = query.strip()
    if not query:
        return []
    if _fts(conn):
        rows = conn.execute(
            "SELECT n.* FROM notes_fts f JOIN notes n ON n.id=f.rowid"
            " WHERE notes_fts MATCH ? AND n.mission_id=? ORDER BY rank LIMIT ?",
            (_fts_query(query), mission_id, limit))
    else:
        rows = conn.execute(
            "SELECT * FROM notes WHERE mission_id=? AND (title LIKE ? OR body_md LIKE ?)"
            " ORDER BY created_at DESC LIMIT ?",
            (mission_id, f"%{query}%", f"%{query}%", limit))
    return [_note(r) for r in rows]


def _fts_query(query: str) -> str:
    tokens = [t for t in "".join(c if c.isalnum() else " " for c in query).split() if t]
    return " OR ".join(f"{t}*" for t in tokens) or '""'


def for_mission(conn: sqlite3.Connection, mission_id: str, limit: int = 200) -> list[Note]:
    return [_note(r) for r in conn.execute(
        "SELECT * FROM notes WHERE mission_id=? ORDER BY created_at DESC LIMIT ?",
        (mission_id, limit))]


def timeline(conn: sqlite3.Connection, mission_id: str) -> list[Note]:
    return [_note(r) for r in conn.execute(
        "SELECT * FROM notes WHERE mission_id=? ORDER BY created_at", (mission_id,))]


def export_html(conn: sqlite3.Connection, mission_id: str) -> Path:
    """Copia el diario en HTML estático para leerlo fuera de la terminal."""
    import html

    path = journal_path(mission_id)
    target = path.with_suffix(".html")
    body = path.read_text() if path.exists() else "# vacío\n"
    pieces = []
    for line in body.splitlines():
        if line.startswith("## "):
            pieces.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("# "):
            pieces.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.strip():
            pieces.append(f"<p>{html.escape(line)}</p>")
    target.write_text(
        "<!doctype html><meta charset='utf-8'><title>Diario "
        f"{html.escape(mission_id)}</title><style>body{{font:16px system-ui;max-width:760px;"
        "margin:8vh auto;line-height:1.5;background:#10131a;color:#eef}h2{color:#8bd}"
        "</style>" + "\n".join(pieces))
    return target


def _note(row) -> Note:
    return Note(id=row["id"], mission_id=row["mission_id"], plan_id=row["plan_id"],
                attack_id=row["attack_id"], kind=row["kind"], title=row["title"],
                body_md=row["body_md"], created_at=row["created_at"])


def archive(mission_id: str) -> Path | None:
    """Empaqueta el diario cuando la misión se cierra."""
    path = journal_path(mission_id)
    if not path.exists():
        return None
    target = path.parent / "journal.md.bak"
    shutil.copy2(path, target)
    return target
