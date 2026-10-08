# REVIEW.md — Revisión de T-02e (commit `f7a0ca3`)

Revisor, 2026-10-08. SQLite 3.45.1. Todo se ejecutó en copias del repo dentro del scratchpad
(`.../scratchpad/w/`); el repo no se tocó (`git status --short` vacío, sin commit).
Lo revisado: diff de `f7a0ca3` (solo `tests/test_esquema.py`, `TASKS.md`, `PROGRESS.md`), `app/schema.sql`,
`ARCHITECTURE.md` (modelo de datos), D-007/D-016/D-017/D-018 y la entrada de PROGRESS.
`schema.sql` coincide con ARCHITECTURE y con `SQL_ESPERADO` (la prueba pasa; leído a mano también).

## Qué se verificó de verdad

- `pytest` en el repo: **390 passed**; también con `SECRET_KEY=abc` y con `FLASK_DEBUG=1` (390 cada una).
- Conteos: 357 antes (`git archive f7a0ca3~1` + `pytest`) y 390 ahora (`--collect-only`): **+33**, coincide.
- 49 mutaciones del esquema en copia (suite `tests/test_esquema.py`, 281 pruebas): 36 semánticas y 13 inocuas.
- 7 mutaciones de PROGRESS repetidas con la **suite completa** (390): `tipo`+`'otro'` 9, `estado`+`'cancelada'` 6,
  `rol` con `lower()` 7, tope 1440 en `duracion_min` 4, `ON UPDATE CASCADE` 2, quitar `instr` 6, quitar `COLLATE NOCASE` 3.
  Los siete números **coinciden exactamente** con PROGRESS.
- 11 mutaciones "otro CHECK distinto" para probar las constantes `CHECK_*` (ver R-05).
- Valores límite de `duracion_min` directamente contra SQLite (ver R-04).
- NO verifiqué: el recorrido con `flask run`/curl (T-02e no lo requiere), `init-db` sobre una base antigua,
  ni otras versiones de SQLite (el texto del mensaje de error de CHECK podría variar entre versiones; ver R-02).

## Hallazgos

### R-01 — La comparación de `sqlite_master` es sólida contra cambios semánticos — informativa (confirmación)
Cada una de estas mutaciones hace fallar al menos una prueba (n.º de fallos entre paréntesis):
valor añadido a un CHECK (7, 6, 9), `DEFAULT 50→51` (2), orden de columnas (1), quitar `NOT NULL` (3), quitar `UNIQUE` del
correo (2), `COLLATE NOCASE→BINARY` (3), quitar `REFERENCES` (6), `ON DELETE CASCADE` (6 y 4), `ON UPDATE CASCADE` (2),
`INTEGER→NUMERIC` (1), `INTEGER PRIMARY KEY→INT PRIMARY KEY` (86), añadir columna (1 y 1), añadir índice, trigger o vista (1 cada
uno, por `test_no_hay_otros_objetos_en_la_base`), `>0→>=0` (3), tope superior (4), `STRICT` (1), `WITHOUT ROWID` (13 + 239 errores),
`UNIQUE` cambiado de columnas o de orden (4 y 3), `ON CONFLICT REPLACE` (3), `AUTOINCREMENT` (1), `DEFERRABLE` (3),
`DEFAULT` de `leida` (1) o de `estado` quitado (192), `hora_id NOT NULL` (27), quitar una rama de la coherencia (2),
espacios dentro del literal del GLOB (76).
Cambios **inocuos** que NO rompen nada (correcto): sangría de 2 espacios, tabs, CRLF, líneas en blanco extra, comentario `--`
fuera de las tablas, reordenar las tablas, quitar `IF NOT EXISTS`, quitar el `;` final, espacios de más al final de una línea.
Recomendación: ignorar.

### R-02 — Ciertos reformateos inocuos SÍ rompen las pruebas (más estricta de lo necesario) — baja
Evidencia (mutación en copia → fallos): minúsculas en `not null`/`primary key` (3), comentario `-- ...` o `/* */` **dentro** de
un `CREATE TABLE` (1 cada uno), `CHECK ( rol IN (...) )` con espacios tras `(` (1), `IN ('paciente','profesional')` sin espacio tras
la coma (**7**: SQL + las constantes `CHECK_ROL`), `REFERENCES usuarios(id)` sin espacio (1).
Causa: SQLite guarda en `sqlite_master` el texto original sin comentarios eliminados ni mayúsculas normalizadas, y el mensaje de
error del CHECK reproduce el texto de la expresión, de modo que `CHECK_*` también depende del formato exacto. Además, depende de
que SQLite siga imprimiendo ese texto (comportamiento de 3.45.1, no documentado como contrato).
Es una elección defendible (más vale estricta que laxa) y el fallo es evidente, pero **nadie lo dejó escrito**: la primera vez que
alguien ponga un comentario dentro de una tabla de `schema.sql` verá un diff de una sola línea enorme.
Recomendación: backlog (con T-05 o la siguiente tarea que toque el archivo): añadir al comentario de la prueba "el formato de
`schema.sql` dentro de cada CREATE TABLE está congelado; los comentarios van fuera de las tablas".

### R-03 — El normalizador colapsa espacios dentro de literales — informativa (teórica)
`" ".join(sql.split())` convierte `'a  b'` y `'a  b'` en `'a b'`, así que un cambio de solo espacios **dentro de un
literal de cadena** pasaría. Hoy ningún literal del esquema contiene espacios (los valores son `'libre'`, `'reservada'`, el GLOB…),
así que **no hay hueco real**; el espacio dentro del GLOB se detecta (76 fallos, porque el GLOB está fijado además por las
pruebas de formato). Pasaría a ser real si una tarea futura añade un `DEFAULT 'sin  datos'` o un `IN ('a  b')`.
Recomendación: ignorar; mencionarlo si algún día se agrega un literal con espacios.

### R-04 — Valores vecinos: aportan poco sobre la comparación del SQL, y falta un límite real: `duracion_min` no entera — baja
(a) Redundancia. Toda mutación de los valores vecinos (`tipo`+`'otro'`, etc.) ya la detecta la comparación del SQL. Los vecinos solo
aportan algo si alguien relajara la comparación (p. ej. por R-02), o para reformulaciones equivalentes que la comparación sí rechaza
(`BETWEEN 0 AND 1`: detecta el SQL y también las pruebas de valores). Son ~21 casos baratos y documentan el contrato; no son ruido
grave. `test_rol_aprobado_aceptado` y `test_duracion_por_defecto_es_50` repiten lo que ya hacen las fijaciones; `1` y `50`
en `test_duracion_sin_tope_superior` repiten las pruebas de duración positiva.
(b) Hueco: con el esquema actual, `duracion_min` **acepta** `'abc'`, `''`, `0.5`, `1.5`, `1e30`, `inf` y BLOB, y `True`→1
(INTEGER affinity de SQLite no impone tipo; `'abc' > 0` es verdadero en SQLite). Se rechazan `0`, `-1`, `0.0`, `'0'`, `False` y NULL.
Ninguna prueba lo documenta (solo la comparación del SQL impediría añadir un `typeof(...)`, y tampoco impide que alguien lo quite
creyendo que ya existe). No es un defecto de T-02e (viene de D-007) pero T-02e prometía "fijar el conjunto exacto de valores".
`2**63` falla en Python, no en SQLite. `recordatorio_enviado`/`leida` no tienen este problema (el `IN (0,1)` lo cierra).
Recomendación: T-05 debe validar que `duracion_min` sea entero positivo en la aplicación (anotarlo en T-05, como ya se hizo con
la fecha en la «Nota R-02/R-09»); decisión humana opcional: añadir `typeof(duracion_min) = 'integer'` al CHECK. Si no se añade,
backlog: una prueba que documente la limitación como `test_fecha_con_forma_valida_pero_inexistente_se_acepta_en_la_base`.

### R-05 — Las constantes `CHECK_*` sí comprueban qué CHECK falló — informativa, con matices bajos
Evidencia (cada una hizo fallar pruebas que NO son las de comparación de SQL/FK, es decir, fallan por el mensaje): `leida` con
`BETWEEN` (2), `recordatorio_enviado` con `BETWEEN` (3), `duracion_min >= 1` (2), `tipo` reordenado (8), `rol` reordenado (6),
`estado` reordenado (5), ramas de la coherencia intercambiadas (7), `length(inicio)=19 AND` delante (121), `instr` delante (121),
CHECK de `inicio` nombrado (121), CHECK de coherencia nombrado (7). Son 11 de 11 (se pidieron al menos 6).
También probé desde el lado de las pruebas: poner por defecto en `insertar_hora` un `inicio` inválido da 27 fallos y poner
`estado='reservada'` sin paciente da 186; es decir, un valor por defecto roto ya no pasa inadvertido (era el R-04 original de T-02g).
Matices:
- El orden de evaluación importa: SQLite informa el **primer** CHECK que falla (columnas en orden, luego los de tabla). Con un
  `inicio` inválido por defecto, las pruebas de rechazo de `duracion_min`/`recordatorio_enviado` siguen pasando (su CHECK va antes);
  quien las detecta son las pruebas de aceptación. Aceptable.
- `CHECK_INICIO` (`"inicio GLOB "`) y `CHECK_COHERENCIA` (prefijo hasta `paciente_id IS NULL`) son prefijos: no distinguen GLOB de
  `instr` dentro del mismo CHECK, ni qué rama de la coherencia falló. Lo cubren las pruebas de NUL y de coherencia por separado.
- El mensaje de PROGRESS dice que **TODAS** las pruebas de rechazo por CHECK exigen ya el CHECK concreto. Quedan cuatro sin
  fragmento: `test_inicio_que_no_es_texto_rechazado`, `test_las_variantes_ya_no_eluden_la_unique` (en `tests/test_esquema.py`, con
  `pytest.raises(IntegrityError)` desnudo; en la segunda el rechazo podría venir de la UNIQUE) y `test_rol_invalido_rechazado` /
  `test_estado_invalido_rechazado` de `tests/test_db.py`. Son duplicados de pruebas que sí exigen el fragmento, así que no hay riesgo
  real; solo la afirmación es ligeramente exagerada.
Recomendación: ignorar el mecanismo; backlog menor (con la limpieza de redundancias de T-02g R-03 / T-02c #9) para pasar esas cuatro
a `rechazada(...)` o borrarlas.

### R-06 — Mantenibilidad: el cambio legítimo del esquema obliga a tocar varios sitios y solo se explica uno — media-baja
Evidencia: si T-05 o una tarea futura añade una columna, un índice o un valor a un CHECK, hay que actualizar a la vez
`SQL_ESPERADO`, `FK_ESPERADAS` (si hay FK), la constante `CHECK_*` correspondiente (si cambia su texto), las listas de vecinos,
`test_db.py` (lista de columnas con `PRAGMA table_info`, líneas ~85-110), `test_no_hay_otros_objetos_en_la_base` (si hay un índice
o trigger) y `ARCHITECTURE.md`. El comentario del código dice solo "hay que actualizar el SQL esperado aquí", y la bitácora nombra
`SQL_ESPERADO` y `FK_ESPERADAS`. No menciona `CHECK_*`, `test_db.py` ni cómo obtener el texto nuevo (por ejemplo,
`SELECT sql FROM sqlite_master` normalizado). Un implementador despistado recibirá un fallo largo y tendrá que deducirlo; el riesgo
más probable es que "arregle" `SQL_ESPERADO` copiando lo que salga sin revisar si el cambio estaba aprobado. Para eso no hay
protección más que la regla humana de CLAUDE.md (el esquema solo cambia con decisión aprobada).
Además hay dos fuentes de verdad por diseño (`schema.sql` y `SQL_ESPERADO`); es el punto de la tarea, no un defecto.
Recomendación: backlog, barato: ampliar el comentario de la sección con la lista de lugares a tocar y la nota "solo con una decisión
aprobada en DECISIONS.md", junto con R-02. Hacerlo la próxima vez que se toque el archivo.

### R-07 — Veracidad de PROGRESS.md y coherencia con TASKS.md — informativa (con una exageración menor)
- 390 y 33 nuevos: **verdadero** (357 en `f7a0ca3~1`, 390 ahora, +33).
- "Se reemplazaron 15 aserciones, no se borró ninguna prueba": **verdadero**. El diff retira 15 líneas con `"CHECK constraint failed"`
  (14 de nivel normal y 1 anidada en `test_inicio_con_nul_no_elude_la_unique`) y las sustituye por `CHECK_*`; comparando los
  nombres de funciones `test_*` entre `f7a0ca3~1` y `f7a0ca3`: 0 desaparecidas, 9 nuevas (más parametrizaciones). El resumen del
  usuario "no se borró ninguna prueba" es cierto; lo que sí cambió es que 15 aserciones pasaron a ser **más estrictas**, lo cual
  la bitácora dice.
- Mutaciones: los 7 números reproducidos a mano coinciden (ver arriba). El procedimiento descrito (copia temporal, solo cambia
  `schema.sql`, suite completa) es el que yo repetí. Sin discrepancias.
- Fila R-04 del backlog de TASKS.md: **procede quitarla**. La propia fila la asignaba a "T-02e (al fijar el SQL exacto)" y el
  trabajo la resuelve (R-05). Matiz: el texto de T-02e en TASKS.md no la lista en "También" ni en el "Término", así que el
  alcance real fue un poco mayor que el escrito; está bien justificado en PROGRESS y es pequeño.
- `schema.sql`, `ARCHITECTURE.md`, `SPEC.md`, `DECISIONS.md` intactos (`git show --stat`: solo 3 archivos). Cumple la regla 3
  de CLAUDE.md (sin funciones extra) y la regla 10 (sin archivos nuevos).
- Lo único que PROGRESS no registra son las fragilidades R-02/R-03; no es un error de veracidad.

### R-08 — Interacción con tareas futuras — informativa
- T-03c y T-04: no tocan el esquema; sin efecto. T-04 depende de T-03c, no de T-02e.
- T-05: cualquier `CREATE INDEX` (p. ej. para consultar horas por profesional/estado), cualquier columna nueva o cualquier
  trigger romperá a propósito `test_no_hay_otros_objetos_en_la_base` / `SQL_ESPERADO`: avisarlo en la tarea (R-06). T-05 además
  debe validar `duracion_min` entero (R-04b) y la fecha existente (ya anotado).
- T-10/T-11 (recordatorios y notificaciones): si añaden una columna o un índice único de deduplicación, mismo caso.
- T-14 y la fila de backlog "T-02c #4" (`init-db` sobre esquema antiguo, comparar `sqlite_master` con `schema.sql`): la lógica de
  `_sql` y `SQL_ESPERADO` podría reutilizarse, pero hoy está sólo en las pruebas; anotarlo allí si se decide implementarlo.
- La redundancia nueva (vecinos vs SQL) conviene añadirla a la fila de backlog "T-02g R-03" para que se limpie junto con las
  demás cuando se toque el archivo.

## Resumen

| Id | Severidad | Recomendación |
|---|---|---|
| R-01 | informativa | ignorar |
| R-02 | baja | backlog (comentario: formato congelado, comentarios fuera de las tablas) |
| R-03 | informativa | ignorar |
| R-04 | baja | T-05 valida `duracion_min` entero; decisión humana opcional sobre `typeof`; backlog: prueba que documente la limitación |
| R-05 | informativa/baja | ignorar el mecanismo; backlog: 4 pruebas con `IntegrityError` desnudo |
| R-06 | media-baja | backlog (ampliar la explicación de qué actualizar) |
| R-07 | informativa | ignorar |
| R-08 | informativa | anotar en T-05 / backlog existentes |

Nada bloquea. T-02e cumple su criterio de término: las cuatro mutaciones citadas (`tipo`+`'otro'`, `estado`+`'cancelada'`, `rol`
con `lower()`, tope en `duracion_min`) hacen fallar pruebas (9, 6, 7, 4) y además `ON UPDATE CASCADE` (2) y el `instr` de D-018 (6);
`pytest` pasa con 390.

**Veredicto: APROBADA.**
