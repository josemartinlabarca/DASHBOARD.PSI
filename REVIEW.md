# REVIEW.md — Revisión de T-05b (commit `f867530`)

Revisor, 2026-10-08. Python 3.13, SQLite 3.45.1, journal_mode `delete`. Todo experimento y mutación se hizo en copias bajo el scratchpad (`.../scratchpad/{r2,rbase,mutx*,mutc}` y scripts `r2_common.py`, `r2_matriz.py`, `r2_dst.py`, `r2_perf.py`, `r2_carrera.py`, `r2_mut.py`, más `r2/tests/test_rev{,2,3}.py` solo en la copia). El repo no se tocó (`git status` limpio).
Leído: `git show f867530` (código, DECISIONS, PROGRESS, TASKS, el diff de `tests/test_horas.py`), la revisión anterior (R-01, R-03, R-04, R-05), D-025 con su corrección, D-026, `app/profesional.py` completo.

## Veredicto: APROBADA

No hay hallazgos de severidad alta ni media. Los cuatro hallazgos de T-05 (R-01, R-03, R-04, R-05) quedan cerrados y el criterio de término se cumple (las tres mutaciones exigidas hacen fallar pruebas: 11, 18 y 2). Lo que sigue son bordes y deuda de pruebas para T-06.

## Qué se verificó ejecutando

- `pytest`: **881 passed en 36,8 s** (coincide con PROGRESS; `test_horas.py` pasó de 138 a 214 casos recolectados = +76; 805 + 76 = 881).
- **Solape con instantes absolutos**: 400 casos clásicos (5 x 5 x 16 desfases) contra un modelo independiente (`datetime.timestamp()` con `ZoneInfo`): 0 discrepancias. Matriz de cambio de horario: 49 inicios base (alrededor de las 6 transiciones de 2026 a 2028: 22:00, 22:30, 23:00, 23:30, 23:59 del sábado y 00:00, 01:00, 02:00 del domingo) x 6 duraciones x 6 duraciones x 16 desfases = **17 748 casos, 0 discrepancias**. Casos pedidos: septiembre, 50 min a las 23:30 contra 01:00 -> solape; contra 01:19 -> solape; contra 01:20 -> libre (pegada). Abril, 120 min desde las 22:30 contra 00:00 -> libre; 210 min -> solape; 150 min -> pegada, libre. Otro profesional nunca bloquea.
- **Tope de fecha**: 14 casos con reloj fijo (día exacto, +1 día, 29-feb-2028 -> límite 28-feb-2030 y 01-mar rechazado, 31-dic y 1-ene, 2024-02-29 -> 2026-02-28, 00:00:01 y 23:59) y un caso con `TZ=UTC` en el proceso (22:30 de Chile = 01:30 UTC del día siguiente): el tope usa el día de Chile. En `app/` el único uso de `datetime.now` fuera de `ahora_chile` es `creado_en` del registro (`auth.py:97`), ajeno al tope.
- **Entradas raras**: 178 envíos (fechas como `9999-12-31`, `10000-01-01`, `+2028-10-09`, dígitos de ancho completo y arábigo-índicos, `2028-10-09\n`, `\x00`, barras, ISO semanal, 5000 caracteres, SQL, `<script>`; horas `24:00`, `10:00:00`, `１０:００`; duraciones `1e2`, `٥٠`, `0x10`, `9`*400; campos repetidos `fecha=2028-10-08&fecha=9999-12-31`, ausentes, JSON, bytes no UTF-8): ninguno dio 500 (solo 200, 302 o 400) y todo lo guardado casó con `^\d{4}-\d\d-\d\dT\d\d:\d\d:00$` y fecha <= límite. No encontré formato que eluda el tope (el valor que se compara es el `date` ya interpretado; con campos repetidos `request.form.get` toma el primero).
- **Carrera real**: 12 procesos contra un archivo SQLite llamando a `crear_hora` con inicios solapados: 5 corridas, siempre **1 aceptada, 11 rechazadas, 0 transacciones abiertas**. `BEGIN IMMEDIATE` sigue siendo la primera sentencia de `crear_hora` (lectura del código y mutante M07 "solape antes del BEGIN" muere).
- **Ya publicada vs solape**: doble envío -> «Esa hora ya está publicada.»; mismo inicio con otra duración -> «se solapa»; 10:30 -> «se solapa»; con una fila solapada anterior y una idéntica posterior se elige la idéntica; 10:00/31 -> «se solapa» con la otra. **Otro profesional**: misma hora de otro -> se acepta (302) y no se menciona; el mensaje solo describe filas del propio profesional.
- **Mutaciones**: 16 propias (R-01 abajo); las 3 del criterio reproducidas (sin tope 11 fallos, solape en reloj de pared 18, sin CSRF en «Eliminar» 2: coinciden con PROGRESS).
- **Rendimiento**: `buscar_solape` con 50 000 filas de un profesional en archivo SQLite: **0,56 a 0,63 s** (el implementador dice ~0,5 s; coincide); con 5 000 filas, 72 ms; `crear_hora` completo, 0,63 s.
- **Veracidad**: 76 pruebas nuevas, las 4 líneas eliminadas de `tests/test_horas.py` son: un `import` reemplazado, un `import` local movido arriba, una línea en blanco, y el caso `("10:00", "50", "idéntica")` de la parametrización de solapes, que pasó a la prueba de «ya publicada». Quedan los **9 casos** de solape restantes (conté: 10:25, 09:30, 10:49, 09:11, 10:00/10, 10:00/120, 10:10, 09:00/180, 09:59/52). No se perdió cobertura (el caso idéntico sigue probado, ahora con el mensaje nuevo). D-025 (5): el texto original está **íntegro** (comprobado con una búsqueda de la subcadena original dentro de la línea nueva) y la corrección va añadida después, visible, con fecha y referencia a D-026.

## Qué NO se verificó

- Navegador real, recorrido manual con `flask run` (PROGRESS lo declara honestamente como no hecho).
- gunicorn con varios workers y WAL.
- Las 30 mutaciones del implementador, salvo las 3 del criterio: `mut_t05b.py` no está en el repo. Mis 16 son distintas.
- Otras versiones de Python o de los datos de zona (`tzdata`).

## Hallazgos

### R-01 — Tres mutaciones propias sobreviven a la suite completa (baja)
De 16 mutaciones propias (distintas de las 30), 13 mueren y **3 sobreviven con 881 pruebas OK** (corridas con la suite completa):
- **M11 (la que importa):** `listar_horas_futuras` compara `inicio > ahora` con el «ahora» pasado a UTC ingenuo (`ahora.astimezone(timezone.utc).replace(tzinfo=None)` en vez de `ahora.replace(tzinfo=None)`). Con el reloj fijo a las 12:00 de Chile (15:00 UTC) el panel ocultaría las horas de 12:00 a 15:00 de hoy y nadie lo detecta. No hay prueba con una hora libre del mismo día entre «ahora» y «ahora en UTC». T-06 usará el mismo patrón para la lista de pacientes.
  Reproducir: en una copia, cambiar la línea `ahora_local = formatear_inicio(...)` como arriba; `pytest` -> 881 passed.
- **M06:** quitar `ORDER BY inicio` de `buscar_solape`: solo cambia cuál de varias horas solapadas se nombra en el mensaje. Cosmético; la docstring promete «la primera por fecha» y ninguna prueba lo exige.
- **M04:** aceptar `float` como duración guardada (`isinstance(valor, (int, float))`): la fila REAL pasa a bloquear. No lo produce la aplicación; el comportamiento «la fila con duración REAL no bloquea» (PROGRESS) no tiene prueba que lo fije.
Mueren: 29-feb -> 1-mar (M01), tope con día de UTC (M02), offset fijo -3 en vez de la zona (M03), `es_la_misma` con `<=` (M05), solape antes del `BEGIN` (M07), fecha de tope en formato ISO (M08), fin del mensaje en UTC (M09), tope +1 día (M10), «ya publicada» devuelve la primera (M12), `inicio_s <= intervalo[1]` (M13), tope solo si hay hora (M14), segundos en el mensaje (M15), sin `rollback` tras solape (M16).
**Recomendación:** tarea nueva dentro de T-06 (o backlog inmediato): una prueba del panel con una libre a las 13:00 de hoy y reloj a las 12:00 que pase a UTC distinto de Chile; la misma prueba debe existir para la lista de T-06. M06 y M04: ignorar o una prueba de una línea cada una.

### R-02 — La lectura de todas las horas del profesional ocurre dentro del bloqueo de escritura y crece con la historia (baja)
`buscar_solape` hace `SELECT ... WHERE profesional_id = ?` sin acotar fecha y recorre en Python **todas** las filas, también las pasadas, con `BEGIN IMMEDIATE` ya tomado. Medido: 5 000 filas 72 ms, 50 000 filas 0,6 s. Con 12 procesos simultáneos y 50 000 filas, la cola de bloqueos sobrepasa los 5 s por defecto de `sqlite3` y varios reciben `OperationalError: database is locked` (en mi corrida: «EXC OperationalError database is locked» en ambas repeticiones); con 20 000 filas no ocurrió. Es el R-02 de la revisión anterior, agravado por el barrido en Python. Realista en v1: unas 2 500 filas por año por profesional; 0,6 s tardaría ~20 años. Es aceptable hoy.
El tiempo de espera de la carrera no depende del número de pacientes, solo de las horas del profesional y de la concurrencia en la **misma** base (un solo escritor global en SQLite).
¿Conviene limitar a un rango? Sí, a futuro: `inicio BETWEEN` (texto canónico ordenable) del día anterior al día siguiente al candidato lo deja en < 1 ms (medido: 0,16 ms), pero hay que decidir qué hacer con filas insertadas por otro camino con duración enorme (el esquema no pone tope, D-007; la aplicación sí: 480 min).
**Recomendación:** backlog (T-14, junto con el manejo de «database is locked» con 503 en español); no bloquea T-06.

### R-03 — Filas guardadas en hora ambigua o inexistente, y filas raras (informativa)
La aplicación no las crea (D-025 4), pero si existen por otro camino se interpretan con `fold=0` (primer pasaje) y el cálculo es coherente: una fila en 23:30 de la noche de abril (+60) ocupa el primer pasaje (hasta la «segunda» 23:30) y deja libre 00:15 y 00:30; una fila en 00:30 de la noche de septiembre (hora que no existe) se toma con el desfase anterior (04:30 UTC, es decir 01:30 en pared) y solapa con 01:15 y no con 23:45 del sábado. Coincide con el modelo (`fold=0`).
Filas raras con `buscar_solape` y `_describir`: duración 0, -5, `'abc'`, 0.5, 1e30, NULL no se comparan y no lanzan; `2**62` bloquea las horas posteriores (el esquema lo permite) y `_describir` no lanza; `0001-01-01T00:00:00` y `9999-12-31T23:59:59` no lanzan (en 9999 se muestra solo el inicio); `2027-02-30T10:00:00`, `2027-13-01...`, `x` se saltan en la comparación y salen en el mensaje tal cual (`--x `). Candidato en año 9999 (inalcanzable por el tope) lanza `ValueError` dentro del `try`, con `rollback` y re-lanzamiento: no hay transacción abierta.
**Recomendación:** ignorar.

### R-04 — Tope de fecha: detalles de diseño (informativa)
- El 29 de febrero pasa al 28 de febrero del año destino (si hoy es 29-feb-2028 el límite es 28-feb-2030 y el 1-mar-2030 se rechaza): un día menos que «2 años justos». Coherente con D-026; ningún error.
- La comparación es por día de Chile (`ahora.date()` del reloj con zona) y el último día se acepta completo, a cualquier hora; una sesión de 480 min que empieza el último día puede terminar pasado el tope: aceptado y documentado en la prueba.
- Mensaje claro y en español, bajo «Fecha». El tope usa la misma fecha de «ahora» que la comprobación del pasado, un único punto de tiempo (`ahora_chile`).
**Recomendación:** ignorar.

### R-05 — «Ya publicada» es correcta y no filtra datos ajenos (informativa)
La comparación usa solo las filas del `profesional_id` de la sesión; una hora idéntica de otro profesional no produce ese mensaje ni se nombra. Un detalle: el mensaje también aparece si el profesional ve repetida una hora que publicó hace días (no solo un doble clic); es verdadero y suficiente. Si la hora idéntica ya fue reservada por un paciente, el mensaje sigue siendo «ya publicada» (no revela el paciente).
**Recomendación:** ignorar.

### R-06 — Interacción con T-06, T-07, T-08 y T-10 (informativa, para quien tome esas tareas)
- **Regla 5 del SPEC (paciente con dos reservas a la misma hora)**: si T-07 la comprueba por solape de intervalos (no solo mismo `inicio`), debe usar instantes absolutos como aquí; hoy `a_segundos_utc` y `_intervalo_guardado` son funciones «privadas» de `profesional.py`. Conviene moverlas a un módulo compartido (p. ej. `app/horario.py`, con entrada en DECISIONS si es archivo nuevo) en vez de volver a escribir `strftime('%s', ...)` en SQL, que sería el «reloj de pared» corregido aquí.
- **T-06**: la lista de horas libres y futuras debe comparar texto de reloj de Chile ingenuo (como hace `listar_horas_futuras`) y, ver R-01, tener una prueba de la franja «entre ahora y ahora-UTC».
- **T-07/T-08**: `UPDATE ... WHERE estado='libre' AND inicio > ?` con el mismo «ahora» de `ahora_chile`; y tratar «la hora ya no existe» (el profesional la eliminó mientras el paciente miraba) igual que «ya no está libre», no como 404. T-08 (cancelar con 24 h) debe usar instantes absolutos (la diferencia de 24 h con reloj de pared falla las dos noches de cambio de horario, igual que R-03 anterior); T-10 igual.
- **Eliminar, estados**: sin cambios con T-05b; `DELETE` con `estado='libre'` y `ON DELETE SET NULL` siguen siendo la defensa.
- **Suite**: ~37 s; la proyección de la revisión anterior (70-90 s con T-06..T-13) sigue vigente; el umbral de acción de PROGRESS (60 s) es razonable.
**Recomendación:** pasar estas notas a las tareas T-06..T-10 (el orquestador).

### R-07 — Veracidad de PROGRESS.md y D-026 (informativa)
Cuadra con lo ejecutado: 881 pruebas, +76, cuatro líneas eliminadas de `tests/` sin pérdida de cobertura, 9 casos de solape conservados, 11/18/2 fallos en las tres mutaciones del criterio, ~0,5 s con 50 000 filas, suite ~37 s (dice 34 a 38). La corrección de D-025 (5) conserva el texto original. Reservas: (a) el recuento «30 mutantes, 29 muertos» no es reproducible porque `mut_t05b.py` vive en el scratchpad; (b) D-025 (5) y D-026 llevan la hora 13:54 y la entrada de PROGRESS 14:21 (el commit dice 14:21): plausible por haber escrito la decisión antes, no verificable; (c) PROGRESS declara honestamente que no se repitió el recorrido manual ni la concurrencia real tras el cambio. Yo sí repetí la concurrencia (arriba): correcta.
**Recomendación:** ignorar.

## Resumen para el orquestador

| ID | Sev. | Qué | Destino |
|---|---|---|---|
| R-01 | baja | M11 (listado con «ahora» en UTC), M06 y M04 sobreviven a 881 pruebas | Prueba de listado con franja ahora..ahora-UTC en T-06 (tarea) |
| R-02 | baja | Barrido completo de horas bajo `BEGIN IMMEDIATE`; 50 000 filas = 0,6 s, 12 procesos = «database is locked» | Backlog T-14 (ventana por fecha + 503) |
| R-03 | info | Filas ambiguas/inexistentes/raras: comportamiento coherente (`fold=0`) | Ignorar |
| R-04 | info | Detalles del tope (29-feb, último día entero) | Ignorar |
| R-05 | info | «Ya publicada» correcta, sin fuga entre profesionales | Ignorar |
| R-06 | info | Reutilizar instantes absolutos en regla 5 (T-07), 24 h (T-08/T-10); mover funciones a módulo compartido | Notas a T-06..T-10 |
| R-07 | info | PROGRESS y D-025/D-026 veraces; mutaciones del implementador no reproducibles | Ignorar |
