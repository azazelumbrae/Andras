"""Colectores OSINT. Cada uno declara qué necesita y qué kinds produce."""
from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

from andras.models import Finding, Mission
from andras.recon import http

CollectorFn = Callable[["Ctx"], list[Finding]]


@dataclass
class Ctx:
    mission: Mission
    config: dict
    log: Callable[[str], None]

    def fetch(self, url: str, **kwargs) -> str:
        text, ctype, _ = http.fetch(url, delay=float(self.config.get("recon_delay", 1.5)), **kwargs)
        return http.html_to_text(text) if "html" in ctype else text


@dataclass
class Collector:
    name: str
    kinds: tuple[str, ...]
    requires: tuple[str, ...]
    run: CollectorFn


REGISTRY: dict[str, Collector] = {}


def register(name: str, kinds: tuple[str, ...], requires: tuple[str, ...] = ()):
    def wrap(fn: CollectorFn) -> CollectorFn:
        REGISTRY[name] = Collector(name=name, kinds=kinds, requires=requires, run=fn)
        return fn

    return wrap


def applicable(mission: Mission) -> list[Collector]:
    have = {k for k in ("domain", "target_name", "target_company", "target_role")
            if getattr(mission, k, "")}
    return [c for c in REGISTRY.values() if set(c.requires) <= have]


# ---------------------------------------------------------------- dorks

DORK_TEMPLATES = [
    '"{name}" {company} filetype:pdf',
    '"{name}" {company} filetype:xlsx',
    '"{name}" {company} correo contacto',
    '"{name}" {company} linkedin',
    '"{name}" {domain}',
    'site:{domain}',
    '"{company}" organigrama',
    '"{company}" clientes',
]


@register("dorks", kinds=("doc",), requires=("target_name",))
def dorks(ctx: Ctx) -> list[Finding]:
    out = []
    for template in DORK_TEMPLATES:
        query = template.format(name=ctx.mission.target_name,
                                company=ctx.mission.target_company,
                                domain=ctx.mission.domain).replace("  ", " ").strip()
        if query.startswith('""'):
            continue
        for hit in search(query, limit=6, log=ctx.log):
            out.append(Finding(kind="doc", value=hit, source=f"dork:{query}",
                               confidence=40, source_domain="duckduckgo.com"))
    return out


def search(query: str, limit: int = 6, log=None) -> list[str]:
    import urllib.parse

    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    try:
        html = http.fetch(url)[0]
    except http.FetchError as exc:
        if log:
            log(f"  ! ddg {query[:40]}: {exc}")
        return []
    urls = []
    for raw in re.findall(r'class="result__a"[^>]*href="([^"]+)"', html)[:limit]:
        if raw.startswith(("//duckduckgo.com/l/?uddg=", "/l/?uddg=")):
            raw = urllib.parse.unquote(raw.split("uddg=")[1].split("&")[0])
        if raw.startswith("http"):
            urls.append(raw)
    return urls


# ---------------------------------------------------------------- infra

@register("crt", kinds=("domain", "infra"), requires=("target_company",))
def crt_sh(ctx: Ctx) -> list[Finding]:
    slug = re.sub(r"[^a-z0-9]", "", ctx.mission.target_company.lower())
    if len(slug) < 4:
        return []
    try:
        body = ctx.fetch(f"https://crt.sh/?q=%25{slug}%25&output=json", timeout=40)
        rows = json.loads(body)
    except (http.FetchError, json.JSONDecodeError):
        return []
    out, seen = [], set()
    for row in rows[:400]:
        for domain in str(row.get("name_value", "")).split("\n"):
            domain = domain.strip().lstrip("*.").lower()
            if slug in domain and domain.count(".") <= 2 and domain not in seen:
                seen.add(domain)
                out.append(Finding(kind="domain", value=domain, source="crt.sh/api",
                                   source_domain="crt.sh", confidence=45))
    return out[:15]


@register("dns", kinds=("infra",), requires=("domain",))
def dns(ctx: Ctx) -> list[Finding]:
    out = []
    for rtype in ("MX", "TXT", "NS", "A"):
        try:
            proc = subprocess.run(["dig", "+short", rtype, ctx.mission.domain],
                                  capture_output=True, text=True, timeout=15, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        values = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        if values:
            out.append(Finding(kind="infra", value=f"{rtype}: " + " ".join(values[:8]),
                               source=f"dig:{rtype}", source_domain="dns", confidence=60))
    return out


@register("whois", kinds=("infra",), requires=("domain",))
def whois(ctx: Ctx) -> list[Finding]:
    try:
        proc = subprocess.run(["whois", ctx.mission.domain], capture_output=True, text=True,
                              timeout=25, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return []
    keep = ("registrar", "creation", "created", "expiry", "registrant", "name server",
            "organization", "country")
    lines = [line.strip() for line in proc.stdout.splitlines()
             if line.strip() and any(k in line.lower() for k in keep)]
    if not lines:
        return []
    return [Finding(kind="infra", value="\n".join(lines[:25]), source="whois",
                    source_domain="whois", confidence=65)]


# ---------------------------------------------------------------- identidad

@register("github", kinds=("repo", "username"), requires=("target_name",))
def github(ctx: Ctx) -> list[Finding]:
    query = ctx.mission.target_name.replace(" ", "+")
    try:
        data = json.loads(ctx.fetch(
            f"https://api.github.com/search/users?q={query}&per_page=5",
            headers={"Accept": "application/vnd.github+json"}))
    except (http.FetchError, json.JSONDecodeError):
        return []
    out = []
    for user in data.get("items", [])[:5]:
        out.append(Finding(kind="username", value=user["login"], source=user["html_url"],
                           source_domain="github.com", confidence=50))
        try:
            repos = json.loads(ctx.fetch(user["repos_url"] + "?per_page=5"))
        except (http.FetchError, json.JSONDecodeError, KeyError):
            continue
        for repo in repos if isinstance(repos, list) else []:
            out.append(Finding(kind="repo", value=repo["html_url"], source=user["html_url"],
                               source_domain="github.com", confidence=45))
    return out


@register("email_patterns", kinds=("email",), requires=("target_name", "domain"))
def email_patterns(ctx: Ctx) -> list[Finding]:
    parts = [p for p in ctx.mission.target_name.lower().replace(".", " ").split() if p]
    domain = ctx.mission.domain
    if len(parts) < 2 or not domain:
        return []
    first, last = parts[0], parts[-1]
    candidates = {f"{first}.{last}", f"{first}{last}", f"{first[0]}{last}",
                  f"{first}_{last}", f"{last}.{first}"}
    return [Finding(kind="email", value=f"{candidate}@{domain}",
                    source="pattern:nombre+dominio", source_domain=domain, confidence=35)
            for candidate in sorted(candidates)]
