"""Presupuesto por misión: pasos, tokens, dólares y cripto. Nada se ejecuta sin tope."""
from __future__ import annotations

import json
import sqlite3

DEFAULTS = {"max_steps": 40, "max_tokens": 300_000, "max_usd": 3.0,
            "max_crypto": {"btc": 0.001, "xmr": 0.0}}


class BudgetExceeded(RuntimeError):
    pass


def get(conn: sqlite3.Connection, mission_id: str) -> dict:
    row = conn.execute("SELECT budget, spend_usd, spend_crypto FROM missions WHERE id=?",
                       (mission_id,)).fetchone()
    if not row:
        raise ValueError(f"misión inexistente: {mission_id}")
    budget = {**DEFAULTS, **json.loads(row["budget"] or "{}")}
    budget["max_crypto"] = {**DEFAULTS["max_crypto"], **budget.get("max_crypto", {})}
    budget["spent_usd"] = float(row["spend_usd"] or 0)
    budget["spent_crypto"] = {"btc": 0.0, "xmr": 0.0,
                              **json.loads(row["spend_crypto"] or "{}")}
    budget["max_usd"] = float(budget["max_usd"])
    budget["max_steps"] = int(budget["max_steps"])
    budget["max_tokens"] = int(budget["max_tokens"])
    return budget


def set_budget(conn: sqlite3.Connection, mission_id: str, **fields) -> dict:
    current = {k: v for k, v in get(conn, mission_id).items()
               if k in {"max_steps", "max_tokens", "max_usd", "max_crypto"}}
    if "max_crypto" in fields:
        current["max_crypto"] = {**current["max_crypto"], **fields.pop("max_crypto")}
    current.update({k: v for k, v in fields.items() if k in DEFAULTS})
    conn.execute("UPDATE missions SET budget=? WHERE id=?", (json.dumps(current), mission_id))
    return get(conn, mission_id)


def charge_usd(conn: sqlite3.Connection, mission_id: str, amount: float) -> None:
    if amount <= 0:
        return
    conn.execute("UPDATE missions SET spend_usd=spend_usd+? WHERE id=?", (amount, mission_id))


def charge_crypto(conn: sqlite3.Connection, mission_id: str, chain: str, amount: float) -> None:
    if amount <= 0:
        return
    budget = get(conn, mission_id)
    spent = budget["spent_crypto"]
    spent[chain] = spent.get(chain, 0.0) + amount
    conn.execute("UPDATE missions SET spend_crypto=? WHERE id=?", (json.dumps(spent), mission_id))


def check_usd(conn: sqlite3.Connection, mission_id: str, amount: float) -> None:
    budget = get(conn, mission_id)
    if budget["spent_usd"] + amount > budget["max_usd"]:
        raise BudgetExceeded(f"tope en dólares: {budget['spent_usd']:.4f}+{amount:.4f} "
                             f"> {budget['max_usd']:.4f}")


def check_crypto(conn: sqlite3.Connection, mission_id: str, chain: str, amount: float) -> None:
    budget = get(conn, mission_id)
    limit = budget["max_crypto"].get(chain, 0.0)
    if budget["spent_crypto"].get(chain, 0.0) + amount > limit:
        raise BudgetExceeded(f"tope en {chain}: {budget['spent_crypto'].get(chain, 0.0)}"
                             f"+{amount} > {limit}")


def summary(conn: sqlite3.Connection, mission_id: str) -> str:
    b = get(conn, mission_id)
    spent = ", ".join(f"{v:.6f} {k}" for k, v in b["spent_crypto"].items() if v)
    return (f"pasos {b['max_steps']} · tokens {b['max_tokens']} · "
            f"USD {b['spent_usd']:.3f}/{b['max_usd']:.2f}"
            + (f" · cripto {spent}" if spent else ""))
