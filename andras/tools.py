"""Herramientas externas: OSINT real, SMTP y HTTP. Tolerante a fallos."""
import json
import os
import re
import smtplib
import ssl
import subprocess
import urllib.error
import urllib.request
from email.message import EmailMessage

TIMEOUT = 180


def have_toolkit(config):
    return os.access(config.get("osint_toolkit", ""), os.R_OK)


def run_tool(config, tool, args, timeout=TIMEOUT):
    """Ejecuta una herramienta del toolkit OSINT. Devuelve (ok, salida)."""
    root = config.get("osint_toolkit", "")
    binary = os.path.join(root, "bin", tool)
    if not os.access(binary, os.X_OK):
        return False, f"herramienta no disponible: {tool}"
    try:
        proc = subprocess.run(
            [binary, *args], capture_output=True, text=True, timeout=timeout, check=False,
            cwd=root, env={**os.environ, "NO_COLOR": "1"},
        )
    except subprocess.TimeoutExpired:
        return False, f"{tool}: timeout"
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, out[-8000:]


def http_get(url, headers=None, timeout=20, max_bytes=400_000):
    req = urllib.request.Request(url, headers={"User-Agent": "ANDRAS/2.0", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = resp.headers.get("Content-Type", "")
            body = resp.read(max_bytes)
            return True, ctype, body.decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return False, "http", f"{exc.code} {exc.reason}"
    except Exception as exc:  # red, DNS, TLS
        return False, "error", str(exc)


def html_to_text(html):
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<(br|/p|/div|/li|/h[1-6]|/tr)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def fetch_page(url):
    ok, ctype, body = http_get(url)
    if not ok:
        return False, body
    if "html" in ctype:
        return True, f"URL: {url}\n\n{html_to_text(body)[:6000]}"
    return True, body[:4000]


def smtp_send(config, to, subject, body, html_body=None):
    user = os.environ.get(config.get("smtp_user_env", "ANDRAS_SMTP_USER"), "")
    password = os.environ.get(config.get("smtp_password_env", "ANDRAS_SMTP_PASSWORD"), "")
    if not user or not password:
        raise SystemExit("Faltan credenciales SMTP en el entorno")
    msg = EmailMessage()
    msg["From"] = f"{config['from_name']} <{config['from_address']}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    if config["smtp_security"] == "ssl":
        smtp = smtplib.SMTP_SSL(config["smtp_host"], int(config["smtp_port"]),
                                context=ssl.create_default_context(), timeout=20)
    else:
        smtp = smtplib.SMTP(config["smtp_host"], int(config["smtp_port"]), timeout=20)
        smtp.ehlo()
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
    with smtp:
        smtp.login(user, password)
        smtp.send_message(msg)


def whois_summary(domain):
    try:
        proc = subprocess.run(["whois", domain], capture_output=True, text=True, timeout=25, check=False)
    except Exception as exc:
        return False, str(exc)
    if proc.returncode != 0:
        return False, (proc.stderr or "whois falló")[:300]
    keep = ("registrar", "creation", "created", "expiry", "registrant", "name server",
            "organization", "org", "country", "email")
    lines = [l.strip() for l in proc.stdout.splitlines()
             if l.strip() and any(k in l.lower() for k in keep)]
    return True, "\n".join(lines[:40])


def dns_records(domain):
    out = {}
    for rtype in ("MX", "TXT", "A", "NS"):
        try:
            proc = subprocess.run(["dig", "+short", rtype, domain], capture_output=True,
                                  text=True, timeout=15, check=False)
            values = [l for l in proc.stdout.splitlines() if l.strip()]
            if values:
                out[rtype] = values[:12]
        except Exception:
            continue
    return out


def duckduckgo(query, limit=8):
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    ok, _ctype, html = http_get(url)
    if not ok:
        return []
    results = []
    for block in re.findall(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL)[:limit]:
        raw_url, title = block
        title = re.sub(r"<[^>]+>", "", title).strip()
        if raw_url.startswith("//duckduckgo.com/l/?uddg="):
            raw_url = urllib.parse.unquote(raw_url.split("uddg=")[1].split("&")[0])
        results.append({"url": raw_url, "title": title})
    return results


def owned_domains(name, limit=10):
    """Dominios que contienen el nombre, vía crt.sh (Certificate Transparency)."""
    slug = re.sub(r"[^a-z0-9]", "", name.lower())
    if len(slug) < 4:
        return []
    ok, _ctype, body = http_get(f"https://crt.sh/?q=%25{slug}%25&output=json")
    if not ok:
        return []
    try:
        rows = json.loads(body)
    except json.JSONDecodeError:
        return []
    domains = {}
    for row in rows:
        for dom in str(row.get("name_value", "")).split("\n"):
            dom = dom.strip().lstrip("*.").lower()
            if slug in dom and dom.count(".") <= 2 and dom not in domains:
                domains[dom] = row.get("not_before", "")
    return sorted(domains.items(), key=lambda kv: kv[1], reverse=True)[:limit]


import urllib.parse
