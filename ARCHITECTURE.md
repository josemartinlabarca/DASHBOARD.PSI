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
- `sesion_version` INTEGER NOT NULL DEFAULT 0 (D-022: la sesión guarda `(id, sesion_version)`; solo es válida si coincide con la de la base; el logout la incrementa con un `UPDATE` atómico y así invalida cualquier copia anterior de la cookie)
- índice único parcial `CREATE UNIQUE INDEX IF NOT EXISTS un_solo_profesional ON usuarios (rol) WHERE rol = 'profesional'` (D-023: la base impide un segundo profesional; los pacientes no entran en el índice)

**horas**
- `id` INTEGER PK
- `profesional_id` INTEGER NOT NULL → usuarios.id
- `inicio` TEXT NOT NULL (ISO 8601, hora local de Chile, formato canónico `YYYY-MM-DDTHH:MM:SS` sin desfase; el esquema lo exige con `CHECK (inicio GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]' AND instr(inicio, char(0)) = 0)`, que valida la forma (y rechaza el carácter nulo, D-018) pero no que la fecha exista: eso lo valida la aplicación)
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

---

## Adiciones posteriores (T-16; el humano autorizó editar este archivo el 2026-10-10)

Solo agrega lo que existía en el código y no estaba aquí (lista de D-052 y T-13 R-08). Nada de lo anterior cambió.

### Módulos y archivos agregados

| Módulo / archivo | Responsabilidad | No debe hacer |
|---|---|---|
| `app/limite.py` | Límite de intentos de login y registro (`reservar`, `absolver`, `Bloqueado`, `BaseOcupada`, `VENTANA_S`, `LIMITES`) sobre la tabla `intentos_acceso` | Reglas de negocio de reservas |
| `app/errores.py` | Páginas de error en español para cualquier `HTTPException` y para la base ocupada (`pagina_de_error`, `error_de_base`, `init_app`) | Mostrar descripciones de Werkzeug ni leer la sesión |
| `app/correo.py` | Normalización de correos: `normalizar_email` (registro, política de caracteres) y `normalizar_email_login` (login, nunca rechaza) | Flask ni base de datos |
| `app/tiempo.py` | Reloj único de la app (`ahora_chile`) y conversión de horas locales a instantes absolutos (`a_segundos_utc`, `mostrar_inicio`, `mostrar_instante`) | Reglas de reserva |
| `app/templates/error.html` | Página de error común | Leer sesión o mensajes flash |
| `app/templates/acceso_denegado.html` | Respuesta 403 de los decoradores de rol | — |
| `app/templates/_notificaciones.html` | Panel de notificaciones compartido por `/paciente` y `/profesional` | — |
| `app/static/` | `style.css` y `favicon.svg` | — |
| `tests/esquemas_antiguos/` | Esquemas SQL de commits anteriores, como datos de prueba de `init-db` | — |

`db.py` ahora también contiene: `version_esquema` (lee `PRAGMA user_version`) y `VERSION_ESQUEMA`, `ConvertidorId` y `regex_de_ids_hasta` (ids de ruta acotados), `abrir_base_existente`, `comprobar_que_se_puede_escribir`, `errores_de_sqlite_como_mensaje`, `inicializar` (transaccional), `fk_de_avisos_sin_set_null` y `avisar_si_la_base_es_antigua`. `seguridad.py` además fija la política CSP y otras cabeceras de seguridad (`agregar_cabeceras_de_seguridad`) y avisa de cabeceras de proxy sin configurar (`avisar_si_hay_proxy_sin_configurar`).

### Tabla `intentos_acceso`

- `id` INTEGER PK
- `accion` TEXT NOT NULL CHECK (accion IN ('login','registro'))
- `ambito` TEXT NOT NULL CHECK (ambito IN ('ip','par','correo'))
- `clave` TEXT NOT NULL (no vacía)
- `instante` INTEGER NOT NULL (segundos desde 1970, UTC)
- índices `intentos_acceso_clave ON (accion, ambito, clave, instante)` e `intentos_acceso_instante ON (instante)`.

### Rutas agregadas

| Método | Ruta | Rol | Descripción |
|---|---|---|---|
| POST | `/notificaciones/leidas` | paciente | Marcar todas sus notificaciones como leídas |
| POST | `/profesional/notificaciones/leidas` | profesional | Marcar todas sus notificaciones como leídas |

### Configuración y variables

Claves de `app.config`: `SECRET_KEY`, `SESSION_COOKIE_SECURE`, `TRUSTED_PROXY_COUNT`, `OUTBOX_PATH`, `DATABASE` y `DATABASE_TIMEOUT` (esta última solo la cambian las pruebas). Todas salen de variables de entorno del mismo nombre salvo `DATABASE_TIMEOUT`; el detalle de uso está en `README.md`.
