"""Fase OSINT: collectors reales + triaje del LLM. Todo pasa a `artifacts`."""
import hashlib
import json
import time

from . import db, llm, tools

IOC_KINDS = {"email", "phone", "username", "domain", "social", "leak", "person",
             "company", "infra", "doc", "repo", "breach", "credential"}

DORK_PROMPT = """Eres un analista OSINT. Genera consultas de buscador (estilo dork) para
reunir información pública sobre el objetivo. Devuelve JSON:
{"dorks": ["..."], "hipotesis": ["..."]}
Reglas: máximo 8 dorks, en español e inglés, combinando nombre + empresa/dominio cuando existan.
Incluye dorks para: documentos (filetype:pdf, filetype:xlsx), perfiles, filtraciones,
subdominios/paneles, y correos. `hipotesis` son 3 vectores de ataque plausibles.
"""

TRIAGE_PROMPT = """Extrae datos del texto de una página web pública sobre un objetivo.
Devuelve JSON: {"artifacts": [{"kind": "...", "key": "...", "value": "...", "confidence": 0-100}]}
`kind` en: email, phone, username, domain, social, person, company, infra, doc, breach.
Solo datos que aparezcan literalmente en el texto. `key` es corto (ej. "email", "cargo", "socio").
Máximo 12 artifacts. Si no hay nada relevante devuelve lista vacía.
"""


def slug(value):
    return hashlib.sha1(value.encode()).hexdigest()[:12]


class Findings:
    def __init__(self, conn, mission_id):
        self.conn = conn
        self.mission_id = mission_id
        self.items = []

    def add(self, kind, key, value, source, confidence=60):
        value = (value or "").strip()[:300]
        if not value:
            return
        before = self.conn.total_changes
        db.add_artifact(self.conn, self.mission_id, kind, key, value, source, confidence)
        if self.conn.total_changes > before:
            self.items.append({"kind": kind, "key": key, "value": value,
                               "source": source, "confidence": confidence})

    def from_pairs(self, kind, pairs, source, confidence=70):
        for value in pairs:
            self.add(kind, kind, value, source, confidence)


def seed(conn, mission_id, record):
    findings = Findings(conn, mission_id)
    if record["target_name"]:
        findings.add("person", "nombre", record["target_name"], "input", 100)
    for field, kind in (("target_role", "person"), ("target_company", "company"),
                        ("domain", "domain"), ("goal", "objetivo")):
        if record[field]:
            findings.add(kind, field, record[field], "input", 100)
    return findings


def username_candidates(record):
    name = record["target_name"] or ""
    parts = [p for p in name.lower().replace(".", " ").split() if p]
    out = set()
    if len(parts) >= 2:
        first, last = parts[0], parts[-1]
        out.update({f"{first}.{last}", f"{first}{last}", f"{first}_{last}",
                    f"{first[0]}{last}", f"{last}{first[0]}"})
    if len(parts) == 1:
        out.add(parts[0])
    if record["domain"]:
        out.add(record["domain"].split(".")[0])
    return sorted(u for u in out if len(u) > 3)[:6]


def gather(conn, config, record, log=print):
    """Ejecuta los collectors dentro de un presupuesto de tiempo."""
    mid = record["id"]
    findings = seed(conn, mid, record)
    status = {"skipped": [], "errors": []}
    budget = int(config.get("osint_budget_seconds", 600))
    deadline = time.monotonic() + budget

    def left():
        return deadline - time.monotonic()

    def step(label, fn, *args, **kwargs):
        if left() < 20:
            status["skipped"].append(f"{label}: sin tiempo")
            return None
        log(f"  · {label}")
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            status["errors"].append(f"{label}: {exc}")
            return None

    emails = [a["value"] for a in findings.items if a["kind"] == "email"][:3]
    domains = [a["value"] for a in findings.items if a["kind"] == "domain"][:3]

    if tools.have_toolkit(config):
        t = int(config.get("osint_tool_timeout", 120))
        for email in emails:
            out = step(f"mailaccess {email}", tools.run_tool, config, "mailaccess",
                       ["investigate", email], timeout=t)
            if out and out[0]:
                for value in list(_emails(out[1]))[:6]:
                    findings.add("email", "email", value, "mailaccess", 60)
        for domain in domains:
            out = step(f"mailaccess harvest {domain}", tools.run_tool, config, "mailaccess",
                       ["harvest-emails", "--domain", domain], timeout=t)
            if out and out[0]:
                for value in list(_emails(out[1]))[:10]:
                    findings.add("email", "email", value, "mailaccess", 65)

        for user in username_candidates(record)[:2]:
            out = step(f"aliens_eye {user}", tools.run_tool, config, "aliens_eye",
                       [user, "--only-found", "--json-stdout"], timeout=t)
            if out and out[0]:
                for name, url in _json_socials(out[1]):
                    findings.add("social", name, url, "aliens_eye", 55)

        for query in [q for q in (record["target_company"], record["domain"]) if q][:2]:
            out = step(f"gitgraber {query}", tools.run_tool, config, "gitgraber",
                       ["-q", query], timeout=t)
            if out and out[0]:
                for url in _urls(out[1])[:8]:
                    findings.add("repo", "repo", url, "gitgraber", 50)
    else:
        status["skipped"].append("toolkit OSINT no configurado")

    for dork in _dorks(config, record, log):
        hits = step(f"buscador: {dork[:60]}", tools.duckduckgo, dork, limit=6) or []
        for hit in hits:
            findings.add("doc", "resultado", hit["url"], "ddg", 40)

    pages = 0
    max_pages = int(config.get("max_pages_per_mission", 14))
    for hit in list(findings.items):
        if pages >= max_pages or left() < 30:
            break
        if hit["kind"] not in {"doc", "social", "repo"} or hit["source"] not in {"ddg", "maigret"}:
            continue
        pages += 1
        fetched = step(f"leer {hit['value'][:70]}", tools.fetch_page, hit["value"])
        if fetched and fetched[0]:
            _triage(config, findings, fetched[1], hit["value"], log)

    for domain in domains:
        out = step(f"whois {domain}", tools.whois_summary, domain)
        if out and out[0]:
            findings.add("infra", "whois", out[1], "whois", 45)
        recs = step(f"dns {domain}", tools.dns_records, domain)
        if recs:
            findings.add("infra", "dns", json.dumps(recs), "dig", 50)

    owned = step("crt.sh", tools.owned_domains,
                 record["target_company"] or record["target_name"] or "") or []
    for dom, _date in owned:
        findings.add("domain", "dominio-relacionado", dom, "crt.sh", 40)

    return findings, status


def _dorks(config, record, log):
    if not llm.available(config):
        base = record["target_company"] or record["domain"] or record["target_name"]
        return [f'"{base}" filetype:pdf', f'"{base}" email']
    prompt = (f"Objetivo: {record['target_name']} | cargo: {record['target_role']} | "
              f"empresa: {record['target_company']} | dominio: {record['domain']} | "
              f"meta: {record['goal']}")
    try:
        data = llm.chat_json(config, [{"role": "system", "content": DORK_PROMPT},
                                      {"role": "user", "content": prompt}])
    except llm.LLMError as exc:
        log(f"  ! dorks por LLM fallaron ({exc}); uso genéricos")
        return [f'"{record["target_company"] or record["target_name"]}" filetype:pdf']
    return [d for d in data.get("dorks", [])][:8]


def _triage(config, findings, text, source, log):
    if not llm.available(config):
        return
    try:
        data = llm.chat_json(config, [{"role": "system", "content": TRIAGE_PROMPT},
                                      {"role": "user", "content": text[:6000]}])
    except llm.LLMError:
        return
    for item in data.get("artifacts", [])[:12]:
        if item.get("kind") in IOC_KINDS:
            findings.add(item["kind"], item.get("key", item["kind"]), item.get("value", ""),
                         f"triage:{source[:60]}", int(item.get("confidence", 55)))


def _emails(text):
    import re
    return set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)) - {
        "example@example.com", "test@test.com"}


def _urls(text):
    import re
    return [u.rstrip(".,)\"'") for u in re.findall(r"https?://[^\s\"'<>]+", text)]


def _json_socials(out):
    start = out.find("{")
    if start == -1:
        return []
    try:
        data = json.loads(out[start:])
    except json.JSONDecodeError:
        return []
    pairs = []
    results = data.get("results") or data.get("sites") or []
    if isinstance(results, dict):
        results = [{"site": k, **v} if isinstance(v, dict) else {"site": k}
                   for k, v in results.items()]
    for row in results:
        if str(row.get("status", "")).lower().startswith("found") or row.get("found"):
            site = row.get("site") or row.get("name") or "perfil"
            url = row.get("url") or row.get("profile_url") or ""
            if url:
                pairs.append((site, url))
    return pairs
