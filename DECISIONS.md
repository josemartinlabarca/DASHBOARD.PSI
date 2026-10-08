# DECISIONS — registro de decisiones

Formato: una entrada corta por decisión. Los agentes agregan aquí cualquier
decisión técnica que no esté ya cubierta, en lugar de tomarla en silencio.

## D-001 — Flask + SQLite + Jinja2
- **Fecha:** 2026-10-07
- **Decisión:** Usar Flask, SQLite y plantillas del lado del servidor.
- **Porqué:** Mínimas dependencias, un solo archivo de base de datos, nada que
  instalar aparte de Python. Ideal para aprender el flujo con agentes sin
  pelear con herramientas.
- **Alternativas descartadas:** Django (más pesado), React + API (dos proyectos
  en uno), Postgres (requiere servidor).

## D-002 — Notificaciones simuladas
- **Fecha:** 2026-10-07
- **Decisión:** Guardar notificaciones en base de datos y en `outbox.log`; sin correo real.
- **Porqué:** Evita credenciales y servicios externos; el comportamiento se
  puede probar de forma determinista.

## D-003 — Reserva atómica con un solo UPDATE
- **Fecha:** 2026-10-07
- **Decisión:** Reservar con `UPDATE ... WHERE estado='libre'` y revisar `rowcount`.
- **Porqué:** Garantiza que no haya doble reserva sin lógica de bloqueo.

## D-004 — Un solo profesional en v1
- **Fecha:** 2026-10-07
- **Decisión:** El profesional se crea por CLI; no hay registro público de profesionales.
- **Porqué:** Simplifica permisos y evita decidir un flujo de verificación.

## D-005 — Versión de pytest acotada en `requirements.txt`
- **Fecha:** 2026-10-07
- **Decisión:** Fijar `pytest>=9,<10` (versión probada: 9.1.1), igual que Flask (`>=3.1,<3.2`).
- **Porqué:** Una instalación nueva no debe traer un cambio mayor de pytest que rompa las pruebas sin aviso. Es una dependencia ya existente; solo se acota su rango (hallazgo 2 de la revisión de T-01).
- **Alternativas descartadas:** dejar `pytest` sin versión (no reproducible); fijar versión exacta con `==` (demasiado rígido para v1).

## D-006 — `init-db` no destructivo (`CREATE TABLE IF NOT EXISTS`)
- **Fecha:** 2026-10-07
- **Decisión:** `schema.sql` usa `CREATE TABLE IF NOT EXISTS` y `init-db` nunca borra datos; ejecutarlo sobre una base existente solo crea las tablas que falten. No modifica tablas ya existentes (los cambios de esquema futuros requerirán otra decisión).
- **Porqué:** Es lo más simple y seguro: evita perder citas o usuarios por ejecutarlo dos veces.
- **Alternativas descartadas:** `DROP TABLE` + recrear (destructivo, exigiría confirmación); sistema de migraciones (excesivo para v1).

## D-008 — `SECRET_KEY` se exige al atender peticiones, no al crear la app
- **Fecha:** 2026-10-08
- **Decisión:** `create_app` ya no lanza error por falta de `SECRET_KEY`. Si la clave falta, está vacía o es solo espacios (se decide con `strip()`, sin modificar una clave válida) y no hay `TESTING`/`DEBUG`, se registra un `before_request` que lanza `RuntimeError` con el mensaje claro; con `TESTING`/`DEBUG` se usa el valor de desarrollo. Toda petición sin clave fuera de debug responde 500 y el log muestra el mensaje.
- **Porqué:** La clave solo hace falta para firmar sesiones y CSRF, es decir, al servir peticiones; los comandos CLI (`init-db` y los futuros `create-professional`, `send-reminders`) crean la app pero no atienden peticiones, así que heredan la regla sin trabajo extra. `before_request` vive en la app, no en `flask run`: gunicorn u otro servidor WSGI también pasa por él, de modo que una app sin clave fuera de debug/testing nunca atiende una petición (se ejecuta antes de cualquier vista, también 404 y estáticos). No depende de `sys.argv`. Costo aceptado: con `flask run` sin clave el servidor arranca y falla en cada petición en vez de abortar al inicio.
- **Alternativas descartadas:** detectar el comando por `sys.argv` (frágil, no cubre WSGI); validar solo en `flask run` (no protege gunicorn); validar al primer request (más estado y no cubre todos los casos que `before_request`); una fábrica separada para la CLI (duplica configuración).

## D-009 — CSRF propio y centralizado en `app/seguridad.py` (sin dependencias)
- **Fecha:** 2026-10-08
- **Decisión:** Token aleatorio (`secrets.token_hex(32)`) guardado en la sesión firmada de Flask; las plantillas lo obtienen con `{{ csrf_token() }}` (global de Jinja) y lo envían en el campo `csrf_token` (o en la cabecera `X-CSRFToken`). Un `before_request` verifica con `hmac.compare_digest` en todo método que no sea GET/HEAD/OPTIONS/TRACE y responde 400 con un mensaje claro si falta o no coincide. Se registra después del `before_request` de D-008, así que sin `SECRET_KEY` el error sigue siendo el de la clave (hay prueba).
- **Porqué:** Son unas 40 líneas, sin dependencia nueva, y al ser global los formularios futuros (login, reservas, horas) no pueden olvidar la verificación. Se crea el archivo `app/seguridad.py` (no previsto en ARCHITECTURE.md) para que sea reutilizable y no quede dentro de `auth.py`.
- **Alternativas descartadas:** Flask-WTF (dependencia nueva con versión fija; trae formularios y validadores que no usamos); verificar en cada vista (fácil de olvidar).

## D-010 — Validaciones y mensajes del registro
- **Fecha:** 2026-10-08
- **Decisión:** Nombre recortado, 1 a 100 caracteres. Correo recortado y en minúsculas, máximo 254 caracteres, con formato `algo@dominio.tld` (regex simple `^[^@\s]+@[^@\s]+\.[^@\s]+$`; sin verificación por correo, fuera de alcance v1). Contraseña de 8 a 128 caracteres, sin recortar (los espacios cuentan). Rol fijado en el servidor a `paciente`; el formulario nunca se lee para el rol. Los errores de formulario responden 200 con el formulario y mensajes junto a cada campo, conservando nombre y correo, nunca la contraseña. `creado_en` con `datetime.now(ZoneInfo("America/Santiago")).isoformat(timespec="seconds")`.
- **Porqué:** Límites suficientes para personas reales y que acotan el costo del hash (máximo 128). El correo se normaliza antes de guardar para que la restricción UNIQUE cubra variantes de mayúsculas y espacios.
- **Correo duplicado:** no hay consulta previa; se captura `sqlite3.IntegrityError` del INSERT (sin condición de carrera). El mensaje es "No pudimos registrarte con ese correo. Si ya tienes una cuenta, inicia sesión; si no, prueba con otro correo.": no afirma explícitamente que exista, aunque sin verificación por correo es inevitable que quien lo prueba lo deduzca. Se acepta para v1.
- **Alternativas descartadas:** validar el correo con una librería (dependencia); exigir confirmación de contraseña (SPEC no lo pide); 409 para el duplicado (se prefiere el mismo flujo de formulario).

## D-011 — `pytest.ini` con `pythonpath = .` y `testpaths = tests`
- **Fecha:** 2026-10-08
- **Decisión:** Mantener `pytest.ini` (agregado en T-02d) con `pythonpath = .` y `testpaths = tests`.
- **Porqué:** Sin `pythonpath = .`, el comando literal `pytest` del README falla en un venv limpio con `ModuleNotFoundError: app`, porque `app` no está instalado como paquete. `testpaths = tests` evita que pytest recorra otras carpetas (venv, etc.). Registra el ítem de backlog "T-02d #4".
- **Alternativas descartadas:** `pip install -e .` con `pyproject.toml` (más archivos y empaquetado innecesario en v1); `conftest.py` en la raíz (más implícito).

## Plantilla para nuevas decisiones

```
## D-00X — Título
- **Fecha:**
- **Decisión:**
- **Porqué:**
- **Alternativas descartadas:**
```
