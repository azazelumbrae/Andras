"""CLI del daemon: arrancar, parar, estado y control de un plan.

`andras run` sin argumentos tickea todos los planes confirmados. `--detach` lo separa.
"""
from __future__ import annotations

import typer

from andras.ops import daemon


def run(plan: list[str] | None = typer.Option(None, "--plan", help="plan concreto (repetible)"),
        interval: int = typer.Option(daemon.DEFAULT_INTERVAL, "--interval",
                                     help="segundos entre ticks"),
        once: bool = typer.Option(False, "--once", help="un solo tick y salir"),
        detach: bool = typer.Option(False, "--detach", help="separar el proceso y volver")) -> None:
    """Arranca el daemon de ejecución sobre los planes confirmados."""
    if detach:
        raise typer.Exit(daemon.detach(plan, interval=interval))
    raise typer.Exit(daemon.start(plan, interval=interval, once=once))


def stop() -> None:
    """Para el daemon en marcha."""
    raise typer.Exit(daemon.stop())


def status() -> None:
    """Estado del daemon."""
    typer.echo(daemon.status())


def pause(plan: str) -> None:
    """Pausa los pasos pendientes de un plan."""
    typer.echo(f"{daemon.pause(plan)} pasos pausados")


def resume(plan: str) -> None:
    """Reanuda un plan pausado."""
    typer.echo(f"{daemon.resume(plan)} pasos reanudados")


def abort(plan: str) -> None:
    """Aborta el plan: deja de enviar y lo marca como abortado."""
    daemon.abort(plan)
    typer.echo("plan abortado")


def main() -> None:
    """Entrada para el proceso separado (`python -m andras.ops.cli run`)."""
    command = typer.Typer(add_completion=False)
    command.command()(run)
    command.command()(stop)
    command.command()(status)
    command.command()(pause)
    command.command()(resume)
    command.command()(abort)
    command()


if __name__ == "__main__":
    main()
