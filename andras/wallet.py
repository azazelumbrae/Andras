"""Wallets burner, mixer y treasury. Sólo terminal y lo más ligero posible.

Bitcoin con `embit` (BIP39 → BIP84, testnet por defecto); Monero por `monero-wallet-rpc`.
La semilla se guarda en la base de datos: es un laboratorio, no un monedero de producción.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass

from andras.store.db import now

ROLES = ("burner", "mixer", "treasury")
CHAINS = ("btc", "xmr")


class WalletError(RuntimeError):
    pass


@dataclass(slots=True)
class Wallet:
    id: int
    mission_id: str
    role: str
    chain: str
    address: str
    xpub: str
    fingerprint: str
    label: str
    path: str
    burner: bool
    burned: bool
    created_at: str


def _network(config: dict) -> str:
    network = (config.get("wallet") or {}).get("network", "testnet")
    return "mainnet" if network == "mainnet" else "testnet"


def _embit_network(network: str) -> str:
    return "main" if network == "mainnet" else "test"


def create(conn: sqlite3.Connection, mission_id: str, *, chain: str = "btc",
           role: str = "burner", label: str = "", config: dict | None = None) -> Wallet:
    if chain not in CHAINS:
        raise WalletError(f"cadena no soportada: {chain}")
    if role not in ROLES:
        raise WalletError(f"rol inválido: {role}")
    if chain == "xmr":
        return _create_monero(conn, mission_id, role, label, config or {})
    return _create_btc(conn, mission_id, role, label, config or {})


def _create_btc(conn, mission_id, role, label, config) -> Wallet:
    try:
        from embit import bip32, bip39
        from embit.networks import NETWORKS
        from embit.script import p2wpkh
    except ImportError as exc:  # pragma: no cover - depende del extra
        raise WalletError("instala el extra `crypto` para wallets BTC") from exc
    network = _network(config)
    names = NETWORKS[_embit_network(network)]
    words = bip39.mnemonic_from_bytes(os.urandom(16)) if role != "treasury" else ""
    seed = bip39.mnemonic_to_seed(words) if words else b"\x01" * 64
    root = bip32.HDKey.from_seed(seed, version=names["xprv"])
    path = "m/84'/1'/0'/0/0" if network == "testnet" else "m/84'/0'/0'/0/0"
    account = root.derive("m/84'/1'/0'" if network == "testnet" else "m/84'/0'/0'")
    child = root.derive(path)
    address = p2wpkh(child.to_public().key).address(names)
    return _insert(conn, mission_id, role, "btc", address=address, xpub=account.to_public().to_base58(),
                   fingerprint=root.fingerprint.hex(), label=label, path=path, mnemonic=words,
                   network=network, burner=role == "burner")


def rpc(config: dict, method: str, params: dict | None = None) -> dict:
    """Llamada a monero-wallet-rpc. Falla claro si no hay nodo."""
    import httpx

    url = (config.get("wallet") or {}).get("monero_rpc", "http://127.0.0.1:18082/json_rpc")
    try:
        resp = httpx.post(url, json={"jsonrpc": "2.0", "id": "1", "method": method,
                                     "params": params or {}}, timeout=25)
    except httpx.HTTPError as exc:
        raise WalletError(f"monero-wallet-rpc no responde: {exc}") from exc
    data = resp.json()
    if data.get("error"):
        raise WalletError(str(data["error"].get("message", data["error"])))
    return data.get("result", {})


def _create_monero(conn, mission_id, role, label, config) -> Wallet:
    result = rpc(config, "create_address", {"label": label or role, "account_index": 0})
    address = result.get("address", "")
    if not address:
        raise WalletError("monero-wallet-rpc no devolvió dirección")
    return _insert(conn, mission_id, role, "xmr", address=address, xpub="", fingerprint="",
                   label=label, path="", mnemonic="", network=_network(config),
                   burner=role == "burner")


def _insert(conn, mission_id, role, chain, **fields) -> Wallet:
    cur = conn.execute(
        "INSERT INTO wallets(mission_id,role,chain,address,xpub,fingerprint,label,path,burner,"
        "burned,created_at,mnemonic,network) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (mission_id, role, chain, fields["address"], fields["xpub"], fields["fingerprint"],
         fields["label"], fields["path"], int(fields["burner"]), 0, now(), fields["mnemonic"],
         fields["network"]))
    return get(conn, int(cur.lastrowid))


def get(conn: sqlite3.Connection, wallet_id: int) -> Wallet | None:
    row = conn.execute("SELECT * FROM wallets WHERE id=?", (wallet_id,)).fetchone()
    return _wallet(row) if row else None


def for_mission(conn: sqlite3.Connection, mission_id: str) -> list[Wallet]:
    return [_wallet(r) for r in conn.execute(
        "SELECT * FROM wallets WHERE mission_id=? ORDER BY created_at", (mission_id,))]


def burn(conn: sqlite3.Connection, mission_id: str) -> int:
    cur = conn.execute("UPDATE wallets SET burned=1 WHERE mission_id=? AND burner=1 AND burned=0",
                       (mission_id,))
    return cur.rowcount


def balance(config: dict, wallet: Wallet) -> str:
    if wallet.chain == "xmr":
        result = rpc(config, "get_balance", {"account_index": 0})
        return f"{result.get('unlocked_balance', 0) / 1e12:.12f} XMR disponibles"
    raise WalletError("el saldo BTC se consulta en un explorador; la wallet es determinista")


def transfer(config: dict, wallet: Wallet, to: str, amount: str) -> dict:
    if wallet.chain != "xmr":
        raise WalletError("las transferencias BTC se firman fuera; usa la watch-only y un "
                          "monedero externo con la semilla")
    return rpc(config, "transfer", {"destinations": [{"address": to, "amount": int(float(amount) * 1e12)}],
                                    "account_index": 0})


def record_tx(conn: sqlite3.Connection, wallet_id: int, *, txid: str = "", direction: str = "out",
              amount: str = "0", fee: str = "0", counterparty: str = "", purpose: str = "",
              state: str = "built") -> int:
    cur = conn.execute(
        "INSERT INTO wallet_txs(wallet_id,txid,direction,amount,fee,counterparty,purpose,state,"
        "created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (wallet_id, txid, direction, amount, fee, counterparty, purpose, state, now()))
    return int(cur.lastrowid)


def txs(conn: sqlite3.Connection, mission_id: str) -> list:
    return list(conn.execute(
        "SELECT t.*, w.chain, w.role FROM wallet_txs t JOIN wallets w ON w.id=t.wallet_id"
        " WHERE w.mission_id=? ORDER BY t.created_at DESC", (mission_id,)))


def swap_brief(chain: str, amount: str) -> str:
    """Qué decirle al operador sobre mezcla y cambio. Sin APIs: son manuales y lentas."""
    if chain == "btc":
        return (
            f"# Mezcla BTC · {amount} BTC\n\n"
            "1. Pasa los fondos de la burner a una dirección de depósito de un intercambio "
            "sin KYC (FixedFloat, ThorSwap) y cambia a Monero.\n"
            "2. Retira el XMR a una wallet nueva, distinta de la burner inicial.\n"
            "3. Espera confirmaciones y anota txid, servicio y comisión. No reutilices la "
            "dirección de depósito.\n"
            "4. Si el importe es alto, parte en dos tandas de 24 h distintas.\n\n"
            "El treasury sólo recibe, nunca firma: es watch-only.")
    if chain == "xmr":
        return (
            f"# Mezcla XMR · {amount} XMR\n\n"
            "1. Envía desde la burner a una subdirección nueva del treasury.\n"
            "2. Espera 10 confirmaciones antes de dar por bueno el movimiento.\n"
            "3. Anota txid y altura de bloque; sin explorador público no hay más rastro.\n"
            "4. Monero ya ofusca origen; no hace falta mezclador externo salvo importes grandes.")
    return f"mezcla para {amount} {chain}"


def _wallet(row) -> Wallet:
    return Wallet(id=row["id"], mission_id=row["mission_id"], role=row["role"],
                  chain=row["chain"], address=row["address"], xpub=row["xpub"],
                  fingerprint=row["fingerprint"], label=row["label"], path=row["path"],
                  burner=bool(row["burner"]), burned=bool(row["burned"]),
                  created_at=row["created_at"])
