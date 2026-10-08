# REVIEW — T-08d Revocar sesión (D-022) y un solo profesional (D-023) (commit `f06bdb5`)

Revisor: leí el diff completo (`git show f06bdb5`), CLAUDE.md, D-004, D-006, D-007, D-022, D-023, T-08d en TASKS, la entrada de PROGRESS (con «Bloqueos»), `app/auth.py`, `app/schema.sql`, la tabla `usuarios` de ARCHITECTURE, README y `tests/test_login.py`, `test_crear_profesional.py`, `test_esquema.py`, `test_db.py`. Todos los experimentos y mutaciones se hicieron en copias del repo bajo el scratchpad (`.../scratchpad/rev`, `/e2e`, `/mut`); no edité código, pruebas ni documentos del proyecto salvo este archivo.

## Veredicto: APROBADA

D-022 y D-023 están bien implementadas y cumplen el término de T-08d (las 3 mutaciones exigidas mueren, `pytest` pasa: 1216 OK reproducido). No hay hallazgos altos. Quedan dos huecos medios/bajos de robustez (R-01, R-02) que conviene absorber en una tarea pequeña antes de T-14; ninguno bloquea T-08e ni T-09.

## Resumen de hallazgos

| ID | Severidad | Tema | Recomendación |
|---|---|---|---|
| R-01 | media | `BEGIN IMMEDIATE` → `BEGIN` sobrevive a toda la suite y rompe la carrera real de `create-professional` (traceback) | tarea nueva (pequeña) |
| R-02 | baja | Base antigua: `init-db` la deja a medias y el login da 500 con cualquier correo; con 2+ profesionales `init-db` revienta | decisión humana / T-14 |
| R-03 | baja | Logout con `database is locked`: 500 tras 5 s y la sesión sigue viva | ignorar el cambio de conducta; 500 en español en T-13 |
| R-04 | baja | Login en carrera con un logout: la sesión nace ya revocada | backlog (T-14) |
| R-05 | informativa | El logout cierra todas las sesiones del usuario (confirmado, documentado) | ignorar; opcional avisar en README |
| R-06 | baja | README no dice que `create-professional` ya se niega a crear un segundo profesional | backlog (documentación) |
| R-07 | informativa | Las pruebas con dos profesionales están aisladas; el ayudante vive en `test_login.py` | backlog |
| R-08 | informativa | T-09..T-12 no dependen del profesional único si usan `horas.profesional_id` | nota para T-09 |
| R-09 | informativa | El futuro «cambio de contraseña» debe incrementar `sesion_version` | nota en TASKS/backlog |
| R-10 | informativa | Mutantes que sobreviven y son equivalentes | ignorar |

## Hallazgos

### R-01 (media) — `BEGIN` diferido en vez de `BEGIN IMMEDIATE` no lo detecta ninguna prueba y rompe la concurrencia real
- **Qué:** PROGRESS dice que «sin `BEGIN IMMEDIATE`» ahora muere (1 prueba: la consulta ocurre con transacción abierta). Eso es cierto para *quitarlo*, pero la prueba solo mira `con.in_transaction`; cambiar a `db.execute("BEGIN")` (diferido) también la deja verde.
- **Evidencia:** mutación `a20_begin_deferred` (`db.execute("BEGIN IMMEDIATE")` → `db.execute("BEGIN")`) con la suite completa: **1216 passed, sobrevive**. Con ese mutante, dos `create-professional` lanzados a la vez (6 rondas, `printf ... | flask create-professional` en dos procesos, `&` y `wait`): **6 de 6 rondas** una de las dos termina con `Traceback ... sqlite3.OperationalError: database is locked` y código 1, en vez del mensaje «Ya existe un profesional...». Con el código real, 3 de 3 rondas: una crea (`exit=0`) y la otra sale con `Error: Ya existe un profesional; en esta versión solo puede haber uno.` y `exit=1`; la base queda con 1 profesional.
- **Gravedad:** el índice sigue impidiendo el segundo profesional (no hay corrupción), pero la protección contra la carrera depende de un detalle que ninguna prueba fija. Un refactor «inocente» a `BEGIN` reintroduce un traceback.
- **Recomendación (tarea nueva, 15 min):** prueba que fije la sentencia exacta (p. ej. `con.set_trace_callback` y exigir que la primera sentencia sea `BEGIN IMMEDIATE`), o una prueba con dos subprocesos reales como la de arriba.

### R-02 (baja) — Base anterior a T-08d: estado a medias, 500 en cualquier login, y `init-db` revienta con 2+ profesionales
- **Evidencia (servidor real, `flask run` puerto 5082, base creada con el `schema.sql` de `f06bdb5^` + `create-professional`):**
  1. `init-db` sobre esa base termina con éxito («Base de datos inicializada.») y **sí crea el índice `un_solo_profesional`** pero **no la columna** (`PRAGMA table_info(usuarios)` sin `sesion_version`). Queda un esquema mezclado.
  2. `POST /login` con credenciales correctas: **500**; con un correo inexistente: **500** también (el `SELECT ... sesion_version` corre antes de saber si el correo existe). `POST /registro` funciona (302): se pueden crear cuentas que luego no pueden entrar.
  3. Una cookie antigua (`{"usuario_id": 1}`) o sin `usuario_id` en una ruta protegida da 302 a `/login` (no consulta la base): bien.
  4. Base antigua con **2 profesionales** (el revisor de T-04 y T-07 los creó así): `init-db` sale con código 1 y traceback `sqlite3.IntegrityError: UNIQUE constraint failed: usuarios.rol`. El README manda borrar la base, pero no menciona este caso.
- **Evaluación:** aceptable mientras no haya datos reales y el README lo advierta (D-006). Lo que README llama «fallaría al iniciar sesión con `no such column`» subestima el efecto: falla *todo* intento de login, incluso con credenciales equivocadas, y `init-db` da un falso «OK».
- **Recomendación (decisión humana, absorber en T-14 o antes):** que `init-db` detecte `usuarios` sin `sesion_version` y termine con un mensaje claro («tu `agenda.db` es anterior a T-08d; bórrala»), o una migración `ALTER TABLE usuarios ADD COLUMN sesion_version INTEGER NOT NULL DEFAULT 0` (SQLite lo admite; D-006 pide decisión para migraciones). Mientras tanto, añadir una línea al README sobre el caso de varios profesionales.

### R-03 (baja) — Logout con `database is locked`: 500 y la sesión sigue viva
- **Evidencia:** conexión externa con `BEGIN IMMEDIATE` abierta; `POST /logout` con cookie y token válidos: **500 tras 5,0 s**, sin `Set-Cookie`; durante el bloqueo un `GET /paciente` con la misma cookie da 200 (lecturas permitidas); al liberar el bloqueo la cookie sigue valiendo (200). Traceback `sqlite3.OperationalError: database is locked` en el log.
- **Evaluación:** es el comportamiento correcto desde el punto de vista de seguridad (falla cerrado respecto de la intención del usuario: ve un error y sabe que no salió). La alternativa «limpiar la cookie igualmente» sería peor: el usuario creería haber salido mientras una copia robada sigue válida, que es justo lo que D-022 quiere evitar. Es la misma conducta de T-05/T-07 ante bloqueos.
- **Recomendación:** no cambiar la lógica. Un manejador 500 en español (ya previsto en T-13) bastaría; opcional más adelante: reintentar el UPDATE una vez.

### R-04 (baja) — Un login que corre a la vez que un logout puede nacer ya revocado
- **Evidencia:** prueba temporal en la copia: `check_password_hash` intercalado con un `UPDATE usuarios SET sesion_version = sesion_version + 1` (otro navegador cierra sesión durante los ~0,15 s de scrypt). Resultado: `POST /login` → 302 `/paciente`, y `GET /paciente` → 302 `/login` sin mensaje.
- **Causa:** `buscar_usuario_por_credenciales` lee `sesion_version` *antes* de verificar la contraseña.
- **Gravedad:** muy improbable (mismo usuario, dos aparatos, ventana de ~150 ms) y falla del lado seguro (queda sin sesión, vuelve a entrar). **Recomendación:** backlog T-14: releer la versión justo antes de `iniciar_sesion`, o aceptarlo documentado.

### R-05 (informativa) — Logout y varios aparatos (consecuencia aceptada de D-022 B): confirmada y documentada
- **Evidencia:** dos logins del mismo usuario (cookies A y B, ambas 200); logout en A → A **y** B dan 302 a `/login`; `sesion_version` quedó en 1. Documentado en D-022 «Implementada» («cerrar sesión en un aparato cierra todas las sesiones de ese usuario») y probado en `test_login.py`. README no lo dice al usuario: opcional.
- **Carreras (servidor real, hilos con curl):** 6 logouts simultáneos con la misma cookie × 5 rondas: todos 302 y la versión subió **1** por ronda (los demás ya llegaban revocados); 4 hilos haciendo `GET` mientras otro hace logout: 77 redirecciones, 3 respuestas 200 (las que ya habían validado) y el logout 302; al final la cookie no sirve. Si dos logouts pasaran la validación a la vez, el `UPDATE` atómico suma 2: inocuo. Sin tracebacks en el log del servidor.

### R-06 (baja) — README no menciona que `create-professional` se niega con un segundo profesional
- La sección «Crear la cuenta del profesional» no dice que solo puede haber uno ni qué responde (`Error: Ya existe un profesional; ...`, código 1). El aviso de borrar `agenda.db` sí está. Dos líneas de README bastan. **Recomendación:** backlog (documentación, T-14).
- Verificado: mensaje en español, código de salida 1, la contraseña no se imprime (`grep` de la contraseña en la salida de los dos procesos: sin coincidencias), `Profesional creado: ...` solo en el éxito. Aceptado y documentado: la contraseña se pide antes de comprobar si ya hay profesional.

### R-07 (informativa) — Pruebas con dos profesionales: aisladas y razonables
- `permitir_varios_profesionales` hace `DROP INDEX IF EXISTS` en la base de *esa* prueba. La plantilla es una base en memoria de sesión y cada prueba recibe una copia (`backup`), así que el `DROP` no la contamina: la suite pasa completa en orden normal (1216 OK; no repetí el orden aleatorio). Se usa en 5 puntos (`pro2` y `nuevo_profesional` en `test_horas.py` y `test_horas_libres.py`).
- **¿Dejan de modelar producción?** Sí en un sentido: producción solo admite uno. Pero esas pruebas verifican que el código filtra por `profesional_id` (defensa en profundidad: eliminar la hora de otro, solape entre profesionales, aislamiento del panel); siguen siendo útiles si D-023 se revierte o se llega a C. No hace falta reescribirlas. Las pruebas del comportamiento real de un solo profesional están en `test_esquema.py` y `test_crear_profesional.py`.
- Mejora menor (backlog): el ayudante vive en `tests/test_login.py` y los demás archivos lo importan de ahí; cuando T-09 lo necesite, moverlo a `conftest.py` como fixture.

### R-08 (informativa) — Interacción con T-09..T-12 y T-14
- No hay en `app/` ninguna consulta del tipo «el profesional» por rol (`grep` de `rol =`/`'profesional'` fuera de `auth.py`: solo el `SELECT 1` de `create-professional`). Las notificaciones deben dirigirse al `horas.profesional_id` de la hora (no a `SELECT id FROM usuarios WHERE rol='profesional'`): con D-023 ambas darían lo mismo hoy, pero la primera sobrevive a una futura opción C. Nota para T-09. No hay ruta de cambio de rol en `app/` (`grep` de `UPDATE usuarios`: solo el UPDATE del logout), por lo que el índice solo se ejercita por SQL directo.
- T-14: añadir la detección de esquema antiguo (R-02) y `SESSION_COOKIE_SECURE`.

### R-09 (informativa) — Cambio de contraseña futuro
- D-022 B dice que el cambio de contraseña incrementa la versión; la función no existe (SPEC §8: sin recuperación). La nota «Implementada» y PROGRESS ya lo dejan escrito. **Recomendación:** si aparece, añadir un `UPDATE ... sesion_version = sesion_version + 1` en la misma transacción que el cambio y una prueba «cookie previa muere». No requiere tarea ahora.

### R-10 (informativa) — Mutantes equivalentes y hechos de SQLite confirmados
- SQLite con afinidad INTEGER acepta como iguales `'1'`, `1.0`, `True` y también `'1 '` (con espacio): `SELECT ... WHERE v = ?` devolvió 1 fila para los cuatro y 0 para `b'1'`. La validación de tipos de `usuario_actual()` ocurre **antes** de la consulta (`_es_id_valido`/`_es_version_valida`), y con cookie forjada firmada contra un servidor real todos los casos dieron 302 a `/login` (ver tabla de abajo).
- Sobrevivientes equivalentes: `a3` (id `0` aceptado: ningún usuario tiene id 0) y `a18` (el logout toma el id de la sesión sin pasar por `usuario_actual()`: `@login_requerido` ya garantiza que coinciden).

## Qué verifiqué ejecutando

| Punto | Resultado |
|---|---|
| Suite | `python3 -m pytest -q` en copia: **1216 passed**. `pytest --collect-only`: 1216. PROGRESS dice 1157 + 59 = 1216: coincide. |
| 7 líneas eliminadas de `tests/` | Las 7 son reemplazos: lista de columnas NOT NULL (+`sesion_version`), SQL exacto de `usuarios`, docstring de «otros objetos» (ahora permite el índice), 2 imports (+`permitir_varios_profesionales`), `test_la_sesion_guarda_solo_el_id...` renombrado con `sesion_version` y su `assert set(datos)`. Sin pérdida de cobertura. |
| Hora de PROGRESS vs commit | Entrada `19:44`; commit `19:44:46 -0300`. Coherente. |
| D-022 de punta a punta (servidor real, `flask run --no-reload`, curl) | Registro, login 302 → `/paciente`, acceso 200, copia de la cookie 200, logout 302 (nueva cookie solo con CSRF); cookie original y copia → 302 `/login`; cookie posterior al logout → 302; segundo logout con cookie vieja → 302 `/login`. `sesion_version` 0→1. |
| Cookies forjadas (firmadas con la `SECRET_KEY`) en `/paciente` | versión correcta 200; mayor 302; menor 302; `'1'`, `True`, `1.0`, `None`, `-1`, `2**63`, `2**63-1` (no coincide), `2**64`, ausente, id `'1'`, id `True`, id `0`, id lista, versión lista/dict, id `2**63`, usuario inexistente: **todos 302**; id 2 con versión de otro usuario (1) 302 y con la suya (0) 200; usuario borrado 302; paciente a `/profesional` 403. 0 tracebacks en el log. |
| Carreras | Ver R-05. Login↔logout: R-04. |
| `database is locked` en logout | R-03. |
| Base antigua | R-02 (servidor real). |
| D-023 SQL | `sqlite_master`: `CREATE UNIQUE INDEX un_solo_profesional ON usuarios (rol) WHERE rol = 'profesional'`; `PRAGMA index_list`: único, `origin 'c'`, parcial. 300 pacientes insertados sin error; segundo profesional por SQL y `UPDATE usuarios SET rol='profesional'` → `IntegrityError: UNIQUE constraint failed: usuarios.rol`; borrado/degradado el profesional se puede crear/subir otro. |
| `create-professional` dos veces y en paralelo | 3 rondas de dos procesos simultáneos: exactamente 1 profesional, el otro sale con el mensaje en español y código 1. Contraseña no impresa. |
| Mutaciones de `schema.sql` (15; ejecutadas contra `test_esquema.py` + `test_db.py`) | **15/15 mueren**: quitar `WHERE` (12 fallas), quitar columna (6), `DEFAULT 1` (4), columna nullable (5), nombre de índice distinto (5), `UNIQUE` sin parcial (12), índice no único (5), `WHERE rol='paciente'` (14), índice sobre `email` (5), tipo `TEXT` (4), sin índice (8), `WHERE` con `AND id > 0` (1: solo el SQL exacto), `WHERE rol IN (...)` (1: solo el SQL exacto), columna en otro orden (2), `COLLATE NOCASE` en el índice (1: solo el SQL exacto). El SQL se compara sobre `init_db` real (marcador `base_real`). |
| Mutaciones de `auth.py` (20 propias, distintas de las 21 del implementador; suite completa `-x`) | **17 mueren, 3 sobreviven**: `a3` y `a18` (equivalentes, R-10) y **`a20` (R-01, real)**. Mueren: límite de versión `2**64` y de id `2**64`, `<=` en vez de `=` en la versión, sin `session.clear()` en logout y en login, versión guardada como `str`, logout sin `@login_requerido`, logout por GET, existencia buscando `paciente`, salida con código 0, imprimir la contraseña, `es_profesional_duplicado` sin `sqlite_errorcode`, mensaje en inglés, `commit` omitido, caché de `g` anulada, login que lee siempre versión 0, `es_correo_duplicado` demasiado amplia. |
| Documentación | Diff de ARCHITECTURE.md: 2 líneas añadidas, solo en `usuarios` (columna e índice): autorizado. DECISIONS: 4 líneas añadidas (D-022/D-023 con «Implementada: T-08d, 2026-10-08 19:44»), texto original intacto. La razón de no incrementar en el login es coherente con D-022 B: B nombra «logout y cambio de contraseña», no el login. |

## No verifiqué

- Navegador real (solo curl y el cliente de pruebas), HTTPS, Windows/macOS.
- Orden aleatorio y simulación Windows de la suite (me fío de PROGRESS; solo corrí el orden normal).
- Bloqueos de escritura prolongados de otras causas (disco lleno, `-wal`): la base usa el modo por defecto.
- `create-professional` con una terminal interactiva real (la contraseña entra por tubería, con el aviso de Click).

## Incidente del Revisor

Por error ejecuté `git checkout f06bdb5^` en el repo (para comparar la prueba antigua), lo que dejó HEAD desprendido un instante. Lo revertí de inmediato con `git checkout agentes/loop`: rama `agentes/loop`, HEAD en `f06bdb5`, `git status` limpio (sin cambios en el árbol). Las mutaciones y experimentos anteriores ya habían usado copias, y no hubo ninguna después del incidente. No hice commit.
