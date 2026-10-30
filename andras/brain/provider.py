"""Transporte LLM multi-proveedor, compatible OpenAI.

Un solo formato de mensajes; el proveedor se elige por fase y hay failover ordenado.
DeepSeek es el valor por defecto; Ollama entra igual porque también habla /v1.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import dataclass

import httpx

from andras.core import load_config

DEFAULTS = {
    "provider": "deepseek",
    "providers": {
        "deepseek": {"base_url": "https://api.deepseek.com", "model": "deepseek-chat",
                     "api_key_env": "ANDRAS_DEEPSEEK_API_KEY", "key_prefix": "deepseek_api_key"},
        "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini",
                   "api_key_env": "ANDRAS_OPENAI_API_KEY", "key_prefix": "openai_api_key"},
        "anthropic": {"base_url": "https://api.anthropic.com/v1", "model": "claude-sonnet-4",
                      "api_key_env": "ANDRAS_ANTHROPIC_API_KEY", "key_prefix": "anthropic_api_key"},
        "ollama": {"base_url": "http://127.0.0.1:11434/v1", "model": "qwen2.5:14b",
                   "api_key_env": "ANDRAS_OLLAMA_API_KEY", "key_prefix": "", "needs_key": False},
    },
}

TRANSIENT = {408, 409, 425, 429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    pass


@dataclass(slots=True)
class Target:
    name: str
    base_url: str
    model: str
    api_key: str
    timeout: float = 180.0


def llm_config(config=None) -> dict:
    config = config or load_config()
    merged = {"provider": DEFAULTS["provider"], "providers": {}, **config.get("llm", {})}
    for name, spec in DEFAULTS["providers"].items():
        merged["providers"].setdefault(name, spec)
    for name, spec in config.get("llm", {}).get("providers", {}).items():
        merged["providers"][name] = {**DEFAULTS["providers"].get(name, {}), **spec}
    return merged


def resolve(config, phase: str = "default") -> list[Target]:
    """Lista ordenada de candidatos: la fase manda, luego el resto como failover."""
    cfg = llm_config(config)
    phase_models = cfg.get("phase_models", {})
    preferred = phase_models.get(phase, {})
    names = []
    if preferred.get("provider"):
        names.append(preferred["provider"])
    names.append(phase if phase in cfg["providers"] else cfg["provider"])
    names += [n for n in cfg["providers"] if n not in names]

    out = []
    for name in names:
        if name not in cfg["providers"]:
            continue
        spec = cfg["providers"][name]
        key = os.environ.get(spec.get("api_key_env", ""), "") or (
            config.get(spec["key_prefix"]) if spec.get("key_prefix") else "")
        if not key and spec.get("needs_key", True):
            continue
        base = (preferred.get("base_url") or spec["base_url"]).rstrip("/")
        model = (preferred.get("model") if preferred.get("provider") == name else None) \
            or spec["model"]
        out.append(Target(name=name, base_url=base, model=model, api_key=key or "ollama",
                          timeout=float(cfg.get("timeout", 180))))
    return out


def available(config, phase: str = "default") -> bool:
    return bool(resolve(config, phase))


def complete(config, messages: list[dict], *, phase: str = "default", temperature: float = 0.7,
             json_mode: bool = False, max_tokens: int = 4000) -> str:
    targets = resolve(config, phase)
    if not targets:
        raise LLMError("Ningún proveedor LLM tiene clave. Exporta ANDRAS_DEEPSEEK_API_KEY "
                       "o configura llm en config.json (ollama no necesita clave).")
    errors = []
    for target in targets:
        try:
            return _call(target, messages, temperature, json_mode, max_tokens)
        except LLMError as exc:
            errors.append(f"{target.name}: {exc}")
    raise LLMError("Todos los proveedores fallaron → " + " | ".join(errors))


def _call(target: Target, messages, temperature, json_mode, max_tokens) -> str:
    payload = {"model": target.model, "messages": messages, "temperature": temperature,
               "max_tokens": max_tokens}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {target.api_key}"}
    last = ""
    for attempt in range(3):
        try:
            resp = httpx.post(f"{target.base_url}/chat/completions", json=payload,
                              headers=headers, timeout=target.timeout)
        except httpx.HTTPError as exc:
            last = str(exc)
            time.sleep(1.5 * (attempt + 1))
            continue
        if resp.status_code in TRANSIENT:
            last = f"HTTP {resp.status_code}"
            time.sleep(1.5 * (attempt + 1))
            continue
        if resp.status_code >= 400:
            raise LLMError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            return resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"respuesta inesperada: {exc}") from exc
    raise LLMError(f"sin respuesta tras reintentos ({last})")


def complete_json(config, messages, *, phase: str = "default", temperature: float = 0.2,
                  max_tokens: int = 4000) -> dict:
    last = ""
    broken = ""
    for attempt, json_mode in enumerate((True, False, False)):
        current = messages
        if attempt == 2 and broken:
            current = messages + [
                {"role": "assistant", "content": broken[:4000]},
                {"role": "user", "content": "Ese JSON era inválido. Devuelve solo el objeto "
                                            "JSON corregido, sin explicación."}]
        try:
            raw = complete(config, current, phase=phase, temperature=temperature,
                           json_mode=json_mode, max_tokens=max_tokens)
        except LLMError as exc:
            last = str(exc)
            if attempt >= 1:
                raise
            continue
        try:
            data = json.loads(strip_fences(raw))
            if isinstance(data, dict):
                return data
            last = "el JSON no es un objeto"
        except json.JSONDecodeError:
            last = "JSON inválido"
            broken = raw
    raise LLMError(f"El modelo no devolvió JSON usable ({last})")


def complete_tools(config, messages: list[dict], tools: list[dict], *, phase: str = "agent",
                   temperature: float = 0.3, max_tokens: int = 2000) -> dict:
    """Un turno con `tools`. Devuelve el mensaje del modelo tal cual (con `tool_calls`).

    No interpreta nada: el bucle del agente decide. El failover es el mismo que en `complete`.
    """
    targets = resolve(config, phase)
    if not targets:
        raise LLMError("Ningún proveedor LLM tiene clave para el agente.")
    errors = []
    for target in targets:
        try:
            return _call_tools(target, messages, tools, temperature, max_tokens)
        except LLMError as exc:
            errors.append(f"{target.name}: {exc}")
    raise LLMError("Todos los proveedores fallaron → " + " | ".join(errors))


def _call_tools(target: Target, messages, tools, temperature, max_tokens) -> dict:
    payload = {"model": target.model, "messages": messages, "temperature": temperature,
               "max_tokens": max_tokens, "tools": tools, "tool_choice": "auto"}
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {target.api_key}"}
    last = ""
    for attempt in range(3):
        try:
            resp = httpx.post(f"{target.base_url}/chat/completions", json=payload,
                              headers=headers, timeout=target.timeout)
        except httpx.HTTPError as exc:
            last = str(exc)
            time.sleep(1.5 * (attempt + 1))
            continue
        if resp.status_code in TRANSIENT:
            last = f"HTTP {resp.status_code}"
            time.sleep(1.5 * (attempt + 1))
            continue
        if resp.status_code >= 400:
            raise LLMError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            body = resp.json()
            message = body["choices"][0]["message"]
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"respuesta inesperada: {exc}") from exc
        usage = body.get("usage", {}) or {}
        calls = []
        for call in message.get("tool_calls") or []:
            function = call.get("function", {})
            calls.append({"id": call.get("id") or secrets.token_hex(6),
                          "name": function.get("name", ""),
                          "arguments": function.get("arguments", "")})
        return {"content": message.get("content") or "",
                "reasoning": message.get("reasoning") or "",
                "tool_calls": calls, "usage": usage,
                "provider": target.name, "model": target.model}
    raise LLMError(f"sin respuesta tras reintentos ({last})")


def strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else text


COMPLETENESS = (
    "\n\nCONTRATO DE COMPLETITUD: entrega el artefacto completo, listo para usar. "
    "Nada de esquemas, resúmenes ni 'aquí tienes'. Sin preámbulo. Español impecable."
)
