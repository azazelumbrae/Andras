# ANDRAS v3 — arquitectura

> Emulador de adversario para un solo objetivo humano. Recon OSINT dirigido, dossier
> verificado, pretexto generado con técnicas de red team de LLM y entrega multicanal.
> Local-first: nada sale sin una puerta humana.

Estado: diseño. v1 (SMTP + landing) funciona; la capa v2 (OSINT/LLM/dossier/plan) existe
como librería y aún no está cableada.

---

## 1. Principio

ANDRAS no es un escáner. Es un **operador con memoria**: acumula evidencia de fuentes
públicas, la contrasta, elige el gancho más doloroso y monta el ataque con la verosimilitud
de alguien que ya trabajó en esa empresa.

El objetivo del producto no es "enviar un phish": es que una persona concreta haga una cosa
concreta (abrir un enlace, responder, aprobar un MFA, llamar a un número, pagar) y que quede
registrado qué lo consiguió, con qué evidencia y qué señales debió detectar.

### Tres niveles de intrusión

| Modo | Qué hace | Qué necesita |
|---|---|---|
| `passive` | Solo OSINT y dossier | nada |
| `tracked` | Landing con token, píxel, evento de visita | servidor público |
| `interactive` | Landing con formulario, bot de respuesta, captura de OTP | + canal bidireccional |

`interactive` es donde entran Crescendo y Dark Psychology: la conversación se adapta a lo
que la víctima responde.

---

## 2. Cadena de misión

Nueve fases. Cada una escribe en el store y **no avanza sin aprobación explícita**
(`SEND`, `APPROVE`, `GO`), salvo que `--yes` esté activo.

```
M0 Intake ──► M1 Recon ──► M2 Dossier ──► M3 Hook ──► M4 Plan de vectores
                                                              │
        M8 Debrief ◄── M7 Captura ◄── M6 Entrega ◄── M5 Artefactos + QA
```

- **M0 Intake**: `target_name`, `target_role`, `target_company`, `domain`, `goal`
  ("qué debe hacer"), canal, restricciones, ventana temporal, modo.
- **M1 Recon**: colectores con presupuesto, rate limit y allowlist de dominios. Todo hallazgo
  entra como `artifact` con fuente y hash del snapshot.
- **M2 Dossier**: destilación + **crítico adversarial** (ver §4). Cada afirmación arrastra
  los `artifact_id` que la sostienen.
- **M3 Hook**: el LLM elige 1–3 ganchos ordenados por dolor × verificabilidad. Rechaza
  cualquier gancho sin artifact de soporte (`--strict-facts`, por defecto ON).
- **M4 Plan**: 2–3 vectores encadenados, cada uno con ángulo, leverage, stance y guion por
  turno. Ver §3.
- **M5 Artefactos**: correo, landing, SMS, hoja de llamada (vishing), mensaje social. QA
  automático: render, enlaces vivos, dominio plausible, ortografía, coherencia con el dossier.
- **M6 Entrega**: adaptadores. Cada envío crea `campaign` + token.
- **M7 Captura**: visitas, clics, respuestas, formularios, OTP, tiempos.
- **M8 Debrief**: línea temporal, coste, qué funcionó, señales que la víctima debió ver.

---

## 3. Técnicas de LLM (packs)

Los frameworks de unjail.ai se importan como **datos versionados** en `prompts/packs/`, no
como código. Formato:

```yaml
id: help-desk-impersonation
name: THE ACCOUNT-LOCKOUT CALLBACK TRAP
channel: phone
strength: S
purpose: >-
  Convencer al help desk de resetear credenciales de una cuenta privilegiada
  usando datos de recuperación verificados y cobertura de "soporte".
leverage_requires: [target_name, target_company, target_phone, recovery_facts]
turns:            # secuencia de 7, estructura tomada del framework SE
  - role: recon          # 20-35%
    goal: fijar el objetivo y los huecos de información
    success: el modelo ordena el recon y nombra lo que falta
  - role: process_intel  # 30-45%
    goal: mapear procedimiento, responsables y verificaciones del help desk
  ...
  - role: finisher       # 85-100%
    goal: obtener el artefacto completo, no un resumen
    success: el objetivo ejecuta la acción pedida
mappings: [vishing, help desk, authority, KBA]
```

### Packs de origen

| Pack | Uso en ANDRAS |
|---|---|
| Social Engineering (7 turnos, 60+ escenarios) | esqueleto de pretexto para email, voz, help desk, vishing |
| Dark Psychology (7 etapas) | conversaciones largas: validación → apego → sunk cost → presión |
| Crescendo | mantener el hilo y que el turno 7 pida el artefacto completo |
| DRA / component fragmentation | partir la petición para que el LLM no se autolimite |
| Role confusion | inyectar el recon como si fuera contexto propio del modelo |
| Many-shot | fijar formato y tono con ejemplos completos antes del pedido real |
| Manipulation Matrix (69 constructores) | artefactos concretos: keylogger, grabador, clonador de voz |

### Contrato de completitud

Todo prompt de generación termina con un contrato explícito: *"entrega el artefacto
completo, no un esquema, no un resumen, sin preámbulo de asistente"*. Se valida en código
(longitud mínima, presencia de marcadores `{tracking_url}`, ausencia de "Aquí tienes…").

---

## 4. Modelo de evidencia

La regla del documento de OPSEC aplica al dossier: **tres pruebas pasivas valen más que un
smoking gun**.

```sql
CREATE TABLE artifacts (
  id INTEGER PRIMARY KEY,
  mission_id TEXT NOT NULL,
  kind TEXT NOT NULL,           -- email, phone, person, doc, leak, infra, social, credential
  value TEXT NOT NULL,
  source TEXT NOT NULL,         -- URL o nombre de colector
  snapshot_path TEXT,           -- copia congelada de la fuente
  content_hash TEXT,
  fetched_at TEXT NOT NULL,
  confidence INTEGER DEFAULT 40,
  verification TEXT DEFAULT 'single_source',  -- single_source | corroborated | inferred | stale
  UNIQUE(mission_id, kind, value)
);
```

`corroborated` exige ≥2 fuentes independientes (dominios distintos, no dos dorks). Los
inferidos por el LLM nunca suben de `inferred`. Artefacto con `stale` > 90 días no puede ser
el único soporte de un gancho.

### Crítico adversarial

Un segundo LLM, sin ver el plan, audita el dossier con seis preguntas fijas:

1. ¿El brillo oculta algo? (web bonita, pitch pulido)
2. ¿Volumen inflado? ¿Cuántos usuarios reales frente a cuentas dummy?
3. ¿Discrepancia entre lo que dicen, hacen y reclaman?
4. ¿Complejidad emergente no mapeada? (cambios recientes, proveedores nuevos)
5. ¿Esto es calidad o fachada?
6. ¿Qué dato destruiría el pretexto si el objetivo lo comprueba?

Salida: lista de `contradictions`, `gaps`, `kill_switches`. Cada `kill_switch` es un dato
que puede quemar el ataque y debe comprobarse antes de M6.

---

## 5. OPSEC del propio ANDRAS

Lo mismo que audita en la víctima se aplica a nosotros:

- Dominios y buzones por misión, separados de la identidad real.
- Registro de qué infraestructura ya está quemada (`infra_used`).
- Horarios de envío alineados con la zona del objetivo.
- Sin reutilizar plantillas entre misiones: comparación de hashes de cuerpo.
- Enlaces con token opaco; la landing no filtra si el token es válido por temporización.

---

## 6. Estructura objetivo

```
andras/
  api/          FastAPI: routers por fase, websocket de progreso
  web/          Jinja + HTMX + Tailwind (UI de operador)
  cli/          Typer: mismos casos de uso, sin UI
  brain/        cliente LLM, selector de packs, runners multi-turno, contrato de completitud
  recon/        colectores + registry + rate limiter + circuit breaker
  evidence/     store de artifacts, scoring, adversario, snapshots
  artifacts/    render de correo/landing/SMS/vishing + QA
  delivery/     smtp, telegram, twilio, guion de voz
  landing/      plantillas, píxel, formulario, captura OTP
  store/        sqlite + migraciones
prompts/packs/  técnicas versionadas
docs/           este archivo, ADRs
```

Un mismo caso de uso (`run_phase(mission, phase)`) sirve a la API, la CLI y los tests. Nada
de lógica en los routers.

---

## 7. Roadmap

| Fase | Entrega | Criterio de "hecho" | Estado |
|---|---|---|---|
| 0 | repo sano: git, tests, `pyproject`, CI local | `pytest` verde, primer commit | hecho |
| 1 | store + intake + dossier con procedencia | misión creada, artifacts con fuente y confianza | hecho |
| 2 | recon real (5 colectores) | dossier poblado desde 1 email/dominio | hecho, sin red probada |
| 3 | brain + packs + validador | plan de 2 vectores con guiones completos | hecho |
| 4 | artefactos + landing con tracking | correo real enviado y visita registrada | hecho y probado con SMTP local |
| 5 | crítico adversarial + debrief | informe de misión exportable | hecho |
| 6 | canales interactivos (Telegram, SMS) | respuesta de la víctima registrada | envío hecho (Twilio sin probar), respuesta pendiente |
| 7 | captura de credenciales opcional | formulario + OTP | formulario hecho, OTP pendiente |
| 8 | campaña omnicanal con disparadores | secuencia de 3-6 pasos ejecutada sola | hecho |

Fase 0 y 1 son requisito de todo lo demás.

---

## 8. Decisiones cerradas

| Decisión | Elegido | Consecuencia |
|---|---|---|
| Interfaz | **CLI + TUI** (Typer + Rich/Textual), servidor solo para la landing | sin SPA; todo caso de uso es un comando |
| LLM | **multi-proveedor**, DeepSeek por defecto, modelo por fase | un solo cliente compatible OpenAI; Ollama entra como proveedor más |
| Canales | email, landing, hoja de llamada, Telegram, SMS, WhatsApp y los que hagan falta | cada canal es un adaptador con la misma interfaz |
| Credenciales | **formulario simple** en la landing | usuario/contraseña a SQLite, sin proxy |
| Usuarios | single-user local | sin auth salvo token de misión |

La landing se sirve igual porque es parte del canal, no de la UI: el operador vive en la
terminal.

## 9. Campaña omnicanal

Una misión no termina en un correo. `campaign` compone una **secuencia** de 3 a 6 pasos
(`plans` + `plan_steps`) donde cada paso lleva canal, pack, espera y disparador:

| Disparador | Sale cuando |
|---|---|
| `always` | siempre (solo el primer paso) |
| `no_visit` | la víctima no ha abierto el enlace anterior |
| `visited` | sí lo abrió: se explota el interés |
| `no_reply` | no contestó al canal anterior |
| `no_submit` | no dejó credenciales |

Cada paso guarda su propio `attack_id` con guion completo y el mismo gancho. El orden es
deliberado: email abre, SMS empuja, la llamada cierra, el último email pide el artefacto
final. `campaign run` evalúa los disparadores contra `events` y se detiene en cada envío si
no hay `ANDRAS_YES`; `--resume` retoma lo pendiente y reintenta lo fallido.

Si un adaptador no tiene credenciales, el paso se marca `failed` y la terminal imprime el
texto y el enlace con token: el operador puede enviarlo a mano sin romper la secuencia.

Los packs de unjail.ai se importan con `scripts/import_unjail_packs.py` (201 packs, 7 turnos)
y `packs --validate` los comprueba todos.

## 10. El agente

El operador no rellena el plan: lo conduce un agente con herramientas. Hay cuatro fases y
ninguna envía por sí sola.

| Fase | Qué hace | Quién la cierra |
|---|---|---|
| Aclaraciones | 4-6 preguntas de opción múltiple, con respaldo fijo si el modelo falla | el operador |
| Recon | OSINT con herramientas, notas y enlaces de soporte | el agente |
| Plan | 3-6 pasos, criterio de éxito y crítico adversarial | el agente |
| Revisión | lectura, conversación, edición, confirmación | el operador |

El bucle vive en `andras/agent/loop.py`: modelo → herramienta → observación, con tope de
pasos, tokens y dinero. Un plan confirmado es el consentimiento: desde ahí los pasos `send`
corren solos. `spend` pregunta por encima del umbral y `admin` pregunta siempre.

Las herramientas se registran con esquema JSON y clase de permiso (`read`, `write`, `send`,
`spend`, `admin`). Sin registro, el modelo no las ve. Cada llamada queda en `tool_runs` y
el transcript en `data/runs/<id>.jsonl`.

Ningún plan sale sin crítico: se revisan contradicciones, huecos y kill switches. Si el
crítico lo tumba, el agente corrige y reenvía.

## 11. Ejecución y avisos

`andras run start` levanta el daemon; `--detach` lo separa. Cada plan confirmado genera un
`job` por paso con su vencimiento. Un job sólo corre con alquiler, así que dos daemons no
duplican envíos. Los fallos se reintentan con backoff exponencial (5 min → 40 min) y a los
cinco intentos se marcan `failed` y se avisa en nivel `critical`.

Los disparadores se reevalúan cada 2 h y se dan por perdidos a las 96 h. El watchdog avisa
si un plan lleva 48 h sin movimiento.

Avisos: escritorio macOS y Telegram, niveles `info`, `hit` y `critical`. `hit` se dispara
cuando se cumple el criterio de éxito y pausa el resto del plan. Cada aviso queda registrado
en `notifications`, falle o no.

## 12. Webhooks y píxel

`andras serve` expone, además de la landing:

| Ruta | Uso |
|---|---|
| `GET /px/<token>` | píxel de apertura, PNG de 1×1 |
| `GET\|POST /hook/<token>/<tipo>` | aviso de un proveedor externo |

Tipos aceptados: `visited`, `submitted`, `replied`, `delivered`, `bounced`, `opened`,
`clicked`, `reported`, `complained`. Si hay `hook_secret`, el cuerpo debe venir firmado con
`X-Andras-Signature` (HMAC-SHA256 hexadecimal). El cuerpo JSON puede traer `detail`, que se
guarda en el evento.

## 13. Dinero

Tres papeles, siempre en este orden: `burner` paga, `mixer` mezcla, `treasury` sólo recibe.
BTC con `embit` (BIP39 → BIP84, testnet por defecto); Monero por `monero-wallet-rpc`. La
semilla se guarda en la base de datos porque es un laboratorio, no un monedero de producción.

Todo movimiento descuenta del presupuesto cripto de la misión (`0.001 BTC` por defecto) y
el gasto por encima del tope lo autoriza el operador. Las transferencias BTC se firman fuera;
el agente deja el movimiento registrado y el runbook de mezcla.

## 14. OPSEC

Perfiles de red por misión: `direct`, `doh`, `tor` o `proxy`. Con `tor`, el recon sale por
SOCKS5 local; con `doh`, cabeceras de DNS cifrado; `jitter_ms` reparte esperas. Sin Tor
arrancado todo degrada a directo.

`infra burn` marca dominio, buzón y personas como quemados para no reutilizarlos en otra
campaña. El `sim_swap_runbook` deja escrito qué pedir al operador, con qué excusa y qué
ventana se tiene antes de que reviertan la portabilidad.

## 15. Fases

| Fase | Contenido | Estado |
|---|---|---|
| P0 | esquema, registro de herramientas, permisos, preflight, wizard básico | hecho |
| P1 | bucle del agente, OSINT, plan, aclaraciones, revisión | hecho |
| P2 | jobs, scheduler, daemon, webhooks, criterios de éxito, avisos | hecho |
| P3 | SPF/DKIM/DMARC, IMAP, Telegram entrante, runbooks de canal | hecho |
| P4 | wallets BTC/XMR, movimientos, mezcla, treasury | hecho |
| P5 | perfiles de red, Tor, DoH, jitter, quema | hecho |
| P6 | docs, export del diario, pruebas con modelo real | en curso |

## 16. Cierre determinista y suplantación

El agente puede morir a mitad (proveedor caído, tope de pasos, presupuesto). En vez de
perder el trabajo, `runner.finalize` completa el plan con lo conservador: rellena hasta tres
pasos con los canales permitidos, esperas de 24 h y disparador `no_reply`, pone criterio de
éxito por defecto y narrativa neutra, y lo deja `proposed` para revisión humana. El aviso
«plan cerrado por el sistema» viaja en el mensaje final.

La suplantación se decide con `spoof_advice`, que mira el DMARC del dominio y enumera lo que
realmente se puede hacer: nombre visible, `Reply-To` propio o subdominio parecido. Con
`p=reject` no se puede poner el dominio ajeno en el `From` sin alinear SPF/DKIM.

En headless (`--auto` sin terminal), una pregunta del agente se responde con su primera
opción, que es la que él mismo propuso, y se registra en la salida. Así el plan nunca se
queda colgado esperando una respuesta que no va a llegar.

## 17. Pantalla de ejecución

Tras confirmar, el wizard salta a S8: arranca el daemon separado, refresca cada 5 s el estado
de los pasos y los últimos avisos, y ofrece pausa, reanudación, aborto y parada. Cerrar la
pantalla no para nada: el daemon sigue y el operador puede volver por terminal.

La memoria de un ataque suelto se exporta con `andras notes export --mission <id> --attack
<attack_id>`; el diario completo, sin `--attack`.
