"""HTTP educado: UA propio, límite por host, snapshot congelado en disco."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

import httpx

from andras.core import ROOT

UA = "ANDRAS/3.0 (+emulacion autorizada)"
MAX_BYTES = 400_000
DEFAULT_DELAY = 1.5

_last: dict[str, float] = {}


class FetchError(RuntimeError):
    pass


def snapshot_dir(mission_id: str) -> Path:
    path = ROOT / "data" / "snapshots" / mission_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def fetch(url: str, *, delay: float = DEFAULT_DELAY, timeout: float = 20.0,
          headers: dict | None = None, profile: dict | None = None
          ) -> tuple[str, str, str | None]:
    """Devuelve (texto, content_type, ruta_snapshot). Lanza FetchError.

    `profile` es un perfil de red (`andras.net.options`): proxy, UA y DoH.
    """
    from andras import net

    host = httpx.URL(url).host or url
    wait = _last.get(host, 0) + delay - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last[host] = time.monotonic()

    options = net.options({}, profile)
    merged = {"User-Agent": UA, **options["headers"], **(headers or {})}
    try:
        with httpx.stream("GET", url, headers=merged, proxy=options["proxy"],
                          timeout=timeout, follow_redirects=True) as resp:
            if resp.status_code >= 400:
                raise FetchError(f"HTTP {resp.status_code}")
            ctype = resp.headers.get("content-type", "")
            body = bytearray()
            for chunk in resp.iter_bytes():
                body.extend(chunk)
                if len(body) >= MAX_BYTES:
                    break
    except httpx.HTTPError as exc:
        raise FetchError(str(exc)) from exc

    text = body.decode("utf-8", "replace")
    return text, ctype, None


def save(text: str, mission_id: str, label: str) -> str:
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    safe = "".join(c if c.isalnum() or c in "-._" else "_" for c in label)[:60]
    path = snapshot_dir(mission_id) / f"{safe}-{digest}.raw"
    path.write_text(text, errors="replace")
    return str(path)


def html_to_text(html: str) -> str:
    import re

    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<(br|/p|/div|/li|/h[1-6]|/tr)[^>]*>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<[^>]+>", " ", html)
    html = re.sub(r"&nbsp;?", " ", html)
    html = re.sub(r"[ \t]+", " ", html)
    return re.sub(r"\n\s*\n+", "\n\n", html).strip()


def page_text(url: str, mission_id: str, **kwargs) -> tuple[str, str]:
    text, ctype, _ = fetch(url, **kwargs)
    if "html" in ctype:
        text = html_to_text(text)
    path = save(text, mission_id, url)
    return text[:8000], path
