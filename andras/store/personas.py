"""Personas: la identidad del atacante en una campaña (remitente, dominio, teléfono, bio).

La persona es lo que da continuidad entre pasos: el mismo nombre, la misma firma y el
mismo número en todos los canales. Cuando algo se detecta, la persona se quema entera.
"""
from __future__ import annotations

import secrets
import sqlite3
import unicodedata
from dataclasses import dataclass

from andras.store.db import now

KINDS = ("email", "social")


@dataclass(slots=True)
class Persona:
    id: str
    mission_id: str
    kind: str
    sender_name: str
    domain: str
    address: str
    phone: str
    bio: str
    avatar_path: str | None
    burned: bool
    created_at: str


def slug(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    parts = [p for p in plain.lower().replace(".", " ").split() if p]
    return ".".join(parts) or "contacto"


def derive_address(sender_name: str, domain: str, style: str = "nombre.apellido") -> str:
    local = slug(sender_name)
    if style == "inicial":
        bits = [p for p in local.split(".") if p]
        local = (bits[0][:1] + (bits[-1] if len(bits) > 1 else "")) or "info"
    elif style == "soporte":
        local = "soporte"
    return f"{local}@{domain.strip().lower()}" if domain.strip() else local


def create(conn: sqlite3.Connection, mission_id: str, *, sender_name: str, domain: str = "",
           kind: str = "email", phone: str = "", bio: str = "",
           style: str = "nombre.apellido") -> Persona:
    if kind not in KINDS:
        raise ValueError(f"tipo de persona inválido: {kind}")
    if not sender_name.strip():
        raise ValueError("la persona necesita nombre")
    persona = Persona(id=secrets.token_hex(5), mission_id=mission_id, kind=kind,
                      sender_name=sender_name.strip()[:80], domain=domain.strip().lower(),
                      address=derive_address(sender_name, domain, style), phone=phone.strip(),
                      bio=bio.strip(), avatar_path=None, burned=False, created_at=now())
    conn.execute(
        "INSERT INTO personas(id,mission_id,kind,sender_name,domain,address,phone,bio,"
        "avatar_path,burned,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (persona.id, persona.mission_id, persona.kind, persona.sender_name, persona.domain,
         persona.address, persona.phone, persona.bio, None, 0, persona.created_at))
    return persona


def get(conn: sqlite3.Connection, persona_id: str) -> Persona | None:
    row = conn.execute("SELECT * FROM personas WHERE id=?", (persona_id,)).fetchone()
    return _persona(row) if row else None


def for_mission(conn: sqlite3.Connection, mission_id: str) -> list[Persona]:
    return [_persona(r) for r in conn.execute(
        "SELECT * FROM personas WHERE mission_id=? ORDER BY created_at", (mission_id,))]


def update(conn: sqlite3.Connection, persona_id: str, **fields) -> None:
    allowed = {"sender_name", "domain", "address", "phone", "bio", "avatar_path", "burned", "kind"}
    pairs = {k: v for k, v in fields.items() if k in allowed}
    if not pairs:
        return
    conn.execute(f"UPDATE personas SET {', '.join(f'{k}=?' for k in pairs)} WHERE id=?",
                 (*pairs.values(), persona_id))


def burn(conn: sqlite3.Connection, mission_id: str) -> int:
    cur = conn.execute("UPDATE personas SET burned=1 WHERE mission_id=? AND burned=0",
                       (mission_id,))
    return cur.rowcount


def _persona(row) -> Persona:
    return Persona(id=row["id"], mission_id=row["mission_id"], kind=row["kind"],
                   sender_name=row["sender_name"], domain=row["domain"],
                   address=row["address"], phone=row["phone"], bio=row["bio"],
                   avatar_path=row["avatar_path"], burned=bool(row["burned"]),
                   created_at=row["created_at"])
