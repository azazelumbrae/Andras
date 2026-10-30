# Operación de una campaña

Lista de lo que hay que tener listo **antes** de dejar que el agente investigue y antes de
confirmar un plan. Nada de esto lo hace la app por ti: el agente propone y avisa, el operador
decide.

## 1. Antes de empezar

- [ ] `andras preflight` sin `FAIL`. Los `WARN` se leen, no se ignoran.
- [ ] Dominio de envío propio con zona DNS: MX, SPF `-all`, DMARC `p=reject` y DKIM.
      `andras channels audit <dominio>` y `andras channels dkim <dominio>` dan el TXT.
- [ ] Buzón real que reciba respuestas y credenciales IMAP en el entorno
      (`ANDRAS_IMAP_USER`, `ANDRAS_IMAP_PASSWORD`). Sin esto, `replied` no se detecta.
- [ ] `hook_secret` definido: los webhooks sin firma se pueden falsear.
- [ ] `andras serve` accesible desde fuera si la landing va a usarse de verdad.
- [ ] SearXNG levantado (`scripts/dev_searxng.sh`) y `searxng_url` en `config.json`.
- [ ] Perfil de red decidido: `andras net show`. Para OSINT sensible, `tor`.

## 2. Durante el recon

- [ ] El agente pregunta con `ask_operator`; responde con datos, no con “lo que veas”.
- [ ] Cada afirmación del dossier debe tener dos fuentes. Sólo LLM = `inferred`.
- [ ] Comprueba el canal antes de aceptarlo: correo con MX, teléfono con formato, cuenta viva.
- [ ] `landing_check <url>` antes de meter el enlace en el plan.
- [ ] `spoof_advice <dominio>` si vas a usar un nombre visible ajeno.

## 3. Revisión del plan

- [ ] 3 a 6 pasos, con canal distinto al anterior y esperas realistas.
- [ ] Criterio de éxito concreto (`credential_captured` o `event`), no “que pique”.
- [ ] Cada paso dice qué consigue y con qué soporte del dossier.
- [ ] Si el agente cerró el plan por su cuenta (“cerrado por el sistema”), revisa los pasos
      añadidos: son conservadores, no creativos.
- [ ] `andras plan confirm <id>` = consentimiento para **todos** sus envíos.

## 4. Ejecución

- [ ] `andras run start --detach` con el operador delante las primeras horas.
- [ ] `andras notifications` para ver entregas y fallos.
- [ ] `andras run pause <id>` si hay que congelar; `abort` si se rompe el pretexto.
- [ ] Los `failed` con reintentos pendientes se recuperan solos; a los cinco, aviso
      `critical` y decisión humana.

## 5. Cierre

- [ ] `andras notes export --mission <id>`: el diario queda en HTML para el informe.
- [ ] `andras debrief --mission <id>`.
- [ ] `andras net burn --mission <id>`: dominio, buzón y personas no se reutilizan.
- [ ] Revisa `wallet_txs`: todo movimiento anotado, nada fuera del presupuesto.
- [ ] Si se usó SIM, anota la ventana y la fecha de reversión posible del duplicado.

## Límites conocidos

- Las transferencias BTC se firman fuera; la app sólo prepara y registra.
- Monero necesita `monero-wallet-rpc` local.
- Sin Twilio, SMS y WhatsApp quedan `failed` con el texto para enviar a mano.
- El SPF/DKIM sólo protege el dominio del atacante: no convierte un `From` ajeno en legítimo.
