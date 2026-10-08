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

## D-006 — `init-db` no destructivo (`CREATE TABLE IF NOT EXISTS`)
- **Fecha:** 2026-10-07
- **Decisión:** `schema.sql` usa `CREATE TABLE IF NOT EXISTS` y `init-db` nunca borra datos; ejecutarlo sobre una base existente solo crea las tablas que falten. No modifica tablas ya existentes (los cambios de esquema futuros requerirán otra decisión).
- **Porqué:** Es lo más simple y seguro: evita perder citas o usuarios por ejecutarlo dos veces. (D-005 queda reservada para T-02b.)
- **Alternativas descartadas:** `DROP TABLE` + recrear (destructivo, exigiría confirmación); sistema de migraciones (excesivo para v1).

## Plantilla para nuevas decisiones

```
## D-00X — Título
- **Fecha:**
- **Decisión:**
- **Porqué:**
- **Alternativas descartadas:**
```
