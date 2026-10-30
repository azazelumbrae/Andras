"""Campaña omnicanal: composición de la secuencia y ejecución de cada paso."""
from __future__ import annotations

import time

from andras.brain import packs, planner, prompts, provider
from andras.models import Mission
from andras.store import evidence, hooks, plans

SUPPORTED = ("email", "sms", "phone", "social", "telegram", "whatsapp")


def compose(conn, config, mission: Mission, channels: list[str] | None = None,
            length: int = 4, log=print) -> str:
    chosen = hooks.chosen(conn, mission.id) or hooks.list_for(conn, mission.id)[:1]
    if not chosen:
        raise SystemExit("No hay ganchos. Ejecuta `andras hooks` y elige uno.")
    hook = chosen[0]
    channels = [c for c in (channels or mission.channels or ["email", "phone"]) if c in SUPPORTED]
    if not channels:
        raise SystemExit("Sin canales válidos")
    length = max(3, min(6, length))

    menu = []
    for channel in channels:
        for pack in packs.choose(channel=channel, has={a.kind for a in
                                                       evidence.usable(conn, mission.id)}, limit=4):
            menu.append(f"- {pack.id} [{channel}] {pack.name}: {pack.purpose[:140]}")
    if not menu:
        raise SystemExit("No hay packs para esos canales")

    soporte = "\n".join(f"[{a.id}] {a.kind}: {a.value}" for i in hook.artifact_ids
                        for a in evidence.by_ids(conn, [i]))
    message = [{"role": "system", "content": prompts.CAMPAIGN + provider.COMPLETENESS},
               {"role": "user", "content":
                f"Meta: {mission.goal}\nObjetivo: {mission.target_name}, "
                f"{mission.target_role} en {mission.target_company}\n"
                f"Canales permitidos: {', '.join(channels)}\n"
                f"Pasos: {length}\n\nGANCHO: {hook.title}\n{chosen[0].rationale}\n"
                f"Soporte:\n{soporte}\n\nPACKS DISPONIBLES:\n" + "\n".join(menu)}]
    try:
        data = provider.complete_json(config, message, phase="campaign", temperature=0.6,
                                      max_tokens=2500)
        sequence = _validate(data, channels)
    except (provider.LLMError, SystemExit) as exc:
        log(f"  ! composición por LLM falló ({exc}); uso plantilla")
        data, sequence = {}, _template(channels, length)

    plan_id = plans.create(conn, mission.id, str(data.get("title", f"Campaña {mission.target_name}"))[:120]
                           if isinstance(data, dict) else f"Campaña {mission.target_name}",
                           str(data.get("narrative", "")) if isinstance(data, dict) else "")
    catalog = {p.id: p for p in packs.load_all()[0]}
    position = 0
    for step in sequence:
        family = packs.CHANNEL_ALIAS.get(step["channel"], step["channel"])
        pack = catalog.get(step["pack_id"])
        if pack is None or pack.channel != family:
            options = packs.choose(channel=step["channel"], has=set(), limit=8)
            pack = options[position % len(options)] if options else None
        if pack is None:
            continue
        vector = None
        for attempt in (1, 2):
            try:
                vector = planner.build_one(conn, config, mission, pack, hook, channel=step["channel"])
                break
            except provider.LLMError as exc:
                log(f"  ! paso {position + 1} intento {attempt} sin guion ({exc})")
        if not vector:
            continue
        position += 1
        step_id = plans.add_step(conn, plan_id, position, step["channel"], pack_id=pack.id,
                                 delay_hours=step["delay_hours"], trigger=step["trigger"],
                                 why=step["why"])
        plans.attach_attack(conn, step_id, vector.id)
    if not position:
        raise SystemExit("No se pudo generar ningún paso; revisa el proveedor LLM")
    return plan_id


def _validate(data: dict, channels: list[str]) -> list[dict]:
    steps = data.get("steps")
    if not isinstance(steps, list) or len(steps) < 3:
        raise SystemExit("secuencia demasiado corta")
    out = []
    for entry in steps[:6]:
        channel = str(entry.get("channel", ""))
        if channel not in channels:
            continue
        trigger = str(entry.get("trigger", "always"))
        if trigger not in plans.TRIGGERS:
            trigger = "always"
        try:
            delay = float(entry.get("delay_hours", 0))
        except (TypeError, ValueError):
            delay = 0.0
        out.append({"channel": channel, "pack_id": str(entry.get("pack_id", "")),
                    "delay_hours": max(0.0, delay), "trigger": trigger,
                    "why": str(entry.get("why", ""))[:300]})
    if len(out) < 3:
        raise SystemExit("ningún paso válido")
    return out


def _template(channels: list[str], length: int) -> list[dict]:
    base = (channels * length)[:length]
    return [{"channel": channel, "pack_id": "", "delay_hours": 0 if i == 0 else 24 * i,
             "trigger": "always" if i == 0 else "no_submit",
             "why": "escalada por canal" if i else "apertura"}
            for i, channel in enumerate(base)]


def run(conn, config, plan_id: str, *, target: str, resume: bool = False,
        skip_wait: bool = False, log=print) -> list[dict]:
    """Recorre la secuencia. Devuelve el estado de cada paso."""
    plan = plans.get(conn, plan_id)
    if not plan:
        raise SystemExit("Plan inexistente")
    results = []
    for step in plans.steps(conn, plan_id):
        if step["status"] in {"done", "skipped"} and resume:
            continue
        if not step["attack_id"]:
            results.append({"position": step["position"], "status": "sin_guion"})
            continue
        events = _events(conn, step["attack_id"])
        if not plans.fired(step["trigger"], events):
            results.append({"position": step["position"], "status": "no_disparado",
                            "trigger": step["trigger"]})
            continue
        if not skip_wait and step["delay_hours"]:
            wait = step["delay_hours"] * 3600
            log(f"  esperando {step['delay_hours']}h antes del paso {step['position']}…")
            time.sleep(wait)
        results.append({"position": step["position"], "status": "listo",
                        "attack_id": step["attack_id"], "channel": step["channel"]})
        plans.mark(conn, step["id"], "ready")
    return results


def _events(conn, attack_id: str) -> set[str]:
    row = conn.execute("SELECT group_concat(e.event) AS events FROM deliveries d"
                       " JOIN campaigns c ON c.id=d.campaign_id JOIN events e"
                       " ON e.campaign_id=c.id WHERE d.attack_id=?", (attack_id,)).fetchone()
    return set((row["events"] or "").split(",")) if row and row["events"] else set()
