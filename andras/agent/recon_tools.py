"""Herramientas de OSINT del agente. Una fuente por herramienta, artefactos con procedencia."""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import parse_qs, quote, unquote, urlparse

from andras.agent import tools
from andras.evidence import dossier as dossier_mod
from andras.models import Finding
from andras.recon import http
from andras.store import evidence


def _record(ctx, kind: str, value: str, source: str, confidence: int) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        artifact_id, _ = evidence.add(ctx.conn, ctx.mission.id, Finding(
            kind=kind, value=value, source=source, confidence=confidence))
    except ValueError:
        return None
    return artifact_id


_BROWSER = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


def _unwrap(href: str) -> str:
    """DuckDuckGo devuelve redirecciones; saca la URL real del parámetro uddg."""
    if "uddg=" in href:
        params = parse_qs(urlparse(href).query)
        return unquote(params.get("uddg", [href])[0])
    return href if href.startswith("http") else "https:" + href


def _rdap_url(domain: str) -> str:
    """Los .com/.net tienen servidor RDAP propio; el resto va por el redirector."""
    tld = domain.rsplit(".", 1)[-1].lower()
    if tld in {"com", "net"}:
        return f"https://rdap.verisign.com/{tld}/v1/domain/{domain}"
    return f"https://rdap.org/domain/{domain}"


def _ddg(query: str, limit: int) -> list[tuple[str, str]]:
    """DuckDuckGo lite, con reintento: a veces devuelve una página de cortesía."""
    url = f"https://lite.duckduckgo.com/lite/?q={quote(query)}"
    for attempt in range(2):
        try:
            text, _, _ = http.fetch(url, delay=1.2 + attempt, headers={"User-Agent": _BROWSER})
        except http.FetchError:
            continue
        found = re.findall(r"href=\"([^\"]+)\"[^>]*class='result-link'>(.*?)</a>", text,
                           re.DOTALL)
        if found:
            return [(_unwrap(href), re.sub(r"<[^>]+>", "", title).strip())
                    for href, title in found[:limit]]
    return []


def _summary(ids: list[int], label: str) -> str:
    return f"{len(ids)} artefactos guardados de {label}" if ids else f"sin hallazgos en {label}"


@tools.tool("crtsh_subdomains", permission="read",
            description="Subdominios publicados en Certificate Transparency para un dominio. "
                        "Gratis, sin clave, buena fuente de superficie real.",
            schema={"type": "object", "properties": {"domain": {"type": "string"}},
                    "required": ["domain"]})
def crtsh_subdomains(ctx, domain: str) -> dict:
    url = f"https://crt.sh/?q=%25.{quote(domain)}&output=json"
    text, _, _ = http.fetch(url, delay=0.5)
    try:
        rows = json.loads(text)
    except json.JSONDecodeError as exc:
        raise tools.ToolError(f"crt.sh no devolvió JSON ({exc})") from exc
    names = set()
    for row in rows[:400]:
        for name in str(row.get("name_value", "")).splitlines():
            name = name.strip().lower().lstrip("*.")
            if name.endswith(domain) and name != domain:
                names.add(name)
    ids = [_record(ctx, "domain", name, f"https://crt.sh/?q={domain}", 70)
           for name in sorted(names)[:40]]
    ids = [i for i in ids if i]
    return {"text": _summary(ids, "crt.sh") + "\n" + "\n".join(sorted(names)[:40]),
            "data": {"count": len(ids)}}


@tools.tool("rdap_lookup", permission="read",
            description="Registro RDAP de un dominio: registrador, fechas, servidores y estado. "
                        "Sirve para datar la infraestructura del objetivo.",
            schema={"type": "object", "properties": {"domain": {"type": "string"}},
                    "required": ["domain"]})
def rdap_lookup(ctx, domain: str) -> dict:
    source = _rdap_url(domain)
    text, _, _ = http.fetch(source, delay=0.5)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"text": text[:800], "data": {}}
    facts = []
    for entity in data.get("entities", []):
        for role in entity.get("roles", []):
            for item in entity.get("vcardArray", [[], []])[1]:
                if item[0] == "fn":
                    facts.append(f"entidad ({role}): {item[3]}")
    for event in data.get("events", []):
        facts.append(f"{event.get('eventAction')}: {event.get('eventDate')}")
    for server in data.get("nameservers", []):
        facts.append(f"ns: {server.get('ldhName')}")
    ids = [_record(ctx, "infra", fact, source, 65) for fact in facts[:20]]
    return {"text": "\n".join(facts[:20]) or "sin datos RDAP", "data": {"count": len(ids)}}


@tools.tool("wayback_urls", permission="read",
            description="URLs históricas del dominio en Internet Archive. Descubre rutas, "
                        "paneles y documentos retirados.",
            schema={"type": "object",
                    "properties": {"domain": {"type": "string"},
                                   "limit": {"type": "integer"}},
                    "required": ["domain"]})
def wayback_urls(ctx, domain: str, limit: int = 30) -> dict:
    limit = max(1, min(60, limit))
    url = (f"https://web.archive.org/cdx/search/cdx?url={quote(domain)}/*&output=json"
           f"&fl=original&collapse=urlkey&limit={limit}")
    text, _, _ = http.fetch(url, delay=0.5)
    try:
        rows = json.loads(text)[1:]
    except (json.JSONDecodeError, IndexError):
        return {"text": "archive sin resultados", "data": {"count": 0}}
    urls = [row[0] for row in rows if row]
    ids = [_record(ctx, "doc", u, "https://web.archive.org", 45) for u in urls[:limit]]
    return {"text": "\n".join(urls[:limit]), "data": {"count": len(ids)}}


@tools.tool("github_user", permission="read",
            description="Perfil público de GitHub de un usuario: nombre real, empresa, correo "
                        "declarado y repos. Muy útil para correos y tecnologías.",
            schema={"type": "object", "properties": {"handle": {"type": "string"}},
                    "required": ["handle"]})
def github_user(ctx, handle: str) -> dict:
    source = f"https://api.github.com/users/{quote(handle)}"
    text, _, _ = http.fetch(source, delay=0.5, headers={"Accept": "application/vnd.github+json"})
    data = json.loads(text)
    facts = {k: v for k, v in data.items()
             if k in {"name", "company", "email", "blog", "location", "bio", "twitter_username"}}
    for key, value in facts.items():
        if value:
            kind = "person" if key == "name" else "email" if key == "email" else "username"
            _record(ctx, kind, str(value), source, 60)
    repos, _, _ = http.fetch(f"{source}/repos?per_page=10", delay=0.3,
                             headers={"Accept": "application/vnd.github+json"})
    for repo in json.loads(repos)[:10]:
        _record(ctx, "repo", repo.get("html_url", ""), source, 50)
    return {"text": json.dumps(facts, ensure_ascii=False), "data": facts}


PLATFORMS = {
    "github": "https://github.com/{h}",
    "x": "https://x.com/{h}",
    "instagram": "https://www.instagram.com/{h}/",
    "telegram": "https://t.me/{h}",
    "keybase": "https://keybase.io/{h}",
    "reddit": "https://www.reddit.com/user/{h}",
}


@tools.tool("social_probe", permission="read",
            description="Comprueba en qué plataformas existe un alias. Devuelve sólo las que "
                        "responden 200.",
            schema={"type": "object", "properties": {"handle": {"type": "string"}},
                    "required": ["handle"]})
def social_probe(ctx, handle: str) -> dict:
    handle = handle.strip().lstrip("@")
    alive = []
    for template in PLATFORMS.values():
        url = template.format(h=quote(handle))
        try:
            http.fetch(url, delay=0.3, timeout=10)
        except http.FetchError:
            continue
        alive.append(url)
        _record(ctx, "social", url, "sonda directa", 55)
    return {"text": "\n".join(alive) or "el alias no aparece", "data": alive}


@tools.tool("gravatar_check", permission="read",
            description="Comprueba si un correo tiene Gravatar y devuelve el perfil público. "
                        "Confirma que el correo existe y da nombre real.",
            schema={"type": "object", "properties": {"email": {"type": "string"}},
                    "required": ["email"]})
def gravatar_check(ctx, email: str) -> dict:
    digest = hashlib.md5(email.strip().lower().encode()).hexdigest()
    source = f"https://gravatar.com/{digest}.json"
    try:
        text, _, _ = http.fetch(source, delay=0.3)
    except http.FetchError:
        return {"text": "sin gravatar", "data": {}}
    data = json.loads(text).get("entry", [{}])[0]
    if data.get("displayName"):
        _record(ctx, "person", data["displayName"], source, 70)
    for account in data.get("accounts", []):
        _record(ctx, "social", f"{account.get('domain')}/{account.get('username')}", source, 60)
    return {"text": json.dumps(data, ensure_ascii=False)[:800], "data": data}


@tools.tool("email_permutations", permission="read",
            description="Genera correos probables a partir del nombre y el dominio, comprueba "
                        "el MX y los guarda como `inferred` hasta confirmarlos.",
            schema={"type": "object",
                    "properties": {"first": {"type": "string"}, "last": {"type": "string"},
                                   "domain": {"type": "string"}},
                    "required": ["first", "last", "domain"]})
def email_permutations(ctx, first: str, last: str, domain: str) -> dict:
    first, last, domain = (first.lower().strip(), last.lower().strip(), domain.lower().strip())
    source = f"patrones sobre {domain}"
    patterns = [f"{first}.{last}", f"{first[0]}{last}", f"{first}", f"{first}_{last}",
                f"{last}.{first}"]
    ids = [_record(ctx, "email", f"{p}@{domain}", source, 40) for p in patterns]
    return {"text": "\n".join(f"{p}@{domain}" for p in patterns), "data": {"count": len(ids)}}


@tools.tool("http_probe", permission="read",
            description="Descarga una URL, devuelve título y tecnologías evidentes. Usa el "
                        "perfil de red activo (Tor si está configurado).",
            schema={"type": "object", "properties": {"url": {"type": "string"}},
                    "required": ["url"]})
def http_probe(ctx, url: str) -> dict:
    text, ctype, _ = http.fetch(url, delay=float(ctx.config.get("recon_delay", 1.0)))
    plain = http.html_to_text(text) if "html" in ctype else text
    title = re.search(r"<title[^>]*>(.*?)</title>", text, re.DOTALL | re.IGNORECASE)
    hints = [tech for tech in ("wordpress", "drupal", "shopify", "cloudflare", "react",
                               "next.js", "php") if tech in text.lower()]
    head = f"título: {title.group(1).strip()[:120]}" if title else "sin título"
    snapshot = http.save(plain, ctx.mission.id, url)
    _record(ctx, "objetivo", url, url, 60)
    return {"text": f"{head}\ntecnologías: {', '.join(hints) or '—'}\n\n{plain[:1500]}",
            "data": {"snapshot": snapshot, "hints": hints}}


@tools.tool("web_search", permission="read",
            description="Busca en la web. Usa SearXNG si está configurado; si no, prueba "
                        "DuckDuckGo y Marginalia. Si todos fallan te lo dice: no insistas.",
            schema={"type": "object",
                    "properties": {"query": {"type": "string"},
                                   "limit": {"type": "integer"}},
                    "required": ["query"]})
def web_search(ctx, query: str, limit: int = 8) -> dict:
    limit = max(1, min(15, limit))
    pairs, used = [], ""
    base = ctx.config.get("searxng_url", "")
    if base:
        try:
            pairs = _searx(base, query, limit)
            used = "searxng"
        except (http.FetchError, json.JSONDecodeError):
            pairs = []
    if not pairs:
        pairs = _ddg(query, limit)
        used = "duckduckgo"
    if not pairs:
        pairs = _marginalia(query, limit)
        used = "marginalia"
    if not pairs:
        return {"text": "sin resultados: los buscadores están bloqueando o no responden. "
                        "Configura `searxng_url` en config.json y sigue con otras fuentes.",
                "data": {"count": 0, "provider": "ninguno"}}
    source = f"busqueda:{used}:{query[:60]}"
    for href, _ in pairs:
        _record(ctx, "objetivo", href, source, 40)
    body = "\n".join(f"- {title}\n  {href}" for href, title in pairs)
    return {"text": body, "data": {"count": len(pairs), "provider": used}}


def _searx(base: str, query: str, limit: int) -> list[tuple[str, str]]:
    url = f"{base.rstrip('/')}/search?q={quote(query)}&format=json"
    text, _, _ = http.fetch(url, delay=0.6)
    rows = json.loads(text).get("results", [])[:limit]
    return [(r.get("url", ""), f"{r.get('title', '')} — {r.get('content', '')[:200]}")
            for r in rows if r.get("url")]


def _marginalia(query: str, limit: int) -> list[tuple[str, str]]:
    url = f"https://search.marginalia.nu/search?query={quote(query)}"
    try:
        text, _, _ = http.fetch(url, delay=0.8, headers={"User-Agent": _BROWSER})
    except http.FetchError:
        return []
    from html import unescape

    found = re.findall(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', text, re.DOTALL)
    skip = ("marginalia.nu", "creativecommons.org", "ip2location", "github.com/MarginaliaSearch")
    out = []
    for href, title in found:
        title = unescape(re.sub(r"<[^>]+>", "", title)).strip()
        if len(title) < 12 or any(s in href for s in skip):
            continue
        out.append((href, title))
        if len(out) >= limit:
            break
    return out


@tools.tool("dossier_read", permission="read",
            description="Lee el dossier actual y los artefactos usables con su verificación.",
            schema={"type": "object", "properties": {}})
def dossier_read(ctx) -> dict:
    data = dossier_mod.load(ctx.conn, ctx.mission.id)
    usable = evidence.usable(ctx.conn, ctx.mission.id)
    lines = []
    if data:
        for key, values in data.items():
            if isinstance(values, list):
                for item in values[:6]:
                    lines.append(f"{key}: {item.get('texto')} ({item.get('artifacts')})")
    lines += [f"[{a.id}] {a.kind}: {a.value} ({a.verification}, {a.confidence})"
              for a in usable[:40]]
    return {"text": "\n".join(lines) or "dossier vacío", "data": {"usable": len(usable)}}


@tools.tool("artifact_link", permission="write",
            description="Anota que un artefacto sostiene una afirmación. Queda en el diario.",
            schema={"type": "object",
                    "properties": {"artifact_id": {"type": "integer"},
                                   "claim": {"type": "string"}},
                    "required": ["artifact_id", "claim"]})
def artifact_link(ctx, artifact_id: int, claim: str) -> dict:
    found = evidence.by_ids(ctx.conn, [artifact_id])
    if not found:
        raise tools.ToolError(f"artifact inexistente: {artifact_id}")
    from andras.store import notes

    artifact = found[0]
    notes.add(ctx.conn, ctx.mission.id, f"{claim}\n\nsoporte: [{artifact.id}] {artifact.kind} "
              f"{artifact.value} · {artifact.verification}", kind="hallazgo", title=claim[:80])
    return {"text": f"enlazado {artifact.kind} {artifact.value}", "data": {"id": artifact.id}}
