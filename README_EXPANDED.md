# ANDRAS — notas de expansión

La v1 era un simulador de concienciación por SMTP. La v3 lo convierte en emulador de
adversario completo: OSINT real, dossier con procedencia, ganchos puntuados, planes
multi-turno y entrega multicanal.

El detalle operativo está en `README.md`; el diseño y las decisiones, en
`docs/ARCHITECTURE.md`. La correspondencia con los módulos antiguos está en
`docs/DEPRECATED.md`.

Estado actual:

- [x] store con migraciones, misiones, artifacts, ganchos, ataques, entregas
- [x] confianza y corroboración por dominios independientes
- [x] proveedor LLM multi-proveedor con failover y modelo por fase
- [x] packs de técnicas en YAML y validador
- [x] colectores: dorks, crt.sh, DNS, whois, GitHub, patrones de correo
- [x] dossier, ganchos, plan, crítico adversarial
- [x] render por canal, QA y entrega SMTP/Telegram/Twilio/manual
- [x] landing con formulario y captura
- [x] campañas omnicanal con disparadores y reintentos
- [x] 201 packs importados de unjail.ai, validados
- [x] informe de misión exportable (`debrief`)
- [ ] bot conversacional para Telegram (respuesta adaptativa)
- [ ] proxy inverso tipo Evilginx
- [ ] captura de OTP
