# ANDRAS

Emulador de adversario para **un objetivo humano**. Recon OSINT dirigido, dossier con
procedencia, pretexto generado con técnicas de red team de LLM y entrega multicanal.
Local-first: nada sale sin una puerta humana.

Sustituye al simulador de concienciación de la v1, que sigue disponible como entrenamiento
rápido (`preview`, `send`, `serve`, `report`).

Diseño: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · Operación: [docs/OPERACION.md](docs/OPERACION.md).

## Instalación

Copia `.env.example` a `.env` y rellena lo que uses: los secretos van ahí, no en
`config.json`.

```sh
git clone https://github.com/azazelumbrae/Andras.git && cd Andras
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp config.example.json config.json     # edita SMTP, base_url y llm
export ANDRAS_DEEPSEEK_API_KEY='...'
.venv/bin/andras init
```

Sin clave LLM el recon funciona en modo tonto (solo patrones y registros) y el dossier cae a
agregación directa. Para no mandar el dossier fuera, usa `llm.provider: ollama`.

## Wizard

`andras` sin argumentos abre el wizard: entorno, modelo, campaña, objetivo. El agente
conduce el resto. Los mismos pasos existen como comandos para scripting.

```sh
andras              # wizard interactivo (Textual)
andras preflight    # semáforo del entorno sin abrir la interfaz
andras tools        # herramientas registradas del agente
```

El wizard escribe en las mismas tablas que el CLI, así que un plan creado a mano se puede
seguir en la interfaz y al contrario.

## Agente

El agente investiga y propone el plan; el humano lo revisa y confirma. Desde el wizard
(`andras`) o por terminal:

```sh
andras agent --mission <id> [--auto] [--steps 20]   # recon + plan, sin enviar
andras plan confirm <plan_id>                       # consentimiento de sus pasos
andras run start --detach                           # daemon de ejecución
andras run status|stop|pause|resume|abort <plan_id>
```

El plan confirmado autoriza los envíos de sus pasos. El gasto por encima de 0,25 USD y las
acciones administrativas siguen preguntando. Topes por defecto: 40 pasos, 300k tokens, 3 USD
y 0,001 BTC (testnet). Se cambian con `set_budget` o en `config.json`.

Avisos por escritorio y Telegram (`notify` en config): `hit` cuando cae el objetivo,
`critical` si un paso agota reintentos. El diario de la misión queda en
`data/missions/<id>/journal.md` y se exporta con `andras notes export`.

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
andras campaign run  <plan_id> --to ana@acme.com
andras critic  --mission <id>          # auditoría adversarial antes de gastar el envío
andras build   <attack_id>             # render + QA de un vector suelto
andras deliver <attack_id> --to ana@acme.com
andras debrief --mission <id>          # informe en data/reports
andras serve                           # landing y captura (terminal aparte)
```

Cada fase escribe en SQLite y la siguiente se niega a correr sin material. `deliver` y
`campaign run` piden `SEND` por cada envío salvo que exista `ANDRAS_YES=1`.

## Campaña omnicanal

`campaign plan` es el corazón del producto: el LLM recibe la meta, el gancho con su soporte y
el catálogo de packs, y devuelve una secuencia de 3 a 6 pasos con canal, pack, espera y
disparador. Los disparadores son `always`, `no_visit`, `visited`, `no_reply` y `no_submit`:
el siguiente golpe solo sale si el anterior no consiguió su objetivo, así que la campaña se
adapta sola al silencio de la víctima.

- cada paso se genera con su propio guion completo, ligado al mismo gancho y a los mismos
  artifact ids;
- `campaign show` imprime la secuencia entera antes de enviar nada;
- `campaign run --skip-wait` recorre sin esperar y `--resume` retoma donde quedó;
- si un adaptador no tiene credenciales (Twilio, SMTP) el envío se marca `failed` y la
  terminal imprime el texto y el enlace con token para mandarlo a mano.

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
| `toolbox list/show/check/run` | arsenal de ingeniería social; `run` lanza httrack, urlcrazy o eyewitness |
| `preview/send/serve/report` | entrenamiento v1 |

## Operación

Antes de una campaña real, sigue `docs/OPERACION.md`: dominio con SPF/DKIM/DMARC,
buzón IMAP, `hook_secret`, landing comprobada y perfil de red. Al terminar, exporta el
diario y quema la infraestructura.

## Evidencia

Un dato vale lo que valen sus fuentes. Cada artifact guarda URL, snapshot con hash, fecha y
confianza. Dos dominios independientes lo marcan `corroborated`; lo que solo dijo el LLM se
queda `inferred` y nunca sostiene un gancho por sí solo. Nada de "smoking guns": tres pruebas
pasivas y verificables antes que un hallazgo espectacular sin contrastar.

## Técnicas

Los frameworks de [unjail.ai](https://www.unjail.ai/how-jailbreaking-works) viven en
`prompts/packs/`, en YAML versionado: cadena de 7 turnos (reconocimiento, inteligencia de
proceso, pretexto, credibilidad, urgencia, autoridad, finisher), más Dark Psychology,
Crescendo y DRA como capas de prompt. El pack elegido se inyecta en el plan y el contrato de
completitud fuerza el artefacto entero.

## Seguridad

- El servidor escucha en local y no habilita TLS.
- Tokens opacos por campaña; el formulario guarda usuario y contraseña en SQLite.
- Los webhooks exigen HMAC-SHA256 si defines `hook_secret`; sin él se aceptan en claro.
- Las semillas de wallet viven en `data/andras.sqlite3`: laboratorio, no producción.
- `authorized_recipients` acota el entrenamiento v1; en misiones el alcance es el objetivo.
- `config.json`, `data/` y los snapshots están fuera de Git: contienen datos del objetivo.
- Usa el proyecto solo en ejercicios propios y autorizados.
