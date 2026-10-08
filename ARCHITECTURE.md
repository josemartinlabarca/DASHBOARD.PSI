# ARCHITECTURE — Agenda Psi

## Estructura de carpetas (objetivo)

```
agenda-psi/
├── app/
│   ├── __init__.py        # fábrica de la app Flask, registro de blueprints y comandos CLI
│   ├── db.py              # conexión SQLite, init-db
│   ├── schema.sql         # definición de tablas
│   ├── auth.py            # registro, login, logout, decoradores de rol
│   ├── seguridad.py       # protección CSRF global (token en sesión, before_request)
│   ├── paciente.py        # rutas del paciente (dashboard, horas libres, reservar, cancelar)
│   ├── profesional.py     # rutas del profesional (dashboard, agregar/eliminar horas)
│   ├── notificaciones.py  # crear notificación, escribir outbox.log, recordatorios
│   ├── templates/         # plantillas Jinja2
│   └── static/            # style.css
├── tests/                 # pytest
├── requirements.txt
└── (documentación en la raíz)
```

## Módulos y responsabilidades

| Módulo | Responsabilidad | No debe hacer |
|---|---|---|
| `db.py` | Abrir conexión, inicializar esquema | Lógica de negocio |
| `auth.py` | Usuarios, sesiones, control de rol | Reservas |
| `seguridad.py` | Token CSRF y verificación en todo método que modifica estado | Reglas de negocio |
| `profesional.py` | CRUD de horas disponibles | Notificar directamente (llama a `notificaciones.py`) |
| `paciente.py` | Listar, reservar, cancelar | Modificar horas de otros |
| `notificaciones.py` | Registrar y "enviar" avisos | Decidir reglas de reserva |

## Modelo de datos

**usuarios**
- `id` INTEGER PK
- `nombre` TEXT NOT NULL
- `email` TEXT NOT NULL UNIQUE COLLATE NOCASE (no distingue mayúsculas ASCII; no sustituye a la normalización de la aplicación)
- `password_hash` TEXT NOT NULL
- `rol` TEXT NOT NULL CHECK (rol IN ('paciente','profesional'))
- `creado_en` TEXT NOT NULL

**horas**
- `id` INTEGER PK
- `profesional_id` INTEGER NOT NULL → usuarios.id
- `inicio` TEXT NOT NULL (ISO 8601, hora local de Chile, formato canónico `YYYY-MM-DDTHH:MM:SS` sin desfase; el esquema lo exige con `CHECK (inicio GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]')`, que valida la forma pero no que la fecha exista: eso lo valida la aplicación)
- `duracion_min` INTEGER NOT NULL DEFAULT 50 CHECK (duracion_min > 0)
- `estado` TEXT NOT NULL CHECK (estado IN ('libre','reservada')) DEFAULT 'libre'
  (al cancelar, la hora vuelve a `libre` y se limpian `paciente_id` y `reservada_en`)
- `paciente_id` INTEGER NULL → usuarios.id
- `reservada_en` TEXT NULL
- `recordatorio_enviado` INTEGER NOT NULL DEFAULT 0 CHECK (recordatorio_enviado IN (0,1))
- restricción de tabla: `CHECK ((estado = 'libre' AND paciente_id IS NULL AND reservada_en IS NULL) OR (estado = 'reservada' AND paciente_id IS NOT NULL AND reservada_en IS NOT NULL))`
- restricción de tabla: `UNIQUE (profesional_id, inicio)` (impide inicios idénticos; el solape parcial lo controla la aplicación)

**notificaciones**
- `id` INTEGER PK
- `usuario_id` INTEGER NOT NULL → usuarios.id
- `tipo` TEXT NOT NULL CHECK (tipo IN ('confirmacion','recordatorio','cancelacion'))
- `mensaje` TEXT NOT NULL
- `hora_id` INTEGER NULL → horas.id ON DELETE SET NULL (al eliminar la hora, la notificación se conserva con `hora_id` NULL)
- `leida` INTEGER NOT NULL DEFAULT 0 CHECK (leida IN (0,1))
- `creada_en` TEXT NOT NULL

## Flujo clave: reservar una hora

1. Paciente autenticado envía `POST /horas/<id>/reservar`.
2. Se ejecuta **una sola sentencia atómica**:
   `UPDATE horas SET estado='reservada', paciente_id=?, reservada_en=? WHERE id=? AND estado='libre'`
3. Si `rowcount == 0`, la hora ya no estaba libre → mensaje de error amigable.
4. Si `rowcount == 1`, se crean notificaciones de confirmación para paciente y profesional.

Esto evita la doble reserva sin necesidad de bloqueos complejos.

## Rutas principales

| Método | Ruta | Rol | Descripción |
|---|---|---|---|
| GET/POST | `/registro` | público | Registro de paciente |
| GET/POST | `/login` | público | Inicio de sesión |
| POST | `/logout` | autenticado | Cerrar sesión |
| GET | `/paciente` | paciente | Dashboard |
| GET | `/paciente/horas` | paciente | Horas libres |
| POST | `/horas/<id>/reservar` | paciente | Reservar |
| POST | `/horas/<id>/cancelar` | paciente | Cancelar |
| GET | `/profesional` | profesional | Dashboard |
| GET/POST | `/profesional/horas/nueva` | profesional | Agregar hora |
| POST | `/profesional/horas/<id>/eliminar` | profesional | Eliminar hora libre |

## Comandos CLI

- `flask --app app init-db`
- `flask --app app create-professional --email ... --nombre ...`
- `flask --app app send-reminders`
