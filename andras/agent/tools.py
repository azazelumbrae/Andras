"""Registro de herramientas del agente.

Cada herramienta declara su esquema JSON, su clase de permiso y su coste estimado.
Sin registro aquí, el modelo no la ve. Las clases de permiso las interpreta `gates`:
`read` corre libre, `write` escribe, `send` entrega, `spend` gasta, `admin` destruye.
"""
from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from andras.store import budgets

PERMISSIONS = ("read", "write", "send", "spend", "admin")
TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool,
         "array": list, "object": dict}


class ToolError(RuntimeError):
    pass


class PermissionDenied(ToolError):
    pass


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    schema: dict
    permission: str
    run: Callable
    cost_usd: float = 0.0
    needs: tuple[str, ...] = ()


@dataclass(slots=True)
class ToolContext:
    conn: object
    config: dict
    mission: object
    run_id: str
    log: Callable = print
    plan_id: str = ""
    dry_run: bool = False
    ask: Callable | None = None
    seen: set[str] = field(default_factory=set)
    steps_used: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.seen, list):
            self.seen = set(self.seen)


_REGISTRY: dict[str, ToolSpec] = {}


def tool(name: str, *, permission: str = "read", description: str, schema: dict | None = None,
         cost_usd: float = 0.0, needs: tuple[str, ...] = ()):
    if permission not in PERMISSIONS:
        raise ValueError(f"permiso inválido: {permission}")

    def register(func):
        if name in _REGISTRY:
            raise ValueError(f"herramienta duplicada: {name}")
        _REGISTRY[name] = ToolSpec(name=name, description=description,
                                   schema=schema or {"type": "object", "properties": {}},
                                   permission=permission, run=func, cost_usd=cost_usd,
                                   needs=needs)
        return func

    return register


def get(name: str) -> ToolSpec:
    spec = _REGISTRY.get(name)
    if not spec:
        raise ToolError(f"herramienta inexistente: {name}")
    return spec


def all_tools() -> list[ToolSpec]:
    return sorted(_REGISTRY.values(), key=lambda s: (s.permission, s.name))


def catalog(*, allow: tuple[str, ...] = PERMISSIONS) -> list[dict]:
    """Formato `tools` de OpenAI para el modelo."""
    out = []
    for spec in all_tools():
        if spec.permission not in allow:
            continue
        out.append({"type": "function",
                    "function": {"name": spec.name, "description": spec.description,
                                 "parameters": spec.schema}})
    return out


def validate(spec: ToolSpec, args: dict) -> dict:
    if not isinstance(args, dict):
        raise ToolError("los argumentos deben ser un objeto")
    schema = spec.schema
    props = schema.get("properties", {})
    for required in schema.get("required", []):
        if required not in args:
            raise ToolError(f"falta el argumento `{required}`")
    clean = {}
    for key, value in args.items():
        if key not in props:
            continue
        expected = TYPES.get(props[key].get("type", "string"))
        if expected and not isinstance(value, expected):
            raise ToolError(f"`{key}` debe ser {props[key].get('type')}")
        allowed = props[key].get("enum")
        if allowed and value not in allowed:
            raise ToolError(f"`{key}` debe ser uno de: {', '.join(map(str, allowed))}")
        if isinstance(value, str):
            value = value.strip()
        clean[key] = value
    return clean


def signature(spec: ToolSpec, args: dict) -> str:
    return hashlib.sha256(
        (spec.name + json.dumps(args, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()[:16]


def invoke(ctx: ToolContext, name: str, args: dict, *, repeat: bool = False) -> dict:
    """Ejecuta, audita y devuelve `{ok, text, data}`. Nunca propaga la excepción del tool."""
    spec = get(name)
    started = time.monotonic()
    if ctx.mission is not None:
        budget = budgets.get(ctx.conn, ctx.mission.id)
        if budget["spent_usd"] + spec.cost_usd > budget["max_usd"]:
            raise budgets.BudgetExceeded("presupuesto en dólares agotado")
        if ctx.steps_used >= budget["max_steps"]:
            raise budgets.BudgetExceeded("presupuesto de pasos agotado")

    clean = validate(spec, args)
    sig = signature(spec, clean)
    if sig in ctx.seen and not repeat:
        return {"ok": True, "text": "ya ejecutada antes con los mismos argumentos; "
                                    "no repitas, usa el resultado anterior", "data": {},
                "cached": True}
    ctx.seen.add(sig)

    ctx.steps_used += 1
    ok, text, data, error = True, "", {}, ""
    try:
        if ctx.dry_run:
            text = f"simulación de {name} (sin efectos)"
        else:
            outcome = spec.run(ctx, **clean)
            if isinstance(outcome, dict):
                text = str(outcome.get("text", ""))
                data = outcome.get("data", {})
            else:
                text = str(outcome or "")
    except Exception as exc:  # el agente necesita leer el error y decidir
        ok, error = False, f"{type(exc).__name__}: {exc}"
        text = f"error en {name}: {error}"
    ms = int((time.monotonic() - started) * 1000)
    _audit(ctx, spec, clean, text, ok, ms)
    if ok and spec.cost_usd:
        budgets.charge_usd(ctx.conn, ctx.mission.id, spec.cost_usd)
    return {"ok": ok, "text": text, "data": data, "error": error}


def _audit(ctx: ToolContext, spec: ToolSpec, args: dict, result: str, ok: bool, ms: int) -> None:
    from andras.store.db import now

    try:
        ctx.conn.execute(
            "INSERT INTO tool_runs(run_id,mission_id,tool,args,result,permission,cost_usd,ms,ok,"
            "created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (ctx.run_id, getattr(ctx.mission, "id", ""), spec.name,
             json.dumps(args, ensure_ascii=False), result[:4000], spec.permission,
             spec.cost_usd, ms, int(ok), now()))
    except Exception as exc:  # la auditoría nunca debe tumbar la herramienta
        ctx.log(f"  ! auditoría de {spec.name} falló: {exc}")


def describe() -> str:
    """Lista legible para el operador (preflight y `andras tools`)."""
    rows = [f"{s.permission:<6} {s.name:<24} {s.description}" for s in all_tools()]
    return "\n".join(rows)


def reset() -> None:
    _REGISTRY.clear()
