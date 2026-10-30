# Módulos v2 (deprecados)

`osint.py`, `db.py`, `dossier.py`, `attack_plan.py` y `tools.py` fueron la primera capa
OSINT + LLM. Siguen importables y `tools.py` conserva utilidades, pero la ruta viva es:

| v2 | v3 |
|---|---|
| `db.py` | `store/` |
| `osint.py` | `recon/` |
| `dossier.py` | `evidence/dossier.py` |
| `attack_plan.py` | `brain/planner.py` + `prompts/packs/` |
| `llm.py` | `brain/provider.py` |

`core.py` y `server.py` se mantienen: la landing v1 y la tabla de campañas siguen en uso.

Se eliminarán cuando `recon/` cubra los colectores externos que hoy viven en `tools.py`.
