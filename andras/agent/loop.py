"""Bucle del agente: modelo → herramientas → observación, con topes y transcript.

El bucle no sabe de UI ni de canales. Recibe un contexto, una política y un objetivo; devuelve
por qué paró. Todo lo que hace queda auditado en `tool_runs` y en `data/runs/<id>.jsonl`.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from andras.agent import gates, tools
from andras.brain import provider
from andras.core import ROOT
from andras.store import budgets

DEFAULT_COST_PER_1K = 0.001


@dataclass(slots=True)
class LoopResult:
    reason: str
    message: str = ""
    steps: int = 0
    tokens: int = 0
    usd: float = 0.0
    submitted: bool = False
    tool_trace: list[str] = field(default_factory=list)


def transcript_path(run_id: str):
    directory = ROOT / "data" / "runs"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{run_id}.jsonl"


def _log(handle, kind: str, payload: dict) -> None:
    handle.write(json.dumps({"kind": kind, **payload}, ensure_ascii=False) + "\n")
    handle.flush()


def _cost(config: dict, tokens: int) -> float:
    rate = float(config.get("llm", {}).get("cost_per_1k", DEFAULT_COST_PER_1K))
    return tokens / 1000 * rate


def run(ctx, policy: gates.Policy, *, system: str, context: str,
        allow: tuple[str, ...] = tools.PERMISSIONS, stop_when: str = "plan_submit",
        should_stop=None, status=None) -> LoopResult:
    """Ejecuta hasta que el modelo deje de llamar herramientas o se agote el presupuesto."""
    limits = budgets.get(ctx.conn, ctx.mission.id)
    cap = limits["max_steps"] - ctx.steps_used
    result = LoopResult(reason="steps")
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": context}]
    catalog = tools.catalog(allow=allow)
    handle = transcript_path(ctx.run_id).open("a")
    nudged = 0
    idle = 0
    last_status = ""
    try:
        _log(handle, "start", {"system": system[:400], "context": context[:2000]})
        while result.steps < cap:
            remaining = cap - result.steps
            if status:
                current_status = status()
                if current_status != last_status:
                    last_status = current_status
                    messages.append({"role": "user", "content": f"ESTADO ACTUAL: {current_status}"})
            if remaining <= 6 and nudged != remaining:
                nudged = remaining
                messages.append({"role": "user", "content":
                                 f"Quedan {remaining} pasos y el plan no está cerrado. "
                                 "Llama YA a `plan_add_step` hasta llegar a 3-6 pasos, "
                                 "`plan_set_success` y `plan_submit`. Deja de investigar."})
            if should_stop and should_stop():
                result.reason, result.message = "stopped", "detenido por el operador"
                break
            try:
                reply = provider.complete_tools(ctx.config, _sane(messages), catalog,
                                                phase="agent")
            except provider.LLMError as exc:
                reply = None
                error = exc
                for _attempt in range(3):
                    if "HTTP 500" in str(error):
                        _trim(messages, MAX_CONTEXT // 2)
                    else:
                        break
                    time.sleep(2 + 3 * _attempt)
                    try:
                        reply = provider.complete_tools(ctx.config, _sane(messages), catalog,
                                                        phase="agent")
                        break
                    except provider.LLMError as again:
                        error = again
                if reply is None:
                    result.reason, result.message = "llm_error", str(error)
                    break
            tokens = int((reply.get("usage") or {}).get("total_tokens", 0))
            spent = _cost(ctx.config, tokens)
            result.tokens += tokens
            result.usd += spent
            budgets.charge_usd(ctx.conn, ctx.mission.id, spent)
            _log(handle, "assistant", {"content": reply.get("content", ""),
                                       "calls": reply.get("tool_calls", []),
                                       "tokens": tokens})
            if not reply["tool_calls"]:
                finished = status and "estado del plan=proposed" in status()
                if not finished and idle < 4:
                    idle += 1
                    messages.append({"role": "assistant", "content": reply.get("content", "")})
                    hint = status() if status else "el plan sigue abierto"
                    messages.append({"role": "user", "content":
                                     f"Sigue trabajando, no has terminado ({hint}). Usa "
                                     "herramientas: recon, notas o el plan."})
                    continue
                result.reason, result.message = "done", reply.get("content", "")
                break

            messages.append({
                "role": "assistant", "content": reply.get("content", ""),
                "tool_calls": [{"id": call["id"], "type": "function",
                                "function": {"name": call["name"],
                                             "arguments": call["arguments"]}}
                               for call in reply["tool_calls"]]})
            for call in reply["tool_calls"]:
                if call["name"] not in FREE:
                    result.steps += 1
                text = _dispatch(ctx, policy, call, status)
                result.tool_trace.append(f"{call['name']} → {text[:120]}")
                messages.append({"role": "tool", "tool_call_id": call["id"],
                                 "name": call["name"], "content": text[:1800]})
                _trim(messages)
                _log(handle, "tool", {"name": call["name"], "text": text[:2000]})
                if call["name"] == stop_when and _submitted(text):
                    result.reason, result.submitted = "submitted", True
                    break
            if result.submitted:
                break
            current = budgets.get(ctx.conn, ctx.mission.id)
            if current["spent_usd"] >= current["max_usd"]:
                result.reason, result.message = "budget", "tope de gasto alcanzado"
                break
            if ctx.steps_used >= current["max_steps"]:
                result.reason, result.message = "steps", "tope de pasos alcanzado"
                break
        else:
            result.reason, result.message = "steps", "tope de pasos alcanzado"
    finally:
        _log(handle, "end", {"reason": result.reason, "steps": result.steps,
                             "tokens": result.tokens, "usd": result.usd})
        handle.close()
    return result


MAX_CONTEXT = 36_000
KEEP = 8


def _trim(messages: list[dict], limit: int | None = None) -> None:
    """Recorta el transcript para no reventar el contexto del modelo.

    Se conservan el sistema, el encargo y los últimos turnos; lo viejo se condensa en una
    línea. Un mensaje `tool` nunca puede quedar sin su `assistant.tool_calls` delante.
    """
    limit = limit or MAX_CONTEXT
    if len(json.dumps(messages, ensure_ascii=False)) <= limit:
        return
    head, body = messages[:2], messages[2:]
    carry = ""
    while body and len(body) > KEEP + 1 and \
            len(json.dumps(head + body, ensure_ascii=False)) > limit:
        dropped = body.pop(0)
        part = dropped.get("content") or ", ".join(
            c.get("name") or c.get("function", {}).get("name", "?")
            for c in dropped.get("tool_calls", [])) or dropped["role"]
        carry = (carry + "; " + part)[-400:]
        while dropped.get("tool_calls") and body and body[0]["role"] == "tool":
            body.pop(0)
    while body and body[0]["role"] == "tool":
        body.pop(0)
    while body and len(body) > 4 and \
            len(json.dumps(head + body, ensure_ascii=False)) > limit:
        body.pop(0)
        while body and body[0]["role"] == "tool":
            body.pop(0)
    messages[:] = head + ([{"role": "user", "content": "(ya hecho: " + carry + ")"}]
                          if carry else []) + body


def _sane(messages: list[dict]) -> list[dict]:
    """Quita `tool` huérfanos: los proveedores estrictos devuelven 500 con ellos."""
    out = []
    for message in messages:
        if message["role"] == "tool" and not (
                out and out[-1]["role"] == "assistant" and out[-1].get("tool_calls")):
            continue
        if message["role"] == "assistant" and not message.get("tool_calls") and out and \
                out[-1]["role"] == "assistant" and out[-1].get("tool_calls"):
            pass
        out.append(message)
    return out


def _submitted(text: str) -> bool:
    return '"submitted":true' in text.replace(" ", "")


FREE = {"ask_operator", "current_time", "budget_status", "note_search", "dossier_read"}


def _plan_hint(status) -> str:
    if not status:
        return ""
    state = status()
    if "estado del plan=draft" not in state:
        return ""
    try:
        steps = int(state.split("pasos=")[1].split()[0])
    except (IndexError, ValueError):
        return ""
    if steps >= 3:
        return "\n\n⚠ El plan ya tiene pasos suficientes. Cierra YA con `plan_submit`."
    return f"\n\n⚠ Faltan {3 - steps} paso(s) como mínimo antes de `plan_submit`."


def _dispatch(ctx, policy: gates.Policy, call: dict, status=None) -> str:
    name = call["name"]
    try:
        spec = tools.get(name)
    except tools.ToolError as exc:
        return f"error: {exc}"
    try:
        args = json.loads(call["arguments"] or "{}")
    except json.JSONDecodeError:
        return "error: argumentos no son JSON válido"
    try:
        gates.authorize(policy, spec, args)
        outcome = tools.invoke(ctx, name, args)
    except tools.PermissionDenied as exc:
        return f"denegado por el operador: {exc}"
    except budgets.BudgetExceeded as exc:
        return f"presupuesto agotado: {exc}"
    except tools.ToolError as exc:
        return f"error: {exc}"
    ctx.log(f"  · {name}: {outcome['text'].splitlines()[0][:100] if outcome['text'] else ''}")
    text = outcome["text"] or ("hecho" if outcome["ok"] else "sin resultado")
    data = outcome.get("data")
    if isinstance(data, dict) and data.get("submitted"):
        text += '\n{"submitted": true}'
    elif name not in {"plan_submit", "plan_set_success", "plan_set_title"}:
        text += _plan_hint(status)
    return text
