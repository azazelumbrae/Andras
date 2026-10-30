"""Cliente LLM compatible con OpenAI (DeepSeek por defecto). Solo stdlib."""
import json
import os
import urllib.error
import urllib.request

DEFAULTS = {
    "deepseek_base_url": "https://api.deepseek.com",
    "deepseek_model": "deepseek-chat",
}


class LLMError(SystemExit):
    pass


def credentials(config):
    base = os.environ.get(config.get("deepseek_base_url_env", "ANDRAS_DEEPSEEK_BASE_URL")) \
        or config.get("deepseek_base_url") or DEFAULTS["deepseek_base_url"]
    key = os.environ.get(config.get("deepseek_api_key_env", "ANDRAS_DEEPSEEK_API_KEY")) \
        or config.get("deepseek_api_key")
    model = os.environ.get(config.get("deepseek_model_env", "ANDRAS_DEEPSEEK_MODEL")) \
        or config.get("deepseek_model") or DEFAULTS["deepseek_model"]
    if not key:
        raise LLMError(
            "Falta la clave LLM. Exporta ANDRAS_DEEPSEEK_API_KEY o rellena deepseek_api_key en config.json"
        )
    return base.rstrip("/"), key, model


def chat(config, messages, temperature=0.7, json_mode=False, max_tokens=4000):
    base, key, model = credentials(config)
    payload = {"model": model, "messages": messages, "temperature": temperature,
               "max_tokens": max_tokens}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:400]
        raise LLMError(f"LLM HTTP {exc.code}: {body}")
    except urllib.error.URLError as exc:
        raise LLMError(f"No se pudo contactar el LLM ({base}): {exc.reason}")
    return data["choices"][0]["message"]["content"]


def chat_json(config, messages, temperature=0.2):
    """Devuelve JSON parseado; reintenta una vez sin modo json si el modelo no lo respeta."""
    for attempt in (0, 1):
        try:
            raw = chat(config, messages, temperature=temperature, json_mode=attempt == 0)
        except LLMError:
            if attempt == 1:
                raise
            continue
        try:
            return json.loads(strip_fences(raw))
        except json.JSONDecodeError:
            if attempt == 1:
                raise LLMError(f"El LLM no devolvió JSON válido: {raw[:300]}")
    raise LLMError("JSON no disponible")


def strip_fences(text):
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start:end + 1]
    return text


def available(config):
    try:
        credentials(config)
        return True
    except LLMError:
        return False
