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
