import html
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from .core import database, load_config, record


def handler_for(conn):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            token = urlparse(self.path).path.strip("/")
            row = conn.execute("SELECT scenario FROM campaigns WHERE id=?", (token,)).fetchone()
            if not row:
                self.send_error(404, "Ejercicio no encontrado")
                return
            scenario = load_scenario(row[0])
            record(conn, token, "visited")
            page = f"""<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{html.escape(scenario['landing_title'])}</title>
            <style>body{{font:18px system-ui;max-width:680px;margin:12vh auto;padding:24px;background:#10131a;color:#eef}}main{{background:#1b2230;padding:32px;border-radius:16px}}button{{padding:12px 18px;margin:12px 8px 0 0;cursor:pointer}}</style>
            <main><h1>{html.escape(scenario['landing_title'])}</h1><p>{html.escape(scenario['landing_message'])}</p><h2>Señales de este ejercicio</h2><ul>{''.join('<li>'+html.escape(s)+'</li>' for s in scenario['signals'])}</ul><form method="post"><button name="action" value="reported">Marqué el mensaje como sospechoso</button><button name="action" value="continue">Continuar ejercicio</button></form></main></html>"""
            body = page.encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body))); self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.send_header("X-Content-Type-Options", "nosniff"); self.end_headers(); self.wfile.write(body)

        def do_POST(self):
            token = urlparse(self.path).path.strip("/")
            row = conn.execute("SELECT 1 FROM campaigns WHERE id=?", (token,)).fetchone()
            if not row:
                self.send_error(404); return
            size = min(int(self.headers.get("Content-Length", "0")), 1024)
            action = parse_qs(self.rfile.read(size).decode("utf-8", "replace")).get("action", [""])[0]
            if action not in {"reported", "continue"}:
                self.send_error(400); return
            record(conn, token, action)
            self.send_response(303); self.send_header("Location", "/thanks"); self.end_headers()

        def log_message(self, *_args):
            pass
    return Handler


def serve():
    config = load_config(); conn = database(config)
    server = HTTPServer((config.get("bind_host", "127.0.0.1"), int(config.get("port", 8765))), handler_for(conn))
    print(f"ANDRAS escuchando en http://{server.server_address[0]}:{server.server_address[1]} (Ctrl+C para salir)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido")
    finally:
        server.server_close(); conn.close()
