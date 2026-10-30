"""Ejecución del recon con presupuesto, y triaje de las páginas encontradas."""
from __future__ import annotations

import time

from andras.brain import prompts, provider
from andras.models import Finding, Mission
from andras.recon import collectors, http
from andras.store import db, evidence


def run(conn, config, mission: Mission, log=print, budget: int | None = None) -> dict:
    budget = int(budget or config.get("recon_budget_seconds", 420))
    deadline = time.monotonic() + budget
    status = {"added": 0, "errors": [], "skipped": []}
    ctx = collectors.Ctx(mission=mission, config=config, log=log)
    todo = collectors.applicable(mission)
    if not todo:
        raise SystemExit("La misión no tiene datos suficientes para ningún colector "
                         "(hacen falta nombre, empresa o dominio).")

    for collector in todo:
        if time.monotonic() > deadline:
            status["skipped"].append(collector.name)
            continue
        log(f"  · {collector.name}")
        try:
            findings = collector.run(ctx) or []
        except Exception as exc:  # un colector no debe tumbar la fase
            status["errors"].append(f"{collector.name}: {exc}")
            continue
        for finding in findings:
            try:
                _, created = evidence.add(conn, mission.id, finding)
            except ValueError as exc:
                status["errors"].append(f"{collector.name}: {exc}")
                continue
            status["added"] += int(created)
        conn.commit()
    return status


def triage_pages(conn, config, mission: Mission, log=print, limit: int | None = None) -> dict:
    """Lee las URLs encontradas y extrae artifacts con el LLM."""
    limit = int(limit or config.get("recon_max_pages", 8))
    status = {"read": 0, "added": 0, "errors": []}
    if not provider.available(config, "triage"):
        status["errors"].append("sin proveedor LLM; triaje omitido")
        return status

    candidates = [a for a in evidence.list_for(conn, mission.id, {"doc", "repo"})
                  if a.source.startswith(("dork:", "http"))]
    seen = set()
    for art in candidates:
        if status["read"] >= limit:
            break
        url = art.value
        if url in seen:
            continue
        seen.add(url)
        try:
            text, snapshot = http.page_text(url, mission.id)
        except http.FetchError as exc:
            status["errors"].append(f"{url[:60]}: {exc}")
            continue
        status["read"] += 1
        message = [{"role": "system", "content": prompts.TRIAGE},
                   {"role": "user", "content": f"URL: {url}\n\n{text}"}]
        try:
            data = provider.complete_json(config, message, phase="triage", temperature=0.1)
        except provider.LLMError as exc:
            status["errors"].append(f"triage {url[:50]}: {exc}")
            continue
        for item in data.get("artifacts", [])[:12]:
            kind = item.get("kind")
            value = (item.get("value") or "").strip()
            if not kind or not value:
                continue
            try:
                _, created = evidence.add(conn, mission.id, Finding(
                    kind=kind, value=value, source=f"llm:{url}", source_domain="llm",
                    confidence=int(item.get("confidence", 30)), snapshot=snapshot))
            except ValueError:
                continue
            status["added"] += int(created)
        conn.commit()
    return status


def log_run(conn, mission_id: str, phase: str, status: dict) -> None:
    conn.execute("INSERT INTO runs(mission_id,phase,status,log,started_at,ended_at)"
                 " VALUES(?,?,?,?,?,?)",
                 (mission_id, phase, "done" if not status.get("errors") else "partial",
                  db.json.dumps(status), db.now(), db.now()))
