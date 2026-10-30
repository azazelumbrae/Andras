import argparse
import hashlib
import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from .core import ROOT, database, load_config, load_scenario, new_campaign, record

# Subcomandos que son atajos de `preview <escenario>`.
PREVIEW_COMMANDS = {"osint-discover", "phishing-spear", "extortion-bec",
                    "social-bot-fake", "ban-account"}


def allowed(config, address):
    return address.lower() in {item.lower() for item in config.get("authorized_recipients", [])}


def preview(args):
    config = load_config(); scenario = load_scenario(args.scenario)
    if not allowed(config, args.to): raise SystemExit("Destinatario no autorizado en config.json")
    url = config["base_url"].rstrip("/") + "/<token-de-campaña>"
    print(f"Para: {args.to}\nDe: {config['from_name']} <{config['from_address']}>\nAsunto: {scenario['subject']}\n\n{scenario['body'].format(training_url=url)}")


def send(args):
    config = load_config(); scenario = load_scenario(args.scenario)
    if not allowed(config, args.to): raise SystemExit("Destinatario no autorizado. Añádelo explícitamente a config.json")
    user = os.environ.get(config["smtp_user_env"], "")
    password = os.environ.get(config["smtp_password_env"], "")
    if not user or not password: raise SystemExit("Configura las variables de entorno SMTP indicadas en config.json")
    msg = EmailMessage(); msg["From"] = f"{config['from_name']} <{config['from_address']}>"
    msg["To"] = args.to; msg["Subject"] = scenario["subject"]
    msg.set_content(scenario["body"].format(training_url="[enlace de entrenamiento generado al confirmar]"))
    print(f"Destinatario: {args.to}\nAsunto: {scenario['subject']}\nSMTP: {config['smtp_host']}:{config['smtp_port']} ({config['smtp_security']})")
    if input("Escribe SEND para transmitir este mensaje: ").strip() != "SEND": raise SystemExit("Envío cancelado")
    conn = database(config)
    recipient_hash = hashlib.sha256(args.to.lower().encode()).hexdigest()
    campaign = new_campaign(conn, args.scenario, recipient_hash)
    msg.set_content(scenario["body"].format(training_url=config["base_url"].rstrip("/") + "/" + campaign))
    try:
        if config["smtp_security"] == "ssl":
            smtp = smtplib.SMTP_SSL(config["smtp_host"], int(config["smtp_port"]), context=ssl.create_default_context(), timeout=20)
        else:
            smtp = smtplib.SMTP(config["smtp_host"], int(config["smtp_port"]), timeout=20)
            smtp.ehlo(); smtp.starttls(context=ssl.create_default_context()); smtp.ehlo()
        with smtp:
            smtp.login(user, password); smtp.send_message(msg)
        record(conn, campaign, "sent")
    except Exception:
        conn.execute("DELETE FROM campaigns WHERE id=?", (campaign,)); conn.commit(); conn.close()
        raise
    conn.close(); print("Enviado. Mantén el servidor activo para registrar la interacción.")


def report(args):
    config = load_config(); conn = database(config)
    rows = conn.execute("SELECT scenario,event,COUNT(*) FROM campaigns JOIN events ON campaigns.id=events.campaign_id GROUP BY scenario,event ORDER BY scenario,event").fetchall()
    conn.close()
    if args.format == "json": print(json.dumps([{"scenario": a, "event": b, "count": c} for a,b,c in rows], indent=2))
    else:
        print("ANDRAS — resumen de eventos")
        for scenario,event,count in rows: print(f"{scenario}: {event}: {count}")
        if not rows: print("Todavía no hay eventos.")


def deepseek(args):
    """Acciones de la capa v2 (OSINT -> dossier -> plan). Aún sin cablear al pipeline."""
    from . import llm
    config = load_config()
    if not llm.available(config):
        raise SystemExit("Falta la clave LLM. Exporta ANDRAS_DEEPSEEK_API_KEY "
                         "o rellena deepseek_api_key en config.json")
    if args.action != "generate_attack_plan":
        raise SystemExit(f"Acción desconocida: {args.action}. Disponible: generate_attack_plan")
    raise SystemExit("generate_attack_plan necesita una misión creada; "
                     "la creación de misiones llega con el pipeline v3 (ver docs/ARCHITECTURE.md)")


def main():
    parser = argparse.ArgumentParser(prog="andras"); sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="crear config y base de datos")
    sub.add_parser("scenarios", help="listar escenarios")
    p = sub.add_parser("osint-discover", help="preview OSINT scenario")
    p.add_argument("--to", required=True)
    p = sub.add_parser("phishing-spear", help="preview phishing scenario")
    p.add_argument("--to", required=True)
    p = sub.add_parser("extortion-bec", help="preview extortion scenario")
    p.add_argument("--to", required=True)
    p = sub.add_parser("social-bot-fake", help="preview social bot scenario")
    p.add_argument("--to", required=True)
    p = sub.add_parser("ban-account", help="preview ban scenario")
    p.add_argument("--to", required=True)
    p = sub.add_parser("preview"); p.add_argument("scenario"); p.add_argument("--to", required=True)
    p = sub.add_parser("send"); p.add_argument("scenario"); p.add_argument("--to", required=True)
    pr = sub.add_parser("report"); pr.add_argument("--format", choices=["text", "json"], default="text")
    ps_deepseek = sub.add_parser("deepseek", help="acciones de DeepSeek")
    ps_deepseek.add_argument("action", help="acción a ejecutar, ej: generate_attack_plan")
    sub.add_parser("serve", help="iniciar página local")
    args = parser.parse_args()
    if args.cmd == "init":
        config_path = ROOT / "config.json"
        if not config_path.exists(): config_path.write_text((ROOT / "config.example.json").read_text())
        config = load_config(); conn = database(config); conn.close()
        print("Listo. Edita config.json antes de usar SMTP.")
    elif args.cmd == "scenarios":
        for path in sorted((ROOT / "scenarios").glob("*.json")):
            try:
                item = json.loads(path.read_text())
            except json.JSONDecodeError as exc:
                print(f"! {path.name}: JSON inválido ({exc})"); continue
            print(f"{item['id']} — {item['name']}")
    elif args.cmd in PREVIEW_COMMANDS:
        args.scenario = args.cmd; preview(args)
    elif args.cmd == "deepseek":
        deepseek(args)
    elif args.cmd == "preview": preview(args)
    elif args.cmd == "send": send(args)
    elif args.cmd == "report": report(args)
    elif args.cmd == "serve":
        from .server import serve
        serve()


if __name__ == "__main__": main()
