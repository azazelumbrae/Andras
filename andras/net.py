"""Perfiles de red y OPSEC: proxy SOCKS, DoH, UA rotativo y jitter.

Todo es opcional y degrada solo: sin Tor se sale directo, sin DoH se usa el DNS del sistema.
Ningún fallo de red debe impedir una campaña, sólo ensuciarla.
"""
from __future__ import annotations

import json
import random
import secrets
import sqlite3
import time

UAS = (
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"),
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/130.0 Safari/537.36"),
)

MODES = ("direct", "doh", "tor", "proxy")


def settings(config: dict) -> dict:
    net = config.get("net") or {}
    return {"mode": net.get("default_profile", "direct"),
            "proxy_url": (net.get("tor_socks", "socks5://127.0.0.1:9050")
                          if net.get("default_profile") == "tor"
                          else net.get("proxy_url", "")),
            "doh_url": net.get("doh_url", ""),
            "jitter_ms": int(net.get("jitter_ms", 0) or 0)}


def options(config: dict, profile: dict | None = None) -> dict:
    """`{proxy, headers}` para una petición. Un perfil explícito manda sobre el global."""
    chosen = {**settings(config), **(profile or {})}
    mode = chosen.get("mode", "direct")
    proxy = chosen.get("proxy_url") or None if mode in {"tor", "proxy"} else None
    headers = {"User-Agent": random.choice(UAS)}
    if chosen.get("doh_url"):
        headers["Accept"] = "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8"
    return {"proxy": proxy, "headers": headers}


def jitter(config: dict, profile: dict | None = None) -> None:
    """Espera aleatoria para no parecer un rastreador."""
    ms = int((profile or {}).get("jitter_ms") or settings(config)["jitter_ms"])
    if ms > 0:
        time.sleep(random.uniform(0, ms) / 1000)


def create(conn: sqlite3.Connection, mission_id: str, *, mode: str = "direct",
           doh_url: str = "", proxy_url: str = "", jitter_ms: int = 0) -> dict:
    if mode not in MODES:
        raise ValueError(f"modo de red inválido: {mode}")
    from andras.store.db import now

    profile_id = secrets.token_hex(4)
    conn.execute(
        "INSERT INTO net_profiles(id,mission_id,mode,doh_url,ua_pool,jitter_ms,proxy_url,"
        "created_at) VALUES(?,?,?,?,?,?,?,?)",
        (profile_id, mission_id, mode, doh_url, json.dumps(list(UAS)), int(jitter_ms),
         proxy_url, now()))
    return {"id": profile_id, "mode": mode, "doh_url": doh_url}


def for_mission(conn: sqlite3.Connection, mission_id: str) -> list[dict]:
    return [dict(row) for row in conn.execute(
        "SELECT * FROM net_profiles WHERE mission_id=? ORDER BY created_at DESC", (mission_id,))]


def describe(config: dict) -> str:
    current = settings(config)
    return (f"perfil {current['mode']} · proxy {current['proxy_url'] or '—'} · "
            f"doh {current['doh_url'] or '—'} · jitter {current['jitter_ms']} ms")


def burn(conn: sqlite3.Connection, mission_id: str) -> int:
    """Marca la infraestructura detectada de la misión para no reutilizarla."""
    from andras.store.db import now

    cur = conn.execute("UPDATE infra SET detected_at=? WHERE mission_id=? AND detected_at IS NULL",
                       (now(), mission_id))
    return cur.rowcount
