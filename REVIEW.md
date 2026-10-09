# REVIEW — T-10 Recordatorios 24 h antes (commit `b92c5a8`)

Revisor: lee el diff, contrasta con SPEC US-12 / §4 / §5, D-016, D-029, D-030, D-032 y D-033.
No se modificó código, pruebas, TASKS, PROGRESS, DECISIONS ni ARCHITECTURE.
Todo lo ejecutado se hizo en copias bajo el scratchpad (`rev/`, `rev2/`, `m/`), nunca en el repo.

**Veredicto: APROBADA.** No hay hallazgos de severidad alta ni media. Los hallazgos R-01 a R-04
son bajos y van al backlog o a T-14; el resto son informativos.

## Resumen de lo que SÍ se ejecutó

- Suite completa en copia: 1581 pruebas OK (y `tests/test_recordatorios.py` solo: 74 OK, también con `TZ=Asia/Tokyo`). Tras la suite no quedan `outbox.log` ni `agenda.db` en la copia del repo.
- `flask --app app send-reminders` real contra bases en el scratchpad, con `SECRET_KEY` sin definir (D-008 se cumple), con `TZ=UTC`, `Asia/Tokyo` y `America/Santiago`: salida de una sola línea `Recordatorios enviados: N.` sin datos personales, código 0.
- Base con 6 filas (reservada a 23 h, reservada a 30 h, libre, reservada que empezó hace 1 h, `inicio` corrupto `2026-13-45T99:99:99`, reservada con `duracion_min='abc'`): se recuerda solo la de 23 h; las corruptas y las que no corresponden no tiran el comando y quedan sin marcar. `TZ=UTC` la envía, la segunda ejecución con otra zona del sistema ya no repite.
- Barrido de instantes en las dos noches de cambio de horario (ahora = sábado 5-sep-2026 23:30 -04:00 y sábado 4-abr-2026 23:30 -04:00, segunda ocurrencia), 68 horas de pared cada 30 min entre -2 h y +31 h, con `TZ` del sistema = UTC, Asia/Tokyo, America/Santiago y Pacific/Auckland: el conjunto enviado coincide exactamente con `0 < inicio - ahora <= 24 h` en instantes absolutos en las 8 combinaciones. La ventana SQL no deja fuera ninguna hora válida.
- Concurrencia: 4 procesos `flask send-reminders` reales a la vez sobre una base con 1 recordatorio pendiente: 1 sola fila en `notificaciones`, 1 sola línea en `outbox.log`. Además 4 procesos `fork` con `enviar_recordatorios` y un quinto cancelando en bucle (300 horas, reloj fijo): 145 recordatorios, 0 duplicados, 0 recordatorios con `id` posterior a una cancelación de la misma hora, 0 libres con `recordatorio_enviado = 1`, 0 reservadas dentro de la ventana sin marcar.
- Bloqueo: otro proceso con `BEGIN IMMEDIATE` abierto 7 s: el comando espera 5,3 s (timeout por defecto de `sqlite3`), muere con `OperationalError: database is locked`, código 1 y nada queda marcado. No hay espera indefinida.
- Fallos: trigger `RAISE(ABORT)` en `INSERT INTO notificaciones`: traza, ninguna hora marcada, 0 notificaciones; al quitar el trigger la siguiente ejecución sí envía. `OUTBOX_PATH=/dev/full` y `/proc/nope/x.log`: código 0, el error va a `app.logger` (sin contenido de mensajes), hora marcada y notificación guardada, la segunda ejecución no reenvía.
- Mutaciones propias (copia, `tests/test_recordatorios.py` + `tests/test_notificaciones.py`, 125 pruebas): ver R-03 y "Calidad de pruebas".

## Hallazgos

### R-01 — `send-reminders` con base inexistente o sin tablas muestra una traza y crea un archivo vacío (baja)

Evidencia:

```
$ DATABASE=$S/run1/nada.db flask --app app send-reminders
Traceback (most recent call last): ... sqlite3.OperationalError: no such table: horas      (rc=1)
$ ls $S/run1        ->  nada.db            # archivo vacío creado como efecto colateral
$ DATABASE=$S/run1/no/existe/x.db flask --app app send-reminders   -> traza "unable to open database file" (rc=1)
$ DATABASE=<archivo vacío> ...                                       -> traza "no such table: horas" (rc=1)
```

El código de salida es distinto de cero (correcto para cron), pero el mensaje no es claro y un error de tipeo
en `DATABASE` deja un `.db` vacío (porque `get_db` hace `sqlite3.connect`, que crea el archivo). Causa en
`app/db.py:get_db`, no específica de T-10; `create-professional` tiene el mismo comportamiento.

Recomendación: backlog, absorber en T-14 junto con T-02c #4 (aviso por esquema antiguo): en el comando,
capturar `sqlite3.OperationalError` y lanzar `click.ClickException("No se encontró la base de datos ...; ejecuta init-db")`
y no crear el archivo si no existe. No bloquea T-10.

### R-02 — Un bloqueo de más de 5 s termina el comando con traza y código 1, sin reintento (baja)

Evidencia: ver "Bloqueo" arriba (5,3 s, `database is locked`, rc=1). Es el mismo límite aceptado en D-028/D-030
para las peticiones web. Es seguro (nada marcado, la siguiente ejecución del cron reintenta) y D-033 lo implica
pero no lo dice para el comando.

Recomendación: ignorar o mencionarlo en el README de T-14 («si el comando falla con `database is locked`, el cron
lo reintenta en la siguiente ejecución»). No requiere código.

### R-03 — Mutantes que sobreviven: son equivalentes, pero juntos sí se detectan (informativa)

Pregunta del orquestador: (a) quitar `recordatorio_enviado = 0` del `UPDATE` y (b) quitarlo del `SELECT`.

Evidencia (copia, 125 pruebas):

```
(a) UPDATE sin "AND recordatorio_enviado = 0"   -> 125 passed
(b) SELECT sin "AND h.recordatorio_enviado = 0" -> 125 passed
(a)+(b) juntas                                  -> 4 failed, 70 passed:
    test_el_comando_dos_veces_seguidas_no_duplica,
    test_una_reserva_hecha_entre_24_h_y_24_h_mas_el_periodo_se_envia_en_la_siguiente_ejecucion,
    test_tres_procesos_a_la_vez_no_duplican_ningun_aviso (+1)
```

Por qué cada una es equivalente por separado: el `SELECT` y los `UPDATE` ocurren dentro del mismo `BEGIN IMMEDIATE`
y sobre ids distintos (una fila por `id`), así que entre la lectura y la escritura nadie puede cambiar
`recordatorio_enviado`; la segunda barrera nunca ve una fila distinta de la que vio la primera. Cada guarda es
defensa en profundidad de la otra, y las pruebas de «no repite» mueren cuando faltan las dos. No es un hueco de pruebas.

También sobreviven, por la misma razón, estas mutaciones que probé: (c) quitar el `if marcadas != 1: continue`
(125 OK; `rowcount` siempre es 1 dentro del bloqueo), (d) quitar solo `h.estado = 'reservada'` del `SELECT`
(74 OK; ya lo declara PROGRESS) y (e) `desde = ahora de pared` en lugar de `ahora - 1 día` (125 OK; el margen inferior
solo importaría para una hora de pared repetida de abril, que la aplicación no deja guardar, D-025).
Mueren: `MARGEN_SQL_DIAS = 0` (9), `hasta` sin el día extra (9), `hasta = ahora + 1 d + 30 min` y `+ 59 min`
(3 cada una, por la prueba del inicio del horario de verano), sin ordenar por instante (1), sin `rollback` (1),
`timestamp` del `datetime` sin zona (18), `creada_en` sin zona (1), sin la guarda de `intervalo is None` (1),
tipo desconocido que cae en cancelación (5), sin el `continue` del mensaje `None` (40), texto distinto del mensaje (1).

Recomendación: ignorar. Sí corregir la redacción de PROGRESS (ver R-08): dice que sobrevivió «solo» el filtro de
estado; sobreviven al menos (a), (b), (c) y (e) por separado.

### R-04 — Una fila que haga fallar el `INSERT` bloquea los recordatorios de todos los pacientes en cada ejecución (baja)

Evidencia: con un trigger que aborta `INSERT INTO notificaciones`, `send-reminders` termina en traza y no marca
ninguna de las 6 filas; con 2 pacientes en la misma pasada, ninguno recibe aviso mientras la causa persista
(`test_si_falla_un_aviso_a_mitad_no_queda_ninguno_marcado` fija ese comportamiento a propósito).
Es el precio de la atomicidad de la regla (c) de T-09 (marcar y avisar en la misma transacción) y hoy no hay un
camino realista que haga fallar el `INSERT` de una sola fila (usuarios con `NOT NULL`, FK válidas, texto siempre
construido). Aceptable en v1.

Recomendación: ignorar; si algún día aparece un fallo por fila, valorar un savepoint por hora. Decisión humana solo
si se quiere cambiar la semántica «todo o nada» de D-033 (4).

### R-05 — README no dice nada del cron: periodicidad, ejemplo y entorno compartido (baja, para T-14)

`README.md` solo menciona «recordatorio de hora» en el resumen. D-033 y PROGRESS lo reconocen («no está documentado
en README (T-14)»). Para T-14 conviene anotar:

1. El período del cron debe ser **menor que 24 h** y el retraso máximo de un recordatorio es ese período (un recordatorio llega entre `24 h - período` y `24 h` antes). Sugerir cada 5 a 15 minutos; D-033 dice «cada pocos minutos u horas».
2. Ejemplo de crontab, p. ej. `*/10 * * * * cd /ruta/agenda-psi && DATABASE=/ruta/agenda.db OUTBOX_PATH=/ruta/outbox.log .venv/bin/flask --app app send-reminders >> /ruta/reminders.cron.log 2>&1`. Comprobado: el comando no necesita `SECRET_KEY`.
3. `DATABASE` y `OUTBOX_PATH` deben ser los mismos que usa el servidor web; si no, el cron trabaja sobre otra base o escribe el log en otro lugar (el valor por defecto de `DATABASE` es relativo a la raíz de la app, el de `OUTBOX_PATH` va junto a la base).
4. Código de salida 1 + traza si la base está bloqueada o no existe (R-01, R-02); el cron lo reintenta.
5. El log no es fuente de verdad (D-033 7); mirar `notificaciones`.

Recomendación: tarea T-14 (ya está en su alcance); añadir estas cinco líneas a su texto en TASKS.md.

### R-06 — El recorrido manual de SPEC §9 («reserva → confirmación → recordatorio → cancelación») no se puede hacer tal cual (informativa, para T-14)

Con D-029 se reserva solo con más de 24 h de anticipación, se cancela solo con 24 h o más, y el recordatorio solo
llega con 24 h o menos. En el flujo normal el orden «recordatorio → cancelación» solo coincide a las 24 h exactas
(el caso cubierto por `test_si_el_recordatorio_gana_la_cancelacion_igual_funciona_y_reabre_la_hora`). Además el
Verificador no puede esperar 24 h reales. Opciones para T-14: (i) recorrido: reservar una hora a más de 24 h,
adelantar su `inicio` con un `UPDATE horas SET inicio = ...` sobre la base de prueba (la aplicación no lo permite
y las pruebas ya lo hacen por SQL), ejecutar `send-reminders`, comprobar la notificación y la línea del log, y
**cancelar otra reserva** distinta para la parte de la cancelación; (ii) decisión humana: ajustar la redacción de
§9 (SPEC) para que el recordatorio y la cancelación no se pidan sobre la misma reserva. Anotarlo en la tarea T-14.

### R-07 — Notas para T-11 / T-12 sobre notificaciones de tipo `recordatorio` (informativa)

- El recordatorio es una fila solo del paciente (`usuario_id` del paciente); el dashboard del profesional (T-12) no debe esperar una. Añadir una prueba por rol.
- `hora_id` del recordatorio apunta a la hora; si el paciente luego cancela a las 24 h exactas y otro paciente reserva esa hora, el recordatorio viejo conserva `hora_id` hacia una hora que ya es de otro. T-11 debe mostrar solo `mensaje` (y el enlace solo si la hora sigue siendo del mismo paciente, o no enlazar), nunca datos de la hora actual vía `LEFT JOIN` que puedan ser de otro paciente. Mismo cuidado con la nota existente sobre `hora_id` NULL (D-016).
- Ordenar por `id`, no por `creada_en` (ya anotado); el recordatorio usa el `ahora` del cron con zona, igual que las demás.
- La campana puede mostrar «Recordatorio: tienes una hora…» de una hora ya cancelada (solo en el caso de las 24 h exactas). Es coherente con D-033 (5); no hacer nada.

### R-08 — Documentación: veraz en lo esencial, con tres imprecisiones menores (informativa)

- PROGRESS (T-10) afirma «Sobrevivió: quitar solo el filtro `h.estado = 'reservada'`». Verificado (74 OK) pero incompleto: ver R-03. Las 14 mutaciones que declara muertas coinciden en espíritu con las que reproduje; no repliqué los conteos exactos de fallas de cada una.
- PROGRESS «Estado actual» sigue en «Última tarea hecha: T-08d» (el propio implementador lo anota como no suyo). Lo debe actualizar el Orquestador.
- D-030 conserva «Notificaciones (T-09) y recordatorios (T-10) tampoco» dentro de «No implementado»; tiene nota de actualización para D-029 pero no para T-09/T-10. Es historial, sin riesgo.
- Sin contradicciones entre D-033, D-029 y D-030 sobre los bordes: 24 h exactas sí (cancelar permite `>= 24 h`, recordar `<= 24 h`), hora de inicio exacta no. D-033 (2) dice «filas con fecha o duración ilegibles se omiten sin marcarlas»: verificado con CLI real. La cifra «74 pruebas» y «1581» coinciden con lo ejecutado.
- ARCHITECTURE ya lista `flask --app app send-reminders` y `notificaciones.py` con recordatorios: sin cambio necesario.

### R-09 — Huecos menores de pruebas, sin impacto observable (informativa)

- No hay prueba de `enviar_recordatorios` cuando el reloj está en la hora repetida de abril (`fold=1`) ni con filas de hora de pared inexistente/ambigua insertadas por SQL. Lo cubrí con el barrido descrito arriba (coincide con el criterio absoluto) pero no quedó como prueba. Recomendación: backlog, absorber en T-14 si se revisa el horario de verano.
- No hay prueba del comando con base inexistente (R-01) ni con bloqueo (R-02).
- La concurrencia con cancelación real no está probada (solo reservas fijas con 3 procesos). La cancelación y el recordatorio solo se solapan en el instante de las 24 h exactas, y ambas toman `BEGIN IMMEDIATE` y leen dentro: el diseño es correcto y mi simulación con cancelación en paralelo no halló inconsistencias, pero mi corrida casi no tuvo contención (0,2 s). Recomendación: ignorar.

## Calidad de pruebas

Pruebas cuya razón de falla verifiqué con mutaciones (muere exactamente la prueba declarada):

| Prueba | Mutación | Resultado |
|---|---|---|
| `test_orden_por_instante_y_no_por_id` | quitar `pendientes.sort` | falla solo esa |
| `test_si_falla_el_aviso_no_queda_marcado_ni_hay_linea` | quitar `db.rollback()` del `except` | falla solo esa (`db.in_transaction`) |
| `test_el_mensaje_se_basta_solo` | `creada_en` sin zona; texto distinto | falla solo esa (2 mutaciones) |
| `test_una_fila_ilegible_se_omite_sin_marcarla_y_las_buenas_se_envian` | quitar `if intervalo is None: continue` | falla solo esa |
| `test_un_tipo_sin_mensaje_se_rechaza_y_no_inserta_nada[...]` | tipo desconocido cae en cancelación | 5 fallas, las de esa prueba |
| `test_el_borde_se_mide_en_instantes_al_empezar_el_horario_de_verano` | `hasta = ahora + 1 d + 30/59 min` | 3 fallas (una por zona del sistema), las de esa prueba |
| `test_el_borde_de_las_24_horas_y_el_de_inicio` | `ahora.replace(tzinfo=None).timestamp()` | 18 fallas (zona del sistema), y con `MARGEN_SQL_DIAS=0` 9 fallas por el borde exacto |

Observaciones: la ventana SQL solo está atada por el borde de 24 h exacto y por la noche de septiembre; la de abril
no restringe `desde` (R-03 e). Las 74 pruebas pasan solas y con `TZ=Asia/Tokyo`; no escriben fuera de `tmp` ni dejan
`outbox.log` o `agenda.db`. Acoplamiento: el archivo importa ayudantes de `test_cancelar`, `test_horas_libres`,
`test_login`, `test_notificaciones` y `test_reservar`; un cambio en cualquiera de esos módulos puede romperlo
(coste de mantenimiento, no un defecto). Redundancia leve: la prueba del borde se repite ×3 zonas del sistema.

## No verificado

- `cron` real; Windows; `flask run` con un navegador; envío del comando desde un directorio de trabajo distinto de la raíz del proyecto.
- Orden inverso de las pruebas del archivo (mi intento falló por un error en cómo armé los ids; la suite sí corre completa y sola sin dejar residuos).
- Conteos exactos de fallas por mutación que declara PROGRESS (verifiqué que mueren, no cuántas fallas).
- Contención real entre cancelación y recordatorio en el instante de las 24 h exactas con procesos de `flask` separados.
