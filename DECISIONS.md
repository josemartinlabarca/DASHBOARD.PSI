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

## Plantilla para nuevas decisiones

```
## D-00X — Título
- **Fecha:**
- **Decisión:**
- **Porqué:**
- **Alternativas descartadas:**
```
