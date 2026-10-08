# REVIEW — T-07 Reservar hora (commit `a0e39c2`)

Revisor: lee el diff y ejecuta experimentos en copias bajo el scratchpad (`rev/`, `mut_*`, `exp*.py`); no se tocó el repositorio salvo este archivo.

## Veredicto: APROBADA

Las reglas 1 y 5 se cumplen incluso con concurrencia real (procesos, hilos y un servidor `flask run` verdadero). No hay hallazgos de severidad alta. Hay un hallazgo medio que no es un defecto del código de T-07 sino un hueco de planificación (R-01: el paciente no puede ver ni cancelar sus reservas hasta T-11) y varios bajos. Nada de lo siguiente bloquea T-08.

## Qué verifiqué ejecutando (resumen)

| Punto | Resultado |
|---|---|
| Suite completa en copia limpia del commit | 956 OK (46,5 s y 50,7 s en dos corridas). `FLASK_DEBUG=1 SECRET_KEY=abc` sobre `test_reservar.py`: 53 OK. |
| 1. Concurrencia (script `exp1.py`) | **12 procesos y 12 hilos**, 12 pacientes por la misma hora, 15 rondas: siempre 1 éxito, 0 respuestas 500, estado final con los CHECK intactos y `PRAGMA integrity_check` = ok. Un paciente con 12 horas solapadas (12 profesionales), 10 rondas: siempre 1. Un paciente con 12 horas **no** solapadas a la vez: las 12 se reservan (el bloqueo no produce falsos rechazos). Profesional eliminando mientras 2 pacientes reservan, 25 rondas por modo: 13/12 (procesos) y 18/7 (hilos) reservadas/eliminadas, siempre coherente (o la fila existe y está reservada por exactamente un paciente que vio éxito, o no existe y nadie vio éxito), sin 500. Profesional que reserva: 403. Además, **servidor real** `flask run --no-reload` con 12 clientes HTTP simultáneos sobre 6 horas: 1 éxito por hora, solo 302, 0 *tracebacks* en el log (`exp_srv.py`). |
| 2. Regla 5 contra modelo independiente (`exp2.py`) | Modelo con `zoneinfo` (instantes con `fold=0`, descartando horas ambiguas/inexistentes), 3 pacientes, 3 profesionales, duraciones 10-180 min, minutos aleatorios, cancelaciones intercaladas, en la noche de abril (3-4 abr 2027), la de septiembre (4-5 sep 2027) y un día normal: **800 decisiones, 0 discrepancias** (185 aceptadas, 615 rechazadas). Las reservas de otros pacientes no cuentan y las canceladas (estado vuelve a libre) tampoco; adyacentes por ambos lados se aceptan. |
| 3. Hora futura (`exp34.py`) | inicio == ahora: rechazada; +1 s: aceptada; -1 s, en curso, pasada de 5 días: rechazadas; ahora = 11:59:59,9 con inicio 12:00:00: aceptada; ahora = 12:00:00,1: rechazada; hora pasada forzada por POST aunque no salga en la lista: rechazada con «Esa hora ya empezó o ya pasó». |
| 4. Seguridad (`exp34.py`) | «No existe» y «ocupada por otro»: mismo texto, mismo código y mismo `Location`. Ids `0`, `-1`, `abc`, `+1`, `1e3`, `%20`, `1%00`, 10²¹: 404. Sin token, token vacío, token de otra sesión, cabecera `X-CSRFToken` falsa: 400. GET/HEAD: 405 (`Allow: OPTIONS, POST`). Sin sesión (con token de `/login`): 302 a `/login` (lo cubre la suite). Profesional: 403. Campos `paciente_id`, `reservada_en`, `estado`, `profesional_id` en el formulario: ignorados (la fila queda con el paciente de la sesión y la hora del reloj). `Cache-Control: no-store` en la respuesta 302 y en la página a la que redirige. Nombre del profesional `Dr <script>alert(1)</script> & Co`: el flash sale escapado (`&lt;script&gt;`). |
| 5. `reservada_en` | `2026-10-12T12:00:00-03:00`: ISO con zona de Chile, sin fracción, igual que `usuarios.creado_en` (`2026-10-08T15:56:31-03:00`). Invierno -04:00 (lo fija una prueba). |
| 6. Refactor | Ver R-10. |
| 7. Mutaciones propias | 16 (14 pedidas + 2 variantes). Ver R-04 y R-05: 11 mueren, 5 sobreviven (una solo según la zona horaria del equipo). |
| 8. Rendimiento | Bloqueo de escritura de `reservar_hora` con 50 000 filas en `horas`: 32 ms (0 reservas propias), 28 ms (200), 68 ms (2 000). Bloqueo externo de 7 s: la petición espera 5,0 s y responde 500 (página genérica en inglés); al soltarse el bloqueo la siguiente reserva funciona (302). |

No ejecuté: navegador real ni diseño (HTML sin estilos), varias réplicas del servidor, carga sostenida, las 29 mutaciones del implementador (no las repetí; solo las leí en PROGRESS), el recorrido manual exacto de PROGRESS (hice el mío con servidor real y 12 clientes).

## Hallazgos

### R-01 — El paciente no puede ver ni cancelar sus reservas hasta T-11 — media (planificación)
Tras reservar, el paciente solo ve un aviso flash en `/paciente` («Listo, reservaste tu hora: 09-10-2026 10:00 con Dr. Pro.»). Al recargar desaparece, `/paciente` no lista nada (hoy solo saludo, enlace a horas y «Cerrar sesión») y la hora desaparece de `/paciente/horas` (filtra `libre`). T-08 (`POST /horas/<id>/cancelar`) depende solo de T-07 y no menciona ninguna pantalla desde la que cancelar; la lista «próxima sesión / historial» (US-10) está en T-11, que depende de T-09 (después de T-08, T-09). Consecuencias: (a) T-08 quedaría sin botón (solo probable con POST a mano); (b) el recorrido de SPEC §9 (reserva → confirmación → recordatorio → cancelación) no se puede hacer por la interfaz; (c) el mensaje de rechazo de la regla 5 dice «Cancela esa reserva» y el paciente no tiene dónde hacerlo. US-8 («recibo confirmación») se cumple en el mínimo.
Reproducción: reservar y cargar `/paciente` dos veces.
Recomendación: **ajuste de TASKS** (orquestador): que T-08 incluya una lista mínima «Mis reservas» (futuras, con botón «Cancelar» con token CSRF) en `/paciente`, que T-11 después amplía con historial y notificaciones; o adelantar la parte de T-11 que lista reservas.

### R-02 — El reloj se lee antes de esperar el bloqueo: `ahora` y `reservada_en` pueden quedar viejos — baja
La ruta llama `tiempo.ahora_chile()` antes de `BEGIN IMMEDIATE`. Si la petición espera el bloqueo de escritura (hasta 5 s), usa un «ahora» anterior al instante real del commit. Reproducción (`exp9.py`): bloqueo externo de 4,5 s, hora que empieza dentro de 3 s: la reserva se acepta y se confirma a las 16:04:20, **un segundo después de que la hora empezara**, con `reservada_en = 16:04:16` (3-4 s antes del commit). Impacto real mínimo (los bloqueos duran decenas de ms), pero el mismo patrón en T-08 (24 h exactas) y en `reservada_en` (orden de reservas bajo contención) es evitable.
Recomendación: **absorber en T-08**: tomar el reloj dentro de la transacción, después de `BEGIN IMMEDIATE` (p. ej. pasar `tiempo.ahora_chile` como función, o llamarlo dentro) y hacerlo igual en cancelar; una prueba con un bloqueo externo corto que verifique que `reservada_en` es posterior al fin de la espera.

### R-03 — Bloqueo de SQLite > 5 s → 500 con página en inglés — baja (ya conocida)
Medido: 5,0 s de espera y «500 Internal Server Error»; la base queda intacta y la siguiente reserva funciona. Mismo caso que T-05 R-02 (backlog) y reconocido en D-028. La transacción de T-07 es corta (≤ 68 ms con 2 000 reservas propias y 50 000 filas), así que en la práctica solo ocurre con un proceso externo colgado.
Recomendación: **backlog** ya existente (T-05 R-02); al absorberlo, cubrir `crear_hora`, `eliminar_hora`, reservar y cancelar con el mismo manejo (`OperationalError` → «El sistema está ocupado, inténtalo de nuevo»). El cálculo dentro de la transacción es aceptable: son los intervalos de las reservas del paciente (decenas), sin SQL adicional.

### R-04 — Faltan pruebas de que cada salida deja la transacción cerrada — baja
Mutaciones que **sobreviven** a la suite completa: E (sin `rollback` en «ya empezó»), F (sin `rollback` en «no existe»), G (sin `rollback` en «no libre»), Z (el `except` solo atrapa un tipo de error, es decir, no hay `rollback` ante una excepción inesperada). Hoy son inocuas porque `close_db` cierra la conexión al terminar la petición, pero `reservar_hora` es una función con `db` como parámetro (la reutilizarán T-08/T-09/CLI) y el bloqueo de escritura quedaría tomado hasta que alguien cierre la conexión. Mueren: H (sin `rollback` tras `rowcount != 1`), y el de solape (la prueba `test_un_rechazo_no_deja_la_transaccion_abierta`).
Recomendación: **backlog / absorber en T-08**: una prueba parametrizada que, para cada `return False` y para una excepción inyectada (p. ej. `IntegrityError` en el UPDATE), exija `db.in_transaction is False` y que una segunda conexión pueda escribir.

### R-05 — Con la zona del equipo = Chile sobrevive una mutación de zona — baja
Mutación D: `ahora.replace(tzinfo=None).timestamp()` (tomar la hora de pared de Chile como si fuera la del servidor) pasa toda la suite cuando el proceso corre con `TZ=America/Santiago` (el entorno de trabajo lo tiene así) y **muere** con `TZ=UTC` o `TZ=Asia/Tokyo` (verificado). Es decir, la suite solo detecta ese error si se ejecuta en una zona distinta de Chile.
Recomendación: **backlog**: que `conftest.py` fije `TZ=UTC` (con `time.tzset()`) para toda la suite, o una prueba que corra el cálculo bajo `TZ=UTC` en un subproceso. Nota también para el verificador de T-14: correr `pytest` una vez con `TZ=UTC`.

### R-06 — Suite ≈ 48 s: conviene abrir la tarea de velocidad antes de T-09 — baja
Medido: 46,5 s (corrida limpia) y 50,7 s (con `--durations`). T-07 aporta 6,3 s (`test_reservar.py`, 53 pruebas, la concurrencia con procesos son menos de 2 s); `test_horas.py` suma 12,9 s y `test_esquema.py` 6,2 s; ninguna prueba individual pasa de 3,4 s: el costo es de unos 50 ms por prueba (app y base nuevas por prueba). Tendencia: 25 s (T-04b) → 35 s (T-05) → 48 s; cada tarea aporta 5-6 s, y T-08/T-09 la llevarían sobre 60 s.
Recomendación: **tarea nueva pequeña** (después de T-08, antes de T-09) con la solución más barata: base plantilla ya inicializada que se copia por prueba, o una fixture de módulo para las pruebas de solo lectura; `pytest-xdist` requeriría `DECISIONS.md` (dependencia) y revisar la concurrencia de `test_reservar` (procesos y bloqueos). No bloquea nada.

### R-07 — Detalles de enumeración y rutas alias — informativa
(a) Una hora libre que ya empezó responde «Esa hora ya empezó o ya pasó», distinto de «no está disponible»: revela que el id existe y está libre. Ya es visible en la lista (que muestra los ids en los formularios) y es una cuenta única de profesional; **ignorar**. (b) `/horas/١/reservar`, `/horas/0001/reservar` y `/horas/%D9%A1/reservar` llegan al id 1 (302, no 404): Werkzeug acepta dígitos Unicode y ceros a la izquierda; ya anotado (T-05 R-06), **T-14**. (c) PUT/DELETE/PATCH sin token responden 400 (CSRF antes que 405): inocuo.

### R-08 — Preguntas para el humano sobre el alcance — informativa
(1) **Anticipación al reservar**: SPEC no impide reservar una hora que empieza en 3 horas. Esa reserva nunca podrá cancelarse (US-9 exige 24 h) y el recordatorio de T-10 saldría en la primera ejecución. Decidir si se aceptan o se exige un mínimo. (2) **Regla 5** dice «dos reservas a la misma hora»; D-028 la implementa como solape de intervalos [inicio, fin) (más estricta, correcta con duraciones distintas y con D-023). Confirmar que es lo querido (hoy es coherente con la regla 3 del profesional). **Decisión humana**, no bloquea.

### R-09 — Notas para T-08, T-09, T-10, T-11 y T-12 — informativa
- **T-08**: ver R-01 (pantalla) y R-02 (reloj dentro de la transacción). Cancelar con `UPDATE ... SET estado='libre', paciente_id=NULL, reservada_en=NULL WHERE id=? AND paciente_id=? AND estado='reservada'` y revisar `rowcount`; anticipación `inicio_s - ahora_s >= 24*3600`. La regla 5 de T-07 ya ignora lo que vuelve a `libre`. Mensaje distinto para «no es tuya» vs «no existe» no debe filtrar (mismo texto, como en T-07).
- **T-09**: el punto natural es dentro de `reservar_hora`, entre la comprobación `reservadas != 1` y `db.commit()`, con la misma conexión y sin `commit` propio en `notificaciones.py`, para que reserva y notificaciones sean atómicas. El `SELECT` de la hora **no trae `h.profesional_id`** (hoy solo el nombre): T-09 lo necesita para notificar al profesional. El mensaje debe bastarse solo (fecha, hora, contraparte; `hora_id` puede quedar NULL, D-016). La escritura de `outbox.log` (archivo) conviene después del `commit`, para que un fallo del archivo no deshaga una reserva válida; decidirlo explícitamente.
- **T-10**: `recordatorio_enviado` empieza en 0 por el esquema; T-07 no lo toca. Ver R-08 (1).
- **T-11/T-12**: `reservada_en` es texto con desfase; **no ordenar por él**: en la hora repetida de abril `2027-04-03T23:10:00-04:00` (más tarde) ordena antes que `2027-04-03T23:30:00-03:00` (por comparación de texto, no ejecutado). Ordenar por instante de `inicio` (`tiempo.a_segundos_utc`) como hace T-06.

### R-10 — Refactor `intervalo_guardado` y pruebas retiradas — informativa (sin problema)
El diff de `profesional.py` es un traslado literal: `_minutos_guardados` y `_intervalo_guardado` pasan a `tiempo.py` con el cuerpo idéntico (solo cambia el docstring); los tres usos (`buscar_solape`, `_describir`) se actualizan, no quedan referencias al nombre antiguo y `profesional.py` no deja importaciones sin uso. Mi mutación J (aceptar minutos de cualquier tipo en la función movida) muere en `test_horas.py`, así que las pruebas del profesional siguen vigilando la función. Las «6 líneas eliminadas de `tests/`» son 5 de `test_no_hay_boton_de_reservar_todavia` (obsoleta: exigía que no hubiera `<form`; se reemplazó por una prueba que exige el formulario, el token y el id por fila) y 1 de `test_rutas_publicas.py` (la misma línea con `paciente.reservar` agregado): sin pérdida de cobertura. `tests/test_reservar.py` está justificado en D-028 (regla 10 de CLAUDE.md).

### R-11 — Veracidad de PROGRESS.md — informativa (sin problema)
Verificado: 956 pruebas OK; 54 nuevas = 53 en `test_reservar.py` + 1 en `test_horas.py` (la de `test_horas_libres.py` es un reemplazo neto 0); `FLASK_DEBUG=1`/`SECRET_KEY=abc` pasan; la concurrencia con procesos e hilos y los resultados del recorrido (reservar, rechazar a B, cruce, adyacente, 403, sin token, id 2**63) coinciden con lo que reproduje. `reservada_en = 2026-10-08T15:43:21-03:00` es plausible (anterior al commit). La hora de la entrada (15:47) coincide con el commit (15:47:14) y D-028 dice 15:46: esta vez no hay desfase (la regla 8 se respetó). No pude comprobar el contenido de las 29 mutaciones del implementador (script fuera del repo); de mis 16, 11 mueren, y las que sobreviven (R-04, R-05) no coinciden con las suyas porque son distintas.

## Mutaciones propias (distintas de las 29 del implementador)

Cada una en una copia completa; primero `test_reservar + test_horas_libres + test_rutas_publicas + test_horas` con `-x` y, si sobrevive, la suite completa.

| # | Mutación | Resultado |
|---|---|---|
| A | solape solo con `otro_inicio < fin_nuevo` | muere (`adyacentes_o_separadas`) |
| B | solape solo con `inicio_nuevo < otro_fin` | muere (`adyacentes_o_separadas`) |
| C | `minutos * 30` en `tiempo.intervalo_guardado` | muere (`solapes_del_mismo_paciente`) |
| D | `ahora.replace(tzinfo=None).timestamp()` | **sobrevive con TZ=America/Santiago**, muere con TZ=UTC/Tokyo (R-05) |
| E | sin `rollback` en «ya empezó» | **sobrevive** (R-04) |
| F | sin `rollback` en «no existe» | **sobrevive** (R-04) |
| G | sin `rollback` en «no libre» | **sobrevive** (R-04) |
| H | sin `rollback` si `rowcount != 1` | muere (`el_update_condicional_decide`) |
| J | `minutos` acepta cualquier tipo | muere (`test_horas`) |
| K | `reservada_en` con reloj propio (`datetime.now`) | muere (`reserva_exitosa`) |
| M | la ruta acepta GET | muere (`get_no_reserva`) |
| Q | `ID_MAX = 2**63` | muere (`ids_invalidos_o_gigantes`) |
| X | `BEGIN EXCLUSIVE` en vez de `IMMEDIATE` | muere (`primera_sentencia_es_begin_immediate`) |
| Z | `except` que ya no atrapa excepciones inesperadas (sin `rollback`) | **sobrevive** (R-04) |
| W | tolerancia de 1 s a favor de la hora que empieza | muere (`un_segundo_despues_de_ahora_si_se_reserva`) |
| V | el mensaje de solape muestra la hora nueva en lugar de la existente | muere (`solapes_del_mismo_paciente`) |

## Resumen de recomendaciones

| Hallazgo | Severidad | Acción |
|---|---|---|
| R-01 | media | Ajuste de TASKS: lista «Mis reservas» con «Cancelar» dentro de T-08 |
| R-02 | baja | Absorber en T-08 (reloj dentro de la transacción) |
| R-03 | baja | Backlog ya existente (T-05 R-02) |
| R-04 | baja | Absorber en T-08 (prueba de transacción cerrada en cada salida) |
| R-05 | baja | Backlog (`TZ=UTC` en la suite) |
| R-06 | baja | Tarea nueva pequeña de velocidad tras T-08 |
| R-07 | informativa | Ignorar / T-14 |
| R-08 | informativa | Decisión humana (anticipación al reservar; regla 5 como solape) |
| R-09 | informativa | Notas para T-08 a T-12 |
| R-10, R-11 | informativa | Sin acción |
