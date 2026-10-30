"""Landing de entrenamiento: página, formulario opcional y eventos."""
from __future__ import annotations

import html
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from andras.core import database, load_config, load_scenario, record

STYLE = """body{font:18px system-ui;max-width:680px;margin:12vh auto;padding:24px;
background:#10131a;color:#eef}main{background:#1b2230;padding:32px;border-radius:16px}
button{padding:12px 18px;margin:12px 8px 0 0;cursor:pointer}
input{display:block;width:100%;padding:10px;margin:8px 0;border-radius:8px;border:1px solid #3a4356;
background:#0d1117;color:#eef}label{font-size:14px;color:#9aa}"""

CSP = ("default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; "
       "frame-ancestors 'none'")


def _page(title: str, body: str) -> bytes:
    return (f"<!doctype html><html lang='es'><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width'><title>{html.escape(title)}"
            f"</title><style>{STYLE}</style><main>{body}</main></html>").encode()


def handler_for(conn, capture: bool):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            token = urlparse(self.path).path.strip("/")
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
            token = urlparse(self.path).path.strip("/")
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
    conn = database(config)
    server = HTTPServer((config.get("bind_host", "127.0.0.1"), int(config.get("port", 8765))),
                        handler_for(conn, bool(config.get("capture_credentials", True))))
    print(f"ANDRAS escuchando en http://{server.server_address[0]}:{server.server_address[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido")
    finally:
        server.server_close()
        conn.close()
