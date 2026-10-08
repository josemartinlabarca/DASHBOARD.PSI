# PROGRESS — bitácora

Los agentes agregan aquí una entrada al final de cada vuelta. Lo más reciente va **abajo**.

## Estado actual

- Fase: 1 (Base) en curso
- Última tarea hecha: T-02d
- Próxima tarea: T-03 (T-02c sigue pendiente y requiere decisión humana antes de T-05)

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

### [2026-10-07 23:59] T-02b — Endurecer configuración — Implementador
- Qué se hizo: `create_app` ahora lee `SECRET_KEY` solo del entorno (o de `test_config`) y `_validar_secret_key` aplica el valor de desarrollo únicamente si `TESTING` o `DEBUG` están activos (`app.config["DEBUG"]` refleja `FLASK_DEBUG`, que `flask run --debug` fija antes de crear la app); si no, lanza `RuntimeError` en español (una `SECRET_KEY` vacía cuenta como ausente). `requirements.txt`: `pytest>=9,<10` y decisión D-005 en `DECISIONS.md`. README: sección `SECRET_KEY`. Nuevo `tests/test_config.py` (5 pruebas, con `monkeypatch`).
- Cómo se verificó: `python3 -m pytest -q` pasa (14 pruebas). Quitando temporalmente la validación fallan 2 pruebas nuevas (sin clave y clave vacía); se revirtió. Manual: `flask --app app run --debug` sin `SECRET_KEY` respondió 200 en `/` y se cerró; `flask --app app run` sin debug ni clave falla con el mensaje claro. Sin procesos ni `.db` residuales.
- Problemas / dudas: ninguna.
- Siguiente paso sugerido: T-03 (registro de pacientes). T-02c requiere decisión humana.

### [2026-10-08 10:30] T-02d — Corregir efectos de T-02b en CLI y README — Implementador
- Qué se hizo: `create_app` ya no valida `SECRET_KEY` al crearse; `_preparar_secret_key` usa la clave de desarrollo en TESTING/DEBUG, respeta tal cual una clave válida y, si falta/está vacía/es solo espacios (`strip()`), registra un `before_request` que lanza `RuntimeError` con el mensaje claro (D-008). `init-db` y los futuros comandos CLI funcionan sin clave; ninguna petición se atiende sin clave fuera de debug/testing, también bajo gunicorn. README: `export SECRET_KEY=$(python3 -c "...")` sin `<>`, equivalente PowerShell y advertencia sobre `FLASK_DEBUG`. DECISIONS: D-005 antes de D-006, quitada la frase obsoleta, nueva D-008. Se añadió `pytest.ini` (`pythonpath = .`, `testpaths = tests`) porque el `pytest` literal del README fallaba en un venv limpio con `ModuleNotFoundError: app`. Pruebas nuevas en `tests/test_config.py` (25 en total).
- Cómo se verificó: `pytest` 25 pruebas pasan. Con `app/__init__.py` anterior (git stash) fallan 11 pruebas nuevas; se restauró. Recorrido literal del README en copia temporal con venv nuevo y sin `SECRET_KEY` (pip con red, sin `--system-site-packages`): pip install, `init-db` OK, `run --debug` respondió 200 por curl, `pytest` 25 OK; `run` sin debug ni clave respondió 500 con el mensaje en el log. Copia borrada, sin procesos ni `.db` en el repo.
- Problemas / dudas: con `flask run` sin clave el servidor arranca y falla en cada petición (500) en lugar de abortar al inicio; costo aceptado en D-008. CLAUDE.md no contradice el README. `FLASK_DEBUG=off` no cuenta como falso para Flask (solo `0`, `false`, `no`).
- Siguiente paso sugerido: T-03 (registro de pacientes). T-02c sigue requiriendo decisión humana.
