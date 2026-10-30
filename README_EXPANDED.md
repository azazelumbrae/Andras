# ANDRAS - Expansión de Proyecto de Ingeniería Social

## 📋 Resumen del Proyecto Expandido

Este documento describe las modificaciones realizadas al proyecto ANDRAS para convertirlo en una herramienta más completa de simulación de ingeniería social.

### 🎯 Objetivos Principales

1. **Herramientas de OSINT** - Recopilar información sobre víctimas
2. **Phishing** - Simulación de ataques de correo electrónico
3. **Extorsión** - Modelado de amenazas y coacción
4. **Manipulación Social** - Creación de perfiles falsos
5. **Baneos Automáticos** - Simulación de sistemas que bloquean cuentas

### 📁 Estructura del Proyecto

```
andras/
├── README.md              # Documentación original
├── README_EXPANDED.md    # Esta documentación
├── config.json            # Configuración SMTP y destinatarios
├── scenarios/
│   ├── suspicious-email.json      # Escenario original
│   ├── osint-discover.json        # Recopilar información OSINT
│   ├── phishing-spear.json        # Phishing dirigido
│   ├── extortion-bec.json          # Extorsión por BEC (Business Email Compromise)
│   ├── social-bot-fake.json       # Creación de perfiles falsos
│   └── ban-account.json           # Bloqueo automático de cuentas
├── cli.py                 # CLI principal con nuevas subcomandos
├── server.py              # Servidor web
└── core.py                # Lógica central
```

### 🚀 Nuevas Comandos del CLI

| Comando | Descripción |
|---------|-------------|
| `osint-discover <to>` | Preview escenario de OSINT |
| `phishing-spear <to>` | Preview escenario de phishing |
| `extortion-bec <to>` | Preview escenario de extorsión |
| `social-bot-fake <to>` | Preview escenario de bots sociales |
| `ban-account <to>` | Preview escenario de baneos |

### 🔧 Configuración

Edita `config.json` para configurar:
- SMTP host/port/seguridad
- Destinatarios autorizados
- URL base del servidor local

### 📊 Escenarios Incluidos

1. **OSINT Discovery** - Recopilar datos públicos sobre una persona
2. **Spear Phishing** - Ataque dirigido con correo falso y enlaces sospechosos
3. **Extortion BEC** - Amenaza financiera mediante compromiso de cuentas bancarias
4. **Social Bot Fake** - Creación de perfiles falsos para manipular opiniones
5. **Ban Account** - Simulación de sistemas que detectan patrones de comportamiento

### 🛡️ Seguridad y Ética

Este proyecto está diseñado exclusivamente para:
- **Ejercicios educativos** en entornos controlados
- **Entrenamiento de equipos de seguridad**
- **Simulación de ataques** para pruebas de defensa

**No utilice esta herramienta para:**
- Ataques contra personas sin autorización
- Colectas de datos sin permiso
- Manipulación de redes sociales no autorizadas

---

*Documentación generada por el sistema de desarrollo ANDRAS v1.0*
