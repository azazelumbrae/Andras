<p align="center">
  <img src="assets/hero.jpg" alt="ANDRAS, señor de la discordia" width="100%">
</p>

<h1 align="center">ANDRAS</h1>

<p align="center">
  <em>El señor de la discordia, pero con evidencia.</em><br>
  Emulación de adversario contra <strong>un objetivo humano</strong>, conducida por un agente LLM.
</p>

<p align="center">
  <a href="https://github.com/azazelumbrae/Andras/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/azazelumbrae/Andras/actions/workflows/ci.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="Licencia: GPL-3.0-or-later" src="https://img.shields.io/badge/licencia-GPL--3.0--or--later-blue.svg"></a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-3776ab.svg">
  <img alt="Local-first" src="https://img.shields.io/badge/local--first-s%C3%AD-2ea44f.svg">
  <img alt="Estado: alfa" src="https://img.shields.io/badge/estado-alfa-orange.svg">
</p>

<p align="center">
  <a href="#instalación">Instalación</a> ·
  <a href="#cómo-funciona">Cómo funciona</a> ·
  <a href="#ciclo-de-una-misión">Ciclo de una misión</a> ·
  <a href="docs/OPERACION.md">Operación</a> ·
  <a href="docs/ARCHITECTURE.md">Diseño</a>
</p>

---

ANDRAS no dispara correos a una lista. Investiga **a una persona concreta**, reúne pruebas con
procedencia, propone por dónde entrar y redacta la secuencia que más duele. Tú revisas, confirmas
y él ejecuta. Todo local: los datos del objetivo no salen de tu máquina y nada se envía sin una
puerta humana delante.

> **Local-first por diseño.** SQLite en disco, evidencias con hash, wallets en testnet, sin SaaS
> de por medio. Si usas Ollama, ni el dossier sale de casa.

## Por qué existe

El phishing de manual falla por dos motivos: el gancho es genérico y el operador no sabe qué
sostiene cada afirmación. ANDRAS ataca ambos.

- **Evidencia antes que adjetivos.** Cada dato guarda URL, snapshot, fecha y confianza. Dos
  dominios independientes lo suben a `corroborated`; lo que solo dijo el LLM queda `inferred` y
  nunca aguanta un gancho por sí solo.
- **Un plan que se lee antes de gastar el envío.** La secuencia completa, con canal, espera y
  disparador, se imprime y se confirma. El consentimiento es del plan, no del primer correo.
- **Adaptación al silencio.** Si la víctima no abre, no visita o no rellena, el siguiente golpe
  cambia de canal en vez de repetir el mismo tiro.
- **Límites escritos.** Topes de pasos, tokens, dinero y BTC. Cada herramienta del arsenal declara
  qué le impide correr aquí en vez de fingir que vale.

## Instalación

Requisitos: Python 3.11+, macOS o Linux. Sin clave LLM funciona en modo tonto (patrones y
registros); con Ollama no sale nada del equipo.

```sh
git clone https://github.com/azazelumbrae/Andras.git && cd Andras
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'      # añade '.[tui]' para la interfaz
cp .env.example .env                   # secretos aquí, nunca en config.json
cp config.example.json config.json     # edita SMTP, base_url y llm
.venv/bin/andras init
.venv/bin/andras preflight             # semáforo del entorno
```

```sh
.venv/bin/andras                       # wizard (Textual): entorno, modelo, campaña, objetivo
```

El wizard escribe en las mismas tablas que el CLI: un plan creado a mano se sigue en la interfaz
y al contrario. Los mismos pasos existen como comandos para scripting.

## Cómo funciona

```
recon ──▶ dossier ──▶ ganchos ──▶ plan ──▶ revisión humana ──▶ ejecución ──▶ debrief
  │           │           │         │            │                 │
 OSINT     procedencia  dolor ×   canales +   tú confirmas    avisos + diario
 + triaje  por artifact  prueba   disparadores  el plan        + límites
```

1. **Recon** lanza colectores OSINT dirigidos y hace triaje de lo que encuentra.
2. **Dossier** destila el material y asigna un `artifact_id` a cada afirmación.
3. **Ganchos** se ordenan por dolor × verificabilidad, no por lo llamativos que suenan.
4. **Plan** convierte el gancho elegido en una secuencia de 3 a 6 pasos.
5. **Revisión** la imprimes entera y confirmas.
6. **Ejecución** sale por el daemon con presupuesto, reintentos y avisos.
7. **Debrief** deja el informe y el diario exportable.

Cada fase escribe en SQLite y la siguiente se niega a correr sin material.

## Ciclo de una misión

```sh
andras mission new --name "Ana Pérez" --role CFO --company Acme --domain acme.com \
                   --goal "que abra el enlace y meta credenciales" --mode tracked
andras recon   --mission <id>          # OSINT + triaje, con presupuesto
andras dossier --mission <id>          # destila y anota procedencia
andras hooks   --mission <id>          # propone ganchos y los puntúa
andras hook-choose 2 --mission <id>
andras campaign plan --mission <id> --channels email,sms,phone --length 4
andras campaign show <plan_id>         # revisa la secuencia completa
andras plan confirm <plan_id>          # consentimiento de sus pasos
andras campaign run  <plan_id> --to ana@acme.com
andras critic  --mission <id>          # auditoría adversarial antes de gastar el envío
andras build   <attack_id>             # render + QA de un vector suelto
andras deliver <attack_id> --to ana@acme.com
andras debrief --mission <id>          # informe en data/reports
andras serve                           # landing, píxel y captura (terminal aparte)
```

`deliver` y `campaign run` piden `SEND` por cada envío salvo que exista `ANDRAS_YES=1`.

## Agente

El agente investiga y propone; el humano decide. Puedes conducirlo desde el wizard o por
terminal:

```sh
andras agent --mission <id> [--auto] [--steps 20]   # recon + plan, sin enviar
andras plan confirm <plan_id>                       # autoriza los envíos de sus pasos
andras run start --detach                           # daemon de ejecución
andras run status|stop|pause|resume|abort <plan_id>
```

Permisos por clase de acción:

| Clase | Ejemplos | Cuándo pregunta |
|---|---|---|
| `read` / `write` | recon, notas, dossier | nunca |
| `send` | correo, SMS, Telegram | sin plan confirmado |
| `spend` | dominios, wallet | por encima de 0,25 USD |
| `admin` | DNS, quema de infraestructura | siempre |

Topes por defecto: **40 pasos**, **300k tokens**, **3 USD**, **0,001 BTC** en testnet.

Avisos por escritorio y Telegram (`notify`): `hit` cuando cae el objetivo, `critical` si un paso
agota reintentos. El diario queda en `data/missions/<id>/journal.md` y se exporta con
`andras notes export`.

## Campaña omnicanal

`campaign plan` es el corazón del producto. El LLM recibe la meta, el gancho con su soporte y el
catálogo de packs, y devuelve una secuencia con canal, pack, espera y disparador. Los disparadores
—`always`, `no_visit`, `visited`, `no_reply`, `no_submit`— sólo dejan salir el siguiente golpe si
el anterior falló, así que la campaña se adapta sola.

- cada paso se genera con su guion completo, ligado al mismo gancho y a los mismos artifact ids;
- `campaign show` imprime la secuencia entera antes de enviar nada;
- `campaign run --skip-wait` recorre sin esperar y `--resume` retoma donde quedó;
- si un adaptador no tiene credenciales, el envío se marca `failed` y la terminal imprime el texto
  y el enlace con token para mandarlo a mano.

## Arsenal

`andras/toolbox.py` cataloga 24 herramientas de ingeniería social por función —clonado, proxy,
red, marca, captura, payload— con ficha, instalación, uso y límite real. El agente las consulta
antes de prometer un paso.

```sh
andras toolbox list --category clonado
andras toolbox show httrack
andras toolbox check                   # qué falta y cómo se instala
andras toolbox run httrack https://portal.acme.com
```

Sólo la lista blanca se ejecuta desde ANDRAS: `httrack`, `urlcrazy` y `eyewitness`. El resto se
consulta, porque muchas piden Linux, root o estar en la misma red que el objetivo. `urlcrazy` va
vendorizado en `vendor/urlcrazy` con su lanzador: ya no está en rubygems.

## Comandos

| Comando | Qué hace |
|---|---|
| `mission new/list/show/status` | ciclo de vida de la misión |
| `recon` | colectores OSINT + triaje de páginas |
| `dossier` | dossier estructurado con `artifact_id` por afirmación |
| `hooks` / `hook-choose` | ganchos ordenados por dolor × verificabilidad |
| `plan` | vectores sueltos de un canal |
| `campaign plan/show/run` | secuencia omnicanal con disparadores |
| `critic` | contradicciones, huecos y datos asesinos |
| `build` | render por canal y control de calidad |
| `deliver` | envío real y registro |
| `debrief` | informe de misión en markdown |
| `packs --validate` | comprobar los packs de técnicas |
| `tui` | interfaz de terminal |
| `agent` | recon y plan conducidos por el agente |
| `plan confirm/list` | confirmar el consentimiento o listar planes |
| `run start/stop/status/pause/resume/abort` | daemon de ejecución |
| `bot` | contesta por Telegram con el guion de la campaña |
| `notes add/list/search/export` | diario de la campaña (`--attack` para un vector) |
| `wallet new/list` | burner, mixer y treasury |
| `net show/set/burn` | perfiles de red y quema de infraestructura |
| `channels audit/dkim` | SPF/DKIM/DMARC del dominio de envío |
| `toolbox list/show/check/run` | arsenal de ingeniería social |
| `preview/send/serve/report` | entrenamiento del simulador v1 |

## Técnicas

Los frameworks de [unjail.ai](https://www.unjail.ai/how-jailbreaking-works) viven en
`prompts/packs/`, en YAML versionado: cadena de 7 turnos —reconocimiento, inteligencia de proceso,
pretexto, credibilidad, urgencia, autoridad, finisher— más Dark Psychology, Crescendo y DRA como
capas de prompt. El pack elegido se inyecta en el plan y el contrato de completitud fuerza el
artefacto entero.

## Evidencia

Un dato vale lo que valen sus fuentes. Nada de *smoking guns*: tres pruebas pasivas y verificables
antes que un hallazgo espectacular sin contrastar. El dossier dice de dónde sale cada frase y con
cuánta confianza, y el crítico señala lo que se contradice antes de que lo haga la víctima.

## Seguridad y OPSEC

- El servidor escucha en local y no habilita TLS: ponlo detrás de tu túnel.
- Tokens opacos por campaña; el formulario guarda usuario y contraseña en SQLite.
- Los webhooks exigen HMAC-SHA256 si defines `hook_secret`; sin él se aceptan en claro.
- Las semillas de wallet viven en `data/andras.sqlite3`: laboratorio, no producción.
- `config.json`, `.env`, `data/` y los snapshots están fuera de Git: llevan datos del objetivo.
- `authorized_recipients` acota el entrenamiento v1; en misiones el alcance es el objetivo.

Antes de una campaña real, sigue [docs/OPERACION.md](docs/OPERACION.md): dominio con
SPF/DKIM/DMARC, buzón IMAP, `hook_secret`, landing comprobada y perfil de red. Al terminar, exporta
el diario y quema la infraestructura. Diseño interno en [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Estado

Proyecto en alfa, funcional de punta a punta en laboratorio. Lo que todavía cojea está escrito en
[docs/DEPRECATED.md](docs/DEPRECATED.md) y en las fichas del arsenal: sin credenciales Twilio,
SMS y WhatsApp degradan a texto manual; sin dominio e IMAP no hay SPF/DKIM real ni detección de
respuesta; sin `monero-wallet-rpc`, el swap y la mezcla de XMR quedan en runbook.

## Licencia

GPL-3.0-or-later. Ver [LICENSE](LICENSE).

<p align="center"><sub>Úsalo sólo en ejercicios propios y autorizados.</sub></p>
