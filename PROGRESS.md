# PROGRESS — bitácora

Los agentes agregan aquí una entrada al final de cada vuelta. Lo más reciente va **abajo**.

## Estado actual

- Fase: 1 (Base) en curso
- Última tarea hecha: T-01
- Próxima tarea: T-02

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
