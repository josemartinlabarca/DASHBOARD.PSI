# PROGRESS — bitácora

Los agentes agregan aquí una entrada al final de cada vuelta. Lo más reciente va **abajo**.

## Estado actual

- Fase: 2 (Usuarios) en curso
- Última tarea hecha: T-03b
- Próxima tarea: T-04 (T-02c sigue pendiente y requiere decisión humana antes de T-05)

## Bloqueos y dudas abiertas

- Para T-13: el 413 por defecto de Werkzeug (`MAX_CONTENT_LENGTH`, D-014) responde en inglés ("Request Entity Too Large"). Falta una página de error en español; no se arregló en T-03b.
- T-02c sigue esperando la decisión humana sobre D-007 (propuesta sin aprobar); no se tocó.

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

### [2026-10-07 23:36] T-02 — Base de datos — Implementador
- Qué se hizo: `app/schema.sql` con las 3 tablas de ARCHITECTURE.md (CHECK de `rol` y `estado`, UNIQUE de `email`, DEFAULT y claves foráneas); `app/db.py` con `get_db()` (conexión por petición en `g`, `row_factory=sqlite3.Row`, `PRAGMA foreign_keys = ON`), `close_db()`, `init_db()` y comando `init-db`; registro en `create_app` (teardown + comando); `tests/test_db.py` con 8 pruebas. Decisión D-006: `init-db` es no destructivo (`CREATE TABLE IF NOT EXISTS`).
- Cómo se verificó: `python3 -m pytest -q` pasa (9 pruebas); `flask --app app init-db` ejecutado dos veces contra una base temporal (variable `DATABASE`), sin dejar archivos `.db` en el repo.
- Problemas / dudas: `notificaciones.tipo` no tiene CHECK porque ARCHITECTURE.md solo lo lista como comentario; se dejó sin restricción para seguir el documento al pie de la letra.
- Siguiente paso sugerido: T-02b (endurecer configuración).

### [2026-10-07 23:42] T-02b — Endurecer configuración — Implementador
- Qué se hizo: `create_app` ahora lee `SECRET_KEY` solo del entorno (o de `test_config`) y `_validar_secret_key` aplica el valor de desarrollo únicamente si `TESTING` o `DEBUG` están activos (`app.config["DEBUG"]` refleja `FLASK_DEBUG`, que `flask run --debug` fija antes de crear la app); si no, lanza `RuntimeError` en español (una `SECRET_KEY` vacía cuenta como ausente). `requirements.txt`: `pytest>=9,<10` y decisión D-005 en `DECISIONS.md`. README: sección `SECRET_KEY`. Nuevo `tests/test_config.py` (5 pruebas, con `monkeypatch`).
- Cómo se verificó: `python3 -m pytest -q` pasa (14 pruebas). Quitando temporalmente la validación fallan 2 pruebas nuevas (sin clave y clave vacía); se revirtió. Manual: `flask --app app run --debug` sin `SECRET_KEY` respondió 200 en `/` y se cerró; `flask --app app run` sin debug ni clave falla con el mensaje claro. Sin procesos ni `.db` residuales.
- Problemas / dudas: ninguna.
- Siguiente paso sugerido: T-03 (registro de pacientes). T-02c requiere decisión humana.

### [2026-10-08 00:05] T-02d — Corregir efectos de T-02b en CLI y README — Implementador
- Qué se hizo: `create_app` ya no valida `SECRET_KEY` al crearse; `_preparar_secret_key` usa la clave de desarrollo en TESTING/DEBUG, respeta tal cual una clave válida y, si falta/está vacía/es solo espacios (`strip()`), registra un `before_request` que lanza `RuntimeError` con el mensaje claro (D-008). `init-db` y los futuros comandos CLI funcionan sin clave; ninguna petición se atiende sin clave fuera de debug/testing, también bajo gunicorn. README: `export SECRET_KEY=$(python3 -c "...")` sin `<>`, equivalente PowerShell y advertencia sobre `FLASK_DEBUG`. DECISIONS: D-005 antes de D-006, quitada la frase obsoleta, nueva D-008. Se añadió `pytest.ini` (`pythonpath = .`, `testpaths = tests`) porque el `pytest` literal del README fallaba en un venv limpio con `ModuleNotFoundError: app`. Pruebas nuevas en `tests/test_config.py` (25 en total).
- Cómo se verificó: `pytest` 25 pruebas pasan. Con `app/__init__.py` anterior (git stash) fallan 11 pruebas nuevas; se restauró. Recorrido literal del README en copia temporal con venv nuevo y sin `SECRET_KEY` (pip con red, sin `--system-site-packages`): pip install, `init-db` OK, `run --debug` respondió 200 por curl, `pytest` 25 OK; `run` sin debug ni clave respondió 500 con el mensaje en el log. Copia borrada, sin procesos ni `.db` en el repo.
- Problemas / dudas: con `flask run` sin clave el servidor arranca y falla en cada petición (500) en lugar de abortar al inicio; costo aceptado en D-008. CLAUDE.md no contradice el README. `FLASK_DEBUG=off` no cuenta como falso para Flask (solo `0`, `false`, `no`).
- Siguiente paso sugerido: T-03 (registro de pacientes). T-02c sigue requiriendo decisión humana.

### [2026-10-08 00:14] T-03 — Registro de pacientes — Implementador
- Qué se hizo: `app/auth.py` (blueprint `auth`, GET/POST `/registro`; validación, hash con werkzeug, rol fijo `paciente`, correo normalizado, `creado_en` con zona de Chile, duplicado vía `sqlite3.IntegrityError`); `app/seguridad.py` con CSRF propio y global (D-009); `registro.html`; `base.html` muestra mensajes flash; `inicio.html` enlaza a `/registro`; registro mínimo en la fábrica (después de la exigencia de `SECRET_KEY`). Tras registrar: 302 a `/` con flash de éxito. Decisiones D-009 (CSRF), D-010 (validaciones) y D-011 (`pytest.ini`, absorbe backlog T-02d #4, fila quitada de TASKS.md). D-007 sigue reservada para T-02c.
- Cómo se verificó: `python3 -m pytest -q` pasa (62 pruebas: las 25 anteriores + 37 nuevas en `tests/test_registro.py` y `tests/test_seguridad.py`). Pruebas de mutación ejecutadas y revertidas: sin `before_request` CSRF fallan 5; con el rol leído del formulario falla 1; sin hash fallan 2; sin capturar `IntegrityError` fallan 4; con `|safe` en el nombre falla 1. Manual con curl en directorio y base temporales (`flask --app app run --debug`, puerto libre): GET `/registro` 200 con token; POST válido (con `rol=profesional` y correo `Ana@Example.cl`) 302 hacia `/`; mismo POST repetido 200 con mensaje de duplicado, sin 500; POST sin token 400 con el mensaje CSRF; en la base: 1 usuario, hash con prefijo `scrypt:`, rol `paciente`, `creado_en` `...-03:00`. Servidor cerrado, temporales borrados, sin `.db` en el repo.
- Problemas / dudas: el mensaje de duplicado no puede ocultar del todo la existencia del correo sin verificación por correo (aceptado, D-010). `zoneinfo` puede requerir el paquete `tzdata` en Windows; no se agregó dependencia (funciona en Linux/macOS). Los backlog T-02d #2 y #3 siguen para T-04.
- Siguiente paso sugerido: T-04 (login, logout, decoradores de rol y `create-professional`); usar `seguridad.py` para el formulario de login.

### [2026-10-08 00:26] T-03b — Endurecer el registro — Implementador
- Qué se hizo: (1) `requirements.txt` con `tzdata; sys_platform == "win32"` y `ZoneInfo` creado al usarlo (`zona_chile()` con `lru_cache`, error claro si faltan datos) — D-012. (2) `app/correo.py` con `normalizar_email()` (NFKC + recorte + `casefold` + NFKC; `ValueError` ante espacios internos y categorías Unicode Cc/Cf), usada por el registro; archivo nuevo justificado en D-013 (con el homoglifo cirílico como riesgo aceptado). (3) `MAX_CONTENT_LENGTH = 16 * 1024` en la fábrica — D-014. (4) Pruebas reforzadas: CSRF en PUT/PATCH/DELETE, escape del correo en `value="..."`, hash scrypt con mínimos leídos de la versión instalada de werkzeug, duplicado sin SELECT previo (traza SQL con `set_trace_callback`). (5) Nota en D-009 sobre POST a ruta inexistente (400). Pruebas nuevas: `tests/test_correo.py`, `tests/test_zona_horaria.py` y ampliaciones en `test_registro.py` y `test_seguridad.py`. Sin tocar SPEC, ARCHITECTURE, REVIEW, D-007 ni el esquema.
- Cómo se verificó: `python3 -m pytest -q` da 109 pruebas OK sin `SECRET_KEY`/`FLASK_DEBUG`, con `SECRET_KEY=abc` y con `FLASK_DEBUG=1`. Mutaciones ejecutadas en copias temporales (borradas): CSRF solo para POST -> fallan 3 (PUT/PATCH/DELETE); `|safe` en el correo -> 1; `pbkdf2:sha256:1` -> 1; `scrypt:1024:8:1` -> 1 (`scrypt:2:8:1` ni siquiera funciona en OpenSSL: error de memoria); SELECT previo al INSERT -> 1; sin ninguna NFKC -> 4; sin chequeo Cc/Cf -> 11; `lower()` en vez de `casefold` -> 2; sin `MAX_CONTENT_LENGTH` -> 1; `ZoneInfo` al importar -> 2. Quitar solo la primera NFKC deja todo en verde porque la segunda ya cubre el caso (equivalente, no un hueco). Simulación sin zona horaria (`PYTHONTZPATH` a un directorio vacío y `tzdata` bloqueado): `import app`, `create_app()` y `flask init-db` funcionan; registrar un usuario da 500 con el mensaje que pide instalar `tzdata` y no crea el usuario. El paquete `tzdata` NO está instalado en este sistema (Linux usa `/usr/share/zoneinfo`). La línea de requirements se validó en un venv temporal borrado (`pip install --dry-run -r requirements.txt`, `pip download tzdata`, y el marcador evalúa True en win32 y False en linux). Recorrido con servidor temporal y curl: GET `/registro` con token; POST `Ａna@Example.cl` -> 302; POST `ana@example.cl` -> 200 con aviso de duplicado; POST de 20 kB -> 413; POST sin token -> 400; en la base, 1 usuario `ana@example.cl`, rol `paciente`, hash `scrypt:`. Se leyó la base con `sqlite3` de Python (el comando `sqlite3` no está instalado). Servidor cerrado por PID, temporales borrados, sin `.db` en el repo.
- Problemas / dudas: el 413 de Werkzeug está en inglés (anotado para T-13). Un POST sobrecargado da 413 incluso sin token porque el CSRF lee `request.form` primero. El homoglifo cirílico queda sin resolver (D-013). T-02c sigue pendiente de decisión humana.
- Siguiente paso sugerido: T-04 (login, logout, roles, `create-professional`) usando `normalizar_email()`.

