# ANDRAS

Simulador personal de ejercicios de ingeniería social. Envía mensajes de práctica por SMTP a destinatarios que tú autorizas, sirve una página de entrenamiento y registra interacciones sin recoger contraseñas.

ANDRAS v1 es local-first y usa solo la biblioteca estándar de Python 3.11+. No envía nada durante `preview`; el envío real requiere destinatarios presentes en `config.json` y confirmación interactiva.

## Inicio rápido

```sh
cd ~/andras
cp config.example.json config.json
# Mailinator es una bandeja pública de prueba; no uses datos sensibles.
export ANDRAS_SMTP_USER='tu-usuario'
export ANDRAS_SMTP_PASSWORD='tu-contraseña-de-aplicacion'
python3 -m andras.cli init
python3 -m andras.cli scenarios
python3 -m andras.cli preview suspicious-email --to andras-lab@mailinator.com
```

Mailinator sirve para recibir el mensaje de prueba; es un servicio de solo recepción y no ofrece SMTP saliente. El ejemplo autoriza `andras-lab@mailinator.com`, una bandeja pública que cualquiera puede leer. Úsala solo para mensajes ficticios y sin datos personales ni secretos.

El remitente sigue necesitando un SMTP saliente real. Configura host, puerto y remitente en `config.json` (normalmente puerto 587 con STARTTLS o 465 con TLS implícito). Usa una contraseña de aplicación si el proveedor la requiere. No guardes secretos en archivos versionados.

En una terminal, inicia el receptor local:

```sh
python3 -m andras.cli serve
```

En otra, crea y envía el ejercicio:

```sh
python3 -m andras.cli send suspicious-email --to andras-lab@mailinator.com
```

El correo enlaza a `http://127.0.0.1:8765`; solo podrás abrirlo desde el mismo equipo. No expongas este servidor a Internet. Para probar desde otro dispositivo en tu red, cambia `base_url` a una dirección privada controlada y `bind_host` a la interfaz LAN; el servidor no habilita TLS. El enlace contiene un token aleatorio que identifica una interacción, no a una persona.

Consulta resultados con `python3 -m andras.cli report` o expórtalos con `python3 -m andras.cli report --format json`. La base SQLite se crea en `data/andras.sqlite3`.

## Seguridad y privacidad

- Los destinatarios deben estar enumerados explícitamente en `authorized_recipients`.
- El CLI vuelve a comprobar el alcance y pide escribir `SEND` antes de transmitir cada campaña.
- La plantilla no solicita credenciales. ANDRAS no registra campos de formulario ni contenido de correo.
- Configuración, base de datos y secretos locales están excluidos de Git.
- Usa el proyecto solo en ejercicios propios y autorizados. No importes listas de contactos ni redirijas los mensajes a terceros.

## Comandos

- `init`: crea base de datos y configuración si falta.
- `scenarios`: lista escenarios incluidos.
- `preview <scenario> --to <email>`: renderiza el correo sin enviar.
- `serve`: inicia la página local y endpoint de eventos.
- `send <scenario> --to <email>`: envía una campaña SMTP real tras confirmación.
- `report [--format text|json]`: resume eventos locales.

El escenario de ejemplo es deliberadamente ficticio y muestra una página educativa al hacer clic. “Reportar” registra la acción en la página; la integración con buzones o botones reales de reporte queda fuera de v1.
