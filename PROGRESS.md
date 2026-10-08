# PROGRESS — bitácora

Los agentes agregan aquí una entrada al final de cada vuelta. Lo más reciente va **abajo**.

## Estado actual

- Fase: 1 (Base) en curso
- Última tarea hecha: T-02
- Próxima tarea: T-02b

## Bloqueos y dudas abiertas

_(ninguno)_

## Bitácora

### [2026-10-07] Preparación — Humano + Claude
- Qué se hizo: se escribieron README, SPEC, ARCHITECTURE, DECISIONS, CLAUDE, TASKS, PROGRESS, LOOP.
- Cómo se verificó: revisión de coherencia entre documentos.
- Problemas / dudas: ninguna.
- Siguiente paso sugerido: ejecutar T-01 con un solo agente Implementador y revisar a mano el resultado antes de activar el loop.

### [2026-10-07] T-01 — Esqueleto del proyecto — Implementador
- Qué se hizo: `.gitignore`, `requirements.txt` (flask, pytest), fábrica `create_app` en `app/__init__.py` (SECRET_KEY por entorno, DATABASE configurable para T-02), ruta `/` con `base.html` e `inicio.html` en español de Chile, `tests/conftest.py` (fixtures `app` y `client` con base temporal) y `tests/test_inicio.py`.
- Cómo se verificó: `pytest` 1 prueba pasa; `flask --app app run` en puerto 5057 respondió 200 con el título "Agenda Psi" y se cerró.
- Problemas / dudas: ninguna.
- Siguiente paso sugerido: T-02 (schema.sql, db.py y comando init-db).

### [2026-10-07 23:40] T-02 — Base de datos — Implementador
- Qué se hizo: `app/schema.sql` con las 3 tablas de ARCHITECTURE.md (CHECK de `rol` y `estado`, UNIQUE de `email`, DEFAULT y claves foráneas); `app/db.py` con `get_db()` (conexión por petición en `g`, `row_factory=sqlite3.Row`, `PRAGMA foreign_keys = ON`), `close_db()`, `init_db()` y comando `init-db`; registro en `create_app` (teardown + comando); `tests/test_db.py` con 8 pruebas. Decisión D-006: `init-db` es no destructivo (`CREATE TABLE IF NOT EXISTS`).
- Cómo se verificó: `python3 -m pytest -q` pasa (9 pruebas); `flask --app app init-db` ejecutado dos veces contra una base temporal (variable `DATABASE`), sin dejar archivos `.db` en el repo.
- Problemas / dudas: `notificaciones.tipo` no tiene CHECK porque ARCHITECTURE.md solo lo lista como comentario; se dejó sin restricción para seguir el documento al pie de la letra.
- Siguiente paso sugerido: T-02b (endurecer configuración).
