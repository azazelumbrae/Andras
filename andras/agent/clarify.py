"""Preguntas de aclaración: la IA se asegura de haber entendido el encargo."""
from __future__ import annotations

import re

from andras.agent import prompts
from andras.brain import provider

FALLBACK = [
    {"id": "exito", "question": "¿Qué cuenta como éxito para ti en esta campaña?",
     "options": ["Que meta credenciales en la landing",
                 "Que abra el enlace y lo lea",
                 "Que responda al mensaje",
                 "Que llegue a hablar con el atacante"], "multi": False},
    {"id": "canales", "question": "¿Qué canales aceptas que se usen?",
     "options": ["Sólo correo", "Correo y teléfono", "Todo menos whatsapp",
                 "Todos"], "multi": False},
    {"id": "ventana", "question": "¿En qué ventana debe moverse la campaña?",
     "options": ["Menos de 24 horas", "De 1 a 3 días", "Una o dos semanas",
                 "Sin prisa, más de dos semanas"], "multi": False},
    {"id": "presupuesto", "question": "¿Cuánto puedes gastar en infraestructura y cripto?",
     "options": ["Cero: sólo gratis", "Hasta 5 USD", "Hasta 50 USD",
                 "Sin problema si está justificado"], "multi": False},
    {"id": "sospecha", "question": "Si el objetivo sospecha, ¿qué prefieres?",
     "options": ["Insistir con otra identidad", "Bajar el ritmo y esperar",
                 "Cambiar de canal", "Abortar y reportar"], "multi": False},
]


def generate(config, mission, answers: dict | None = None) -> list[dict]:
    context = (f"Objetivo: {mission.target_name}"
               + (f" — {mission.target_role}" if mission.target_role else "")
               + (f" en {mission.target_company}" if mission.target_company else "")
               + f"\nMeta: {mission.goal}\nDominio: {mission.domain or 'desconocido'}")
    if answers:
        context += "\nYa sabemos:\n" + "\n".join(f"- {k}: {v}" for k, v in answers.items())
    message = [{"role": "system", "content": prompts.CLARIFY},
               {"role": "user", "content": context}]
    try:
        data = provider.complete_json(config, message, phase="agent", temperature=0.5,
                                      max_tokens=1200)
        questions = _validate(data.get("questions"))
    except provider.LLMError:
        questions = []
    return questions or FALLBACK


def _validate(raw) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out, seen = [], set()
    for entry in raw[:8]:
        if not isinstance(entry, dict):
            continue
        question = str(entry.get("question", "")).strip()
        options = [str(o).strip()[:120] for o in entry.get("options", [])
                   if str(o).strip()][:4]
        if not question or len(options) < 2:
            continue
        key = re.sub(r"\W+", "", question.lower())[:60]
        if key in seen:
            continue
        seen.add(key)
        out.append({"id": str(entry.get("id") or f"q{len(out) + 1}")[:24],
                    "question": question[:220], "options": options,
                    "multi": bool(entry.get("multi")),
                    "why": str(entry.get("why", ""))[:160]})
        if len(out) == 6:
            break
    return out if len(out) >= 4 else []
