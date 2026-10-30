"""Herramientas de wallet: crear burner/mixer/treasury, registrar movimientos y mezclar."""
from __future__ import annotations

from andras import wallet
from andras.agent import tools
from andras.store import budgets


@tools.tool("wallet_create", permission="write",
            description="Crea una wallet de la campaña. Rol `burner` (paga), `mixer` (mezcla) o "
                        "`treasury` (sólo recibe). BTC en testnet salvo config. Devuelve dirección.",
            schema={"type": "object",
                    "properties": {"chain": {"type": "string", "enum": list(wallet.CHAINS)},
                                   "role": {"type": "string", "enum": list(wallet.ROLES)},
                                   "label": {"type": "string"}},
                    "required": ["chain"]})
def wallet_create(ctx, chain: str, role: str = "burner", label: str = "") -> dict:
    created = wallet.create(ctx.conn, ctx.mission.id, chain=chain, role=role, label=label,
                            config=ctx.config)
    extra = " (semilla guardada en la base de datos)" if chain == "btc" and role != "treasury" else ""
    return {"text": f"wallet {created.id} {chain}/{role}: {created.address}{extra}",
            "data": {"id": created.id, "address": created.address}}


@tools.tool("wallet_list", permission="read",
            description="Lista las wallets de la campaña con rol, cadena y dirección.",
            schema={"type": "object", "properties": {}})
def wallet_list(ctx) -> dict:
    rows = wallet.for_mission(ctx.conn, ctx.mission.id)
    if not rows:
        return {"text": "sin wallets", "data": []}
    body = "\n".join(f"{w.id}. {w.chain}/{w.role} {w.address}"
                     + (" [quemada]" if w.burned else "") for w in rows)
    return {"text": body, "data": [w.id for w in rows]}


@tools.tool("wallet_balance", permission="read",
            description="Saldo de una wallet Monero. Para BTC devuelve que se consulta fuera.",
            schema={"type": "object", "properties": {"wallet_id": {"type": "integer"}},
                    "required": ["wallet_id"]})
def wallet_balance(ctx, wallet_id: int) -> dict:
    found = wallet.get(ctx.conn, wallet_id)
    if not found:
        raise tools.ToolError(f"wallet inexistente: {wallet_id}")
    return {"text": wallet.balance(ctx.config, found), "data": {"chain": found.chain}}


@tools.tool("wallet_transfer", permission="spend",
            description="Envía cripto desde una wallet Monero y descuenta del presupuesto. Con "
                        "BTC devuelve instrucciones porque se firma fuera.",
            schema={"type": "object",
                    "properties": {"wallet_id": {"type": "integer"},
                                   "to": {"type": "string"},
                                   "amount": {"type": "string"},
                                   "purpose": {"type": "string"}},
                    "required": ["wallet_id", "to", "amount"]})
def wallet_transfer(ctx, wallet_id: int, to: str, amount: str, purpose: str = "") -> dict:
    found = wallet.get(ctx.conn, wallet_id)
    if not found:
        raise tools.ToolError(f"wallet inexistente: {wallet_id}")
    value = float(amount)
    budgets.check_crypto(ctx.conn, ctx.mission.id, found.chain, value)
    if found.chain != "xmr":
        wallet.record_tx(ctx.conn, found.id, amount=amount, counterparty=to, purpose=purpose,
                         state="built")
        return {"text": f"movimiento BTC preparado hacia {to} ({amount} BTC).\n\n"
                        + wallet.swap_brief("btc", amount),
                "data": {"address": to}}
    result = wallet.transfer(ctx.config, found, to, amount)
    txid = result.get("tx_hash", "")
    wallet.record_tx(ctx.conn, found.id, txid=txid, amount=amount, counterparty=to,
                     purpose=purpose, state="sent")
    budgets.charge_crypto(ctx.conn, ctx.mission.id, found.chain, value)
    return {"text": f"enviado {amount} {found.chain} a {to} · tx {txid[:20]}…",
            "data": {"txid": txid}}


@tools.tool("wallet_record_tx", permission="write",
            description="Anota un movimiento hecho fuera (firma manual, intercambio) para que el "
                        "diario de la wallet quede completo.",
            schema={"type": "object",
                    "properties": {"wallet_id": {"type": "integer"},
                                   "txid": {"type": "string"},
                                   "direction": {"type": "string", "enum": ["in", "out"]},
                                   "amount": {"type": "string"},
                                   "counterparty": {"type": "string"},
                                   "purpose": {"type": "string"}},
                    "required": ["wallet_id", "amount"]})
def wallet_record_tx(ctx, wallet_id: int, amount: str, txid: str = "", direction: str = "out",
                     counterparty: str = "", purpose: str = "") -> dict:
    if not wallet.get(ctx.conn, wallet_id):
        raise tools.ToolError(f"wallet inexistente: {wallet_id}")
    tx = wallet.record_tx(ctx.conn, wallet_id, txid=txid, direction=direction, amount=amount,
                          counterparty=counterparty, purpose=purpose)
    return {"text": f"movimiento {tx} anotado", "data": {"id": tx}}


@tools.tool("wallet_txs", permission="read",
            description="Historial de movimientos de las wallets de la campaña.",
            schema={"type": "object", "properties": {}})
def wallet_txs(ctx) -> dict:
    rows = wallet.txs(ctx.conn, ctx.mission.id)
    if not rows:
        return {"text": "sin movimientos", "data": []}
    body = "\n".join(f"{r['created_at']} {r['role']}/{r['chain']} {r['direction']} "
                     f"{r['amount']} → {r['counterparty']} {r['purpose']} [{r['state']}]"
                     for r in rows)
    return {"text": body, "data": len(rows)}


@tools.tool("wallet_swap_brief", permission="read",
            description="Pasos de mezcla/cambio para mover fondos de burner a treasury. "
                        "Manual, sin llamar a ningún intercambio.",
            schema={"type": "object",
                    "properties": {"chain": {"type": "string", "enum": list(wallet.CHAINS)},
                                   "amount": {"type": "string"}},
                    "required": ["chain", "amount"]})
def wallet_swap_brief(ctx, chain: str, amount: str) -> dict:
    return {"text": wallet.swap_brief(chain, amount), "data": {"chain": chain}}
