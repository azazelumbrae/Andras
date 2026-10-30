"""Daemon de ejecución: bucle de ticks sobre los planes activos.

`andras run <plan>` lo levanta en primer plano; `--detach` lo separa con pidfile y log.
Interrumpir con SIGINT/SIGTERM deja el estado consistente (los jobs conservan su alquiler).
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

from andras.core import ROOT, load_config
from andras.ops import scheduler
from andras.store import db, jobs, notes, plans

DEFAULT_INTERVAL = 30
PIDFILE = ROOT / "data" / "daemon.pid"
LOGFILE = ROOT / "data" / "daemon.log"


def pidfile() -> Path:
    return PIDFILE


def running() -> int | None:
    if not PIDFILE.exists():
        return None
    try:
        pid = int(PIDFILE.read_text().strip())
    except ValueError:
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return pid


def log(message: str) -> None:
    stamp = db.now()
    line = f"{stamp} {message}"
    print(line, flush=True)
    try:
        LOGFILE.parent.mkdir(parents=True, exist_ok=True)
        with LOGFILE.open("a") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


async def loop(plan_ids: list[str] | None = None, *, interval: int = DEFAULT_INTERVAL,
               once: bool = False) -> int:
    """Tickea hasta que no queden planes activos o llegue una señal."""
    config = load_config()
    stop = asyncio.Event()

    def _stop(*_args) -> None:
        log("señal recibida, cerrando tras el tick en curso")
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, _stop)
        except NotImplementedError:  # plataformas sin add_signal_handler
            signal.signal(sig, _stop)

    while not stop.is_set():
        with db.session(config) as conn:
            targets = plan_ids or scheduler.active_plans(conn)
            plans_now = [p for p in targets if _is_active(conn, p)]
            if not plans_now:
                log("sin planes activos; el daemon termina")
                break
            for plan_id in plans_now:
                try:
                    report = scheduler.tick(conn, config, plan_id, log=log)
                except Exception as exc:
                    log(f"tick de {plan_id} falló: {exc}")
                    continue
                if not report.touched:
                    continue
        if once:
            break
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            continue
    return 0


def _is_active(conn, plan_id: str) -> bool:
    plan = plans.get(conn, plan_id)
    return bool(plan and plan["status"] in {"confirmed", "running"})


def start(plan_ids: list[str] | None = None, *, interval: int = DEFAULT_INTERVAL,
          once: bool = False) -> int:
    existing = running()
    if existing:
        log(f"ya hay un daemon vivo (pid {existing})")
        return 1
    if not plan_ids:
        config = load_config()
        with db.readonly(config) as conn:
            plan_ids = scheduler.active_plans(conn)
        if not plan_ids:
            log("no hay planes confirmados. Confirma uno con `andras plan confirm`.")
            return 1
    PIDFILE.parent.mkdir(parents=True, exist_ok=True)
    PIDFILE.write_text(str(os.getpid()))
    log(f"daemon arrancado (pid {os.getpid()}) sobre {', '.join(plan_ids)}")
    try:
        return asyncio.run(loop(plan_ids, interval=interval, once=once))
    finally:
        PIDFILE.unlink(missing_ok=True)
        log("daemon detenido")


def detach(plan_ids: list[str] | None = None, *, interval: int = DEFAULT_INTERVAL) -> int:
    import subprocess

    if running():
        log("ya hay un daemon vivo")
        return 1
    command = [sys.executable, "-m", "andras.ops.cli", "run", "--interval", str(interval)]
    for plan_id in plan_ids or []:
        command += ["--plan", plan_id]
    LOGFILE.parent.mkdir(parents=True, exist_ok=True)
    with LOGFILE.open("a") as handle:
        process = subprocess.Popen(command, stdout=handle, stderr=handle, start_new_session=True)
    log(f"daemon separado (pid {process.pid}), log en {LOGFILE}")
    return 0


def stop() -> int:
    pid = running()
    if not pid:
        log("no hay daemon vivo")
        return 1
    os.kill(pid, signal.SIGTERM)
    log(f"señal enviada a {pid}")
    return 0


def status() -> str:
    pid = running()
    if not pid:
        return "parado"
    return f"vivo (pid {pid})"


def pause(plan_id: str) -> int:
    config = load_config()
    with db.session(config) as conn:
        count = jobs.pause_all(conn, plan_id)
        plans.set_status(conn, plan_id, "paused")
        notes.add(conn, plans.get(conn, plan_id)["mission_id"], "plan pausado por el operador",
                  kind="decision", plan_id=plan_id)
    return count


def resume(plan_id: str) -> int:
    config = load_config()
    with db.session(config) as conn:
        count = jobs.resume_all(conn, plan_id)
        plans.set_status(conn, plan_id, "running")
        notes.add(conn, plans.get(conn, plan_id)["mission_id"], "plan reanudado por el operador",
                  kind="decision", plan_id=plan_id)
    return count


def abort(plan_id: str) -> None:
    config = load_config()
    with db.session(config) as conn:
        jobs.pause_all(conn, plan_id)
        plans.set_status(conn, plan_id, "aborted")
        notes.add(conn, plans.get(conn, plan_id)["mission_id"], "plan abortado por el operador",
                  kind="decision", plan_id=plan_id)
