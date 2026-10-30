"""Wizard de ANDRAS: ocho pasos, el agente en el centro.

S1 preflight → S2 modelo → S3 campaña → S4 objetivo → S5 aclaraciones → S6 recon →
S7 revisión del plan → S8 ejecución. Los pasos 5 a 8 los conduce el agente.
"""
from __future__ import annotations

import concurrent.futures
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Header, Input, Label, RichLog, Static, TextArea

from andras import preflight
from andras.agent import clarify as clarify_mod
from andras.agent import gates, runner
from andras.agent.tools import ToolContext
from andras.core import load_config
from andras.store import db, missions, notes, plans

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
        self.app.push_screen("clarify")


class AskScreen(ModalScreen):
    """Pregunta bloqueante del agente. Devuelve el texto elegido."""

    BINDINGS: ClassVar = [Binding("escape", "cancel", "cancelar")]

    def __init__(self, question: str, options: list) -> None:
        super().__init__()
        self.question = question
        self.options = options

    def compose(self) -> ComposeResult:
        from textual.containers import Vertical

        with Vertical(classes="dialog"):
            yield Label(self.question, classes="step")
            for option in self.options[:6]:
                yield Button(option, classes="option")
            yield Input(placeholder="respuesta libre…", id="free")
            yield Button("Responder", id="send", variant="primary")

    def on_button_pressed(self, event) -> None:
        if event.button.id == "send":
            return self._send(self.query_one("#free", Input).value)
        if event.button.has_class("option"):
            self._send(str(event.button.label))

    def on_input_submitted(self, event) -> None:
        self._send(event.value)

    def _send(self, value: str) -> None:
        if value.strip():
            self.dismiss(value.strip())

    def action_cancel(self) -> None:
        self.dismiss("")


class ClarifyScreen(WizardScreen):
    """S5 · preguntas generadas por la IA, una por pantalla."""

    def __init__(self) -> None:
        super().__init__()
        self.questions: list[dict] = []
        self.index = 0
        self.answers: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("5 · Aclaraciones", classes="step")
        self.progress = Static("", classes="hint")
        yield self.progress
        self.question = Static("", id="question")
        yield self.question
        for index in range(4):
            yield Button("", id=f"opt{index}", classes="option")
        yield Input(placeholder="u otra respuesta…", id="free")
        yield Footer()

    def on_mount(self) -> None:
        mission = self._mission()
        self.questions = clarify_mod.generate(self.app.state.config, mission,
                                              self.app.state.intent)
        self._paint()

    def _mission(self):
        with db.readonly(self.app.state.config) as conn:
            return missions.get(conn, self.app.state.mission_id)

    def _paint(self) -> None:
        row = self.questions[self.index]
        self.progress.update(f"{self.index + 1} de {len(self.questions)}"
                             + (f" · {row['why']}" if row.get("why") else ""))
        self.question.update(row["question"])
        for index in range(4):
            button = self.query_one(f"#opt{index}", Button)
            if index < len(row["options"]):
                button.label = row["options"][index]
                button.display = True
            else:
                button.display = False
        self.query_one("#free", Input).value = ""
        self.query_one("#free", Input).focus()

    def on_button_pressed(self, event) -> None:
        if event.button.has_class("option"):
            self._answer(str(event.button.label))

    def on_input_submitted(self, event) -> None:
        if event.value.strip():
            self._answer(event.value.strip())

    def _answer(self, value: str) -> None:
        row = self.questions[self.index]
        self.answers[row["question"]] = value
        self.index += 1
        if self.index >= len(self.questions):
            self.app.state.intent = {**self.app.state.intent, "answers": self.answers}
            self.app.push_screen("recon")
            return
        self._paint()


class ReconScreen(WizardScreen):
    """S6 · el agente investiga y escribe el plan, en un hilo aparte."""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("6 · Investigación", classes="step")
        yield Static("El agente lee fuentes, anota y construye el plan. Esc cancela y "
                     "conserva lo hecho.", classes="hint")
        self.log_view = RichLog(highlight=True, markup=False, wrap=True)
        yield self.log_view
        yield Horizontal(Button("Parar", id="stop", variant="warning"))
        yield Footer()

    def on_mount(self) -> None:
        self.app.stop_flag = False
        self.run_agent()

    def _append(self, text: str) -> None:
        self.log_view.write(text)

    def on_button_pressed(self, event) -> None:
        if event.button.id == "stop":
            self.app.stop_flag = True
            self._append("… parando tras la herramienta en curso")

    @work(thread=True, exclusive=True)
    def run_agent(self) -> None:
        app = self.app
        config = app.state.config
        try:
            with db.session(config) as conn:
                mission = missions.get(conn, app.state.mission_id)
                plan_id = runner.draft_plan(conn, mission, app.state.campaign_name)
                ctx = ToolContext(conn=conn, config=config, mission=mission,
                                  run_id=secrets.token_hex(6), plan_id=plan_id,
                                  log=lambda t: self._append_thread(t),
                                  ask=app.ask_blocking)
                policy = app.policy(conn, plan_id)
                self._append_thread("· recon determinista inicial")
                runner.seed(conn, config, mission,
                            log=lambda t: self._append_thread(t))
                answers = app.state.intent.get("answers")
                result = runner.recon(ctx, policy, answers)
                app.call_from_thread(self._finish, result, plan_id)
        except Exception as exc:  # la UI debe seguir viva
            app.call_from_thread(self._fail, exc)

    def _append_thread(self, text: str) -> None:
        self.app.call_from_thread(self._append, text)

    def _finish(self, result, plan_id: str) -> None:
        self._append(f"\nFin: {result.reason} · {result.steps} pasos · "
                     f"{result.tokens} tokens · {result.usd:.4f} USD")
        if result.message:
            self._append(result.message[:600])
        self.app.state.intent = {**self.app.state.intent, "plan_id": plan_id}
        self.app.push_screen("review")

    def _fail(self, exc: Exception) -> None:
        self._append(f"[error] {type(exc).__name__}: {exc}")


class ReviewScreen(WizardScreen):
    """S7 · el humano lee, discute, edita y confirma."""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("7 · Plan", classes="step")
        yield Static("Revisa. Puedes hablar con el agente para cambiarlo antes de confirmar.",
                     classes="hint")
        self.body = Static("", id="plan")
        yield self.body
        self.chat = TextArea(id="chat")
        yield self.chat
        yield Horizontal(
            Button("Enviar al agente", id="talk"),
            Button("Confirmar", id="confirm", variant="success"),
            Button("Cancelar", id="cancel", variant="error"))
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_plan()

    def refresh_plan(self) -> None:
        with db.readonly(self.app.state.config) as conn:
            self.body.update(runner.review_summary(conn, self.app.state.intent["plan_id"]))

    def on_button_pressed(self, event) -> None:
        if event.button.id == "talk":
            message = self.chat.text.strip()
            if message:
                self.chat.text = ""
                self.talk(message)
        elif event.button.id == "confirm":
            self._confirm()
        elif event.button.id == "cancel":
            self._cancel()

    @work(thread=True, exclusive=True)
    def talk(self, message: str) -> None:
        app = self.app
        config = app.state.config
        try:
            with db.session(config) as conn:
                mission = missions.get(conn, app.state.mission_id)
                plan_id = app.state.intent["plan_id"]
                ctx = ToolContext(conn=conn, config=config, mission=mission,
                                  run_id=secrets.token_hex(6), plan_id=plan_id,
                                  log=lambda t: None, ask=app.ask_blocking)
                history = app.state.intent.setdefault("history", [])
                result = runner.chat(ctx, app.policy(conn, plan_id), history, message,
                                     app.state.intent.get("answers"))
                history += [{"role": "user", "content": message},
                            {"role": "assistant", "content": result.message}]
                app.call_from_thread(self._after_talk, result)
        except Exception as exc:
            app.call_from_thread(self._after_talk, exc)

    def _after_talk(self, result) -> None:
        self.refresh_plan()
        if isinstance(result, Exception):
            self.notify(f"{type(result).__name__}: {result}", severity="error")
        elif result.message:
            self.notify(result.message[:200], timeout=8)

    def _confirm(self) -> None:
        config = self.app.state.config
        plan_id = self.app.state.intent["plan_id"]
        with db.session(config) as conn:
            step_count = len(plans.steps(conn, plan_id))
            if step_count < 3:
                self.notify("El plan necesita al menos 3 pasos.", severity="warning")
                return
            plans.set_status(conn, plan_id, "confirmed")
            notes.add(conn, self.app.state.mission_id, f"plan `{plan_id}` confirmado por el "
                      f"operador ({step_count} pasos)", kind="decision", plan_id=plan_id)
        self.app.push_screen("exec")

    def _cancel(self) -> None:
        config = self.app.state.config
        plan_id = self.app.state.intent["plan_id"]
        with db.session(config) as conn:
            plans.set_status(conn, plan_id, "draft")
            notes.add(conn, self.app.state.mission_id, f"plan `{plan_id}` devuelto a borrador",
                      kind="decision", plan_id=plan_id)
        self.notify("Plan guardado como borrador.")


class ExecScreen(WizardScreen):
    """S8 · ejecución: arranca el daemon y vigila pasos y avisos."""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("8 · Ejecución", classes="step")
        yield Static("El daemon corre separado. Pausa o aborta desde aquí; el diario "
                     "recoge cada decisión.", classes="hint")
        self.status = Static("", id="daemon")
        yield self.status
        self.log_view = RichLog(highlight=True, markup=False, wrap=True)
        yield self.log_view
        yield Horizontal(
            Button("Pausar", id="pause", variant="warning"),
            Button("Reanudar", id="resume"),
            Button("Abortar", id="abort", variant="error"),
            Button("Parar daemon", id="stop"),
            Button("Cerrar", id="close", variant="success"))
        yield Footer()

    @property
    def plan_id(self) -> str:
        return self.app.state.intent["plan_id"]

    def on_mount(self) -> None:
        self._launch()
        self.set_interval(5, self._poll)

    def _launch(self) -> None:
        from andras.ops import daemon

        if daemon.detach([self.plan_id]):
            self._append("no se pudo arrancar el daemon (¿ya hay uno vivo?)")
        else:
            self._append(f"daemon separado para el plan {self.plan_id}")
        self._poll()

    def _append(self, text: str) -> None:
        self.log_view.write(text)

    def _poll(self) -> None:
        from andras.ops import daemon

        config = self.app.state.config
        try:
            with db.readonly(config) as conn:
                steps = list(conn.execute(
                    "SELECT position, channel, status FROM plan_steps WHERE plan_id=?"
                    " ORDER BY position", (self.plan_id,)))
                plan = plans.get(conn, self.plan_id)
                alerts = list(conn.execute(
                    "SELECT level, body FROM notifications WHERE plan_id=?"
                    " ORDER BY id DESC LIMIT 3", (self.plan_id,)))
        except Exception as exc:  # la pantalla no debe caerse
            self.status.update(f"[error] {exc}")
            return
        self.status.update(f"daemon: {daemon.status()} · plan: {plan['status'] if plan else '?'}")
        if plan and plan["status"] in {"achieved", "aborted", "done"}:
            self._append(f"plan {plan['status']}: fin de la ejecución")
        for step in steps:
            self._append(f"{step['position']}. {step['channel']} — {step['status']}")
        for alert in alerts:
            self._append(f"[{alert['level']}] {alert['body'][:200]}")

    def on_button_pressed(self, event) -> None:
        from andras.ops import daemon

        action = event.button.id
        if action == "pause":
            self._append(f"{daemon.pause(self.plan_id)} pasos pausados")
        elif action == "resume":
            self._append(f"{daemon.resume(self.plan_id)} pasos reanudados")
        elif action == "abort":
            daemon.abort(self.plan_id)
            self._append("plan abortado")
        elif action == "stop":
            daemon.stop()
            self._append("daemon parado")
        elif action == "close":
            self.app.push_screen("resumen")
        self._poll()


class ResumenScreen(WizardScreen):
    """Cierre de fase: enseña lo recogido."""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Listo para ejecutar", classes="step")
        self.body = Static(id="summary")
        yield self.body
        yield Footer()

    def on_mount(self) -> None:
        state = self.app.state
        plan_id = state.intent.get("plan_id", "—")
        self.body.update(
            f"**Campaña:** {state.campaign_name or '—'}\n\n"
            f"**Modelo:** {state.provider} / {state.model}\n\n"
            f"**Meta:** {state.objective}\n\n"
            f"**Misión:** `{state.mission_id}` · **Plan:** `{plan_id}`\n\n"
            "Siguiente fase: daemon de ejecución, webhooks y avisos.")


class ConfirmScreen(ModalScreen):
    BINDINGS: ClassVar = [Binding("escape", "no", "no")]

    def __init__(self, question: str, payload: dict) -> None:
        super().__init__()
        self.question = question
        self.payload = payload

    def compose(self) -> ComposeResult:
        from textual.containers import Vertical

        with Vertical(classes="dialog"):
            yield Label(self.question, classes="step")
            detail = ", ".join(f"{k}={v}" for k, v in list(self.payload.items())[:4])
            if detail:
                yield Static(detail[:400], classes="hint")
            yield Horizontal(Button("Sí", id="yes", variant="success"),
                             Button("No", id="no", variant="error"))

    def on_button_pressed(self, event) -> None:
        self.dismiss(event.button.id == "yes")

    def action_no(self) -> None:
        self.dismiss(False)


class AndrasApp(App):
    CSS_PATH = CSS_PATH
    TITLE = "ANDRAS"
    SUB_TITLE = "emulación de adversario"
    BINDINGS: ClassVar = [Binding("ctrl+q", "quit_app", "salir")]

    SCREENS: ClassVar = {"preflight": PreflightScreen, "model": ModelPickerScreen,
                         "campaign": CampaignScreen, "name": NameScreen,
                         "objective": ObjectiveScreen, "clarify": ClarifyScreen,
                         "recon": ReconScreen, "review": ReviewScreen,
                         "exec": ExecScreen, "resumen": ResumenScreen}

    def __init__(self) -> None:
        super().__init__()
        self.state = State()
        self.models: list[dict] = []
        self.stop_flag = False

    # ---------------------------------------------------------- puente con el hilo

    def ask_blocking(self, question: str, options: list) -> str:
        future: concurrent.futures.Future = concurrent.futures.Future()
        self.call_from_thread(self._open_ask, question, options or [], future)
        return future.result()

    def _open_ask(self, question: str, options: list, future) -> None:
        self.push_screen(AskScreen(question, options),
                         callback=lambda value: future.set_result(value or ""))

    def approve_blocking(self, question: str, payload: dict) -> bool:
        if self.state.intent.get("auto_approve"):
            return True
        future: concurrent.futures.Future = concurrent.futures.Future()
        self.call_from_thread(self._open_confirm, question, payload, future)
        return bool(future.result())

    def _open_confirm(self, question: str, payload: dict, future) -> None:
        self.push_screen(ConfirmScreen(question, payload),
                         callback=lambda value: future.set_result(bool(value)))

    def policy(self, conn, plan_id: str) -> gates.Policy:
        plan = plans.get(conn, plan_id)
        config = self.state.config.get("agent", {})
        return gates.Policy(mode=config.get("mode", "asistido"),
                            plan_confirmed=bool(plan and plan["status"] == "confirmed"),
                            spend_threshold_usd=float(config.get("spend_threshold_usd", 0.25)),
                            approver=self.approve_blocking)

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
