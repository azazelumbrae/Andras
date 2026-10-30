"""Render de artefactos por canal y control de calidad previo al envío."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from jinja2 import Environment, PackageLoader, select_autoescape

from andras.artifacts import landing

env = Environment(loader=PackageLoader("andras", "templates"),
                  autoescape=select_autoescape(["html", "j2"]))

TRACKING = "{tracking_url}"


@dataclass(slots=True)
class Rendered:
    channel: str
    subject: str
    text: str
    html: str = ""
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def _attacker_steps(payload: dict) -> list[dict]:
    return [step for step in payload.get("steps", []) if step.get("actor", "ATACANTE") == "ATACANTE"]


def _body(payload: dict, channel: str = "email") -> str:
    steps = _attacker_steps(payload)
    if not steps:
        return ""
    if channel == "email":
        return "\n\n".join(step["script"].strip() for step in steps if step.get("script"))
    return steps[-1]["script"]


def build(channel: str, payload: dict, tracking_url: str = TRACKING) -> Rendered:
    body = _body(payload, channel)
    subject = payload.get("subject") or payload.get("angle", "")
    if channel in {"email", "landing"}:
        html = env.get_template("email.html.j2").render(subject=subject, body=body)
        rendered = Rendered(channel=channel, subject=subject, text=body, html=html)
    else:
        rendered = Rendered(channel=channel, subject=subject, text=body)
    rendered.problems = check(rendered, payload)
    return rendered


def call_sheet(payload: dict) -> str:
    lines = [f"# Hoja de llamada — {payload.get('angle', '')}", "",
             f"**Gancho:** {payload.get('leverage', '')}", ""]
    for index, step in enumerate(payload.get("steps", []), start=1):
        lines.append(f"{index}. **{step.get('actor', 'ATACANTE')}** — {step.get('action', '')}")
        lines.append(f"   > {step.get('script', '')}")
        lines.append("")
    return "\n".join(lines)


def check(rendered: Rendered, payload: dict) -> list[str]:
    problems = []
    if not rendered.text.strip():
        problems.append("cuerpo vacío")
    if rendered.channel == "email":
        if TRACKING not in rendered.text:
            problems.append(f"falta {TRACKING}")
        if len(rendered.text) < 120:
            problems.append("cuerpo demasiado corto para un correo")
        if re.match(r"^(aquí tienes|claro|por supuesto)", rendered.text.strip(), re.IGNORECASE):
            problems.append("empieza con muletilla de asistente")
        if "{" in rendered.text.replace(TRACKING, ""):
            problems.append("llaves sin resolver en el cuerpo")
        if not rendered.subject:
            problems.append("sin asunto")
    if rendered.channel in {"sms", "whatsapp"} and len(rendered.text) > 480:
        problems.append("excede un SMS cómodo")
    if not payload.get("steps"):
        problems.append("sin pasos")
    return problems


def landing_page(payload: dict, capture: bool = True) -> str:
    data = landing.from_payload(payload, capture=capture)
    return env.get_template("landing.html.j2").render(**data)
