"""Herramientas de red y OPSEC: perfil por misión, comprobación de Tor y quema de infra."""
from __future__ import annotations

from andras import net
from andras.agent import tools


@tools.tool("net_profile_create", permission="write",
            description="Fija el perfil de red de la campaña: `direct`, `doh` (DNS cifrado), "
                        "`tor` o `proxy`. Con `tor` todo el recon sale por SOCKS5.",
            schema={"type": "object",
                    "properties": {"mode": {"type": "string", "enum": list(net.MODES)},
                                   "proxy_url": {"type": "string"},
                                   "doh_url": {"type": "string"},
                                   "jitter_ms": {"type": "integer"}},
                    "required": ["mode"]})
def net_profile_create(ctx, mode: str, proxy_url: str = "", doh_url: str = "",
                       jitter_ms: int = 0) -> dict:
    profile = net.create(ctx.conn, ctx.mission.id, mode=mode, proxy_url=proxy_url,
                          doh_url=doh_url, jitter_ms=jitter_ms)
    return {"text": f"perfil de red {profile['id']} creado ({mode})", "data": profile}


@tools.tool("net_status", permission="read",
            description="Perfil de red efectivo y perfiles creados para la campaña.",
            schema={"type": "object", "properties": {}})
def net_status(ctx) -> dict:
    profiles = net.for_mission(ctx.conn, ctx.mission.id)
    body = net.describe(ctx.config)
    if profiles:
        body += "\nperfiles de la campaña:\n" + "\n".join(
            f"- {p['id']}: {p['mode']} {p['proxy_url'] or ''}" for p in profiles)
    return {"text": body, "data": {"count": len(profiles)}}


@tools.tool("tor_check", permission="read",
            description="Comprueba si hay circuito Tor local y por qué IP saldría.",
            schema={"type": "object", "properties": {}})
def tor_check(ctx) -> dict:
    import httpx

    proxy = (ctx.config.get("net") or {}).get("tor_socks", "socks5://127.0.0.1:9050")
    try:
        resp = httpx.get("https://check.torproject.org/api/ip", proxy=proxy, timeout=20)
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {"text": f"sin circuito Tor ({exc})", "data": {"ok": False}}
    ok = bool(data.get("IsTor"))
    return {"text": f"Tor {'activo' if ok else 'no confirmado'} · salida {data.get('IP', '?')}",
            "data": {"ok": ok, "ip": data.get("IP", "")}}


@tools.tool("infra_burn", permission="write",
            description="Marca como quemada la infraestructura detectada de la campaña: dominio, "
                        "buzón, persona. No se reutiliza en otra campaña.",
            schema={"type": "object", "properties": {}})
def infra_burn(ctx) -> dict:
    from andras.agent import tools as registry
    from andras.store import personas

    infra = net.burn(ctx.conn, ctx.mission.id)
    people = personas.burn(ctx.conn, ctx.mission.id)
    return {"text": f"{infra} elementos de infra y {people} personas quemados",
            "data": {"infra": infra, "personas": people, "tools": len(registry.all_tools())}}
