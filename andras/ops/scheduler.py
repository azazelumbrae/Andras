"""Planificador: dispara pasos vencidos, vigila el éxito y avisa.

Un tick no envía nada por sí mismo: decide qué está vencido, comprueba el disparador contra los
eventos reales y entrega con `executor`. Todo idempotente: un job sólo se ejecuta con alquiler.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from andras import notify
from andras.delivery import executor
from andras.store import jobs, notes, plans

TRIGGER_RECHECK = timedelta(hours=2)
TRIGGER_GIVE_UP = timedelta(hours=96)
WATCHDOG = timedelta(hours=48)


@dataclass(slots=True)
class TickReport:
    executed: list[dict] = field(default_factory=list)
    waiting: list[int] = field(default_factory=list)
    skipped: list[int] = field(default_factory=list)
    failed: list[int] = field(default_factory=list)
    achieved: bool = False
    alerts: list[str] = field(default_factory=list)

    @property
    def touched(self) -> bool:
        return bool(self.executed or self.skipped or self.failed or self.achieved)


def events_for(conn, plan_id: str) -> set[str]:
    rows = conn.execute(
        "SELECT DISTINCT e.event FROM plan_steps s JOIN attacks a ON a.id=s.attack_id"
        " JOIN deliveries d ON d.attack_id=a.id JOIN events e ON e.campaign_id=d.campaign_id"
        " WHERE s.plan_id=?", (plan_id,))
    return {row["event"] for row in rows}


def criteria(conn, plan_id: str) -> list:
    return list(conn.execute("SELECT * FROM success_criteria WHERE plan_id=?", (plan_id,)))


def evaluate_success(conn, plan_id: str, events: set[str]) -> tuple[bool, str]:
    for row in criteria(conn, plan_id):
        if row["met_at"]:
            return True, row["kind"]
        if row["kind"] == "credential_captured":
            found = conn.execute(
                "SELECT COUNT(*) FROM credentials c JOIN campaigns ca ON ca.id=c.campaign_id"
                " JOIN deliveries d ON d.campaign_id=ca.id JOIN attacks a ON a.id=d.attack_id"
                " JOIN plan_steps s ON s.attack_id=a.id WHERE s.plan_id=?", (plan_id,)).fetchone()
            if found and found[0]:
                conn.execute("UPDATE success_criteria SET met_at=? WHERE id=?",
                             (_iso(), row["id"]))
                return True, "credencial capturada"
        elif row["kind"] == "event":
            wanted = json.loads(row["spec"] or "{}").get("name", "")
            if wanted and wanted in events:
                conn.execute("UPDATE success_criteria SET met_at=? WHERE id=?",
                             (_iso(), row["id"]))
                return True, f"evento {wanted}"
    return False, ""


def tick(conn, config, plan_id: str, *, now: datetime | None = None, log=print) -> TickReport:
    report = TickReport()
    moment = now or datetime.now(UTC)
    plan = plans.get(conn, plan_id)
    if not plan:
        raise SystemExit("Plan inexistente")
    if plan["status"] not in {"confirmed", "running"}:
        return report
    plans.set_status(conn, plan_id, "running")
    jobs.materialize(conn, plan_id, from_now=moment)
    events = events_for(conn, plan_id)

    achieved, why = evaluate_success(conn, plan_id, events)
    if achieved:
        plans.set_status(conn, plan_id, "achieved")
        jobs.pause_all(conn, plan_id)
        notes.add(conn, plan["mission_id"], f"objetivo conseguido: {why}", kind="decision",
                  plan_id=plan_id)
        notify.send(conn, config, level="hit", plan_id=plan_id,
                    body=f"Objetivo cumplido en «{plan['title']}»: {why}.", log=log)
        report.achieved = True
        return report

    for job in jobs.due(conn, plan_id, at=moment):
        step = conn.execute("SELECT * FROM plan_steps WHERE id=?", (job["step_id"],)).fetchone()
        if step["status"] != "pending":
            jobs.finish(conn, job["id"], "done")
            continue
        argued = plans.fired(step["trigger"], events)
        due = datetime.fromisoformat(job["due_at"])
        if not argued:
            if moment - due > TRIGGER_GIVE_UP:
                plans.mark(conn, step["id"], "skipped")
                jobs.finish(conn, job["id"], "done")
                report.skipped.append(step["position"])
                notes.add(conn, plan["mission_id"],
                          f"paso {step['position']} saltado: disparador `{step['trigger']}` "
                          "no se cumplió nunca", kind="obs", plan_id=plan_id)
                continue
            conn.execute("UPDATE jobs SET due_at=? WHERE id=?",
                         (_iso(moment + TRIGGER_RECHECK), job["id"]))
            report.waiting.append(step["position"])
            continue

        jobs.lease(conn, job["id"])
        plans.mark(conn, step["id"], "sending")
        try:
            outcome = executor.run_step(conn, config, step)
        except Exception as exc:  # un adaptador roto no debe parar el plan
            jobs.retry(conn, job["id"], str(exc))
            plans.mark(conn, step["id"], "failed")
            report.failed.append(step["position"])
            log(f"  ! paso {step['position']} reventó: {exc}")
            continue
        if outcome.ok:
            plans.mark(conn, step["id"], "done")
            jobs.finish(conn, job["id"], "done")
            report.executed.append({"position": step["position"], "channel": step["channel"]})
            log(f"  → paso {step['position']} {step['channel']}: enviado")
            notify.send(conn, config, level="info", plan_id=plan_id,
                        body=f"Paso {step['position']} ({step['channel']}) enviado en "
                             f"«{plan['title']}».", log=log)
        else:
            if jobs.retry(conn, job["id"], outcome.error):
                plans.mark(conn, step["id"], "pending")
            else:
                plans.mark(conn, step["id"], "failed")
                notify.send(conn, config, level="critical", plan_id=plan_id,
                            body=f"Paso {step['position']} ({step['channel']}) agotó reintentos: "
                                 f"{outcome.error}", log=log)
            report.failed.append(step["position"])
            log(f"  ! paso {step['position']} falló: {outcome.error}")

    if _stalled(conn, plan_id, moment):
        report.alerts.append("paso sin movimiento desde hace más de 48 h")
        notify.send(conn, config, level="info", plan_id=plan_id,
                    body="El plan lleva 48 h sin movimiento; revisa el paso en curso.", log=log)
    return report


def _stalled(conn, plan_id: str, moment: datetime) -> bool:
    row = conn.execute("SELECT MIN(due_at) AS earliest FROM jobs WHERE plan_id=? AND state IN"
                       " ('queued','ready')", (plan_id,)).fetchone()
    if not row or not row["earliest"]:
        return False
    try:
        return moment - datetime.fromisoformat(row["earliest"]) > WATCHDOG
    except ValueError:
        return False


def run_once(conn, config, plan_ids: list[str], *, now=None, log=print) -> list[TickReport]:
    return [tick(conn, config, plan_id, now=now, log=log) for plan_id in plan_ids]


def active_plans(conn) -> list[str]:
    return [row["id"] for row in conn.execute(
        "SELECT id FROM plans WHERE status IN ('confirmed','running') ORDER BY created_at")]


def _iso(moment: datetime | None = None) -> str:
    return (moment or datetime.now(UTC)).isoformat(timespec="seconds")
