# ANDRAS

Emulador de adversario para **un objetivo humano**. Recon OSINT dirigido, dossier con
procedencia, pretexto generado con técnicas de red team de LLM y entrega multicanal.
Local-first: nada sale sin una puerta humana.

Sustituye al simulador de concienciación de la v1, que sigue disponible como entrenamiento
rápido (`preview`, `send`, `serve`, `report`).

Diseño: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Instalación

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp config.example.json config.json     # edita SMTP, base_url y llm
export ANDRAS_DEEPSEEK_API_KEY='...'
.venv/bin/andras init
```

Sin clave LLM el recon funciona en modo tonto (solo patrones y registros) y el dossier cae a
agregación directa. Para no mandar el dossier fuera, usa `llm.provider: ollama`.

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
| `preview/send/serve/report` | entrenamiento v1 |

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
- `authorized_recipients` acota el entrenamiento v1; en misiones el alcance es el objetivo.
- `config.json`, `data/` y los snapshots están fuera de Git: contienen datos del objetivo.
- Usa el proyecto solo en ejercicios propios y autorizados.
