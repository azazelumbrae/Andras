"""Importa los catálogos de unjail.ai (bundles JS) a packs YAML.

Uso:
    python scripts/import_unjail_packs.py social-engineering ~/se.js
    python scripts/import_unjail_packs.py dark-psychology ~/dp.js

Los bundles son JSON embebido en `JSON.parse('...')`. Los escenarios se escriben como
packs versionados; el canal se infiere de las palabras del enunciado.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "prompts" / "packs"

PHONE = ("call", "caller", "vishing", "phone", "voice call", "help desk", "helpdesk",
         "service desk", "callback", "telephone", "dial", "sim swap", "sim-swap",
         "support line", "hotline", "voicemail", "over the phone", "mfa prompt",
         "push approval", "authenticator prompt")
SMS = ("sms", "text message", "smishing", "one-time code", "one time code", "txt")
SOCIAL = ("teams", "slack", "chat", "whatsapp", "telegram", "messenger", "discord",
          "direct message", "calendar invitation", "comment on the ticket", "pull request",
          "agent", "in-app")

LEVERAGE = {
    "target_phone": ("phone", "call", "sms", "vishing", "callback", "sim"),
    "target_company": ("company", "organi", "vendor", "payroll", "ticket", "help desk"),
    "target_role": ("manager", "director", "admin", "executive", "new hire", "contractor"),
    "recovery_fact": ("recovery", "security question", "reset", "mfa", "password"),
    "domain": ("domain", "registrar", "dns", "sso", "email"),
}


def channel_for(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in PHONE):
        return "phone"
    if any(word in lowered for word in SMS):
        return "sms"
    if any(word in lowered for word in SOCIAL):
        return "social"
    return "email"


def leverage_for(text: str) -> list[str]:
    lowered = text.lower()
    found = {field for field, words in LEVERAGE.items() if any(w in lowered for w in words)}
    return sorted(found | {"target_name"})


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:70]


def pack_from(tool: dict) -> dict:
    blob = f"{tool['name']} {tool.get('description', '')}"
    stages = tool.get("stages") or []
    turns = []
    for stage in stages:
        subtitle = stage.get("subtitle", "")
        role = subtitle.split(" · ")[0].strip().lower() or "exploitation"
        success = re.sub(r"^Success measure:\s*", "", stage.get("realPurpose", "")).strip()
        turns.append({"role": role, "goal": stage.get("title", "").strip(), "success": success})
    return {
        "id": slug(tool["id"]),
        "name": tool["name"][:120],
        "channel": channel_for(blob),
        "strength": (tool.get("profile") or {}).get("strengthTier", "A"),
        "purpose": tool.get("objective", tool.get("description", "")),
        "leverage_requires": leverage_for(blob),
        "leverage_hint": (tool.get("profile") or {}).get("variable", ""),
        "control": (tool.get("profile") or {}).get("comparisonControl", ""),
        "mappings": (tool.get("profile") or {}).get("mappings", []),
        "turn_budget": len(turns),
        "category": tool.get("category", ""),
        "turns": turns,
    }


def load(bundle: Path) -> list[dict]:
    text = bundle.read_text(errors="replace")
    match = re.search(r"JSON\.parse\('(.*)'\)", text, re.S)
    if not match:
        raise SystemExit(f"no encuentro JSON.parse en {bundle}")
    return json.loads(match.group(1).replace("\\'", "'"))


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    framework, path = sys.argv[1], Path(sys.argv[2]).expanduser()
    target = OUT / framework
    target.mkdir(parents=True, exist_ok=True)
    count = 0
    seen = set()
    for tool in load(path):
        pack = pack_from(tool)
        if not pack["turns"] or pack["id"] in seen:
            continue
        seen.add(pack["id"])
        (target / f"{pack['id']}.yaml").write_text(
            yaml.safe_dump(pack, allow_unicode=True, sort_keys=False, width=100))
        count += 1
    print(f"{count} packs → {target}")


if __name__ == "__main__":
    main()
