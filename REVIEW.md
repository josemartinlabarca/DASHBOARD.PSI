# REVIEW.md — Revisión de T-02g (commits `df7a71f` y `17ddc55`)

Revisor, 2026-10-08. SQLite 3.45.1. Todo se ejecutó en copias en el scratchpad; el repo no se tocó
(`git status --short` vacío). `python3 -m pytest -q` en el repo: **357 passed**.

## Qué se verificó de verdad

- CHECK nuevo probado con 23 valores en memoria (script propio, no el de PROGRESS).
- 8 mutaciones del esquema en copia, con `tests/test_esquema.py` completo (248 pruebas).
- Conteos de PROGRESS (95 y 31 pruebas nuevas, 5 fallos al quitar `instr`) recalculados.
- `flask --app app init-db` con el esquema nuevo: OK.
- NO reproduje: el recorrido con `flask run`/curl ni `init-db` sobre una base antigua (afirmados en PROGRESS).

## Hallazgos

### R-01 — El CHECK cierra el hueco del NUL (confirmación, no es defecto) — informativa
Evidencia (insert en `horas` con el esquema de `HEAD`):
`canon` ACEPTA (typeof text, length 19, bytes 19); RECHAZAN con `CHECK constraint failed`: NUL al final,
NUL+texto, NUL al inicio, NUL en medio de la fecha, NUL en medio de la hora, `\x00` solo, BLOB canónico,
BLOB con NUL, entero `20261201`, real `1.5`, `\n` final, espacio como separador, `Z`, fracción `.0`,
`t` minúscula, espacio final, vacío; `NULL` falla por NOT NULL. Con la fila canónica ya insertada,
`canon+'\x00'` no elude la UNIQUE (lo frena el CHECK). Un BLOB canónico también se rechaza (GLOB no
coincide con BLOB), así que no hay forma de tener dos filas "iguales" con tipos distintos.
Recomendación: ignorar.

### R-02 — Pasan el CHECK valores que no son fecha-hora válidas (`2026-13-45T99:99:99`) — informativa (ya decidido)
Evidencia: `2026-13-45T99:99:99`, `0000-00-00T00:00:00` y `9999-99-99T99:99:99` se ACEPTAN (typeof text, 19).
Esto está documentado como riesgo aceptado/delegado: D-017 («el CHECK valida la forma, no que la fecha
exista»), ARCHITECTURE.md línea de `inicio`, T-05 (a: «validar que la fecha exista y no sea pasada»), y la
prueba `test_fecha_con_forma_valida_pero_inexistente_se_acepta_en_la_base` más los comentarios de la ronda 2.
No es hallazgo nuevo. Recomendación: ignorar; T-05 ya lo exige.

### R-03 — Pruebas redundantes (duplicados exactos de valor) — baja
Evidencia (valores idénticos probados dos veces):
- `solo_prefijo_y_nul` == `nul_al_final` (`CANONICO + "\x00"`), ambos en `NULOS_RECHAZADOS`. Mutación «quitar
  `AND instr`» hace fallar las dos (`[nul_al_final]`, `[solo_prefijo_y_nul]`): cuentan como 2 de las "5".
- `2026-12-01 10:00:00` está en `pos10-separador-'T'-por-espacio` y en `COMODINES_Y_SEPARADORES[0]`.
- `20*6-…`, `*026-…`, `…10:00:0?` están en la tabla de comodines y salen también de las sustituciones por
  posición (`pos02/pos00-…-por-asterisco`, `pos18-…-por-interrogacion`).
- `0000-00-00T00:00:00` está en `todo-ceros`, en `test_fecha_con_forma_valida_pero_inexistente…` y cerca de
  `pos*-0`.
Efecto: la cifra "95 pruebas nuevas" infla la cobertura en ~6 casos; no hay falso positivo. Recomendación:
backlog (limpieza cuando se toque el archivo, junto con T-02e).

### R-04 — Los `rechazada(...)` solo exigen «CHECK constraint failed», sin identificar cuál — baja
Evidencia: `rechazada(accion, "CHECK constraint failed")` acepta cualquiera de los CHECK de `horas`. Verifiqué
que hoy no hay falsa razón: `insertar_hora` por defecto es una hora libre válida (duracion 50, estado libre),
y con la mutación `CHECK (1 OR inicio GLOB …)` fallan 123 pruebas, entre ellas las 71 por posición, las 13 de
comodines y las 7 de NUL (conteo por `grep` de la salida de pytest). O sea, hoy todas dependen del CHECK de
`inicio`. El riesgo es futuro: si alguien cambia el valor por defecto de `insertar_hora` (p. ej. `duracion_min`),
las pruebas seguirían en verde por otro CHECK. Recomendación: backlog; afirmar `"inicio GLOB"` en el fragmento
(el mensaje de SQLite incluye el texto del CHECK, visible arriba) o añadirlo a T-02e.

### R-05 — Mutaciones verificadas: las pruebas fallan por la razón declarada — informativa
Resultados en copia (suite `test_esquema.py`, control 0 fallos de 248):
| Mutación | Fallan | Pruebas que fallan |
|---|---|---|
| quitar `AND instr(...)` | 5 | solo las de NUL (final, con texto, prefijo+NUL), UNIQUE-NUL y UPDATE-NUL |
| `instr…=0` → `length(inicio) = 19` | 5 | las mismas 5 (confirma que `length` no sirve) |
| `[T ]` en vez de `T` | 2 | las de espacio como separador |
| comodín en el año (`[0-9]*` ) | 6 | pruebas de año/comodines |
| `[0-8]` en el último dígito de los segundos | 2 | `pos18-9`, `todo-nueves` (solo esas) |
| `[1-9]` en el primer dígito | 3 | `pos00-0`, `todo-ceros`, `fecha_con_forma_valida…` |
| quitar el CHECK | 123 | rechazos por posición/comodín/NUL |
| `AND typeof(inicio)='text'` añadido | 0 | sobrevive: es equivalente (GLOB ya rechaza BLOB/número); no es defecto |
Coincide con las cifras de PROGRESS (5, 2, 6, 123). Nota: de las 7 pruebas de NUL, solo 3 dependen de
`instr`; las otras 4 (inicio, medio, medio de la hora, solo `\x00`) las rechaza ya el GLOB. Es correcto como
red de seguridad, pero el docstring («`instr` lo cierra») sugiere más de lo que ejercitan. Recomendación: ignorar.

### R-06 — Documentación veraz, con dos restos menores — baja
- Verificado: 95 = 7+1+1+1+1+71+13 y 31 = 28+2+1; 357 pasan; la línea `inicio` de ARCHITECTURE.md coincide
  con `schema.sql`; `length(inicio) = 19` solo aparece ya en D-018 (descartada) y en la mutación (iii).
- La nota de corrección sobre `length(inicio)=19` se eliminó junto con el bullet de "Bloqueos" (df7a71f), por
  lo que la afirmación falsa ya no está en ninguna parte viva de PROGRESS; la entrada histórica de T-02f
  («Problemas / dudas: ver "Bloqueos" (NUL en inicio)») ahora apunta a algo que no existe. Es historial; aceptable.
- PROGRESS (ronda 1, "Problemas") dice que TASKS.md pedía «aceptar el espacio»; esa redacción ya se corrigió en
  `9e5e2d2` (commit posterior), por lo que la duda quedó obsoleta, no falsa.
- No reproduje: el recorrido manual con `flask run`/curl y `init-db` sobre base antigua.
Recomendación: ignorar.

### R-07 — T-02e no menciona D-018 — baja
TASKS.md T-02e: «Si D-016 o D-017 cambian el esquema, la comparación debe reflejarlo»; depende de T-02g pero
no cita D-018. Si T-02e compara el SQL de `sqlite_master`, debe incluir `AND instr(inicio, char(0)) = 0`.
Recomendación: tarea nueva trivial (editar TASKS.md) o anotar al orquestador; no bloquea.

### R-08 — Contradicciones entre documentos — ninguna
SPEC no define el formato de `inicio`; ARCHITECTURE, DECISIONS (D-017/D-018), TASKS (T-02g, T-05) y
`schema.sql` coinciden. D-017 dice «la base rechaza cualquier otro formato»: ahora es cierto salvo la
validez calendárica, que D-017 mismo exceptúa.

### R-09 — Impacto en tareas futuras — informativa
T-05 ya recoge: guardar `inicio` solo formateando un `datetime`, validar existencia/no pasado, no usar
`INSERT OR REPLACE`. Falta (menor) anotar que, con el CHECK, un `IntegrityError` por formato debe traducirse a
mensaje de usuario en español y no a 500 (T-05 debe validar antes de insertar). Las demás columnas de texto
(`reservada_en`, `creado_en`) no tienen CHECK de formato; fuera de alcance de D-018.

## Veredicto

**APROBADA.** El CHECK cierra el bypass del NUL (incluidos BLOB/entero/real), las mutaciones objetivo de T-02g
hacen fallar pruebas por la razón correcta, y la documentación es veraz en lo que pude reproducir. Los
hallazgos R-03, R-04 y R-07 son bajos (backlog), sin cambios requeridos.
