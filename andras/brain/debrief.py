"""Debrief de misión: línea temporal y lecciones, en markdown."""

from __future__ import annotations

import json

from andras.brain import prompts, provider
from andras.core import ROOT
from andras.store import hooks, missions, plans


def timeline(conn, mission_id: str) -> list[str]:
    lines = []
    for row in conn.execute(
            "SELECT timestamp, what FROM ("
            " SELECT created_at AS timestamp, 'ataque ' || channel || ': ' || angle AS what"
            " FROM attacks WHERE mission_id=?"
            " UNION ALL SELECT d.sent_at, 'entrega ' || d.channel || ' → ' || d.status || ' ' ||"
            " COALESCE(d.error,'') FROM deliveries d JOIN attacks a ON a.id=d.attack_id"
            " WHERE a.mission_id=?"
            " UNION ALL SELECT e.occurred_at, 'evento ' || e.event FROM events e"
            " JOIN campaigns c ON c.id=e.campaign_id WHERE c.mission_id=?"
            ") ORDER BY timestamp", (mission_id, mission_id, mission_id)):
        if row["timestamp"]:
            lines.append(f"{row['timestamp']}  {row['what']}")
    return lines


def build(conn, config, mission, log=print) -> str:
    counts = missions.counts(conn, mission.id)
    chosen = hooks.chosen(conn, mission.id)
    lines = timeline(conn, mission.id)
    captures = conn.execute(
        "SELECT username, secret FROM credentials c JOIN campaigns k ON k.id=c.campaign_id"
        " WHERE k.mission_id=?", (mission.id,)).fetchall()

    facts = [f"Misión {mission.id}: {mission.target_name} — {mission.goal}",
             (f"Artifacts: {counts['artifacts']} · ganchos: {counts['hooks']} · "
              f"entregas: {counts['deliveries']}"),
             "Gancho elegido: " + (chosen[0].title if chosen else "ninguno"),
             f"Credenciales capturadas: {len(captures)}"]
    if captures:
        facts.append("Capturas: " + ", ".join(f"{c['username']}/{'*' * 6}" for c in captures))
    facts.append("Cronología:\n" + "\n".join(lines[:120]))

    body = "\n".join(facts)
    plan_rows = plans.for_mission(conn, mission.id)
    if plan_rows:
        body += "\n\nPlanes: " + json.dumps(
            [{"title": p["title"], "status": p["status"]} for p in plan_rows], ensure_ascii=False)

    if provider.available(config, "report"):
        try:
            report = provider.complete(config, [
                {"role": "system", "content": prompts.REPORT},
                {"role": "user", "content": body}], phase="report", max_tokens=2000)
        except provider.LLMError as exc:
            log(f"  ! informe por LLM falló ({exc}); guardo solo la cronología")
            report = ""
    else:
        report = ""
    if "##" not in report or len(report) < 200:
        report = "## Cronología\n\n" + "\n".join(lines)

    header = (f"# Debrief — {mission.target_name}\n\nMeta: {mission.goal}\n\n"
              f"## Datos\n\n" + "\n".join(f"- {c}" for c in facts[:4]) + "\n\n")
    text = header + report
    out = ROOT / "data" / "reports" / f"{mission.id}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    return str(out)
