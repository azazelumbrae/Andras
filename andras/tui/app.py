"""Wizard de ANDRAS: ocho pasos, el agente en el centro.

S1 preflight → S2 modelo → S3 campaña → S4 objetivo → S5 aclaraciones → S6 recon →
S7 revisión del plan → S8 ejecución. Los pasos 5 a 8 los conduce el agente.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from andras import preflight
from andras.core import load_config
from andras.store import db

CSS_PATH = Path(__file__).with_name("app.tcss")


@dataclass(slots=True)
class State:
    config: dict = field(default_factory=dict)
    provider: str = ""
    model: str = ""
    mission_id: str = ""
    campaign_name: str = ""
    objective: str = ""
    intent: dict = field(default_factory=dict)
    persona_id: str = ""
    checks: list = field(default_factory=list)


class WizardScreen(Screen):
    BINDINGS: ClassVar = [Binding("escape", "back", "atrás"),
                          Binding("ctrl+q", "quit", "salir")]

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()


class PreflightScreen(WizardScreen):
    def compose(self) -> ComposeResult:
        from textual.widgets import Button

        yield Header()
        yield Static("1 · Entorno", classes="step")
        self.report = Static(preflight.render(self.app.state.checks))
        yield self.report
        self.block = Static("", id="block")
        yield self.block
        yield Button("Continuar", id="next", variant="primary", disabled=bool(
            preflight.blocking(self.app.state.checks)))
        yield Footer()

    def on_mount(self) -> None:
        blocking = preflight.blocking(self.app.state.checks)
        if blocking:
            self.block.update("[red]Falta algo imprescindible. Arregla los puntos rojos y "
                              "vuelve a abrir el wizard.[/red]")
            self.block.add_class("blocked")
        else:
            self.block.update("[green]Entorno suficiente.[/green]")

    def on_button_pressed(self, event) -> None:
        if event.button.id == "next" and not preflight.blocking(self.app.state.checks):
            self.app.push_screen("model")


class ModelPickerScreen(WizardScreen):
    def compose(self) -> ComposeResult:
        from textual.widgets import ListItem, ListView

        yield Header()
        yield Static("2 · Modelo", classes="step")
        yield Static("Sólo aparecen los conectados y respondiendo. Local = los datos "
                     "no salen del equipo.", classes="hint")
        items = []
        for index, model in enumerate(self.app.models, start=1):
            local = " · local" if model["local"] else ""
            items.append(ListItem(Static(f"{index}. {model['provider']} / {model['model']}{local}")))
        if items:
            yield ListView(*items, id="models")
        else:
            yield Static("[red]Ningún modelo respondió al ping. Revisa claves u Ollama.[/red]")
        yield Footer()

    def on_list_view_selected(self, event) -> None:
        index = event.list_view.index or 0
        model = self.app.models[index]
        self.app.state.provider = model["provider"]
        self.app.state.model = model["model"]
        self.app.push_screen("campaign")


class CampaignScreen(WizardScreen):
    def compose(self) -> ComposeResult:
        from textual.widgets import ListItem, ListView

        yield Header()
        yield Static("3 · Campaña", classes="step")
        yield Static("Nueva, o continúa una existente.", classes="hint")
        items = [ListItem(Static("＋ Nueva campaña"), id="new")]
        with db.readonly(self.app.state.config) as conn:
            rows = list(conn.execute(
                "SELECT m.id, m.target_name, m.status, p.title FROM missions m"
                " LEFT JOIN plans p ON p.mission_id=m.id AND p.id=(SELECT id FROM plans"
                " WHERE mission_id=m.id ORDER BY created_at DESC LIMIT 1)"
                " ORDER BY m.created_at DESC LIMIT 15"))
        for row in rows:
            label = f"{row['target_name']} · {row['title'] or row['status']}"
            items.append(ListItem(Static(label), id=row["id"]))
        yield ListView(*items, id="campaigns")
        yield Footer()

    def on_list_view_selected(self, event) -> None:
        item_id = event.item.id or ""
        if item_id == "new":
            self.app.push_screen("name")
            return
        self.app.state.mission_id = item_id
        with db.readonly(self.app.state.config) as conn:
            row = conn.execute("SELECT target_name, goal FROM missions WHERE id=?",
                               (item_id,)).fetchone()
        self.app.state.campaign_name = row["target_name"]
        self.app.state.objective = row["goal"]
        self.notify("Campaña cargada.")
        self.app.push_screen("objective")


class NameScreen(WizardScreen):
    def compose(self) -> ComposeResult:
        from textual.widgets import Input

        yield Header()
        yield Static("3 · Nombre de la campaña", classes="step")
        self.field = Input(placeholder="p. ej. «Proveedor falso · Acme»")
        yield self.field
        yield Footer()

    def on_mount(self) -> None:
        self.field.focus()

    def on_input_submitted(self, event) -> None:
        if not event.value.strip():
            return
        self.app.state.campaign_name = event.value.strip()
        self.app.push_screen("objective")


class ObjectiveScreen(WizardScreen):
    FIELDS = (
        ("target_name", "Objetivo (nombre y apellidos)", "Tim Cook"),
        ("target_role", "Cargo", "CEO"),
        ("target_company", "Empresa", "Apple"),
        ("target_email", "Correo conocido (opcional)", "tim@apple.com"),
        ("target_phone", "Teléfono conocido (opcional)", "+1 408 555 0100"),
    )

    def compose(self) -> ComposeResult:
        from textual.widgets import Input, Select, TextArea

        yield Header()
        yield Static("4 · Objetivo", classes="step")
        yield Static("Qué quieres conseguir. Cuanto más concreto, mejores preguntas.",
                     classes="hint")
        for name, label, placeholder in self.FIELDS:
            yield Static(label, classes="label")
            yield Input(placeholder=placeholder, id=name)
        yield Static("Modo", classes="label")
        yield Select([("pasivo", "passive"), ("con seguimiento", "tracked"),
                      ("interactivo", "interactive")], value="tracked", id="mode")
        yield Static("Meta (el resultado que buscamos)", classes="label")
        self.goal = TextArea(text=self.app.state.objective, id="goal")
        yield self.goal
        yield Static("Canales permitidos", classes="label")
        yield Static("correo · landing · teléfono · telegram · sms · whatsapp", classes="hint")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#target_name").focus()

    def key_ctrl_s(self) -> None:
        self._commit()

    def key_enter(self) -> None:
        if self.focused is self.goal:
            return
        self._commit()

    def _commit(self) -> None:
        from andras.store import missions

        name = self.query_one("#target_name").value.strip()
        goal = self.goal.text.strip()
        if not name or not goal:
            self.notify("Faltan el nombre o la meta.", severity="warning")
            return
        config = self.app.state.config
        with db.session(config) as conn:
            if self.app.state.mission_id:
                missions.update(conn, self.app.state.mission_id, target_name=name,
                                goal=goal,
                                target_role=self.query_one("#target_role").value.strip(),
                                target_company=self.query_one("#target_company").value.strip(),
                                mode=self.query_one("#mode").value)
                mission_id = self.app.state.mission_id
            else:
                intent = {**self.app.state.intent,
                          "campaign_name": self.app.state.campaign_name,
                          "target_email": self.query_one("#target_email").value.strip(),
                          "target_phone": self.query_one("#target_phone").value.strip(),
                          "model": {"provider": self.app.state.provider,
                                    "model": self.app.state.model}}
                mission = missions.create(
                    conn, target_name=name, goal=goal,
                    target_role=self.query_one("#target_role").value.strip(),
                    target_company=self.query_one("#target_company").value.strip(),
                    domain=(self.query_one("#target_email").value.split("@")[-1].strip()
                            if "@" in self.query_one("#target_email").value else ""),
                    mode=self.query_one("#mode").value, intent=intent)
                mission_id = mission.id
            self.app.state.mission_id = mission_id
        self.app.state.objective = goal
        self.notify(f"Campaña {self.app.state.campaign_name or name} lista.")
        self.app.push_screen("resumen")


class ResumenScreen(WizardScreen):
    """Cierre de P0: enseña lo recogido y dónde seguirá el agente."""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Listo para el agente", classes="step")
        self.body = Static(id="summary")
        yield self.body
        yield Static("Siguiente fase: preguntas de aclaración, recon y plan.", classes="hint")
        yield Footer()

    def on_mount(self) -> None:
        state = self.app.state
        self.body.update(
            f"**Campaña:** {state.campaign_name or '—'}\n\n"
            f"**Modelo:** {state.provider} / {state.model}\n\n"
            f"**Meta:** {state.objective}\n\n"
            f"**Misión:** `{state.mission_id}`")
        self.notify("Pulsa Esc para volver o ctrl+q para salir.")


class AndrasApp(App):
    CSS_PATH = CSS_PATH
    TITLE = "ANDRAS"
    SUB_TITLE = "emulación de adversario"
    BINDINGS: ClassVar = [Binding("ctrl+q", "quit_app", "salir")]

    SCREENS: ClassVar = {"preflight": PreflightScreen, "model": ModelPickerScreen,
               "campaign": CampaignScreen, "name": NameScreen,
               "objective": ObjectiveScreen, "resumen": ResumenScreen}

    def __init__(self) -> None:
        super().__init__()
        self.state = State()
        self.models: list[dict] = []

    def on_mount(self) -> None:
        self.state.config = load_config()
        try:
            db.connect(self.state.config).close()
        except Exception as exc:  # el preflight enseñará el fallo
            self.state.checks = [preflight.Check("base de datos", preflight.FAIL, str(exc))]
        else:
            self.state.checks = preflight.run(self.state.config)
        self.models = [m for m in preflight.probe_models(self.state.config) if m["ok"]]
        self.push_screen("preflight")

    def action_quit_app(self) -> None:
        self.exit()


def run() -> None:
    AndrasApp().run()
