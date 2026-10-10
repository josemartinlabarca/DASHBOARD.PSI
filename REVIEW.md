# REVIEW.md — Revisión de T-14b (commit `3786328`, rama `agentes/loop`)

Revisor. Contrastado con TASKS (T-14b, 7 puntos y notas de T-14a ronda 2), D-006, D-007, D-029, D-044, D-045…D-049, **D-050** (amplía D-006), D-051 (propuesta) y la última entrada de PROGRESS (23:17; el commit es de las 23:18:24, coincide).
Todo se ejecutó en copias bajo el scratchpad (`w` = `git archive 3786328`, `t` = copia para la suite, `m`/`mm` = copias mutadas, guiones sueltos `mig*.py`, `rt*.py`, `win*.py`, `busy.py`, `ob.py`, `forz.py`, `idx.py`, `conc.py`, `mut.py`). El repo no se tocó (`git status` limpio, sin `agenda.db` ni `outbox.log`). El contenedor se reinició a mitad de la revisión: se repitieron las comprobaciones de `send-reminders`/`create-professional` tras el reinicio; ningún servidor ni proceso quedó vivo.

## Veredicto: APROBADA (con 2 hallazgos medios/bajos que recomiendo absorber en T-14c)

Lo central funciona y aguanta lo que intenté: ningún dato se pierde en `init-db` con los 6 esquemas históricos, es transaccional e idempotente, la ventana de D-044 coincide con un oráculo independiente en miles de casos (incluidos los cambios de horario), la base ocupada da 503 en español sin duplicar datos y las mediciones declaradas se reproducen. Lo que encontré es un caso real de 500 sobre bases muy antiguas que la documentación dice que «funcionan» (R-01) y varios bordes del CLI `init-db` sin pulir. Ninguno pierde datos.

## Hallazgos

### R-01 (media) — Base anterior a T-02f: tras `init-db` «sigue funcionando», pero eliminar una hora libre con notificaciones da 500
Las tablas de los esquemas `748f18e`, `cd9f209` y `0f29be6` no tienen `ON DELETE SET NULL` en `notificaciones.hora_id`. `init-db` solo lo avisa y además sella `user_version = 1`. La documentación (aviso de `init-db`, README «la base sigue funcionando, sin esas protecciones», D-050) lo presenta como inocuo. No lo es: cancelar una reserva deja una notificación con `hora_id` apuntando a una hora que vuelve a `libre`, y si el profesional la elimina:
```
python3 rt2.py   # crea la base con el esquema antiguo, init-db, login del profesional, POST /profesional/horas/2/eliminar
748f18e post-init: {'eliminar libre con notif': 500}   sqlite3.IntegrityError: FOREIGN KEY constraint failed
cd9f209 post-init: {'eliminar libre con notif': 500}
df7a71f post-init: {'eliminar libre con notif': 302}   (esquema con SET NULL: correcto)
```
Es el flujo normal «reservar → cancelar → el profesional elimina esa hora». Alcance real acotado: bases creadas en las primeras ~48 h del proyecto (D-007 las daba por de práctica). Además, una vez sellado `user_version = 1`, `es_esquema_antiguo` ya no puede ayudar (y un `IntegrityError` no es `OperationalError`).
**Recomendación (T-14c, tarea pequeña):** o (a) corregir el texto del aviso/README/D-050 («funciona salvo eliminar horas con avisos: 500») y recomendar recrear la base, o (b) capturar `IntegrityError` en `eliminar_hora` y responder con mensaje (o hacer `UPDATE notificaciones SET hora_id = NULL WHERE hora_id = ?` antes del `DELETE`, que no destruye nada). La opción (b) cierra el caso sin reconstruir tablas.

### R-02 (baja) — Dos `init-db` simultáneos: el segundo falla con traza («duplicate column name»)
`inicializar` decide (columnas, tablas, `user_version`, nº de profesionales) **antes** de `BEGIN IMMEDIATE`; si otro `init-db` confirma entre la lectura y el bloqueo, el segundo ejecuta `ALTER TABLE … ADD COLUMN` otra vez. Reproducido de forma determinista (pausa en la lectura de columnas del hilo B):
```
python3 race3.py  ->  {'A': ('ok', ['se agregó la columna usuarios.sesion_version']), 'B': ('ERR', 'OperationalError', 'duplicate column name: sesion_version')}
```
La base queda correcta (la transacción se revierte; la carrera no ocurrió espontáneamente en 18 intentos con 6 procesos reales porque el arranque de Flask los serializa). Misma ventana para «aparece un 2.º profesional entre la comprobación y el bloqueo» (el `CREATE UNIQUE INDEX` falla y se revierte, con traza). Sin pérdida de datos.
**Recomendación (backlog / T-14c):** abrir `BEGIN IMMEDIATE` antes de leer el estado, o reintentar una vez la decisión si el `ALTER` falla por columna duplicada.

### R-03 (baja) — `init-db` muestra traza de Python ante archivos que no son una base utilizable
`abrir_base_existente` (send-reminders/create-professional) trata esos casos con mensajes claros; `init-db` no:
```
archivo de texto            -> rc 1, Traceback … sqlite3.DatabaseError: file is not a database
base corrupta               -> rc 1, Traceback … database disk image is malformed
DATABASE = carpeta / carpeta inexistente -> rc 1, Traceback … unable to open database file
solo lectura (chattr +i)    -> rc 1, Traceback … attempt to write a readonly database
bloqueada (BEGIN IMMEDIATE) -> rc 1 tras 5,2 s, Traceback … database is locked
archivo vacío (0 bytes)     -> rc 0, «Base de datos inicializada.» (correcto)
esquema que falla a medias  -> rc 1, Traceback; la base queda intacta (verificado)
```
Código de salida ≠ 0 y datos intactos en todos, pero la traza contradice el espíritu del punto 4. Una base de versión más nueva (`user_version = 7`) se acepta: avisa y no cambia el número, pero sí agrega el índice faltante (`se creó el índice intentos_acceso_instante`): lo que el README dice («avisa y no cambia su número») es verdad solo a medias.
**Recomendación (backlog):** envolver `inicializar` en el mismo traductor de errores de `abrir_base_existente` (mensaje en español, código 1).

### R-04 (baja) — `create-professional` con la base ocupada sigue mostrando traza; además pide la contraseña antes de comprobar la base
Confirmado D-051 D: con `BEGIN IMMEDIATE` retenido por otro proceso, `create-professional` lanza `OperationalError: database is locked` (traza). Con `BEGIN EXCLUSIVE` sí da el mensaje claro (falla antes, al listar tablas). Tampoco comprueba la base antes de `click.prompt("Contraseña")`: con `DATABASE` mal escrito el usuario escribe la contraseña dos veces y recién entonces ve el error. `send-reminders` y los 7 casos de archivo (inexistente, carpeta inexistente, es carpeta, no SQLite, sin tablas, 0 bytes, enlace roto) dan mensaje en español, código 1, sin traza y **sin crear ningún `.db`** (verificado con listado del directorio). Con la base ocupada (EXCLUSIVE) `send-reminders` responde en 5,2 s con el mensaje claro.
**Recomendación:** hacerlo en T-14c (ya propuesto en D-051 D), y abrir la base antes de pedir la contraseña.

### R-05 (baja, razonado, no ejecutado) — TOCTOU en `abrir_base_existente`
Se comprueba `os.path.isfile` y luego `sqlite3.connect` crea el archivo si desapareció entre ambos pasos (ventana de microsegundos). No lo reproduje (exigiría borrar el archivo en esa ventana). Se cierra abriendo con URI `file:…?mode=rw`. Solo informativo.

### R-06 (baja) — Un POST forzado SÍ distingue una hora oculta de una inexistente (D-050 punto 6 lo afirma al revés)
Libre y ocupada dan lo mismo (objetivo de T-08e R-03: mensaje, código, cuerpo y tiempo; mediana 1,7 ms ambas, sin diferencia medible), pero la frase de D-050 «una hora oculta … responde lo mismo que una inexistente» no es cierta:
```
python3 forz.py
libre 12h       302 /paciente/horas  flash=Solo se puede reservar con más de 24 horas…
ocupada 12h     302 /paciente/horas  flash=Solo se puede reservar con más de 24 horas…
libre pasada    302 …                flash=Esa hora ya empezó o ya pasó…
ocupada pasada  302 …                flash=Esa hora ya empezó o ya pasó…
ocupada lejos   302 …                flash=Esa hora ya no está disponible…
inexistente     302 …                flash=Esa hora ya no está disponible…
```
Quien prueba ids sabe qué ids existen (horas pasadas o a ≤ 24 h) frente a los que no. Impacto casi nulo (ids secuenciales, horas publicadas son visibles de todos modos). **Recomendación:** corregir la redacción de D-050 (o, si importa, hacer que inexistente dé el mismo mensaje de «ya empezó» solo para ids ≤ máximo, lo que sería peor). Basta con la corrección del texto.

### R-07 (baja) — `esta_ocupada` también convierte `SQLITE_LOCKED` en 503 y esa rama no tiene prueba
Mutación M06 (solo `SQLITE_BUSY`) **sobrevive** (13 pruebas OK). «database table is locked» es un fallo del propio programa (dos cursores en una conexión), no una base ocupada por otro proceso; hoy se disfrazaría de 503. Los demás `OperationalError` (por ejemplo «no such column» con la base al día, «disk I/O error») sí se relanzan como 500: probado por `test_otro_error_de_sqlite_sigue_siendo_500…` y M14 la mata. Las respuestas 503 son texto fijo: no filtran texto de SQLite (verificado en cuerpo: sin «locked»/«sqlite»). **Recomendación:** quitar `SQLITE_LOCKED` o añadir una prueba que fije la decisión.

### R-08 (baja) — Bordes de `outbox.log`
Verificado: crea con 0600 con `umask` 022/077/000 (con 277 queda 0400 y las escrituras siguientes fallan registradas en el log, sin romper la reserva); existente 0644 avisa una sola vez por proceso; NUL en la ruta, carpeta como ruta y `/dev/full` (ENOSPC) devuelven False con `logger.error` sin lanzar; carpeta inexistente se crea (la hoja `c` 0700, pero las intermedias `a`, `a/b` quedan 0755); 8 procesos × 50 escrituras de 3 KB: 400 líneas, 0 mal formadas, modo 0600; un enlace simbólico a un archivo existente **escribe en el destino** (y avisa si es 0644), y uno colgante **crea el destino** con 0600: documentado en README, aceptable porque `OUTBOX_PATH` lo fija el administrador. Un FIFO sin lector bloquearía la petición (`os.open` sin `O_NONBLOCK`); la ruta es del administrador, solo informativo. El README/D-050 dicen «carpeta 0700 solo si la crea la app»: es cierto solo para la última carpeta.

### R-09 (baja) — README conserva una afirmación incondicional que la nota (b) corrigió en el código
La «Advertencia» dice «En debug la clave es un valor público fijo … cualquiera podría falsificar sesiones» sin el matiz «si no defines `SECRET_KEY`». El mensaje de rechazo del código sí es veraz (nota (b)). Notas (a), (c) y (d) cumplidas: CLI propio con `FLASK_DEBUG=1` y sin clave → `RuntimeError: Me niego a servir…` (probado con un `click.command` propio); README y docstrings citan D-049 y D-050; la consecuencia (d) está documentada.

### R-10 (informativa) — Ruta con id justo sobre el máximo: GET da 405 y no 404
`/horas/9223372036854775808/reservar`: POST 404 (correcto) pero GET 405 (el `ValidationError` del convertidor hace que Werkzeug considere la ruta como existente solo para otros métodos); con 20 dígitos da 404. Inofensivo.

### R-11 (informativa) — Evaluación de D-050 como ampliación de D-006
- **¿Debe decidirlo el humano?** Ya estaba autorizado en esencia: TASKS T-14b punto 3 pide «aviso claro **o migración mínima** con `PRAGMA user_version` … sin borrar datos». D-050 elige la migración mínima, pero cambia una frase aprobada de D-006 («no modifica tablas ya existentes»): ahora hace `ALTER TABLE usuarios ADD COLUMN`. Aun así D-006 lleva la nota «Ampliada por D-050» y D-050 se marcó para el humano. **Recomiendo que el humano lo confirme explícitamente** (una línea), porque abre la puerta a futuras migraciones aditivas.
- **Riesgo real:** bajo. Probado con 6 esquemas (`748f18e`, `cd9f209`, `0f29be6`, `df7a71f`, `f06bdb5`, `e2384c2`) con datos (usuarios, horas reservadas, notificaciones con y sin `hora_id`): todos los datos y columnas previas idénticos antes/después, `foreign_key_check` vacío, `integrity_check` ok, `user_version` 0 → 1, segunda ejecución idempotente (salida «inicializada», base idéntica), 2 profesionales (4 esquemas) → se detiene con código 1 y base **byte a byte idéntica**, dos veces seguidas. El `ALTER` es aditivo (valor por defecto 0, no reescribe filas). Lo único que cambia es que `user_version = 1` se sella aunque queden tablas viejas (ver R-01).
- Los tres `.sql` de `tests/esquemas_antiguos/` son idénticos (`diff`) a `git show <hash>:app/schema.sql` de `748f18e`, `df7a71f` y `f06bdb5`. Faltan en las pruebas `cd9f209`, `0f29be6` y `e2384c2` (distintos en la práctica: R-01 aparece justo en los dos primeros).
- Con 748f18e/df7a71f… sin `init-db` y con la app sirviendo: login, registro y paneles con cookie dan **503 en español** (nunca 500); el log lleva el detalle. `send-reminders` da el mensaje de tabla faltante, código 1.

### R-12 (informativa) — Documentación y backlog
- PROGRESS 23:17 / D-050 23:16 / commit 23:18:24: coherentes con `git log`. Mediciones reproducidas (ver abajo). No pude verificar las cifras de mutaciones declaradas (26 + 18 + …) ni las capturas de navegador: no ejecuté el navegador.
- La tabla de backlog de TASKS no tachó las filas cubiertas por T-14b (el propio PROGRESS lo dice): el orquestador debería hacerlo (T-14a R-05/R-06/R-09, T-05 R-06, T-05b R-02, T-08e R-03/R-11, T-09 R-02/R-04/R-06, T-10 R-01, T-11b R-02).
- **Para `ARCHITECTURE.md` (humano):** `db.py` (`user_version`, `ConvertidorId`, `abrir_base_existente`), `errores.py` (503 y `error_de_base`), `intentos_acceso_instante`, `DATABASE_TIMEOUT`, `tests/esquemas_antiguos/`, `tests/test_base_ocupada.py`.
- **Para T-14c:** R-01 (500 al eliminar con avisos en bases antiguas), R-02/R-03/R-04 (`init-db`/`create-professional` sin traza), D-051 A…D, el matiz de R-09 en el README, tachar el backlog, y la prueba con lector de pantalla de las tablas en tarjetas ya listada. La suite completa con token hostil sigue siendo una corrida manual.

## Verificado ejecutando (resultados)
- **Ventana D-044:** 6 bordes exactos (24 h−1 s, 24 h, 24 h+1 s, 60 d−1 s, 60 d, 60 d+1 s) → se listan exactamente `+1 s`, `60 d−1 s` y `60 d` (24 h estricto, 60 d inclusivo); 100 horas → sin aviso, 101 → 100 + aviso, 100 + 1 fuera de ventana → sin aviso (la propuesta C de D-051 sigue vigente); 3 profesionales × 140 con inicios repetidos (paginación por teclas): 100 filas, 0 repetidas, igual a la lista completa; 300 casos aleatorios + 400 casos con cortes a ±6 h de los cambios de horario de sept-2026/abr-2027/sept-2027/abr-2028 y horas inexistentes/ilegibles: **0 discrepancias** con un oráculo que recorre toda la tabla. 50 000 horas: `/paciente/horas` 0,0083 s y 44 888 bytes con aviso (declarado 0,008 s/45 KB).
- **`buscar_solape`:** 1 500 casos aleatorios contra fuerza bruta (cruzando los cambios de horario, duraciones hasta 100 000 min insertadas por SQL, ventana): 0 discrepancias. 12 procesos × 3 altas con 50 000 horas: 0,88 s y 0 errores `locked` (declarado 0,79 s).
- **Base ocupada** (retención real de 6,5 s, 5,0 s de espera): reservar, cancelar, marcar leídas (paciente y profesional), agregar, eliminar, login y registro → 503, `Retry-After: 5`, en español, enlace de reintento, sin traza; «Agregar hora» y registro conservan lo escrito; tras liberar, el reintento funciona y no hay duplicados (3 horas/1 reservada, 1 usuario nuevo). GET de `/paciente` con bloqueo EXCLUSIVE → 503.
- **Índice nuevo:** `EXPLAIN QUERY PLAN` del `UPDATE` y del `DELETE … LIMIT 500` usan `intentos_acceso_instante`; `reservar()` con 1 000 000 de filas: 17–22 ms; reloj 24 h adelantado → espera 900 s (no crece).
- **Convertidor:** `%D9%A1`, ancho completo, `01`, 20 dígitos, `-1`, `0`, `1.0` → 404; `9223372036854775807` válido; ruta legítima sigue con 302 (POST) / 405 (GET).
- **Suite:** 2179 pruebas OK 3 veces (46,7 / 45,1 / 44,8 s; ~45 s frente a ~42 s de T-14a ronda 2: +3 s), 1 vez más con `SECRET_KEY`, `FLASK_DEBUG`, `TZ=Asia/Tokyo`, `SESSION_COOKIE_SECURE`, `TRUSTED_PROXY_COUNT`, `DATABASE` inexistente, `OUTBOX_PATH=/dev/full` y el token CSRF hostil juntas: OK; sin `outbox.log` ni `agenda.db` residuales. Lo más lento: la guarda de CSRF hostil (4,1 s). Las pruebas que miran el reloj real usan tolerancia de 5 s o sincronizan procesos con margen.
- **Mutaciones propias (22; en copias, nunca en el repo), 21 matadas por la razón declarada y 1 sobrevive:** 24 h `>=`, ventana 60 d exclusiva, tope 101, aviso `>=`, convertidor con ceros, `init-db` sin transacción (BEGIN+COMMIT: muere `test_si_el_script_falla_a_medias_no_queda_nada_a_medias`), sin `user_version`, 2 profesionales `> 2`, `MARGEN_VENTANA` 0, sin rama de filas largas, outbox 0644, outbox sin `O_APPEND`, estado antes que fecha, 503 que enmascara todo, sin reubicar marcas futuras, sin índice, texto «no más de», abrir base sin comprobar archivo, hora repetida sin aclaración. **Sobrevive:** solo `SQLITE_BUSY` en `esta_ocupada` (R-07).

## No verificado
Navegador (capturas de PROGRESS), el recorrido con un servidor HTTP real y proxy, Windows, la carrera real de dos `init-db` sin pausas artificiales (solo la provocada), el TOCTOU de R-05, la afirmación de «26 + 18 mutaciones» del implementador, y base de solo lectura por permisos (se probó con `chattr +i` porque se ejecuta como root).
