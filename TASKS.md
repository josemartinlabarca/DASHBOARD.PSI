# TASKS

Estados: `PENDIENTE` · `EN CURSO` · `HECHA` · `BLOQUEADA`

Cada tarea tiene un **criterio de término** verificable. Un agente solo marca
`HECHA` cuando ese criterio se cumple y `pytest` pasa.

---

## Fase 1 — Base

### T-01 — Esqueleto del proyecto
- **Estado:** HECHA
- **Depende de:** —
- **Qué:** Si no existe, `git init` con `.gitignore` (venv, `*.db`, `outbox.log`, `__pycache__`). Crear `app/` con fábrica Flask, `requirements.txt`, `tests/conftest.py` con app de prueba y base temporal.
- **Término:** `pytest` corre (aunque sea con una prueba trivial) y `flask --app app run` levanta una página de inicio.

### T-02 — Base de datos
- **Estado:** HECHA
- **Depende de:** T-01
- **Qué:** `schema.sql` según `ARCHITECTURE.md`, `db.py` y comando `init-db`.
- **Término:** Prueba que crea la base y verifica que existen las 3 tablas con sus restricciones.

### T-02b — Endurecer configuración (hallazgos de la revisión de T-01)
- **Estado:** HECHA
- **Depende de:** T-02
- **Qué:** (1) `SECRET_KEY`: el valor por defecto solo se acepta en modo debug/testing; en otro caso la app falla al arrancar si falta la variable de entorno. (2) Fijar versión de `pytest` en `requirements.txt` y registrar la dependencia en `DECISIONS.md` (D-005). (3) Documentar `SECRET_KEY` en `README.md`.
- **Término:** Pruebas: arranque sin `SECRET_KEY` fuera de debug/testing falla; en testing funciona. Debe quedar HECHA **antes** de T-03.
- **Origen:** REVIEW de T-01, hallazgos 1 (media) y 2 (baja).

### T-02d — Corregir efectos de T-02b en comandos CLI y README (hallazgos de la revisión de T-02b)
- **Estado:** HECHA
- **Depende de:** T-02b
- **Qué:** (1) **Defecto:** `flask --app app init-db` falla sin `SECRET_KEY` fuera de debug, y el README lo manda ejecutar primero. Hacer que los comandos CLI de mantenimiento (`init-db`, y luego `create-professional`, `send-reminders`) no exijan `SECRET_KEY` (que solo se necesita para servir peticiones), manteniendo la exigencia en `flask run` fuera de debug; registrar la decisión en `DECISIONS.md` (D-007 está reservada para T-02c, usa D-008). (2) Tratar una `SECRET_KEY` de solo espacios como ausente. (3) README: mostrar `export SECRET_KEY=$(python3 -c "...")` sin `<>`, y advertir que `FLASK_DEBUG` no debe activarse en un entorno expuesto. (4) `DECISIONS.md`: quitar la frase desactualizada de D-006 sobre D-005 y ordenar D-005 antes de D-006. (5) Pruebas: `init-db` sin clave ni debug funciona; `FLASK_DEBUG` con `0`/`false` sin clave falla; clave pasada por `test_config` se respeta; clave de espacios falla.
- **Término:** El recorrido literal del README (venv → pip install → init-db → run --debug) funciona en un entorno limpio sin `SECRET_KEY`; `pytest` pasa. Debe quedar HECHA **antes** de T-03.
- **Origen:** REVIEW de T-02b, hallazgos 1 (media), 2–6 (bajas).

### T-02c — Reforzar integridad del esquema (hallazgos de la revisión de T-02)
- **Estado:** HECHA — decisión humana APROBADA (D-007, opciones A–F, 2026-10-08); implementada en esta tarea, incluida la edición autorizada de `ARCHITECTURE.md` (opción F).
- **Depende de:** T-02
- **Qué:** Tras aprobar el humano las propuestas en `DECISIONS.md` (D-007) y actualizar `ARCHITECTURE.md`: (1) CHECK que ate `estado`, `paciente_id` y `reservada_en` en `horas` (reserva consistente, regla §4.1); (2) CHECK de `notificaciones.tipo`; (3) CHECK de dominio en `duracion_min > 0` y `recordatorio_enviado IN (0,1)`; (4) evaluar `UNIQUE(profesional_id, inicio)` como refuerzo parcial de §4.3. Además, completar las pruebas de `NOT NULL` y de las FK `horas.paciente_id` y `notificaciones.hora_id`, y hacer que `test_comando_init_db` compare columnas. También decidir si `usuarios.email` lleva `COLLATE NOCASE` (la UNIQUE de SQLite distingue mayúsculas y hoy la unicidad depende solo de `normalizar_email()`; hallazgo 3 de la revisión de T-03) y, aprobado por el humano, añadir a `ARCHITECTURE.md` el módulo `seguridad.py` (`# protección CSRF global (token en sesión, before_request)`, y su fila en la tabla de módulos).
- **Término:** Pruebas nuevas fallan si se quita cualquiera de los CHECK/NOT NULL/FK; `pytest` pasa. Debe quedar HECHA **antes** de T-05.
- **Origen:** REVIEW de T-02, hallazgos 1–6 (ver historial git de `REVIEW.md`).

## Fase 2 — Usuarios

### T-02f — Aplicar al esquema las decisiones D-016 y D-017 (aprobadas 2026-10-08 01:04)
- **Estado:** HECHA — decisiones humanas **APROBADAS** (D-016 opción 1, D-017 opción 2). Autorizada a modificar `app/schema.sql` y el "Modelo de datos" de `ARCHITECTURE.md` **solo** para estos dos cambios.
- **Depende de:** T-02c
- **Qué:** (1) `notificaciones.hora_id INTEGER REFERENCES horas (id) ON DELETE SET NULL` (D-016). (2) En `horas`: `CHECK (inicio GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]')` (D-017). (3) Reflejarlos en `ARCHITECTURE.md` y añadir en el README/PROGRESS la recomendación de borrar `agenda.db` (ya explicada por D-006). (4) Pruebas: reservar → cancelar → eliminar la hora funciona y deja las notificaciones con `hora_id` NULL y su mensaje intacto; eliminar una hora **sin** notificaciones sigue funcionando; los cinco formatos de la revisión (`...T10:00`, `... 10:00`, `...T10:00:00`, `...-03:00`, `...-04:00`) se rechazan salvo el canónico; el canónico se acepta y su duplicado lo rechaza la UNIQUE; una fecha con forma válida pero inexistente (p. ej. mes 13) **se acepta** a nivel de base de datos (lo valida la aplicación en T-05) y eso queda documentado en una prueba. Ninguna prueba existente se debilita; las que insertaban `inicio` en otro formato se corrigen a datos válidos.
- **Término:** Pruebas nuevas fallan si se quita el `ON DELETE SET NULL` o el CHECK del formato; `python3 -m pytest` pasa.
- **Origen:** D-016 y D-017 (revisión de T-02c, hallazgos 1 y 3).

### T-02g — Cerrar el hueco del carácter nulo en `horas.inicio` (D-018, aprobada 2026-10-08 01:16)
- **Estado:** HECHA — decisión humana **APROBADA** (D-018). Autorizada a modificar `app/schema.sql` y la línea `inicio` de `ARCHITECTURE.md` **solo** para esto.
- **Depende de:** T-02f
- **Qué:** (1) Añadir `AND instr(inicio, char(0)) = 0` al CHECK de formato de `horas.inicio` (D-018) y reflejarlo en `ARCHITECTURE.md`. (2) **Reemplazar** la prueba `test_limitacion_conocida_nul_tras_el_prefijo_canonico_pasa_el_check` (que documenta el defecto aceptándolo y fallaría sin explicación al corregirlo) por pruebas que exijan el rechazo: NUL al final, NUL solo tras el prefijo, NUL con texto, NUL al inicio y NUL en medio; el canónico se acepta. (3) Cerrar los huecos de las mutaciones del GLOB que dejaban todo en verde (hallazgo 5 de la revisión de T-02f): una prueba **por posición** de carácter inválido (16 de los 19 caracteres no son separadores: sustituir cada dígito por una letra y cada separador por otro carácter), rechazar el espacio como separador (`2026-12-01 10:00:00`), y un comodín en el año. (4) En la prueba de control con claves foráneas apagadas, afirmar el estado del `PRAGMA` tras apagarlo (hallazgo 7).
- **Término:** Las mutaciones "quitar `instr(...)`", "GLOB con `[T ]`", "comodín en el año" y "quitar el CHECK de `inicio`" hacen fallar al menos una prueba; `python3 -m pytest` pasa. Debe quedar HECHA **antes** de T-02e y de T-05.
- **Origen:** D-018 (revisión de T-02f, hallazgos 1, 2, 5 y 7).

### T-02e — Fijar el conjunto exacto de valores del esquema en las pruebas (hallazgo de la revisión de T-02c)
- **Estado:** HECHA
- **Depende de:** T-02c, T-02f, T-02g
- **Qué:** Las pruebas de T-02c no detectan una restricción **ampliada**: añadir `'otro'` al CHECK de `notificaciones.tipo`, `'cancelada'` al de `horas.estado`, comparar `rol` con `lower()` o añadir un tope superior a `duracion_min` deja las 187 pruebas en verde (comprobado por el orquestador y por el revisor). Hacer que las pruebas fijen el conjunto exacto: la técnica más simple es comparar el SQL de cada tabla de `sqlite_master` con el esperado (normalizando espacios), o probar valores vecinos inválidos. Si D-016 o D-017 cambian el esquema, la comparación debe reflejarlo.
- **También (hallazgo 6 de la revisión de T-02f):** añadir `ON UPDATE CASCADE` a `notificaciones.hora_id` hoy pasa sin que ninguna prueba falle porque la prueba de `PRAGMA foreign_key_list` solo lee `on_delete`: que compare también `on_update` (y la columna entera de `foreign_key_list`).
- **También (hallazgo R-07 de la revisión de T-02g):** si la prueba compara el SQL de `sqlite_master`, el CHECK de `inicio` esperado debe incluir `AND instr(inicio, char(0)) = 0` (D-018).
- **Término:** Las mutaciones "ampliar `tipo` con `'otro'`", "ampliar `estado` con `'cancelada'`", "`rol` con `lower()`" y "tope superior en `duracion_min`" hacen fallar al menos una prueba; `python3 -m pytest` pasa. Debe quedar HECHA **antes** de T-05.
- **Origen:** REVIEW de T-02c, hallazgo 2.

### T-03 — Registro de pacientes
- **Estado:** HECHA
- **Depende de:** T-02b, T-02d
- **Qué:** Ruta `/registro` con formulario, validación y hash de contraseña. Correo único.
- **Término:** Pruebas: registro válido, correo duplicado rechazado, contraseña guardada con hash.

### T-03b — Endurecer el registro (hallazgos de la revisión de T-03)
- **Estado:** HECHA
- **Depende de:** T-03
- **Qué:**
  1. **Windows sin `tzdata` (media):** `ZoneInfo("America/Santiago")` falla al importar `auth.py` en Windows sin el paquete, rompiendo incluso `init-db`. Añadir `tzdata; sys_platform == "win32"` a `requirements.txt` (D-012) y no crear el `ZoneInfo` al importar el módulo, sino en el momento de usarlo.
  2. **Normalización del correo (media):** extraer `normalizar_email()` (NFKC + `casefold` + rechazo de caracteres de control y de espacios internos) en un lugar reutilizable por el login y `create-professional` (D-013). Pruebas con las variantes que el revisor encontró: ancho completo, `ß`/`ss`, carácter de ancho cero.
  3. **Tamaño de la petición (media):** fijar `MAX_CONTENT_LENGTH` (~16 kB) con prueba (413) y entrada en `DECISIONS.md` (D-014).
  4. **Pruebas que no detectaban mutaciones (baja):** CSRF también para PUT/PATCH/DELETE; el escape de `email` en `value="..."` (no solo el nombre); que el hash use los parámetros de scrypt por defecto (prefijo y costo mínimo); que la prueba del duplicado falle si se añade un SELECT previo, o corregir su docstring.
  5. **Documentación (baja):** añadir a D-009 que un POST a una ruta inexistente responde 400 y no 404/405 porque el CSRF corre antes del enrutamiento.
- **Término:** Cada mutación citada en el punto 4 hace fallar al menos una prueba; `python3 -m pytest` pasa; el módulo importa sin error simulando ausencia de zona horaria del sistema (`PYTHONTZPATH` vacío) cuando `tzdata` está instalado, y `requirements.txt` lo declara para Windows. Debe quedar HECHA **antes** de T-04.
- **Origen:** REVIEW de T-03, hallazgos 1, 3, 4, 5 y 7 (ver historial git de `REVIEW.md`).

### T-03c — Cerrar los hallazgos de la revisión de T-03b
- **Estado:** HECHA (2026-10-08 11:28) — decisión humana del punto 2 **APROBADA** (D-015, opción 2, 2026-10-08 00:38).
- **Depende de:** T-03b
- **Qué:**
  1. **Pruebas de `normalizar_email` (media):** el implementador afirmó que quitar la primera NFKC era "equivalente"; es **falso** (cambia el resultado en 637 puntos de código y rompe la idempotencia, comprobado por el orquestador). Añadir pruebas con esos casos (p. ej. `ϒ` U+03D2) y una prueba **exhaustiva de idempotencia** sobre todos los puntos de código; corregir en `PROGRESS.md` la frase falsa de la entrada de T-03b.
  2. **Política de caracteres del correo (media, D-015 opción 2, aprobada):** hoy solo se rechazan las categorías Cc, Cf y los espacios; pasan selectores de variación, U+034F, rellenos hangul, braille en blanco, U+FFFD, combinantes sueltos y puntos de uso privado o no asignados (los Cn dependen de la versión de Python). Implementar la opción 2: rechazar todas las categorías `C*` y las marcas `Mn`, `Mc`, `Me` tras NFKC; las pruebas que fija D-015 (precompuesto y descompuesto se normalizan igual; combinante suelto rechazado). Los homoglifos siguen aceptados (riesgo aceptado, a revisar en T-14).
  3. **D-014 (media):** corregir el texto: afirma que una ruta futura puede subir el límite, pero el `before_request` del CSRF lee el cuerpo antes y da 413 igualmente; indicar el mecanismo real (configuración global o excepción explícita).
  4. **`tzdata` incondicional (baja):** quitar el marcador `sys_platform == "win32"` (Alpine, distroless y Linux mínimos sin `/usr/share/zoneinfo` fallarían en el primer registro) y actualizar D-012. Añadir una prueba HTTP de "500 y cero usuarios" cuando faltan los datos de zona horaria, una prueba de la rama "con `tzdata` instalado y `PYTHONTZPATH` vacío funciona", que `test_zona_chile_se_crea_una_sola_vez` no deje la caché poblada para otras pruebas, y una prueba que falle si se borra la línea de `tzdata` de `requirements.txt`.
  5. **Separadores y plegados (baja):** pruebas con U+2028, U+2029, U+1680 y marcas bidi (cambiar `isspace()` por `== " "` hoy no rompe nada); ampliar D-013 con `ς`, `ſ`, `K` (kelvin), `İ` e `ı`.
  6. **Entradas no `str` (baja):** que `normalizar_email` lance `ValueError` (no `TypeError`) o documentar el contrato.
  7. **Suite lenta (baja):** pasó de 0,2 s a ~5 s por el scrypt real en cada registro. Fixture `autouse` con hash rápido, salvo en pruebas marcadas `hash_real` que verifican el hash; sin debilitar las pruebas de seguridad.
  8. **D-010 desactualizada (baja):** actualizarla para que remita a D-012 y D-013.
  9. **`IntegrityError` genérico en el registro (baja, hallazgo 7 de la revisión de T-02c):** hoy cualquier violación de la base de datos muestra el mensaje de "correo duplicado"; distinguir la violación de `UNIQUE` sobre `email` de cualquier otra (que debe tratarse como error interno, no como duplicado) y probarlo.
- **Término:** Las mutaciones "sin primera NFKC", "sin segunda NFKC", "`isspace()` por `== " "`" y "borrar `tzdata` de requirements.txt" hacen fallar al menos una prueba; la prueba de idempotencia pasa; `python3 -m pytest` pasa y es notablemente más rápida. Debe quedar HECHA **antes** de T-04.
- **Origen:** REVIEW de T-03b (ver historial git de `REVIEW.md`).

### T-04 — Login, logout y control de rol
- **Estado:** HECHA
- **Depende de:** T-03b, T-03c, T-02c
- **Qué:** `/login`, `/logout`, decoradores `solo_paciente` y `solo_profesional`, comando `create-professional`. Debe además: (a) usar `normalizar_email()` de T-03b; (b) llamar a `session.clear()` y regenerar el token CSRF al iniciar y cerrar sesión (evita fijación de sesión); (c) guardar en la sesión **solo el id del usuario**; (d) fijar `SESSION_COOKIE_SAMESITE="Lax"`; (e) un mensaje **único** para credenciales inválidas, sin distinguir correo inexistente de contraseña errónea; (f) absorber los ítems del backlog T-02d #2 y #3. **Añadidos por la revisión de T-03c:** (g) el login captura el `ValueError` de `normalizar_email` y responde con el **mismo** mensaje genérico, calculando un hash falso para igualar tiempos (R-07); (h) `create-professional` reutiliza `es_correo_duplicado` de `app/auth.py` (R-08); (i) la fixture de hash rápido (D-019) debe cubrir cualquier módulo nuevo que importe `generate_password_hash`/`check_password_hash`, añadir `--strict-markers` a `pytest.ini` y una prueba que falle si el hash rápido no está activo (R-06); (j) el campo de correo de `registro.html` y de `login.html` no puede usar `type="email"` con validación del navegador si bloquea `señor@…` (R-04): usar `type="text"` con `inputmode="email"` y `autocomplete="email"`, y comprobarlo en un navegador.
- **Término:** Pruebas: login correcto/incorrecto, paciente no accede a `/profesional` (US-3), el token CSRF cambia tras el login, el mensaje de error es idéntico para correo inexistente y contraseña errónea.

### T-04b — Cerrar hallazgos de la revisión de T-04 (sin decisiones humanas)
- **Estado:** HECHA
- **Depende de:** T-04
- **Qué:** (1) **R-01 (media):** pruebas de CSRF en `/login` (POST sin token → 400; con token de otra sesión → 400; el token anterior al login ya no sirve); la mutación "eximir `/login` del CSRF" debe hacer fallar una prueba. (2) **R-03 (media):** `Cache-Control: no-store` (y `Pragma: no-cache`) en toda respuesta de páginas privadas y en `/login` tras autenticarse, con pruebas; verificar que el botón «atrás» tras el logout no muestra el panel (documenta lo que se pueda comprobar). (3) **R-05 (baja):** una prueba que compare cabeceras y código de estado entre los distintos fallos de login, y el borde del id de sesión (`2**63 - 1`, `2**63`, `0`, `-1`) sin 500. (4) **R-07 (baja):** el nombre (registro y `create-professional`) rechaza caracteres de control, saltos de línea, ESC y marcas bidi (categorías `C*`), con mensaje en español; pruebas. (5) **R-06 (baja):** crear `hash_falso()` al construir la app (o al primer arranque) para que el primer login de un correo inexistente no sea más lento y no se calcule varias veces en paralelo; prueba que lo fije.
- **Término:** Las mutaciones "eximir `/login` del CSRF", "quitar `no-store`", "nombre con salto de línea aceptado" y "id `2**63` sin validar" hacen fallar al menos una prueba; `python3 -m pytest` pasa. Debe quedar HECHA **antes** de T-05.
- **Origen:** REVIEW de T-04 (R-01, R-03, R-05, R-06, R-07).

## Fase 3 — Horas

### T-05 — Profesional agrega y elimina horas
- **Estado:** HECHA
- **Depende de:** T-04, T-04b, T-02c, T-02e, T-02f, T-02g
- **Qué:** Formulario y rutas de US-4 y US-5 con reglas 2, 3 y 4.
- **Requisitos que vienen de las revisiones de T-02c (resolver al implementar):** (a) **D-016 y D-017 ya están decididas** (T-02f las aplica al esquema): la aplicación debe guardar `inicio` siempre en formato canónico `YYYY-MM-DDTHH:MM:SS` hora local de Chile, validar que la fecha exista y no sea pasada, y poder eliminar una hora que fue reservada y cancelada; (b) la comprobación de solape (regla §4.3 y §4.5) debe hacerse dentro de una transacción `BEGIN IMMEDIATE`, porque el esquema solo impide inicios idénticos, no solapes parciales; (c) pruebas del flujo real: reservar → cancelar → eliminar la hora debe funcionar.
- **Consecuencia de D-016 (revisión de T-02f, hallazgo 3):** `INSERT OR REPLACE` / `REPLACE INTO` sobre `horas` borra y reinserta la fila, lo que **dispara `ON DELETE SET NULL` y pierde el vínculo de las notificaciones sin avisar** (comprobado por el revisor). Prohibido en todo el código sobre `horas`: usar `INSERT`, `UPDATE` o `DELETE` explícitos (una prueba o una comprobación sobre el código fuente debe vigilarlo). `UPDATE` y `ON CONFLICT DO UPDATE` no lo disparan. Además `inicio` solo se guarda como resultado de formatear un `datetime` (nunca texto crudo del formulario).
- **Nota (revisión de T-02g, R-02/R-09):** el esquema acepta fechas de forma válida pero imposibles (`2026-13-45T99:99:99`); la validación del calendario es **solo** de la aplicación y debe ocurrir *antes* de insertar. Un `IntegrityError` por formato debe traducirse a un mensaje en español, no a un 500.
- **Nota (revisión de T-02e, R-04):** el esquema acepta en `duracion_min` valores no enteros (`'abc'`, `0.5`, `1e30`, BLOB) porque D-007 solo exige `> 0`; la aplicación debe validar que sea un entero positivo antes de insertar. Añadir `typeof(duracion_min) = 'integer'` al CHECK sería decisión humana (nueva D-0xx) y no se propone todavía.
- **Término:** Pruebas: crear hora válida, rechazar pasado, rechazar solape, no eliminar reservada.

### T-05b — Cerrar hallazgos de la revisión de T-05 (sin decisiones humanas)
- **Estado:** HECHA
- **Depende de:** T-05
- **Qué:** (1) **R-01 (media):** tope superior de fecha futura (máximo 2 años desde hoy, documentado en una decisión nueva de la aplicación, no del esquema) con mensaje en español; hoy `9999-12-31 23:59` se acepta y un solape posterior da 500 por `OverflowError` en `_describir`. Además `_describir`/`mostrar_inicio` no deben poder lanzar excepción con ninguna fila válida del esquema. Pruebas con 2500-01-01, 9999-12-31 y el límite exacto. (2) **R-03 (baja):** el solape se calcula en "reloj de pared" y falla en las dos noches de cambio de horario (50 min a las 23:30 la noche de septiembre pisa las 01:00 y no se detecta; 120 min en abril da falso solape). Calcular inicio y fin como **instantes absolutos** (datetimes con zona, convertidos a UTC) y comparar en Python las horas del mismo profesional; pruebas con ambas noches. Actualizar D-025 (5) con lo que quede. (3) **R-05 (baja):** el botón «Eliminar» del panel lleva token CSRF, y una prueba lo exige (quitarlo hoy no rompe nada); revisar las otras mutaciones que sobreviven (PROGRESS nombra 4; el revisor halló 3 distintas). (4) **R-04 (baja):** doble envío de «Agregar» muestra «se solapa» aunque la hora sí se creó: si la hora solapada es exactamente la misma (mismo inicio y duración, mismo profesional), el mensaje debe decir «Esa hora ya está publicada». Pruebas.
- **Término:** Las mutaciones "sin tope superior", "solape en reloj de pared" y "quitar CSRF del botón Eliminar" hacen fallar al menos una prueba; `python3 -m pytest` pasa. Debe quedar HECHA **antes** de T-06.
- **Origen:** REVIEW de T-05 (R-01, R-03, R-04, R-05).

### T-06 — Paciente ve horas libres
- **Estado:** HECHA
- **Depende de:** T-05, T-05b
- **Qué:** `/paciente/horas` con horas libres futuras ordenadas (US-7).
- **Nota (revisión de T-05b, R-01):** el filtro «futuras» debe usar la hora de Chile (no UTC) y llevar una prueba que lo fije: con el reloj entre «ahora» y «ahora en UTC» (3-4 h de diferencia), una hora de hoy aún futura debe aparecer; la mutación «comparar con la hora UTC» debe hacer fallar una prueba. Reutiliza `ahora_chile()`. Considera mover `a_segundos_utc` y `ahora_chile` a un módulo compartido (p. ej. `app/tiempo.py`, justificado en DECISIONS.md) porque T-07/T-08/T-10 lo necesitan.
- **Término:** Prueba: solo aparecen horas libres y futuras.

### T-07 — Reservar hora
- **Estado:** HECHA
- **Depende de:** T-06
- **Qué:** `POST /horas/<id>/reservar` con UPDATE atómico (D-003) y reglas 1 y 5.
- **Nota (revisión de T-04b, R-10):** acotar el `id` de la ruta (`<int:id>`) a un máximo razonable (< 2**63) para que un id gigante dé 404 y no un 500; con prueba.
- **Nota (revisión de T-05b, R-06):** las reglas de anticipación (24 h, §4) se calculan con instantes absolutos (aware → UTC), nunca con el reloj de pared; pruebas en las noches de cambio de horario. **Nota (revisión de T-06, R-02):** `a_segundos_utc` con `fold=0` no está fijado por ninguna prueba (cambiarlo a `fold=1` no rompe nada): añadir esa prueba en esta tarea.
- **Notas de la revisión de T-06 para esta tarea:** formulario POST por fila con el id de la hora y token CSRF; ruta con `<int>` acotado; doble reserva resuelta con `UPDATE ... WHERE estado='libre'` y revisión de `rowcount`, todo dentro de `BEGIN IMMEDIATE`; volver a comprobar que la hora sea futura con instantes absolutos; la regla 5 (paciente sin dos reservas solapadas) por solape de intervalos; considerar la carrera «el profesional elimina la hora» / «el paciente la reserva» (rowcount = 0 → mensaje amable, no 500).
- **Término:** Pruebas: reserva exitosa; segunda reserva de la misma hora falla; paciente no puede tener dos a la misma hora.

### T-08 — Cancelar reserva
- **Estado:** HECHA
- **Depende de:** T-07
- **Qué:** `POST /horas/<id>/cancelar` con anticipación mínima de 24 h (US-9); la hora vuelve a `libre`.
- **Nota (revisión de T-04b, R-10):** acotar el `id` de la ruta (`<int:id>`) a un máximo razonable (< 2**63) para que un id gigante dé 404 y no un 500; con prueba.
- **Nota (revisión de T-05b, R-06):** las reglas de anticipación (24 h, §4) se calculan con instantes absolutos (aware → UTC), nunca con el reloj de pared; pruebas en las noches de cambio de horario. **Nota (revisión de T-06):** el UPDATE de cancelación filtra por paciente y estado y se revisa `rowcount`; anticipación con instantes absolutos.
- **Añadidos por la revisión de T-07:** (a) **R-01 (media):** el paciente no tiene dónde ver ni cancelar sus reservas hasta T-11; esta tarea incluye una lista mínima «Mis reservas» en `/paciente` (hora, profesional, duración) con botón «Cancelar» por fila (formulario POST con CSRF); T-11 la amplía después con notificaciones; (b) **R-02 (baja):** leer el reloj **después** de obtener el bloqueo `BEGIN IMMEDIATE` (también en `reservar_hora`, T-07): hoy se reservó una hora 1 s después de empezar y `reservada_en` quedó 3 s antes del commit; pruebas; (c) **R-04 (baja):** pruebas de que cada salida de rechazo hace `rollback` (no queda transacción abierta) y de que una excepción inesperada se re-lanza tras `rollback`; hoy las mutaciones que quitan el `rollback` en tres salidas sobreviven; (d) **R-05 (baja):** una prueba de T-07 sobrevive solo con `TZ=America/Santiago` en el equipo: hacerla independiente de la zona del sistema; (e) D-029 (regla de 24 h al reservar) está PENDIENTE del humano: no la implementes; si se aprueba antes, se aplica aquí.
- **Término:** Pruebas: cancelar con >24 h funciona, con <24 h se rechaza, la hora queda libre.

### T-08b — Acelerar la suite de pruebas (R-06 de la revisión de T-07)
- **Estado:** HECHA
- **Depende de:** T-08
- **Qué:** la suite pasó de ~10 s a ~48 s y cada tarea suma 5–6 s. Medir con `pytest --durations=25`, y reducir sin perder cobertura: fixtures de ámbito `module`/`session` para bases de solo lectura, base SQLite en memoria o plantilla copiada (`init-db` una vez y copiar el archivo) en vez de recrear el esquema en cada prueba, no repetir la prueba exhaustiva de idempotencia (2,4 s) en cada entorno, cache de la zona horaria. Prohibido borrar pruebas o debilitar aserciones.
- **Guía del revisor de T-08 (R-03):** con 1117 pruebas la suite tarda ~66 s: el *setup* suma ~34 s (972 pruebas × 35 ms creando la base) y las llamadas ~29 s. Copiar una base plantilla no basta: hay que recortar también el costo de `tests/test_horas.py` y `tests/test_cancelar.py` (reutilizar la aplicación y el cliente, desactivar el hash real cuando no importa, evitar reloj real). Medir con `--durations=15` antes y después. La fixture `zona_del_sistema_fija` (TZ=UTC) debe mantenerse y su compatibilidad con Windows (sin `tzset`).
- **Término:** `python3 -m pytest` pasa con el mismo número de pruebas (o más) y en menos de 30 s; las mutaciones representativas de T-02e, T-05 y T-07 siguen muriendo (re-ejecutar 6 de ellas y mostrarlas).
- **Origen:** REVIEW de T-07, R-06; backlog T-03c R-11, T-04b R-08, T-05 R-12.

### T-08c — Endurecer la infraestructura de pruebas de T-08b (sin decisiones humanas)
- **Estado:** HECHA
- **Depende de:** T-08b
- **Qué:** (1) **R-01 (media):** `tests/conftest.py` usa `/dev/shm` sin comprobar su capacidad; con 12 MB libres la suite se rompe a las ~650 pruebas («database or disk is full») y Docker trae 64 MB por defecto (pico actual 23,5 MB). Usar `/dev/shm` solo si el espacio libre es holgado (≥ 4× el pico medido) y, si no, caer al directorio temporal normal; permitir forzarlo con una variable de entorno; pruebas de la decisión con `shutil.disk_usage` simulado. (2) **R-02 (baja):** crear el directorio con `tempfile.mkdtemp` (nombre impredecible, permisos 0700) y limpiarlo también ante SIGTERM/`atexit`. (3) **R-03 (baja):** `tests/test_zona_horaria.py::test_las_pruebas_anteriores_no_dejan_la_cache_poblada` depende del orden de ejecución (falla en orden aleatorio, ya fallaba antes de T-08b): hacerla independiente (que ella misma limpie y verifique el estado que prueba) sin debilitarla; comprobar que la mutación que deja la caché poblada sigue haciéndola fallar. (4) Actualizar el criterio de D-031: el umbral de 30 s es orientativo (mediciones de 24 a 31 s según el equipo); el criterio firme es «no más de la mitad del tiempo previo a T-08b (63 s)».
- **Término:** la suite pasa en orden normal, inverso y aleatorio (semillas 1–4) y con `/dev/shm` simulado casi lleno; las mutaciones «quitar la comprobación de espacio» y «dejar la caché poblada» hacen fallar al menos una prueba; mismo nº de pruebas o más. Debe quedar HECHA **antes** de T-09.
- **Origen:** REVIEW de T-08b (R-01, R-02, R-03, R-04).

### T-08d — Aplicar D-022 y D-023 al esquema y a la aplicación (decisiones aprobadas)
- **Estado:** HECHA (2026-10-08 19:44) — decisiones humanas **APROBADAS** (D-022 opción B, D-023 opción A, 2026-10-08 19:18). Autorizada a modificar `app/schema.sql` y la tabla `usuarios` de `ARCHITECTURE.md` **solo** para esto.
- **Depende de:** T-08c
- **Qué:** (1) **D-022:** columna `sesion_version INTEGER NOT NULL DEFAULT 0` en `usuarios`; la sesión guarda `(id, versión)`; `usuario_actual()` rechaza si la versión no coincide con la de la base; el logout incrementa la versión (invalida cualquier copia anterior de la cookie); el login guarda la versión vigente. Pruebas: una cookie copiada antes del logout deja de valer; cookies de otro usuario/versión rechazadas; tipos raros en la sesión. (2) **D-023:** `create-professional` se niega con mensaje en español si ya existe un profesional, e índice único parcial `CREATE UNIQUE INDEX IF NOT EXISTS ... ON usuarios (rol) WHERE rol = 'profesional'` en el esquema; pruebas con SQL directo (segundo profesional rechazado por la base). (3) Actualizar `tests/test_esquema.py` (SQL exacto de T-02e, lista de objetos permitidos: ahora hay un índice declarado) y `tests/test_db.py`; mutaciones: quitar el índice, no incrementar la versión en logout, no comparar la versión. (4) Nota D-006: `init-db` no altera tablas existentes → borrar `agenda.db` tras el cambio; documentarlo en README y en una advertencia si es posible.
- **Término:** las 3 mutaciones anteriores hacen fallar al menos una prueba; `python3 -m pytest` pasa. Debe quedar HECHA **antes** de T-09.
- **Origen:** D-022 y D-023 (revisiones de T-04 y de T-07).

### T-08e — Aplicar D-020 y D-029 (decisiones aprobadas)
- **Estado:** HECHA (2026-10-08 20:33) — decisiones humanas **APROBADAS** (D-020 opción B, D-029 opción B, 2026-10-08 19:18). Autorizada a añadir la regla de anticipación al reservar en `SPEC.md` §4 **solo** para esto.
- **Depende de:** T-08c
- **Qué:** (1) **D-029:** reservar solo con más de 24 h de anticipación (mismo criterio que cancelar: instantes absolutos, borde exacto documentado y probado en las dos noches de cambio de horario); mensaje en español claro; `/paciente/horas` no ofrece el botón «Reservar» a las horas con menos de 24 h (o las muestra marcadas «ya no se puede reservar»); regla 5 = solape de intervalos (ya implementada: dejarla documentada en SPEC). Añadir la regla a SPEC §4. Ajustar las pruebas de T-07/T-08 que reservaban a <24 h. (2) **D-020:** `normalizar_email`: fuera de ASCII solo letras y números (categorías `L*` y `N*`) más una lista corta de rellenos explícitamente rechazados (U+3164, U+115F, U+1160, U+2800, U+FFFD, U+FFFC, símbolos U+2400–U+2422, guiones y puntos medios no ASCII U+2010–U+2015, U+00B7); sigue rechazando `C*` y `Mn/Mc/Me` y espacios; `señor@`, tildes, `ü` siguen válidos. Pruebas exhaustivas sobre todos los puntos de código con la lista; D-013/D-015 con nota visible de actualización. (3) Mutaciones: quitar `L*`/`N*`, quitar un relleno, borde de 24 h con `<=`, botón visible a <24 h.
- **Añadidos por la revisión de T-08d:** (4) **R-01 (media):** una prueba que fije que `create-professional` abre `BEGIN IMMEDIATE` *antes* de comprobar si ya hay profesional (cambiarlo por `BEGIN` sobrevive hoy a toda la suite y con él dos `create-professional` simultáneos terminan con traceback `database is locked` en 6 de 6 rondas); la prueba debe ser de comportamiento (dos procesos reales) y no solo de caja blanca; (5) **R-06:** el README debe decir que `create-professional` se niega a crear un segundo profesional (D-023).
- **Término:** las mutaciones anteriores hacen fallar al menos una prueba; `python3 -m pytest` pasa. Debe quedar HECHA **antes** de T-09.
- **Origen:** D-020 (revisión de T-03c) y D-029 (revisión de T-07/T-08).

## Fase 4 — Notificaciones

### T-09 — Notificaciones de confirmación y cancelación
- **Estado:** HECHA
- **Depende de:** T-08, T-08b, T-08c, T-08d, T-08e
- **Qué:** `notificaciones.py`; crear registros y escribir `outbox.log` al reservar y cancelar (US-11, US-13).
- **Nota de revisión de T-02f (`hora_id` puede ser NULL, D-016):** T-09: el mensaje de la notificación debe bastarse solo (fecha, hora y contraparte), porque `hora_id` queda NULL si la hora se elimina (D-016); prueba con la hora eliminada.
- **Notas de la revisión de T-07 (R-09):** el `SELECT` de la hora en `reservar_hora` no trae `profesional_id` (añadirlo si hace falta); las notificaciones se insertan **dentro** de la transacción, antes del `commit`, para que reserva y aviso sean atómicos; en T-11/T-12 no ordenar por `reservada_en` (texto con offset: no ordena bien en la noche de cambio de hora).
- **Notas de la revisión de T-08e (R-10):** el texto de confirmación debe decir hasta cuándo se puede cancelar (inicio − 24 h, hora local de Chile); las notificaciones se insertan dentro de la transacción de reservar y de cancelar (antes del `commit`).
- **Término:** Pruebas: se crean notificaciones para ambas partes y aparece la línea en el log.

### T-10 — Recordatorios 24 h antes
- **Estado:** HECHA
- **Depende de:** T-09
- **Qué:** Comando `send-reminders` (US-12); no repite recordatorios (`recordatorio_enviado`).
- **Nota de revisión de T-02f (`hora_id` puede ser NULL, D-016):** T-10: el recordatorio depende de `horas.recordatorio_enviado`, no de las notificaciones; añadir una prueba con una hora eliminada que tuvo notificaciones.
- **Notas de la revisión de T-08e (R-09):** el recordatorio se define como «falta ≤ 24 h y la hora no empezó», con instantes absolutos, y se prueba el instante exacto de las 24 h (donde aún se puede cancelar y debe recordarse); una reserva hecha entre 24 h y 24 h + el período del cron queda con el recordatorio vencido al confirmarse (aceptado: se envía en la siguiente ejecución); las pruebas de «hora a <24 h» insertan la reserva por SQL porque la aplicación ya no la permite; definir quién gana si cancelación y recordatorio coinciden.
- **Notas de la revisión de T-09 (R-01, R-05, R-08):** (a) `notificaciones.registrar`/`_mensajes` NO sirven para `recordatorio`: cualquier tipo distinto de `confirmacion` produce el texto de «Cancelaste tu hora» e inserta siempre dos filas; T-10 debe añadir su propio texto (y decidir a quién avisa) y una prueba que impida usar un tipo sin mensaje; (b) el log puede quedar con una línea parcial si el disco falla a mitad de escritura, y el orden de las líneas no es el orden de commit entre procesos: no usar el log como fuente de verdad, solo `horas.recordatorio_enviado` y `notificaciones`; (c) marcar `recordatorio_enviado` y registrar el aviso en la misma transacción.
- **Término:** Pruebas con hora a <24 h: envía una sola vez aunque se ejecute dos veces.

## Fase 5 — Interfaz

### T-11 — Dashboard del paciente
- **Estado:** HECHA (2026-10-09 00:14)
- **Depende de:** T-09
- **Qué:** `/paciente` con próxima sesión, historial y campana de notificaciones (US-10).
- **Nota de revisión de T-02f (`hora_id` puede ser NULL, D-016):** T-11: listar notificaciones con `LEFT JOIN` a `horas` y mostrar el mensaje sin enlace cuando `hora_id` es NULL (D-016).
- **Nota (revisión de T-09, R-09):** ordenar las notificaciones por `id` (creciente en el orden de inserción), no por `creada_en` (texto con offset: no ordena bien en la noche de cambio de horario).
- **Nota (revisión de T-10, R-07):** el recordatorio es solo del paciente; las notificaciones se muestran por su `mensaje` (autosuficiente), nunca derivando datos de `hora_id`, que puede apuntar luego a una hora de otro paciente o quedar NULL. Mostrar también las de tipo `recordatorio`.
- **Término:** Prueba de contenido por rol; revisión visual en navegador.

### T-11b — Aplicar D-035 y cerrar los hallazgos de la revisión de T-11
- **Estado:** HECHA
- **Depende de:** T-11
- **Qué:** (1) **D-035 (aprobada):** función compartida `notificaciones.marcar_leidas(db, usuario_id)` y ruta `POST` para «Marcar todas como leídas» (solo si hay no leídas; CSRF; solo las del usuario en sesión; ignora ids recibidos; idempotente; solo rol paciente por ahora, T-12 la reutiliza para el profesional); (2) tope de 20 notificaciones en el panel con el contador de no leídas por una consulta `COUNT` aparte (D-035); (3) R-03: prueba de que las filas con fecha o duración ilegibles se omiten (hoy una mutación que las mete al historial pasa la suite); (4) R-04: el ayudante `filas_de_reservas` de `tests/test_cancelar.py` debe fallar (no devolver `[]`) si la sección «Mis reservas» no existe; (5) R-05: reescribir `test_no_hay_ninguna_accion_para_marcar_como_leida` según D-035; (6) R-06: orden de secciones: «Próxima sesión» y «Mis reservas» antes que las notificaciones, y un enlace/botón «Reservar hora» visible (SPEC §6.3); (7) R-09 (favicon 404) queda para T-13.
- **Término:** pruebas: marcar leídas baja el contador a 0 y solo para ese usuario (otro paciente y el profesional no cambian), CSRF obligatorio, profesional y anónimo no pueden usar la ruta, con 25 notificaciones se ven 20 pero el contador cuenta todas las no leídas; las mutaciones «marcar sin filtro de usuario», «aceptar sin CSRF», «quitar el LIMIT» y «contar solo las 20 visibles» hacen fallar al menos una prueba; `python3 -m pytest` pasa.
- **Origen:** REVIEW de T-11 (R-01…R-06) y D-035.

### T-12 — Dashboard del profesional
- **Estado:** HECHA (2026-10-09 09:35)
- **Depende de:** T-09, T-11b
- **Qué:** `/profesional` con agenda, horas libres y notificaciones (US-6).
- **Nota de revisión de T-02f (`hora_id` puede ser NULL, D-016):** T-12: igual que T-11: `LEFT JOIN` y mensaje sin enlace cuando `hora_id` es NULL (D-016).
- **Nota (revisión de T-08e, R-10):** el profesional puede crear horas a menos de 24 h que ningún paciente podrá reservar: marcarlas en su agenda («no reservable») o avisarlo al crearlas.
- **Nota (revisión de T-09, R-09):** ordenar las notificaciones por `id` (creciente en el orden de inserción), no por `creada_en` (texto con offset: no ordena bien en la noche de cambio de horario).
- **Notas de la revisión de T-11b (R-03, R-07):** (a) `@solo_paciente` da 403 al profesional: necesita su propia ruta POST delgada que llame a `notificaciones.marcar_leidas` y **comparta** con la del paciente la función que redacta el mensaje flash (no duplicarla); (b) con exactamente 20 notificaciones el aviso «Se muestran tus 20 más recientes» sugiere que hay más: usar `LIMIT 21`, recortar a 20 y mostrar el aviso solo si llegó la fila 21, y leer el 20 desde `TOPE_PANEL` (hoy está escrito a mano en la plantilla) tanto en el panel del paciente como en el del profesional; (c) las pruebas dependen de `<h2>Mis reservas</h2>` e `<h2>Historial</h2>` sin atributos: si cambian, actualizar a la vez los ayudantes.
- **Término:** Prueba de contenido por rol; revisión visual en navegador.

### T-13 — Estilo y plantilla base amigable
- **Estado:** HECHA (2026-10-09 10:55)
- **Depende de:** T-11, T-12
- **Qué:** `style.css` con tonos calmados, diseño responsivo, mensajes de error claros.
- **Notas de las revisiones de T-11, T-11b y T-12 (para no perderlas):** (a) clases CSS ya presentes y sin estilo: `campana`, `no-leida`, `leida`, `notificaciones`, `mensaje`; no suprimir `:focus-visible` y no indicar «nueva/leída» solo por color; (b) favicon: hoy `/favicon.ico` da 404 en la primera carga; (c) las pruebas dependen del HTML literal (`<h2>Mis reservas</h2>`, `<h2>Historial</h2>`, `th scope`, `caption`): si T-13 los cambia, actualizar a la vez los ayudantes de prueba; (d) 400/413 en español con enlace para volver (backlog T-03 #6); enlazar `style.css` en `base.html`; (e) contenido del panel del profesional: «Horas libres» dice «Aún no tienes horas publicadas» cuando solo hay sesiones pasadas, la frase «Para eliminarla, el paciente debe cancelar primero» se repite en cada fila, y las sesiones pasadas no tienen tope; (f) botón/enlace «Reservar hora» destacado en el panel del paciente.
- **Término:** Revisión en pantalla de escritorio y de celular; sin texto ilegible.

### T-13b — Eliminar la prueba intermitente por el token CSRF (hallazgo del orquestador en T-13)
- **Estado:** HECHA (2026-10-09 11:35)
- **Depende de:** T-13
- **Qué:** `tests/test_dashboard_profesional.py::test_filas_ilegibles_se_omiten_sin_romper` (T-12) afirma `"abc" not in html`, pero la página lleva el token CSRF (64 caracteres hexadecimales aleatorios) y a veces contiene «abc» por azar: la suite falla de forma intermitente (reproducido 2 veces en ~25 corridas completas; salida guardada: `'abc' is contained here: ... value="cabcb8136c8f...">`). (1) Corregir esa prueba para que busque el valor ilegible en el lugar correcto (p. ej. en el texto de las filas/tablas de agenda, no en toda la página) o use un marcador imposible de generar por azar (p. ej. `duracion_min='no-numero-xyz!'`). (2) **Auditar todas las pruebas** que afirmen la ausencia de una subcadena corta en una página completa (`not in html`, `not in r.text`, etc.) cuando la página incluye el token CSRF u otro valor aleatorio, y corregir las que puedan fallar por azar (sin debilitar las aserciones). (3) Añadir una prueba/guarda que reproduzca el problema de forma determinista (por ejemplo fijando el token de sesión a un valor que contenga «abc» y verificando que las pruebas de paneles siguen pasando).
- **Término:** con el token CSRF forzado a un valor que contiene «abc», «xyz», «00», «<», etc., las pruebas de paneles y de ausencia de texto pasan; la mutación «volver a `"abc" not in html` sobre toda la página» hace fallar al menos una prueba; `python3 -m pytest` pasa 3 veces seguidas sin variables.
- **Origen:** corrida repetida de la suite del orquestador durante la verificación de T-13.

### T-13c — Cerrar los hallazgos de la revisión de T-13 (D-039 aprobada)
- **Estado:** HECHA (2026-10-09 12:17)
- **Depende de:** T-13, T-13b
- **Qué:** (1) **R-01 (media):** a 360 px la columna «Cancelar»/«Eliminar» queda cortada (339 px de contenido en 311 visibles, también con el foco) y las fechas se parten a mitad («12-10-» / «2026 11:00»): que las tablas de reservas y de agenda sean usables a 320, 360 y 390 px (por ejemplo, formato de tarjeta en pantallas angostas conservando `th scope`, `caption` y el HTML del que dependen las pruebas, o columnas que no se partan y acciones siempre alcanzables); medir con Playwright a 320, 360, 390 y 1280 px, claro y oscuro. (2) **R-02:** el flash dice «Listo: Listo, reservaste…»: la hoja antepone «Listo: » y el mensaje ya empieza con «Listo,»; arreglar sin duplicar y con prueba. (3) **R-03 / D-039 (aprobada):** con sesión iniciada, el logo del encabezado lleva a `/paciente` o `/profesional` según el rol; sin sesión, al inicio; con pruebas por rol y anónimo. (4) **R-04 (media):** la guarda de T-13b detecta pruebas por nombre de variable y no ve `get_data(as_text=True)` ni variables intermedias: hacerla robusta (p. ej. interceptar la respuesta/ejecutar todas las pruebas de páginas con el token hostil forzado en una pasada en lugar de depender de nombres) sin sumar más de unos segundos. (5) **R-05:** pruebas para las 5 mutaciones de accesibilidad que sobreviven: enlace «Saltar», `id="contenido"`, `tabindex` de las tablas con scroll, subrayado de «nueva» y `aria-invalid` en «Agregar hora». (6) Corregir las 4 filas del backlog marcadas «T-13» que ya no aplican o quedaron sin hacer (R-06): hacerlas o reasignarlas a T-14 con motivo.
- **Término:** a 320, 360 y 390 px no hay contenido cortado ni scroll horizontal de página y todas las acciones son alcanzables con teclado; las mutaciones de R-01…R-05 hacen fallar al menos una prueba; `python3 -m pytest` pasa 3 veces seguidas.
- **Origen:** REVIEW de T-13 (R-01…R-06) y D-039.

## Fase 6 — Cierre

### T-14 — Recorrido de punta a punta y revisión final
- **Estado:** PENDIENTE
- **Depende de:** T-13
- **Qué:** Verificador ejecuta el recorrido completo de `SPEC.md` §9; Revisor contrasta código contra SPEC.
- **Notas de la revisión de T-10 (R-05, R-06):** (a) README: periodicidad del cron **menor que 24 h** (p. ej. cada 15 min), ejemplo de crontab, `DATABASE` y `OUTBOX_PATH` iguales a los del servidor web, y que el comando sale con código 1 si falla; (b) con D-029 el recorrido de SPEC §9 «recordatorio → cancelación» solo coincide a las 24 h exactas: el Verificador adelanta el `inicio` por SQL y cancela otra reserva, o el humano ajusta la redacción de §9.
- **Término:** Todas las casillas de "Definición de terminado" marcadas; hallazgos en `REVIEW.md` resueltos.

---

## Backlog de baja prioridad (no bloquea nada; recoger cuando se toque la zona)

Hallazgos de severidad baja que las revisiones dejaron anotados. Cada uno indica
en qué tarea conviene absorberlo.

| Origen | Hallazgo | Absorber en |
|---|---|---|
| T-02d #1 | `FLASK_DEBUG=1` heredado en un servidor real usa la clave pública de desarrollo sin aviso | T-14 (revisión final de seguridad) |
| T-02d #6 | README: aclarar "solo en tu máquina" junto a `--debug`; `FLASK_DEBUG=off` cuenta como verdadero en Flask | T-14 |
| T-01 #3–4 | `base.html` aún no enlaza `style.css` | T-13 |
| T-03 #2 | Cookie de sesión sin `Secure` (hace falta HTTPS para activarla) | T-14 |
| T-03 #4 | `/registro` sin límite de frecuencia: cada registro cuesta ~0,12 s de CPU por scrypt | T-14 |
| T-03 #6 | La página de error 400 de CSRF es la genérica de Werkzeug, en inglés y sin enlace para volver: añadir `errorhandler(400)` con plantilla en español | T-13 |
| T-03 #8 | El mensaje de duplicado casi confirma que el correo existe (aceptado en D-010) | T-14 (revisar de nuevo) |
| T-03 #9 | Los límites de longitud cuentan caracteres, no bytes (inocuo) | — |
| T-02c #4 | `init-db` sobre una base con esquema antiguo termina con éxito y sin aviso, dejando las tablas sin las restricciones nuevas; avisar con `PRAGMA user_version` o comparando `sqlite_master` con `schema.sql` | T-14 |
| T-02f #9 | `README.md:39`: la nota sobre borrar `agenda.db` es exacta pero la línea quedó demasiado larga | cuando se toque el README |
| T-02g R-03 | Pruebas redundantes en `tests/test_esquema.py`: `solo_prefijo_y_nul` duplica `nul_al_final`; tres casos de comodín y el del espacio salen también de las sustituciones por posición; `0000-00-00T00:00:00` se prueba tres veces | cuando se toque ese archivo |
| T-02g R-06 | Restos menores en `PROGRESS.md`: la entrada histórica de T-02f remite a una duda ya resuelta y la duda sobre «aceptar el espacio» quedó obsoleta tras `9e5e2d2` | cuando se toque PROGRESS |
| T-02e R-02 | Las pruebas de SQL exacto fallan con reformateos inocuos (minúsculas en `not null`, comentario dentro de un `CREATE TABLE`, `IN ('a','b')` sin espacio) y las `CHECK_*` dependen del texto del mensaje de SQLite 3.45.1; no está escrito | cuando se toque `tests/test_esquema.py` (añadir un comentario que lo explique) |
| T-02e R-06 | Un cambio legítimo del esquema obliga a tocar `SQL_ESPERADO`, `FK_ESPERADAS`, las `CHECK_*` y la lista de columnas de `tests/test_db.py`; el comentario del código solo menciona la primera | cuando un cambio de esquema lo exija (T-05/T-10/T-14) |
| T-02e R-05 | Quedan 4 pruebas de rechazo con `IntegrityError` desnudo (2 en `test_esquema.py`, 2 en `test_db.py`), duplicadas por otras que sí exigen el CHECK | cuando se toque ese archivo |
| T-03c R-11 | La suite no quedó más rápida (≈11 s): `test_esquema.py` gasta ~4 s en crear la base de cada prueba y la prueba exhaustiva de idempotencia 2,4 s. Fixture de módulo/sesión para la base de solo lectura | cuando la suite pase de ~15 s |
| T-03c R-12 | Los puntos no asignados (Cn) dependen de la versión de Unicode de Python: un Python más antiguo podría rechazar en el login un correo ya registrado | T-14 (fijar versión mínima de Python o revisar) |
| T-04 R-09 | Mensajes de Click (contraseñas que no coinciden) y la página 400 en inglés; accesibilidad del login sin pruebas | T-14 (reasignada en T-13c: los mensajes de Click son del comando CLI, no de la hoja; la página 400 ya está en español desde T-13) |
| T-04 R-08 | Con la clave de desarrollo pública (`FLASK_DEBUG=1`) cualquiera puede forjar una cookie y entrar al panel del profesional (ya anotado en T-02d #1) | T-14 |
| T-04 | Sin límite de intentos de login ni bloqueo | T-14 |
| T-04b R-01 | Sobreviven 3 mutaciones del CSRF: aceptar un prefijo del token, eximir `/login` si el cuerpo es JSON y con cuerpo vacío | cuando se toque `tests/test_seguridad.py` |
| T-04b R-02 | Las pruebas de `no-store` no cubren 405, 413, 500, HEAD ni OPTIONS (con servidor real sí llevan la cabecera); el hook sobrescribe `Cache-Control` y una vista no puede salirse | cuando se toque ese archivo |
| T-04b R-05 | ZWJ/ZWNJ rechazados en el nombre: afecta a nombres persas y algunos devanagari, no a Chile; decisión humana de baja prioridad | junto a D-020 |
| T-04b R-06 | Pasan nombres visualmente vacíos (U+3164, U+2800, combinante suelto) y «zalgo» de hasta 100 caracteres | junto a D-020 |
| T-04b R-08 | Suite de ~25 s: fijar un umbral de ~60 s antes de abrir tarea de velocidad | cuando supere 60 s |
| T-04b R-04 | El botón «atrás» con bfcache en navegadores con interfaz/Firefox/Safari no está comprobado | T-14 |
| T-05 R-02 | Si otro escritor retiene el bloqueo de SQLite más de 5 s, agregar y eliminar horas dan 500 ("database is locked"); sin transacción abierta. Manejar con mensaje en español y reintento | T-08 / T-14 |
| T-05 R-04 | Doble envío de «Eliminar» da 404 en inglés | T-13 (páginas 404 en español) |
| T-05 R-06 | Werkzeug acepta dígitos Unicode en la URL (`%D9%A1` borró la hora 1): inocuo, pero ids de ruta deberían ser solo ASCII si se endurece | T-14 |
| T-05 R-07 | El panel oculta las horas ya iniciadas pero aún no terminadas; decidir si se muestran | T-06/T-08 |
| T-05 R-12 | La suite supera 35 s; el umbral de acción es 60 s | cuando supere 60 s |
| T-05b R-02 | `buscar_solape` lee todas las horas del profesional (también las pasadas) dentro del bloqueo de escritura; con 50 000 filas y 12 procesos aparece «database is locked». Limitar a una ventana de fechas alrededor del candidato (0,16 ms medido) | T-14 |
| T-06 R-01 | `/paciente/horas` sin tope ni paginación: con 50 000 horas libres tarda 1,28 s y pesa 6,55 MB; ventana de fechas o tope de N filas | T-14 (reasignada en T-13c: elegir el tope cambia lo que ve el paciente y no estaba entre los 6 puntos) |
| T-06 R-04 | Tabla sin `caption`/`scope` (hecho en T-13), sin hora de término ni día de la semana, página sin cierre de sesión | T-14 (reasignada en T-13c: hora de término y día de la semana cambian el formato de fecha que fijan muchas pruebas; el cierre de sesión queda a un clic con el logo, que ahora lleva al panel, D-039) |
| T-06 R-07 | Hora inventada en PROGRESS por el implementador (segunda vez, regla 8): si se repite, endurecer con una comprobación automática (script que compare con el commit) | si reincide |
| T-08 R-06 | ~~Una sesión en curso desaparece de «Mis reservas»~~ — resuelto por T-11 (D-034): aparece como «Próxima sesión» en curso | — |
| T-08 R-07 | El `SELECT` de cancelar no trae `profesional_id` ni el nombre del paciente (T-09 los necesitará); `outbox.log` se escribe después del commit; T-10 debe leer el estado dentro de `BEGIN IMMEDIATE` | T-09/T-10 |
| T-08 R-08 | En Windows las pruebas con `zona_sistema` se saltan (sin `tzset`): los bordes por zona solo corren en Linux/macOS | T-14 |
| T-08b R-05 | La caché de URL de las pruebas usa API privada de Werkzeug y la plantilla no es segura entre hilos | si se actualiza Werkzeug |
| T-08b | `pytest-xdist` funciona (1135 OK en 17,7 s) pero emite avisos de `fork`; no se adopta sin decisión (dependencia nueva) | si la suite vuelve a pasar de 60 s |
| T-08d R-02 | Con una base antigua (sin `sesion_version`) `init-db` dice «OK», crea el índice pero no la columna y luego `POST /login` da 500; con 2+ profesionales `init-db` revienta con traceback. Aviso claro o migración (`PRAGMA user_version`) | T-14 |
| T-08d R-04 | Un login simultáneo a un logout en otro navegador puede nacer ya revocado | T-14 |
| T-08d R-08 | T-09 debe notificar usando `horas.profesional_id`, no «el profesional» por rol; el futuro cambio de contraseña deberá incrementar `sesion_version` | T-09 / cuando exista |
| T-08e R-02 | La suite tarda ~34 s (el criterio firme de D-031 es 31,5 s): dos recorridos de 1,1 M de puntos de código (≈3,7 s), la prueba de dos procesos (1,5 s) y cientos de pruebas que montan app y base; revisar cuando pase de 45 s | cuando pase de 45 s |
| T-08e R-03 | Un POST forzado a una hora oculta distingue «libre» de «ocupada» (el estado se comprueba antes que la anticipación); ya pasaba con las horas pasadas | T-14 |
| T-08e R-04/R-05 | Letras en blanco U+13441/U+13442 aceptadas; una cuenta guardada con un carácter hoy rechazado ya no puede iniciar sesión (sin migración); rechazados nuevos: punto medio catalán (`col·legi`) y fracciones | T-14 |
| T-08e R-11 | Mensaje a las 24 h exactas dice «menos» (decir «no más de»); el mensaje de solape sugiere cancelar algo que a veces no se puede; README sin la regla 7 | T-14 (reasignada en T-13c: son textos de reglas de negocio y del README, fuera de los 6 puntos) |
| T-09 R-02 | `outbox.log` queda con los permisos del umask (0644) y contiene nombres y correos | T-14 |
| T-09 R-03 | `outbox.log` y `notificaciones` crecen sin límite; un paciente puede repetir reservar y cancelar sin freno | T-14 (junto al límite de frecuencia) |
| T-09 R-04 | `OUTBOX_PATH` sigue enlaces simbólicos y una ruta relativa depende del directorio de trabajo; documentar en el README | T-14 |
| T-09 R-06 | En la hora repetida de abril el límite de cancelación del texto es ambiguo (conservador) | T-14 |
| T-09 R-07 | Pruebas débiles: la de contraseña es casi tautológica, la de «no escriben en el proyecto» solo mira la configuración, los permisos 0o644 no tienen prueba (la mutación a 0o666 sobrevive) y el único test multiproceso usa horas distintas por proceso | cuando se toque `tests/test_notificaciones.py` |
| T-10 R-01 | `send-reminders` con `DATABASE` inexistente, en un directorio inexistente o sin tablas muestra una traza y sale con 1; con un archivo inexistente crea un `.db` vacío (`get_db` hace `sqlite3.connect`) | T-14 |
| T-10 R-02/R-04 | Con la base bloqueada más de 5 s el comando muere con `database is locked` (el cron reintenta); un `INSERT` que falle bloquea los recordatorios de todos en cada ejecución (consecuencia del todo-o-nada, aceptado en v1) | T-14 |
| T-10 R-03/R-09 | Mutantes equivalentes que sobreviven: quitar el filtro `recordatorio_enviado = 0` del `SELECT` o del `UPDATE` por separado (se respaldan; juntas fallan 4 pruebas), quitar el `rowcount`, `desde = ahora`; faltan pruebas de `fold=1`, del comando con base inexistente y de la ventana inferior | cuando se toque `tests/test_recordatorios.py` |
| T-11b R-01 | «Marcar todas» marca también una notificación que llegó después de cargar el panel y que el usuario no vio (efecto: pierde el estado «nueva»); arreglarlo exige un `hasta_id`, que choca con «ignora ids» de D-035 | decisión humana si se quiere; sin urgencia |
| T-11b R-02 | Con la base bloqueada más de 5 s, cualquier POST lanza `database is locked` (500); es de toda la app, no solo de esta ruta | T-14 |
| T-11b R-04 | Sin `X-Frame-Options` ni CSP en ninguna respuesta; el CSRF también se acepta por la cabecera `X-CSRFToken` | T-14 |
| T-12 R-01 | «Ver la reserva» es engañoso en avisos viejos: si Ana reserva, cancela y Beto reserva la misma hora, los avisos del profesional (incluido «La hora quedó libre») enlazan a la fila de Beto | T-13 (rotular el enlace o quitarlo en cancelaciones) |
| T-12 R-02 | Las mutaciones que quitan el `sort` de libres/agenda o su desempate por id sobreviven: el orden sale del índice `UNIQUE(profesional_id, inicio)`, no del código ni de las pruebas | cuando se toque `tests/test_dashboard_profesional.py` |
| T-12 R-04 | D-036 dice «función única» para las 24 h, pero `reservar_hora` (`app/paciente.py`) conserva su propia comparación en vez de `es_reservable` | T-14 (unificar) |
| T-13 R-08 | Pendientes del humano en `ARCHITECTURE.md`: `errores.py`, `error.html`, `_notificaciones.html`, `static/`, las rutas POST de «leídas» (paciente y profesional), `correo.py`, `tiempo.py` | el humano |
| T-02c #9 | En `tests/test_esquema.py` la cobertura de NOT NULL y FK es triplemente redundante y la rama `usuarios` de `test_not_null_rechaza_null` es poco legible | cuando se toque ese archivo |

---

## Tareas que pueden correr en paralelo (en ramas separadas)

- T-11 y T-12 (después de T-09).
- Dentro de la Fase 3 no: son secuenciales porque comparten `horas`.
