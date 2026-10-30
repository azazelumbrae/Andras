"""Preflight: semáforo del entorno antes de dejar que el agente toque nada."""
from __future__ import annotations

import os
import shutil
import socket

import httpx

from andras.core import ROOT, load_config
from andras.store import db

OK, WARN, FAIL = "ok", "warn", "fail"
ICON = {OK: "[green]●[/green]", WARN: "[yellow]●[/yellow]", FAIL: "[red]●[/red]"}


class Check:
    __slots__ = ("detail", "fix", "level", "name")

    def __init__(self, name: str, level: str, detail: str, fix: str = "") -> None:
        self.name, self.level, self.detail, self.fix = name, level, detail, fix

    def __repr__(self) -> str:
        return f"<Check {self.name} {self.level}>"


def _port(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run(config: dict | None = None) -> list[Check]:
    from andras.brain import provider

    checks: list[Check] = []
    try:
        config = config or load_config()
    except SystemExit:
        return [Check("config", FAIL, "falta config.json", "`andras init`")]

    checks.append(Check("config", OK, "config.json cargado"))

    try:
        db.connect(config).close()
        path = db.db_path(config)
        free = shutil.disk_usage(path.parent).free / 1e9
        checks.append(Check("base de datos", OK if free > 1 else WARN,
                            f"{path} · {free:.1f} GB libres"))
    except Exception as exc:
        checks.append(Check("base de datos", FAIL, str(exc), "revisa `database` en config.json"))

    targets = provider.resolve(config, "agent")
    if not targets:
        checks.append(Check("modelos", FAIL, "ningún proveedor con credenciales",
                            "exporta ANDRAS_DEEPSEEK_API_KEY o arranca Ollama"))
    else:
        live = [m for m in probe_models(config) if m["ok"]]
        if live:
            checks.append(Check("modelos", OK,
                                ", ".join(f"{m['provider']}:{m['model']}" for m in live)))
        else:
            checks.append(Check("modelos", FAIL, "ningún proveedor respondió al ping",
                                "revisa clave y `base_url`, o arranca `ollama serve`"))

    checks.append(_smtp(config))
    checks.append(_imap(config))
    checks.append(_telegram(config))
    checks.append(_twilio(config))
    checks.append(Check("tor", OK if _port("127.0.0.1", 9050) else WARN,
                        "socks 9050 activo" if _port("127.0.0.1", 9050) else "sin circuito",
                        "brew services start tor"))
    checks.append(Check("monero-rpc", OK if _port("127.0.0.1", 18082) else WARN,
                        "rpc 18082" if _port("127.0.0.1", 18082) else "no disponible",
                        "monero-wallet-rpc --rpc-bind-port 18082 …"))
    checks.append(Check("dominio", OK if config.get("from_domain") else WARN,
                        config.get("from_domain") or "sin dominio propio: entrega sólo local",
                        "define `from_domain` y su zona SPF/DKIM"))
    checks.append(Check("avisos", OK if _notify_ready(config) else WARN,
                        _notify_detail(config), "configura el bloque `notify`"))
    checks.append(Check("textual", OK if _importable("textual") else FAIL,
                        "interfaz disponible" if _importable("textual") else "falta textual",
                        "pip install -e '.[tui]'"))
    return checks


def _smtp(config: dict) -> Check:
    host, server = config.get("smtp_host", ""), config.get("smtp_server", "")
    if server and host:
        return Check("smtp", OK, f"{host}:{config.get('smtp_port')} · {server}")
    if host:
        return Check("smtp", WARN, f"{host}:{config.get('smtp_port')} (sin servidor de recepción)")
    return Check("smtp", WARN, "sin salida de correo", "rellena smtp_* en config.json")


def _imap(config: dict) -> Check:
    host = config.get("imap_host", "")
    return Check("imap", OK if host else WARN, host or "sin lectura de respuestas",
                 "rellena imap_* para detectar `replied`")


def _telegram(config: dict) -> Check:
    token = config.get("telegram_token") or os.environ.get("ANDRAS_TELEGRAM_TOKEN", "")
    return Check("telegram", OK if token else WARN,
                 "bot configurado" if token else "sin bot: no hay envío ni respuestas",
                 "crea un bot con @BotFather y guarda telegram_token")


def _twilio(config: dict) -> Check:
    sid = config.get("twilio_sid") or os.environ.get("ANDRAS_TWILIO_SID", "")
    return Check("sms/whatsapp", OK if sid else WARN,
                 "twilio configurado" if sid else "sin proveedor sms/whatsapp",
                 "rellena twilio_sid y twilio_token")


def _notify_ready(config: dict) -> bool:
    return bool(config.get("notify"))


def _notify_detail(config: dict) -> str:
    channels = ", ".join(config.get("notify", {}).get("channels", [])) or "ninguno"
    return f"canales: {channels}"


def _importable(module: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(module) is not None


def blocking(checks: list[Check]) -> list[Check]:
    return [c for c in checks if c.level == FAIL]


def render(checks: list[Check]) -> str:
    lines = []
    for check in checks:
        lines.append(f"{ICON[check.level]} {check.name:<16} {check.detail}")
        if check.fix and check.level != OK:
            lines.append(f"   └ {check.fix}")
    return "\n".join(lines)


def probe_models(config: dict) -> list[dict]:
    """Lista proveedores utilizables con una llamada real de un token."""
    from andras.brain import provider

    out = []
    for target in provider.resolve(config, "agent"):
        ok, detail = True, ""
        try:
            resp = httpx.post(f"{target.base_url}/chat/completions",
                              headers={"Authorization": f"Bearer {target.api_key}"},
                              json={"model": target.model, "max_tokens": 1,
                                    "messages": [{"role": "user", "content": "ok"}]},
                              timeout=6)
            ok = resp.status_code < 400
            detail = "" if ok else f"HTTP {resp.status_code}"
        except httpx.HTTPError as exc:
            ok, detail = False, str(exc)[:80]
        out.append({"provider": target.name, "model": target.model, "local":
                    target.base_url.startswith("http://127.0.0.1"), "ok": ok, "detail": detail})
    return out


def root() -> str:
    return str(ROOT)
