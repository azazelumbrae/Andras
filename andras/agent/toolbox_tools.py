"""El arsenal, a mano del agente: qué hay, qué falta y qué encaja con cada fase."""
from __future__ import annotations

from andras import toolbox
from andras.agent import tools


@tools.tool("toolbox_list", permission="read",
            description="Lista el arsenal de ingeniería social por categoría (clonado, proxy, "
                        "red, marca, captura, payload) con su estado de instalación. Úsalo "
                        "antes de prometer un paso que dependa de una herramienta.",
            schema={"type": "object",
                    "properties": {"category": {"type": "string",
                                                "enum": list(toolbox.CATEGORIES)}}})
def toolbox_list(ctx, category: str = "") -> dict:
    found = toolbox.all_tools(category)
    return {"text": toolbox.table(category), "data": {"count": len(found)}}


@tools.tool("toolbox_show", permission="read",
            description="Ficha completa de una herramienta: qué hace, cómo se instala, cómo se "
                        "usa y si tiene sentido en esta máquina.",
            schema={"type": "object", "properties": {"key": {"type": "string"}},
                    "required": ["key"]})
def toolbox_show(ctx, key: str) -> dict:
    try:
        tool = toolbox.get(key)
    except toolbox.ToolboxError as exc:
        raise tools.ToolError(str(exc)) from exc
    return {"text": toolbox.card(tool), "data": {"installed": toolbox.installed(tool)}}


@tools.tool("toolbox_install_hint", permission="read",
            description="Comandos para instalar lo que falta, opcionalmente de una categoría. "
                        "No instala nada: los devuelve para que el operador los ejecute.",
            schema={"type": "object",
                    "properties": {"category": {"type": "string",
                                                "enum": list(toolbox.CATEGORIES)}}})
def toolbox_install_hint(ctx, category: str = "") -> dict:
    pending = toolbox.missing(category)
    if not pending:
        return {"text": "no falta nada de esa categoría", "data": {"missing": []}}
    body = "\n".join(f"- {t.name}: {t.install}" for t in pending)
    return {"text": body, "data": {"missing": [t.key for t in pending]}}


@tools.tool("toolbox_snapshot", permission="write",
            description="Anota en la misión qué arsenal había disponible al planificar, para que "
                        "el plan no dependa de algo ausente sin dejarlo escrito.",
            schema={"type": "object", "properties": {}})
def toolbox_snapshot(ctx) -> dict:
    result = toolbox.record_check(ctx.conn, ctx.mission.id)
    return {"text": f"{len(result['ready'])} herramientas disponibles, "
                    f"{len(result['missing'])} ausentes. Anotado.",
            "data": result}
