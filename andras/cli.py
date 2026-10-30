"""CLI de ANDRAS. Toda la cadena de misión vive aquí; la landing es el único servidor."""
from __future__ import annotations

import json
import os
import smtplib
import ssl
from email.message import EmailMessage

import typer
from rich.console import Console
from rich.table import Table

from andras.core import ROOT, database, load_config, load_scenario, new_campaign, record
from andras.models import Mission

app = typer.Typer(add_completion=False, help="Emulador de adversario OSINT + ingeniería social.")
console = Console()

PREVIEW_COMMANDS = {"osint-discover", "phishing-spear", "extortion-bec",
                    "social-bot-fake", "ban-account"}


# ------------------------------------------------------------------ utilidades

def _config() -> dict:
    return load_config()


def _mission(config, mission_id: str | None) -> Mission:
    from andras.store import db, missions

    with db.session(config) as conn:
        mission = missions.get(conn, mission_id) if mission_id else missions.latest(conn)
    if not mission:
        raise typer.BadParameter("No hay misión. Crea una con `andras mission new`.")
    return mission


def _confirm(prompt: str, expected: str = "SEND") -> None:
    if os.environ.get("ANDRAS_YES"):
        return
    if typer.prompt(prompt, default="").strip().upper() != expected:
        raise typer.Exit("Cancelado")


def _table(title: str, columns: list[str], rows: list[list]) -> None:
    table = Table(title=title)
    for column in columns:
        table.add_column(column)
    for row in rows:
        table.add_row(*[str(cell) for cell in row])
    console.print(table)


# ------------------------------------------------------------------ v1: entrenamiento

@app.command()
def init() -> None:
    """Crea config.json y la base de datos si faltan."""
    config_path = ROOT / "config.json"
    if not config_path.exists():
        config_path.write_text((ROOT / "config.example.json").read_text())
    conn = database(load_config())
    conn.close()
    console.print("Listo. Edita config.json antes de usar SMTP.")


@app.command()
def scenarios() -> None:
    """Lista escenarios incluidos."""
    for path in sorted((ROOT / "scenarios").glob("*.json")):
        try:
            item = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            console.print(f"[red]! {path.name}: JSON inválido ({exc})[/red]")
            continue
        console.print(f"{item['id']} — {item['name']}")


@app.command()
def preview(scenario: str, to: str) -> None:
    """Renderiza un escenario sin enviar."""
    config = _config()
    item = load_scenario(scenario)
    if not _allowed(config, to):
        raise typer.Exit("Destinatario no autorizado en config.json")
    url = config["base_url"].rstrip("/") + "/<token>"
    console.print(f"Para: {to}\nDe: {config['from_name']} <{config['from_address']}>\n"
                  f"Asunto: {item['subject']}\n\n{item['body'].format(training_url=url)}")


@app.command()
def send(scenario: str, to: str) -> None:
    """Envía una campaña SMTP real tras confirmación."""
    config = _config()
    item = load_scenario(scenario)
    if not _allowed(config, to):
        raise typer.Exit("Destinatario no autorizado. Añádelo a config.json")
    user = os.environ.get(config["smtp_user_env"], "")
    password = os.environ.get(config["smtp_password_env"], "")
    if not user or not password:
        raise typer.Exit("Configura las variables SMTP del entorno")
    console.print(f"Destinatario: {to}\nSMTP: {config['smtp_host']}:{config['smtp_port']}")
    _confirm("Escribe SEND para transmitir")
    conn = database(config)
    campaign = new_campaign(conn, scenario, _hash(to))
    msg = EmailMessage()
    msg["From"] = f"{config['from_name']} <{config['from_address']}>"
    msg["To"] = to
    msg["Subject"] = item["subject"]
    msg.set_content(item["body"].format(training_url=config["base_url"].rstrip("/") + "/" + campaign))
    try:
        _smtp(config, user, password).send_message(msg)
        record(conn, campaign, "sent")
    except Exception:
        conn.execute("DELETE FROM campaigns WHERE id=?", (campaign,))
        conn.commit()
        raise
    finally:
        conn.close()
    console.print("Enviado.")


@app.command()
def report(fmt: str = typer.Option("text", "--format")) -> None:
    """Resume eventos de las campañas v1."""
    conn = database(_config())
    rows = conn.execute("SELECT scenario,event,COUNT(*) FROM campaigns JOIN events"
                        " ON campaigns.id=events.campaign_id GROUP BY scenario,event"
                        " ORDER BY scenario,event").fetchall()
    conn.close()
    if fmt == "json":
        console.print_json(json.dumps([{"scenario": a, "event": b, "count": c} for a, b, c in rows]))
        return
    if not rows:
        console.print("Todavía no hay eventos.")
    for scenario, event, count in rows:
        console.print(f"{scenario}: {event}: {count}")


@app.command()
def serve() -> None:
    """Sirve la landing y registra eventos."""
    from andras.server import serve as run

    run()


def _allowed(config, address: str) -> bool:
    return address.lower() in {a.lower() for a in config.get("authorized_recipients", [])}


def _hash(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.lower().encode()).hexdigest()


def _smtp(config, user: str, password: str):
    if config["smtp_security"] == "ssl":
        smtp = smtplib.SMTP_SSL(config["smtp_host"], int(config["smtp_port"]),
                                context=ssl.create_default_context(), timeout=20)
    else:
        smtp = smtplib.SMTP(config["smtp_host"], int(config["smtp_port"]), timeout=20)
        smtp.ehlo()
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
    smtp.login(user, password)
    return smtp


# ------------------------------------------------------------------ v3: misiones

mission_app = typer.Typer(help="Misiones: crear, listar, inspeccionar.")
app.add_typer(mission_app, name="mission")


@mission_app.command("new")
def mission_new(
    name: str = typer.Option(..., "--name", help="Nombre del objetivo"),
    goal: str = typer.Option(..., "--goal", help="Qué debe hacer la persona"),
    role: str = typer.Option("", "--role"),
    company: str = typer.Option("", "--company"),
    domain: str = typer.Option("", "--domain"),
    mode: str = typer.Option("passive", "--mode"),
    channels: str = typer.Option("email", "--channels", help="lista separada por comas"),
    notes: str = typer.Option("", "--notes"),
) -> None:
    """Crea una misión de emulación."""
    from andras.store import db, missions

    with db.session(_config()) as conn:
        created = missions.create(conn, target_name=name, goal=goal, target_role=role,
                                  target_company=company, domain=domain, mode=mode,
                                  channels=[c.strip() for c in channels.split(",") if c.strip()],
                                  notes=notes)
    console.print(f"Misión [bold]{created.id}[/bold] creada. Siguiente: andras recon --mission "
                  f"{created.id}")


@mission_app.command("list")
def mission_list() -> None:
    from andras.store import db, missions

    with db.session(_config()) as conn:
        items = missions.all_missions(conn)
        rows = [[m.id, m.target_name, m.status, m.mode, m.created_at] for m in items]
    _table("Misiones", ["id", "objetivo", "estado", "modo", "creada"], rows)


@mission_app.command("show")
def mission_show(mission_id: str) -> None:
    from andras.store import db, missions

    with db.session(_config()) as conn:
        mission = missions.get(conn, mission_id)
        if not mission:
            raise typer.Exit("Misión inexistente")
        counts = missions.counts(conn, mission_id)
    console.print_json(json.dumps({**mission.__dict__, "cuentas": counts}, ensure_ascii=False))


@mission_app.command("status")
def mission_status(mission_id: str, status: str) -> None:
    from andras.store import db, missions

    with db.session(_config()) as conn:
        missions.set_status(conn, mission_id, status)
    console.print(f"{mission_id} → {status}")


# ------------------------------------------------------------------ v3: fases

@app.command()
def recon(mission_id: str | None = typer.Option(None, "--mission"),
          budget: int = typer.Option(0, "--budget", help="segundos"),
          pages: int = typer.Option(8, "--pages", help="páginas a triar")) -> None:
    """Recon OSINT + triaje. Llena artifacts con fuente y confianza."""
    from andras.recon import run as runner
    from andras.store import db, evidence, missions

    config = _config()
    mission = _mission(config, mission_id)
    with db.session(config) as conn:
        status = runner.run(conn, config, mission, log=console.print, budget=budget or None)
        if pages:
            status["triage"] = runner.triage_pages(conn, config, mission, log=console.print,
                                                   limit=pages)
        runner.log_run(conn, mission.id, "recon", status)
        missions.set_status(conn, mission.id, "recon")
        verified = [(a.kind, a.value, a.verification, a.confidence)
                    for a in evidence.list_for(conn, mission.id)]
    _table(f"Artifacts ({len(verified)})", ["tipo", "valor", "verificación", "conf"],
           [[k, v[:60], ver, c] for k, v, ver, c in verified])
    if status["errors"]:
        console.print(f"[yellow]{len(status['errors'])} errores[/yellow]")


@app.command()
def dossier(mission_id: str | None = typer.Option(None, "--mission")) -> None:
    """Destila el dossier desde los artifacts."""
    from andras.evidence import dossier as dossier_mod
    from andras.store import db, missions

    config = _config()
    mission = _mission(config, mission_id)
    with db.session(config) as conn:
        data = dossier_mod.build(conn, config, mission, log=console.print)
        missions.set_status(conn, mission.id, "dossier")
    console.print(dossier_mod.to_text(data))


@app.command()
def hooks(mission_id: str | None = typer.Option(None, "--mission"),
          limit: int = typer.Option(5, "--limit")) -> None:
    """Genera y puntúa ganchos de ataque."""
    from andras.brain import planner
    from andras.store import db, missions
    from andras.store import hooks as hooks_store

    config = _config()
    mission = _mission(config, mission_id)
    with db.session(config) as conn:
        created = planner.generate_hooks(conn, config, mission, limit=limit)
        missions.set_status(conn, mission.id, "hook")
        rows = [[h.id, h.score, h.pain, h.verifiability, h.title] for h in
                hooks_store.list_for(conn, mission.id)]
    if not created:
        raise typer.Exit("El modelo no devolvió ganchos con soporte")
    _table("Ganchos", ["id", "score", "dolor", "verificab.", "título"], rows)
    console.print("Elige uno: andras hook-choose <id> --mission " + mission.id)


@app.command("hook-choose")
def hook_choose(hook_id: int, mission_id: str | None = typer.Option(None, "--mission")) -> None:
    from andras.store import db
    from andras.store import hooks as hooks_store

    mission = _mission(_config(), mission_id)
    with db.session(_config()) as conn:
        hooks_store.choose(conn, mission.id, hook_id)
    console.print(f"Gancho {hook_id} elegido")


@app.command()
def plan(mission_id: str | None = typer.Option(None, "--mission"),
         channel: str | None = typer.Option(None, "--channel"),
         count: int = typer.Option(2, "--count")) -> None:
    """Genera vectores de ataque completos."""
    from andras.brain import planner
    from andras.store import db, missions

    config = _config()
    mission = _mission(config, mission_id)
    with db.session(config) as conn:
        vectors = planner.build_attacks(conn, config, mission, channel=channel, count=count)
        missions.set_status(conn, mission.id, "plan")
    for vector in vectors:
        console.rule(f"{vector.vector} — {vector.angle}")
        console.print(f"[dim]{vector.leverage}[/dim]")
        for index, step in enumerate(vector.steps, start=1):
            console.print(f"{index}. [bold]{step.actor}[/bold] {step.action}\n{step.script}\n")


@app.command("packs")
def packs_command(validate: bool = typer.Option(False, "--validate")) -> None:
    """Lista (o valida) los packs de técnicas."""
    from andras.brain import packs

    items, errors = packs.load_all()
    for pack in items:
        console.print(f"{pack.strength} {pack.channel:9} {pack.id} — {pack.name}")
    if validate:
        if errors:
            for error in errors:
                console.print(f"[red]{error}[/red]")
            raise typer.Exit(1)
        console.print(f"{len(items)} packs válidos")


@app.command()
def critic(mission_id: str | None = typer.Option(None, "--mission")) -> None:
    """Audita dossier y plan con un crítico adversarial."""
    from andras.evidence import critic as critic_mod

    config = _config()
    mission = _mission(config, mission_id)
    from andras.store import db

    with db.session(config) as conn:
        result = critic_mod.audit(conn, config, mission)
    console.print_json(json.dumps(result, ensure_ascii=False))
    if result["verdict"] == "roto":
        raise typer.Exit(2)


@app.command("attacks")
def attacks_command(mission_id: str | None = typer.Option(None, "--mission")) -> None:
    """Lista los vectores generados."""
    from andras.store import db

    mission = _mission(_config(), mission_id)
    with db.readonly(_config()) as conn:
        rows = [[r["id"], r["vector"], r["channel"], r["angle"], r["status"]]
                for r in conn.execute("SELECT * FROM attacks WHERE mission_id=? ORDER BY id",
                                      (mission.id,))]
    _table("Vectores", ["id", "vector", "canal", "ángulo", "estado"], rows)


@app.command()
def build(attack_id: str) -> None:
    """Renderiza el artefacto del vector y pasa el QA."""
    from andras.artifacts import render
    from andras.brain import planner
    from andras.store import db

    config = _config()
    with db.readonly(config) as conn:
        attack = planner.load(conn, attack_id)
    if not attack:
        raise typer.Exit("Vector inexistente")
    rendered = render.build(attack["channel"], attack)
    out_dir = ROOT / "data" / "artifacts" / attack["mission_id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{attack_id}.txt").write_text(rendered.text)
    if rendered.html:
        (out_dir / f"{attack_id}.html").write_text(rendered.html)
    if attack["channel"] == "phone":
        (out_dir / f"{attack_id}.md").write_text(render.call_sheet(attack))
    console.print(f"Asunto: [bold]{rendered.subject}[/bold]\n\n{rendered.text}")
    if rendered.problems:
        for problem in rendered.problems:
            console.print(f"[yellow]QA: {problem}[/yellow]")
        raise typer.Exit(2)
    console.print(f"[green]QA limpio[/green] → {out_dir}")


@app.command()
def deliver(attack_id: str, to: str = typer.Option(..., "--to"),
            force: bool = typer.Option(False, "--force")) -> None:
    """Enruta el artefacto por su canal y registra la entrega."""
    from andras.brain import planner
    from andras.delivery import pipeline
    from andras.store import db

    config = _config()
    with db.session(config) as conn:
        attack = planner.load(conn, attack_id)
        if not attack:
            raise typer.Exit("Vector inexistente")
        channel = attack["channel"]
        if channel in {"email", "sms", "telegram", "whatsapp"}:
            _confirm(f"Enviar por {channel} a {to}. Escribe SEND")
        outcome = pipeline.deliver(conn, config, attack_id, to, force=force)
    if outcome.problems:
        for problem in outcome.problems:
            console.print(f"[yellow]QA: {problem}[/yellow]")
    if not outcome.ok:
        console.print(f"[red]Fallo: {outcome.error}[/red]")
        console.print("[dim]Copia el mensaje a mano:[/dim]\n" + outcome.text)
        raise typer.Exit(1)
    console.print(f"Entregado. Enlace: {outcome.url}")
    if channel in {"phone", "social"}:
        from andras.artifacts import render

        console.print(render.call_sheet(attack))


# ------------------------------------------------------------------ v3: campaña

campaign_app = typer.Typer(help="Campañas omnicanal: planificar y ejecutar la secuencia.")
app.add_typer(campaign_app, name="campaign")


@campaign_app.command("plan")
def campaign_plan(mission_id: str | None = typer.Option(None, "--mission"),
                  channels: str = typer.Option("", "--channels"),
                  length: int = typer.Option(4, "--length")) -> None:
    """Compone la secuencia omnicanal y genera el guion de cada paso."""
    from andras.brain import campaign
    from andras.store import db, plans

    config = _config()
    mission = _mission(config, mission_id)
    wanted = [c.strip() for c in channels.split(",") if c.strip()] or None
    with db.session(config) as conn:
        plan_id = campaign.compose(conn, config, mission, channels=wanted, length=length,
                                   log=console.print)
        plan = plans.get(conn, plan_id)
    console.print(f"Plan [bold]{plan_id}[/bold] — {plan['title']}")
    console.print(plan["narrative"])
    _show_steps(config, plan_id)


def _show_steps(config, plan_id: str) -> None:
    from andras.store import db, plans

    with db.readonly(config) as conn:
        rows = [[s["position"], s["channel"], s["pack_id"], s["delay_hours"], s["trigger"],
                 s["status"], s["attack_id"] or ""]
                for s in plans.steps(conn, plan_id)]
    _table("Pasos", ["#", "canal", "pack", "espera h", "disparador", "estado", "ataque"], rows)


@campaign_app.command("show")
def campaign_show(plan_id: str) -> None:
    """Muestra un plan y el guion de cada paso."""
    from andras.brain import planner
    from andras.store import db, plans

    config = _config()
    with db.readonly(config) as conn:
        plan = plans.get(conn, plan_id)
        if not plan:
            raise typer.Exit("Plan inexistente")
        rows = list(plans.steps(conn, plan_id))
        attacks = {s["attack_id"]: planner.load(conn, s["attack_id"]) for s in rows
                   if s["attack_id"]}
    console.print(f"[bold]{plan['title']}[/bold]\n{plan['narrative']}\n")
    for step in rows:
        console.rule(f"{step['position']}. {step['channel']} — {step['pack_id']}")
        console.print(f"[dim]+{step['delay_hours']}h · {step['trigger']} · {step['why']}[/dim]")
        attack = attacks.get(step["attack_id"])
        if not attack:
            console.print("[yellow]sin guion generado[/yellow]")
            continue
        for substep in attack.get("steps", []):
            console.print(f"[bold]{substep.get('actor')}[/bold] {substep.get('action')}")
            console.print(substep.get("script", "") + "\n")


@campaign_app.command("run")
def campaign_run(plan_id: str, to: str = typer.Option(..., "--to"),
                 resume: bool = typer.Option(False, "--resume"),
                 skip_wait: bool = typer.Option(False, "--skip-wait")) -> None:
    """Ejecuta la secuencia respetando disparadores y esperas."""
    from andras.brain import campaign
    from andras.delivery import pipeline
    from andras.store import db, plans

    config = _config()
    with db.session(config) as conn:
        ready = campaign.run(conn, config, plan_id, target=to, resume=resume,
                             skip_wait=skip_wait, log=console.print)
        plans.set_status(conn, plan_id, "running")
        for item in ready:
            if item["status"] != "listo":
                console.print(f"  · paso {item['position']}: {item['status']}"
                              + (f" ({item.get('trigger')})" if item.get("trigger") else ""))
                continue
            step = next(s for s in plans.steps(conn, plan_id)
                        if s["position"] == item["position"])
            if item["channel"] in {"email", "sms", "telegram", "whatsapp"}:
                _confirm(f"Paso {step['position']} por {item['channel']}. Escribe SEND")
            outcome = pipeline.deliver(conn, config, item["attack_id"], to)
            plans.mark(conn, step["id"], "done" if outcome.ok else "failed")
            console.print(f"  → paso {step['position']} {item['channel']}: "
                          + ("enviado" if outcome.ok else f"fallo ({outcome.error})"))
            if outcome.problems:
                for problem in outcome.problems:
                    console.print(f"    [yellow]QA: {problem}[/yellow]")
            if not outcome.ok:
                console.print(f"    [dim]enlace: {outcome.url}[/dim]")
                console.print("    [dim]texto para enviar a mano:[/dim]\n    "
                              + outcome.text.replace("\n", "\n    "))
        plans.set_status(conn, plan_id, "done")


@app.command()
def debrief(mission_id: str | None = typer.Option(None, "--mission")) -> None:
    """Genera el informe de la misión y lo guarda en data/reports."""
    from andras.brain import debrief as debrief_mod
    from andras.store import db

    config = _config()
    mission = _mission(config, mission_id)
    with db.session(config) as conn:
        path = debrief_mod.build(conn, config, mission, log=console.print)
    console.print(f"Informe: {path}")


@app.command()
def tui() -> None:
    """Abre la TUI."""
    from andras.tui import run

    run()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
