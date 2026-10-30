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

app = typer.Typer(add_completion=False, help="Emulador de adversario OSINT + ingeniería social.",
                  invoke_without_command=True)
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


@app.callback()
def _root(ctx: typer.Context) -> None:
    """Sin subcomando, abre el wizard."""
    if ctx.invoked_subcommand is None:
        from andras.tui import run

        run()
        raise typer.Exit


@app.command()
def preflight() -> None:
    """Comprueba el entorno: modelos, correo, tor, wallets y avisos."""
    from andras import preflight as checks

    report = checks.run()
    console.print(checks.render(report))
    if checks.blocking(report):
        raise typer.Exit(1)


@app.command("tools")
def list_tools() -> None:
    """Lista las herramientas que el agente puede usar."""
    from andras.agent import tools as registry

    console.print(registry.describe())


# ------------------------------------------------------------------ v1: entrenamiento

@app.command()
def init(searxng: bool = typer.Option(False, "--searxng",
                                      help="prepara un SearXNG local en docker")) -> None:
    """Crea config.json y la base de datos si faltan."""
    import secrets as secrets_mod

    config_path = ROOT / "config.json"
    if not config_path.exists():
        config_path.write_text((ROOT / "config.example.json").read_text())
        data = json.loads(config_path.read_text())
        data["hook_secret"] = secrets_mod.token_hex(32)
        config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    env_path = ROOT / ".env"
    if not env_path.exists() and (ROOT / ".env.example").exists():
        env_path.write_text((ROOT / ".env.example").read_text())
        console.print("Creado `.env` desde `.env.example`: rellena los secretos.")
    if searxng:
        import secrets

        target = ROOT / "data" / "searxng" / "settings.yml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "use_default_settings: true\nserver:\n"
            f"  secret_key: \"{secrets.token_hex(32)}\"\n  limiter: false\n"
            "search:\n  safe_search: 0\n  formats:\n    - html\n    - json\n")
        console.print("SearXNG preparado. Arráncalo con `scripts/dev_searxng.sh`.")
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


def _ask_operator(question: str, options: tuple = ()) -> str:
    """Pregunta al humano si hay terminal; sin ella elige la primera opción.

    Devolver vacío dejaba al agente sin respuesta y colgaba el plan, así que en
    headless se toma la opción conservadora que propuso él mismo y se anota.
    """
    import sys

    if not sys.stdin.isatty():
        answer = options[0] if options else ""
        console.print(f"[dim]pregunta sin terminal:[/dim] {question} {options}"
                      + (f" [dim]→ {answer}[/dim]" if answer else ""))
        return answer
    try:
        return typer.prompt(f"{question} {options}")
    except (typer.Abort, EOFError):
        return ""


@app.command()
def agent(mission_id: str | None = typer.Option(None, "--mission"),
          auto: bool = typer.Option(False, "--auto", help="no preguntar, usar el encargo"),
          steps: int = typer.Option(0, "--steps", help="tope de pasos de esta tanda")) -> None:
    """Deja al agente investigar y proponer el plan, sin enviar nada."""
    import secrets

    from andras.agent import clarify as clarify_mod
    from andras.agent import gates, runner
    from andras.agent.tools import ToolContext
    from andras.store import budgets, db

    config = _config()
    mission = _mission(config, mission_id)
    with db.session(config) as conn:
        caps = {k: v for k, v in (config.get("agent") or {}).items()
                if k in {"max_steps", "max_tokens", "max_usd"}}
        if steps:
            caps["max_steps"] = steps
        budgets.set_budget(conn, mission.id, **caps)
        answers = {}
        if not auto:
            for row in clarify_mod.generate(config, mission):
                options = " / ".join(row["options"])
                answers[row["question"]] = typer.prompt(f"{row['question']} [{options}]")
        plan_id = runner.draft_plan(conn, mission, mission.target_name)
        ctx = ToolContext(conn=conn, config=config, mission=mission,
                          run_id=secrets.token_hex(6), plan_id=plan_id, log=console.print,
                          ask=_ask_operator)
        policy = gates.Policy(mode="autonomo" if auto else "asistido",
                              approver=lambda q, p: typer.confirm(q, default=True))
        console.print("[dim]recon determinista inicial…[/dim]")
        runner.seed(conn, config, mission, log=console.print)
        result = runner.recon(ctx, policy, answers)
    console.print(f"[bold]Fin:[/bold] {result.reason} · {result.steps} pasos · "
                  f"{result.tokens} tokens · {result.usd:.4f} USD")
    if result.message:
        console.print(result.message)
    with db.readonly(config) as conn:
        console.print(runner.review_summary(conn, plan_id))
    console.print(f"\nPlan [bold]{plan_id}[/bold]. Confírmalo con `andras plan confirm` "
                  "o desde el wizard.")


plan_app = typer.Typer(help="Planes del agente: confirmar, listar.")
app.add_typer(plan_app, name="plan")


@plan_app.command("confirm")
def plan_confirm(plan_id: str) -> None:
    """Marca un plan como confirmado (consentimiento permanente para sus pasos)."""
    from andras.store import db, plans

    config = _config()
    with db.session(config) as conn:
        plan = plans.get(conn, plan_id)
        if not plan:
            raise typer.Exit("Plan inexistente")
        if len(plans.steps(conn, plan_id)) < 3:
            raise typer.Exit("El plan necesita al menos 3 pasos")
        plans.set_status(conn, plan_id, "confirmed")
    console.print(f"Plan [bold]{plan_id}[/bold] confirmado.")


@plan_app.command("list")
def plan_list(mission_id: str | None = typer.Option(None, "--mission")) -> None:
    """Lista los planes de una misión."""
    from andras.store import db, plans

    config = _config()
    mission = _mission(config, mission_id)
    with db.readonly(config) as conn:
        rows = [[p["id"], p["status"], p["title"], len(plans.steps(conn, p["id"]))]
                for p in plans.for_mission(conn, mission.id)]
    _table("Planes", ["id", "estado", "título", "pasos"], rows)


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


ops_app = typer.Typer(help="Daemon de ejecución: arrancar, parar, estado, pausa y aborto.")
app.add_typer(ops_app, name="run")


@ops_app.command("start")
def ops_start(plan: list[str] | None = typer.Option(None, "--plan"),
              interval: int = typer.Option(30, "--interval"),
              once: bool = typer.Option(False, "--once"),
              detach: bool = typer.Option(False, "--detach")) -> None:
    """Arranca el daemon (alias del subcomando)."""
    from andras.ops import cli as ops

    ops.run(plan, interval, once, detach)


@ops_app.command("stop")
def ops_stop() -> None:
    """Para el daemon."""
    from andras.ops import cli as ops

    ops.stop()


@ops_app.command("status")
def ops_status() -> None:
    """Estado del daemon."""
    from andras.ops import cli as ops

    ops.status()


@ops_app.command("pause")
def ops_pause(plan: str) -> None:
    """Pausa un plan."""
    from andras.ops import cli as ops

    ops.pause(plan)


@ops_app.command("resume")
def ops_resume(plan: str) -> None:
    """Reanuda un plan."""
    from andras.ops import cli as ops

    ops.resume(plan)


@ops_app.command("abort")
def ops_abort(plan: str) -> None:
    """Aborta un plan."""
    from andras.ops import cli as ops

    ops.abort(plan)


notes_app = typer.Typer(help="Diario de la campaña: añadir, buscar, exportar.")
wallet_app = typer.Typer(help="Wallets burner → mixer → treasury.")
net_app = typer.Typer(help="Perfiles de red, Tor y quema de infraestructura.")
channels_app = typer.Typer(help="Correo propio: SPF/DKIM/DMARC y contexto de canales.")
for _sub, _name in ((notes_app, "notes"), (wallet_app, "wallet"), (net_app, "net"),
                    (channels_app, "channels")):
    app.add_typer(_sub, name=_name)


@notes_app.command("add")
def notes_add(body: str, mission_id: str | None = typer.Option(None, "--mission"),
              kind: str = typer.Option("obs", "--kind"),
              title: str = typer.Option("", "--title")) -> None:
    """Añade una nota al diario."""
    from andras.store import db, notes

    config = _config()
    mission = _mission(config, mission_id)
    with db.session(config) as conn:
        note = notes.add(conn, mission.id, body, kind=kind, title=title)
    console.print(f"Nota #{note.id} guardada.")


@notes_app.command("list")
def notes_list(mission_id: str | None = typer.Option(None, "--mission")) -> None:
    """Lista el diario, lo más reciente primero."""
    from andras.store import db, notes

    config = _config()
    mission = _mission(config, mission_id)
    with db.readonly(config) as conn:
        rows = [[n.created_at, n.kind, n.title or "—", n.body_md[:60]]
                for n in notes.for_mission(conn, mission.id)]
    _table("Diario", ["fecha", "tipo", "título", "texto"], rows)


@notes_app.command("search")
def notes_search(query: str, mission_id: str | None = typer.Option(None, "--mission")) -> None:
    """Busca en el diario."""
    from andras.store import db, notes

    config = _config()
    mission = _mission(config, mission_id)
    with db.readonly(config) as conn:
        rows = [[n.id, n.created_at, n.body_md[:100]]
                for n in notes.search(conn, mission.id, query)]
    _table(f"Coincidencias: {query}", ["id", "fecha", "texto"], rows)


@notes_app.command("export")
def notes_export(mission_id: str | None = typer.Option(None, "--mission"),
                 attack_id: str = typer.Option("", "--attack")) -> None:
    """Copia el diario en HTML estático; con `--attack`, sólo la memoria de ese vector."""
    from andras.store import db, notes

    config = _config()
    mission = _mission(config, mission_id)
    with db.session(config) as conn:
        path = notes.export_html(conn, mission.id, attack_id or None)
    console.print(f"Diario exportado: {path}")


@wallet_app.command("new")
def wallet_new(chain: str = typer.Option(..., "--chain"),
               role: str = typer.Option("burner", "--role"),
               mission_id: str | None = typer.Option(None, "--mission")) -> None:
    """Crea una wallet para la campaña."""
    from andras import wallet
    from andras.store import db

    config = _config()
    mission = _mission(config, mission_id)
    with db.session(config) as conn:
        created = wallet.create(conn, mission.id, chain=chain, role=role, config=config)
    console.print(f"Wallet {created.id} {chain}/{role}: {created.address}")


@wallet_app.command("list")
def wallet_list(mission_id: str | None = typer.Option(None, "--mission")) -> None:
    """Lista las wallets de la campaña."""
    from andras import wallet
    from andras.store import db

    config = _config()
    mission = _mission(config, mission_id)
    with db.readonly(config) as conn:
        rows = [[w.id, w.chain, w.role, w.address, "sí" if w.burned else "no"]
                for w in wallet.for_mission(conn, mission.id)]
    _table("Wallets", ["id", "cadena", "rol", "dirección", "quemada"], rows)


@net_app.command("show")
def net_show() -> None:
    """Perfil de red efectivo."""
    from andras import net

    console.print(net.describe(_config()))


@net_app.command("set")
def net_set(mode: str = typer.Option(..., "--mode"),
            doh: str = typer.Option("", "--doh"),
            proxy: str = typer.Option("", "--proxy"),
            jitter: int = typer.Option(0, "--jitter")) -> None:
    """Cambia el perfil de red global en config.json."""
    import json as json_mod

    from andras.core import ROOT

    config = _config()
    net_block = config.setdefault("net", {})
    net_block["default_profile"] = mode
    if doh:
        net_block["doh_url"] = doh
    if proxy:
        net_block["proxy_url"] = proxy
    if jitter:
        net_block["jitter_ms"] = jitter
    (ROOT / "config.json").write_text(json_mod.dumps(config, indent=2, ensure_ascii=False) + "\n")
    console.print("perfil de red actualizado")


@net_app.command("burn")
def net_burn(mission_id: str | None = typer.Option(None, "--mission")) -> None:
    """Quema la infraestructura y personas de la campaña."""
    from andras import net
    from andras.store import db, personas

    config = _config()
    mission = _mission(config, mission_id)
    with db.session(config) as conn:
        infra = net.burn(conn, mission.id)
        people = personas.burn(conn, mission.id)
    console.print(f"{infra} infra y {people} personas quemadas")


@app.command("notifications")
def notifications_command(limit: int = typer.Option(20, "--limit")) -> None:
    """Últimos avisos al operador y si se entregaron."""
    from andras.store import db, notifications

    config = _config()
    with db.readonly(config) as conn:
        rows = [[n["created_at"], n["level"], n["channel"], "sí" if n["ok"] else "no",
                 n["body"][:60]] for n in notifications.recent(conn, limit=limit)]
    _table("Avisos", ["fecha", "nivel", "canal", "ok", "texto"], rows)


@channels_app.command("audit")
def channels_audit(domain: str) -> None:
    """Audita SPF, DKIM y DMARC del dominio de envío."""
    from andras.agent import channel_tools
    from andras.agent.tools import ToolContext
    from andras.store import db

    config = _config()
    with db.session(config) as conn:
        ctx = ToolContext(conn=conn, config=config, mission=None, run_id="cli")
        console.print(channel_tools.dns_audit_spf_dkim_dmarc(ctx, domain)["text"])


@channels_app.command("dkim")
def channels_dkim(domain: str, selector: str = typer.Option("andras", "--selector")) -> None:
    """Genera un par DKIM y muestra el TXT que hay que publicar."""
    from andras.agent import channel_tools
    from andras.agent.tools import ToolContext
    from andras.store import db

    config = _config()
    with db.session(config) as conn:
        ctx = ToolContext(conn=conn, config=config, mission=None, run_id="cli")
        console.print(channel_tools.generate_dkim_zone(ctx, domain, selector)["text"])


def main() -> None:
    app()


if __name__ == "__main__":
    main()
