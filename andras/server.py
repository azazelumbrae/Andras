"""Landing de entrenamiento, píxel de apertura y receptor de webhooks."""
from __future__ import annotations

import hashlib
import hmac
import html
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from andras.core import load_config, load_scenario, record
from andras.store import db

STYLE = """body{font:18px system-ui;max-width:680px;margin:12vh auto;padding:24px;
background:#10131a;color:#eef}main{background:#1b2230;padding:32px;border-radius:16px}
button{padding:12px 18px;margin:12px 8px 0 0;cursor:pointer}
input{display:block;width:100%;padding:10px;margin:8px 0;border-radius:8px;border:1px solid #3a4356;
background:#0d1117;color:#eef}label{font-size:14px;color:#9aa}"""

CSP = ("default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; "
       "frame-ancestors 'none'")

PIXEL = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d"
    "4944415478da63f8ffff3f0005fe02fea735d5b00000000049454e44ae426082")

HOOK_KINDS = {"visited", "submitted", "replied", "delivered", "bounced", "complained",
              "opened", "clicked"}
SAFE_KINDS = {"visited", "submitted", "reported", "continue"}


def _page(title: str, body: str) -> bytes:
    return (f"<!doctype html><html lang='es'><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width'><title>{html.escape(title)}"
            f"</title><style>{STYLE}</style><main>{body}</main></html>").encode()


def handler_for(conn, capture: bool, secret: str = ""):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            if path.startswith("/hook/"):
                return self._hook(path.split("/")[2:], parsed.query)
            if path.startswith("/px/"):
                token = path.strip("/").split("/")[1]
                if self._campaign(token):
                    record(conn, token, "opened")
                return self._raw(200, PIXEL, "image/png")
            token = path.strip("/")
            if token in {"", "thanks"}:
                return self._send(200, _page("Gracias", "<h1>Registrado</h1>"
                                             "<p>La interacción quedó anotada. Puedes cerrar."))
            row = conn.execute("SELECT scenario, attack_id FROM campaigns WHERE id=?",
                               (token,)).fetchone()
            if not row:
                return self._send(404, _page("No encontrado", "<h1>Ejercicio no encontrado</h1>"))
            record(conn, token, "visited")
            title, message, signals = self._copy(row)
            form = ""
            if capture:
                form = ("<form method='post'><label>Correo</label>"
                        "<input name='username' autocomplete='off'>"
                        "<label>Contraseña</label>"
                        "<input name='secret' type='password' autocomplete='off'>"
                        "<button name='action' value='submitted'>Entrar</button></form>")
            body = (f"<h1>{html.escape(title)}</h1><p>{html.escape(message)}</p>{form}"
                    "<h2>Señales de este ejercicio</h2><ul>"
                    + "".join(f"<li>{html.escape(s)}</li>" for s in signals)
                    + "</ul><form method='post'><button name='action' value='reported'>"
                      "Marqué el mensaje como sospechoso</button>"
                      "<button name='action' value='continue'>Continuar ejercicio</button></form>")
            self._send(200, _page(title, body))

        def _campaign(self, token: str):
            return conn.execute("SELECT id FROM campaigns WHERE id=?", (token,)).fetchone()

        def _raw(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _signed(self, body: bytes) -> bool:
            """Si hay secreto configurado, el aviso debe venir firmado con HMAC-SHA256."""
            if not secret:
                return True
            given = self.headers.get("X-Andras-Signature", "")
            expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            return hmac.compare_digest(given.strip().lower(), expected)

        def _hook(self, parts: list[str], query: str) -> None:
            if len(parts) < 2 or not parts[0] or not parts[1]:
                return self._raw(400, b"token y tipo obligatorios", "text/plain; charset=utf-8")
            token, kind = parts[0], parts[1]
            if kind not in HOOK_KINDS:
                return self._raw(400, b"tipo desconocido", "text/plain; charset=utf-8")
            if not self._campaign(token):
                return self._raw(404, b"campana inexistente", "text/plain; charset=utf-8")
            length = min(int(self.headers.get("Content-Length", "0") or 0), 65536)
            raw = self.rfile.read(length) if length else b""
            if not self._signed(raw):
                return self._raw(401, b"firma invalida", "text/plain; charset=utf-8")
            detail = ""
            if raw:
                try:
                    payload = json.loads(raw)
                    detail = str(payload.get("detail", ""))[:300]
                except (json.JSONDecodeError, AttributeError):
                    detail = raw.decode("utf-8", "replace")[:300]
            record(conn, token, kind, detail)
            self._raw(204, b"", "text/plain; charset=utf-8")

        def _copy(self, row) -> tuple[str, str, list[str]]:
            if row["attack_id"]:
                from andras.artifacts import landing
                from andras.brain import planner

                attack = planner.load(conn, row["attack_id"])
                if attack:
                    data = landing.from_payload(attack, capture=False)
                    return data["title"], data["message"], data["signals"]
            scenario = load_scenario(row["scenario"])
            return scenario["landing_title"], scenario["landing_message"], scenario["signals"]

        def do_POST(self):
            parsed = urlparse(self.path)
            path = parsed.path
            if path.startswith("/hook/"):
                return self._hook(path.split("/")[2:], parsed.query)
            token = path.strip("/")
            if not conn.execute("SELECT 1 FROM campaigns WHERE id=?", (token,)).fetchone():
                return self._send(404, _page("No encontrado", "<h1>Ejercicio no encontrado</h1>"))
            length = min(int(self.headers.get("Content-Length", "0")), 4096)
            data = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
            action = data.get("action", [""])[0]
            if action not in {"reported", "continue", "submitted"}:
                return self._send(400, _page("Error", "<h1>Acción inválida</h1>"))
            if action == "submitted":
                conn.execute("INSERT INTO credentials(campaign_id,username,secret,captured_at)"
                             " VALUES(?,?,?,datetime('now'))",
                             (token, data.get("username", [""])[0][:200],
                              data.get("secret", [""])[0][:200]))
            record(conn, token, action)
            self.send_response(303)
            self.send_header("Location", "/thanks")
            self.end_headers()

        def _send(self, code: int, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    return Handler


def serve() -> None:
    config = load_config()
    conn = db.connect(config)
    secret = config.get("hook_secret") or ""
    server = HTTPServer((config.get("bind_host", "127.0.0.1"), int(config.get("port", 8765))),
                        handler_for(conn, bool(config.get("capture_credentials", True)), secret))
    print(f"ANDRAS escuchando en http://{server.server_address[0]}:{server.server_address[1]}")
    if not secret:
        print("aviso: sin `hook_secret` los webhooks no se firman")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido")
    finally:
        server.server_close()
        conn.close()
