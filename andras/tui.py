"""TUI mínima: lista de misiones y detalle."""
from __future__ import annotations

from typing import ClassVar

from rich.table import Table

from andras.core import load_config
from andras.store import db, missions


def render(conn) -> Table:
    table = Table(title="ANDRAS — misiones")
    for column in ("id", "objetivo", "estado", "modo"):
        table.add_column(column)
    for mission in missions.all_missions(conn):
        table.add_row(mission.id, mission.target_name, mission.status, mission.mode)
    return table


def run() -> None:
    try:
        from textual.app import App, ComposeResult
        from textual.widgets import Footer, Header, Static
    except ImportError:
        from rich.console import Console

        with db.readonly(load_config()) as conn:
            Console().print(render(conn))
        print("Instala el extra `tui` para la interfaz interactiva: pip install -e '.[tui]'")
        return

    class AndrasApp(App):
        BINDINGS: ClassVar = [("q", "quit", "salir"), ("r", "refresh", "recargar")]

        def compose(self) -> ComposeResult:
            yield Header()
            yield Static(id="body")
            yield Footer()

        def on_mount(self) -> None:
            self.action_refresh()

        def action_refresh(self) -> None:
            with db.readonly(load_config()) as conn:
                self.query_one("#body", Static).update(render(conn))

    AndrasApp().run()
