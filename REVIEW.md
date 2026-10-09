# REVIEW — T-09 Notificaciones de confirmación y cancelación (commit `0b5a51a`)

Revisor: leí el diff completo (`git show 0b5a51a`), CLAUDE.md, SPEC.md (US-11, US-12, US-13, §4, §5), el texto de T-09 a T-12 en TASKS (notas de T-02f, T-07 R-09 y T-08e R-10), D-016, D-029 y D-032, la última entrada de PROGRESS, `app/notificaciones.py` y los cambios en `app/paciente.py`. Todo lo que ejecuté se hizo en copias bajo el scratchpad (`git archive 0b5a51a` → `rv/`); en el repo no cambié nada salvo este archivo, y el árbol no tiene `outbox.log` ni `agenda.db` ni cambios sin confirmar.

## Veredicto: APROBADA

El comportamiento de T-09 es correcto contra SPEC: ambas partes reciben aviso al reservar y al cancelar, el profesional avisado es el dueño de la hora, el mensaje de confirmación dice hasta cuándo cancelar con la resta en instantes absolutos (comprobado en las dos noches de cambio de horario), los mensajes se bastan solos, y las filas se insertan dentro de `BEGIN IMMEDIATE` antes del `commit`. El log neutraliza la inyección de líneas. Los hallazgos son de severidad baja o informativa; el más relevante (R-01, trampa para T-10) conviene anotarlo antes de empezar T-10.

| Id | Severidad | Tema | Recomendación |
|---|---|---|---|
| R-01 | media | `registrar` / `_mensajes` no sirven para `recordatorio`: cualquier tipo distinto de `confirmacion` produce texto de cancelación y siempre crea dos filas | anotar en T-10 |
| R-02 | baja | `outbox.log` queda con permisos del umask (0644 típico) y contiene nombres y correos | backlog T-14 |
| R-03 | baja | Crecimiento sin límite de `outbox.log` y de `notificaciones` (ciclo reservar/cancelar sin freno) | backlog T-14 |
| R-04 | baja | La ruta de `OUTBOX_PATH` sigue enlaces simbólicos y una ruta relativa depende del directorio de trabajo | backlog T-14 / README |
| R-05 | baja | Un fallo de disco a mitad de línea deja una línea parcial a la que se pega la siguiente; el log no se puede reconciliar con la base | backlog; anotar en T-10 |
| R-06 | baja | El límite de cancelación en la hora repetida de abril es ambiguo en el texto | ignorar o backlog |
| R-07 | baja | Pruebas débiles: contraseña (tautológica), «no escriben en el proyecto» (solo mira la configuración), permisos sin prueba | backlog |
| R-08 | informativa | Orden de líneas del log no es el orden de commit entre procesos | anotar en T-10/T-11/T-12 |
| R-09 | informativa | Documentación: afirmaciones de PROGRESS/D-032 coherentes con lo ejecutado; faltan README y notas para T-10 a T-12 | ver abajo |

## Hallazgos

### R-01 (media) — `registrar` solo sirve para confirmación y cancelación
`_mensajes(tipo, hora)` trata como cancelación todo tipo que no sea `confirmacion`, y `registrar` inserta siempre dos filas (paciente y profesional). US-12 pide recordatorio **solo al paciente** y el esquema ya admite `tipo = 'recordatorio'`.

Evidencia:
```
$ python3 -c "from app import notificaciones as n; h={'profesional_id':1,'inicio':'2026-12-01T10:00:00','duracion_min':50,'profesional':'P','profesional_email':'p','paciente':'A','paciente_email':'a'}; print(n._mensajes('recordatorio',h))"
('Cancelaste tu hora con P del 01-12-2026 a las 10:00 (hora de Chile). La hora quedó libre.', 'A canceló su hora contigo del 01-12-2026 a las 10:00 (hora de Chile). La hora quedó libre.')
```
Quien reutilice `registrar` en T-10 sin leer el código enviaría un recordatorio que dice «Cancelaste tu hora» y además avisaría al profesional (SPEC §US-12 solo nombra al paciente).

**Recomendación.** Anotar en T-10: no reutilizar `registrar` tal cual; añadir un `MSG_RECORDATORIO` y decidir (y probar) si el profesional recibe algo. Mejor aún, que T-10 haga fallar `_mensajes` con un tipo desconocido (`ValueError`) en lugar del texto de cancelación. Esto también debe quedar en la tarea: el recordatorio debe insertar sus filas y poner `recordatorio_enviado = 1` en la misma transacción `BEGIN IMMEDIATE` y escribir el log después del `commit` (nota de T-08 R-07).

### R-02 (baja) — Permisos del log
`escribir_outbox` abre con `0o644` y el sistema aplica el umask: con `022` el archivo queda legible por todos. Contiene nombre y correo de pacientes y del profesional (datos personales), no contraseñas ni tokens.

Evidencia (copia en el scratchpad, `escribir_outbox` con `OUTBOX_PATH` propio):
```
umask 022 -> archivo 0o644, carpeta creada 0o755
umask 077 -> archivo 0o600, carpeta creada 0o700
```
No hay prueba de permisos (la mutación `0o644` → `0o666` sobrevive: 51 passed). Con una base `agenda.db` que ya tiene los mismos datos y permisos equivalentes, el riesgo es bajo.

**Recomendación.** Backlog para T-14: abrir con `0o600` y decir en el README que el log contiene datos personales.

### R-03 (baja) — Crecimiento sin límite
No hay rotación ni tope. Un paciente registrado puede repetir reservar y cancelar (cancelar se permite con más de 24 h) sin freno; cada ciclo añade 4 líneas al log (unos 167 bytes cada una, medido: 20 líneas = 3350 bytes) y 4 filas a `notificaciones`. Es el mismo origen que T-03 #4 (sin límite de frecuencia). No hay riesgo de 500: el fallo de disco está capturado (comprobado con `/dev/full`: `escribir_outbox` devuelve `False` y registra el error).

**Recomendación.** Backlog T-14, junto con el límite de frecuencia; anotar rotación (`logrotate`) en el README.

### R-04 (baja) — Ruta de `OUTBOX_PATH`
`os.open` sigue enlaces simbólicos y una ruta relativa se resuelve contra el directorio de trabajo del proceso, no contra la base.

Evidencia:
```
OUTBOX_PATH=.../t/link.log  (enlace a .../t/victima)  -> escribir_outbox True; se crea/escribe «victima»
```
La variable la controla quien despliega, no el usuario de la web; por eso solo es baja. Una ruta con NUL se captura (`ValueError`) y el directorio se captura (`OSError`): ambos comprobados por las pruebas parametrizadas.

**Recomendación.** Backlog T-14: documentar en el README (`OUTBOX_PATH` absoluta, solo escribible por el servicio); opcional `O_NOFOLLOW`.

### R-05 (baja) — Línea parcial y falta de reconciliación
Con `_escribir_completo` un disco que se llena entre dos `write` de una misma línea dejaría una línea sin `\n`; la siguiente escritura se pega a ella y forma una línea mal formada (no falsifica un registro con campos válidos, pero rompe un `split` del lector). Además D-032 acepta que, si el proceso muere entre el `commit` y la escritura, la notificación queda en la base sin línea; no hay columna ni marca que permita saber cuáles faltan. Aceptable en v1 (SPEC §5: simulación de correo) y D-032 lo documenta, pero para T-10 conviene anotar que la base es la fuente de verdad y el log no.

**Recomendación.** Backlog; anotar en T-10: el recordatorio se marca `recordatorio_enviado = 1` en la base; si falla el log no se reintenta (mismo límite aceptado).

### R-06 (baja) — Hora repetida en el límite de cancelación
Para una sesión cuyo `inicio − 24 h` cae en la hora repetida de abril el texto muestra una hora de pared que ocurre dos veces, sin desfase.
```
_limite_para_cancelar("2026-04-05T23:30:00") -> "04-04-2026 a las 23:30"   # el instante es la 2.ª ocurrencia (UTC-4)
```
La primera lectura del paciente (23:30 UTC-3) es una hora antes: conservadora. El cálculo en instantes absolutos es correcto (comprobado: 2026-04-05T10:00 → 04-04 11:00; 2026-09-06T10:00 → 05-09 09:00; 2026-12-01T10:00 → 30-11 10:00; fechas fuera de rango → `None` y texto «24 horas antes de la sesión»).

**Recomendación.** Ignorar o backlog (añadir «(segunda vez)» sería excesivo).

### R-07 (baja) — Calidad de pruebas
Mutaciones reales sobre `tests/test_notificaciones.py` (script `mut.py`, copia en el scratchpad, `pytest -x`). MUEREN por la razón declarada 12 de 13: sin `O_APPEND` (muere en `test_reservar_y_cancelar_varias_veces...`), `break` tras el primer aviso, límite de 23 h, aviso al profesional con el texto del paciente, `sanear` sin `Zl/Zp`, `sanear` sin `Zs`, sin `makedirs`, el fallo de disco que propaga (`raise`), sin escribir el log tras cancelar, `LEFT JOIN` por `h.paciente_id` en lugar del actor, duración fija de 50, barra sin duplicar. SOBREVIVE: permisos `0o644` → `0o666` (R-02).

Debilidades:
- `test_el_mensaje_no_lleva_contrasena_ni_hash` es casi tautológica: pasaría aunque se agregara cualquier campo sensible que nadie selecciona; nunca podría fallar con el código actual salvo que se interpolara una clave.
- `test_las_pruebas_no_escriben_en_el_proyecto` solo compara rutas de configuración, no mira el sistema de archivos.
- El único test multiproceso (`test_procesos_reales...`) usa horas distintas por proceso: no prueba la contención sobre **una** hora. Lo comprobé a mano (6 procesos reales, 10 horas, cada una disputada por todos): 10 reservas, 20 filas, 20 líneas, exactamente 2 avisos por hora y ninguno cruzado, porque quien pierde sale antes de `registrar`.
- Orden/aislamiento: la suite completa pasa (1507 passed en 35,6 s) y no deja `outbox.log` ni `agenda.db` en el árbol (`find` en la copia y `ls` en el repo, vacíos).

**Recomendación.** Backlog: una prueba de permisos con la corrección de R-02, y una de contención sobre una sola hora.

### R-08 (informativa) — Orden del log
La línea se escribe después del `commit`; dos procesos pueden confirmar A y B y escribir B y A. Cada línea lleva `creada_en` (hora de la decisión), pero T-11/T-12 no deben ordenar por `creada_en` (texto con desfase; nota de T-07 R-09) sino por `notificaciones.id`, y quien lea `outbox.log` no debe suponer orden de commit.

### R-09 (informativa) — Documentación e impacto en T-10 a T-14
Verifiqué la verdad de PROGRESS/D-032: `1507 passed` coincide con lo que ejecuté; los 51 tests, el `conftest` y la ausencia de archivos tras la suite son ciertos; el recorrido manual con `flask run` figura como **no hecho** (honesto). Las 17 mutaciones de PROGRESS no las repetí (su script no está en el repo); las 13 mías son consistentes. `ANTICIPACION_CANCELAR_S` duplicada: la prueba `test_el_limite_de_cancelacion_del_mensaje_es_el_de_la_regla_de_cancelar` la cubre (la mutación 24 → 23 h en `notificaciones` muere; no probé el sentido contrario, 23 h en `paciente`, que otras pruebas de cancelar ya cubren). No hay contradicciones entre D-032, PROGRESS y TASKS. La fila «T-08 R-07» del backlog (el `SELECT` de cancelar no trae profesional ni paciente) quedó resuelta por esta tarea y puede cerrarse.

Faltan estas notas (no las escribo; son del orquestador):
- **T-10:** R-01, R-05 y R-08; reutilizar `escribir_outbox`; recordatorio y `recordatorio_enviado` en la misma transacción; usar `ValueError` para tipos desconocidos.
- **T-11/T-12:** ordenar notificaciones por `id`; el texto ya trae fecha y contraparte, así que con `hora_id` NULL se muestra tal cual (confirmado por la prueba de hora eliminada); la campana usa `leida`, que T-09 no toca.
- **T-13:** nada.
- **T-14:** R-02, R-03, R-04; README (`OUTBOX_PATH`, datos personales en el log, rotación; hoy el README no menciona `outbox.log`); el recorrido manual de SPEC §9 debe incluir ver las líneas del log.

## Qué verifiqué ejecutando y qué no
Ejecuté: `pytest tests/test_notificaciones.py` (51 passed) y la suite completa en la copia (1507 passed); `sanear` con 17 entradas hostiles (salto, U+2028, NEL, tabulador, ESC, barra, NUL, carácter astral, sustituto suelto, U+202E, U+200B); `_limite_para_cancelar` en 10 fechas incluidas las dos noches de cambio; permisos con dos umask; enlace simbólico; `/dev/full`; 6 procesos reales sobre las mismas 10 horas; 13 mutaciones. No ejecuté: `flask run` real, Windows/macOS, el INSERT que falla con un disparador propio (confié en las 4 pruebas parametrizadas, cuyas mutaciones de commit anticipado declaradas por el implementador no repetí), ni el aviso por `app.logger` en producción.
