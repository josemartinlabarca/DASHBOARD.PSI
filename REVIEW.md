# REVIEW — T-08 Cancelar reserva y «Mis reservas» (commit `1a8e1d8`)

Revisor: leí el diff y ejecuté experimentos y mutaciones en copias bajo el scratchpad (`rev/`, `exp/`, `mut/`, `mutar.py`). No se tocó el repositorio salvo este archivo (`git status` limpio antes de escribirlo). Sin commit.

## Veredicto: CAMBIOS REQUERIDOS

La lógica de T-08 es correcta: el borde de 24 h, la concurrencia, el reloj tras el bloqueo y «Mis reservas» pasaron todo lo que probé, y los hallazgos R-01, R-02, R-04 y R-05 de T-07 quedan cerrados. El único bloqueante es **R-01 de esta revisión**: la fixture automática `time.tzset()` hace que **ninguna prueba corra en Windows**, plataforma que el README y D-012 declaran soportada. Es un arreglo de pocas líneas. Además hay un callejón sin salida de producto (R-02, ya conocido como D-029) que conviene que el humano decida antes de T-09.

## Qué verifiqué ejecutando

| Punto | Resultado |
|---|---|
| Suite (copia del commit, `TZ=America/Santiago` del equipo) | **1117 passed en 65,9 s** (la entrada dice ≈62 s). 1117 − 956 = 161 nuevas (158 en `test_cancelar.py` + 3 por la prueba parametrizada nueva de `test_reservar.py`). Las líneas eliminadas de `tests/` son 4 (`git diff a64a234 1a8e1d8 -- tests`): 3 en `test_reservar.py` y 1 en `test_rutas_publicas.py`, como dice PROGRESS. |
| 1. Borde de 24 h, `exp/e1.py` y `e1b.py` | Modelo independiente (`zoneinfo`, `fold=0`, resta de instantes UTC), **1500 casos aleatorios** (1055 pegados al borde ±2 s y ±1 µs) en las ventanas de septiembre y abril de 2026 y 2027 y en un día normal, con el sistema en UTC: **0 discrepancias**, ninguna transacción abierta. Casos fijos con el sistema en Tokio: exactamente 24:00:00 se permite; +1 µs, +0,5 s y +1 s se rechazan; −1 µs y −1 s se permiten; 6 horas de las dos noches de cambio de horario (23:30, 01:00, 00:30, 10:00) × {0, −1, +1 s}: todas coinciden con el modelo. |
| 1. HTTP, `e2.py` | Reserva ajena, inexistente, ya libre y doble clic: **mismo texto y mismo `Location: /paciente`**. Profesional: 403. GET: 405. Sin token: 400. Una reserva con `recordatorio_enviado=1` queda tras cancelar como `('libre', NULL, NULL, 0)`; la reserva ajena no cambia. Una notificación ligada a la hora **sigue ahí con `hora_id` intacto** (no se borra la fila, `ON DELETE SET NULL` no se dispara). Tras cancelar, Beto reserva la misma hora y, tras cancelar él, Ana la reserva de nuevo. Los CHECK impiden `libre` con `paciente_id`, `reservada` sin `reservada_en`, etc. (verificado con UPDATE directo). |
| 2. Concurrencia real, `e4.py` | Archivo SQLite, cada cliente con su app y su conexión, barrera, **12 procesos y 12 hilos**, 3 rondas por escenario: 12 cancelaciones simultáneas = exactamente 1 «Cancelaste…» y 11 «No encontramos…»; 6 cancelaciones de Ana contra 6 reservas de Beto = siempre 1 cancelación y 1 reserva, estado final `reservada` por Beto; 6 cancelaciones contra 6 eliminaciones del profesional = 1 cancelación y 1 eliminación (fila borrada, el resto «No se puede eliminar…» o 404); mezcla 4+4+4 coherente. **0 respuestas 500**, `PRAGMA integrity_check` ok, la base se abre sin bloqueo después. |
| 3. Reloj tras el bloqueo, `e5.py` | Un hilo mantiene `BEGIN IMMEDIATE` 2 s con otra conexión; la llamada espera. `reloj` se invoca a los **2,05 s (reservar) y 2,04 s (cancelar)**, después de soltar el bloqueo; `reservada_en` = segundo de commit, no el de la llamada (2 s antes). R-02 de T-07 cerrado. Otros llamadores de `reservar_hora`: solo la ruta y 3 pruebas (`grep`). |
| 4. «Mis reservas», `e3.py` | 0 reservas: «No tienes reservas próximas.» Con reservas en curso (empezó hace 30 min), pasada (hace 7 días), exactamente ahora, 23 h 59 min 59 s, 24 h exactas, 3 semanas y 5 semanas, más una de Beto y una hora libre: salen solo las 4 futuras propias, ordenadas por instante; 23:59:59 sin botón y con «Ya no se puede cancelar (faltan menos de 24 horas)»; 24:00:00 con botón; 3 formularios de cancelar + el de «Cerrar sesión», los 4 con `csrf_token`. Nombre de profesional `<script>alert(1)</script>&"x` escapado (`&lt;script&gt;`). `Cache-Control: no-store`, `Pragma: no-cache`. Nada de Beto ni de horas libres. |
| 5. Fixture de zona | Ver R-01 y R-05. Simulé Windows (`del time.tzset` vía `sitecustomize`): `tests/test_login.py` da **95 errores** `AttributeError: module 'time' has no attribute 'tzset'`. Una prueba temporal con `zona_sistema` seguida de otra sin ella ve `TZ=UTC` y se restaura bien (con `TZ` definido y sin definir). |
| 6. Mutaciones propias | **20** (14 pedidas + 6 más), subconjunto `test_cancelar, test_reservar, test_horas_libres, test_rutas_publicas, test_seguridad` con `-x`. **18 mueren, 2 sobreviven** (R-04). Tabla abajo. |
| 7. Suite | `--durations=0`: setup 33,6 s (972 × ≈35 ms), llamadas 28,6 s. Ver R-03. |
| 8. D-029, `e6.py` | Reservar una hora a 17 h: «Listo, reservaste tu hora…» sin aviso; en el panel sale «Ya no se puede cancelar»; cancelar por POST da el mensaje de anticipación; el profesional no puede eliminarla («Primero debe cancelarse la reserva»). Ver R-02. |

No verifiqué: navegador real ni diseño (HTML sin estilos); el recorrido manual del implementador (hice el mío por el cliente de pruebas de Flask, no con `flask run` y curl); las 51 mutaciones del implementador (solo las leí); `BEGIN IMMEDIATE` esperando más de 5 s (500 conocido, declarado, no lo repetí); varias réplicas ni carga sostenida; la suite con `TZ=Asia/Tokyo` (tampoco los «6 corridas» de concurrencia: confío en mis propias rondas).

Veracidad de PROGRESS: coincide en 1117/161/4 líneas, el R-05 reproducido (mi N16 muere), la hora de la entrada (`2026-10-08 16:34`) con el commit (16:34:50 −03) y la nota «reservar_hora cambió de firma, sin otros llamadores». Sin discrepancias.

### Mutaciones propias (distintas de las 51 del implementador)

| # | Mutación | Resultado |
|---|---|---|
| N01 | 24 h − 1 s | muere |
| N02 | decide con el **fin** de la sesión | muere |
| N03 | aviso de éxito con el `inicio` crudo | muere |
| N04 | `rowcount != 1` devuelve `True` | muere |
| N05 | panel muestra la que empieza justo ahora | muere |
| N06 | panel ordena solo por id | muere |
| N07 | cancelar redirige a la lista de horas libres | muere |
| N08 | plantilla sin el texto «Ya no se puede cancelar» | muere |
| N09 | columna profesional con el nombre del paciente | muere |
| N10 | ruta `min=0` | muere |
| N11 | cancelar sin comprobar fecha ilegible (cae en «poca anticipación») | **sobrevive** |
| N12 | `reservada_en` con `timespec="minutes"` | muere |
| N13 | `cancelar_reserva` ignora el parámetro `reloj` | muere |
| N14 | panel con reloj real en vez de `tiempo.ahora_chile` | muere |
| N15 | margen SQL de 1 día a 0 | **sobrevive** |
| N16 | `reservar_hora` con hora de Chile leída como hora del sistema (R-05 de T-07) | muere |
| N17 | botón del panel decidido con el fin de la sesión | muere |
| N18 | sin `rollback` en «poca anticipación» | muere |
| N19 | sin `rollback` en el solape de `reservar_hora` | muere |
| N20 | `except` de `cancelar_reserva` traga la excepción | muere |

M04 y M05 del implementador **sí son equivalentes**: con el CHECK de `horas`, `paciente_id` no nulo implica `reservada` y una hora libre tiene `paciente_id` NULL (probé los tres UPDATE que lo violarían: `IntegrityError`).

## Hallazgos

### R-01 — La fixture automática `time.tzset()` rompe toda la suite en Windows — media
`tests/conftest.py` llama `time.tzset()` en `zona_del_sistema_fija` (autouse) y en `fijar_zona_sistema`. `time.tzset` no existe en Windows. README (`.venv\Scripts\activate`, PowerShell, `pytest`) y D-012 (`tzdata` para `win32`) tratan Windows como soportado, y CLAUDE.md dice que una tarea no está terminada si `pytest` no pasa.
Reproducción: `printf 'import time\ndel time.tzset\n' > sc/sitecustomize.py; PYTHONPATH=sc python3 -m pytest -q tests/test_login.py` → 95 errores de configuración, ninguna prueba corre.
Recomendación: **tarea nueva T-08c (pequeña, antes de T-09)**: proteger con `hasattr(time, "tzset")`; si no existe, la autouse no hace nada y `zona_sistema` marca `pytest.skip("sin time.tzset")` (o parametriza solo con la zona actual); una prueba que fije el comportamiento simulando la ausencia como arriba. No requiere decisión humana.

### R-02 — Callejón sin salida: una reserva hecha con < 24 h no la puede deshacer nadie, y nada lo avisa al reservar — media (D-029)
Reproducción (`exp/e6.py`, ahora = 12:00): Ana reserva una hora de mañana 05:00 (17 h). Mensaje: «Listo, reservaste tu hora…», sin advertencia (ni en `horas_libres.html` ni en la confirmación). Después el panel dice «Ya no se puede cancelar»; el POST de cancelar da «Solo puedes cancelar con al menos 24 horas… comunícate con el profesional»; el **profesional tampoco puede**: eliminar da «No se puede eliminar una hora reservada. Primero debe cancelarse la reserva» (regla 4), y no existe ninguna pantalla donde el profesional cancele. El texto sugiere una salida que la aplicación no ofrece.
Es lo que D-029 describe; lo nuevo es que el mensaje de cancelar remite a un profesional que en v1 no tiene herramienta. La implementación de T-08 es coherente con SPEC (no se pedía otra cosa).
Recomendación: **decisión humana D-029, antes de T-09**. Si se aprueba B (solo reservar con ≥ 24 h), debe usar la misma constante y el mismo `>=` que cancelar, para que toda reserva exitosa sea cancelable en el instante de reservar; si C, el aviso va en la lista de horas libres (por fila con < 24 h) y en la confirmación, no solo después. Mientras tanto, cambiar el texto «comunícate con el profesional» por uno que no prometa una vía inexistente (T-09 o T-12).

### R-03 — La suite sube a 65,9 s; T-08b confirmado, con una advertencia sobre su meta — baja
`pytest --durations=0`: ningún caso pasa de 3 s (el mayor es `flask run` real, 3,0 s; luego la idempotencia exhaustiva, 2,8 s). El tiempo está en el conjunto: **setup 33,6 s** (972 preparaciones de ≈35 ms; `app` + `init_db` por prueba, en `test_cancelar.py` además un `init_db` autouse), **llamadas 28,6 s**. Por archivo (setup+llamada): `test_cancelar` 14,2 s (158 pruebas), `test_horas` 13,0 s (393), `test_reservar` 7,4 s, `test_esquema` 6,6 s (279), `test_login` 4,9 s, `test_registro` 4,6 s, `test_config` 4,0 s.
Orientación: copiar una base ya inicializada (plantilla) en vez de `init_db` en cada prueba recortaría la mayor parte del setup, pero la meta de T-08b (< 25 s) también exige bajar las llamadas (28,6 s hoy): `test_horas`, `test_cancelar` y las parametrizaciones. T-08 aportó ≈ 13,5 s (158 pruebas) sobre los 48 s anteriores.
Recomendación: **T-08b tal como está**; añadir en su texto que setup y llamadas pesan casi lo mismo.

### R-04 — Dos mutaciones sobreviven; ninguna es un defecto — baja
N11: si una reserva tiene fecha ilegible (solo por SQL, el CHECK deja pasar `2026-13-45T99:99:99`), quitar el chequeo hace que el rechazo salga con el mensaje de anticipación en vez del de «no encontrada»; la prueba `test_la_fila_con_fecha_ilegible…` solo exige categoría `error` y que la fila no cambie. Es un cambio de texto de un estado que la app no produce. N15: el margen SQL de 1 día es defensa; con 0 solo se pierde una fila imposible de crear (hora inexistente de septiembre guardada por SQL). Recomendación: **ignorar**.

### R-05 — La fixture `TZ=UTC` por prueba es adecuada, con tres matices — informativa
Evaluación: no hay código de la aplicación que dependa de la zona del sistema (`grep`: solo `datetime.now(zona_chile())` y conversiones con `zoneinfo`), de modo que fijar UTC no deja de probar nada de la app; la única clase de error que sí detecta es leer la hora de Chile como hora local (N16 la mata, y con el equipo en Santiago antes sobrevivía). Es una decisión adecuada, no excesiva, y el implementador la dejó expuesta como decisión suya, con la forma de revertirla. Se restaura bien y no contamina entre pruebas. Matices: (1) `os.environ["TZ"]` es del proceso, no del hilo; vale porque cada prueba corre hilos y procesos propios dentro de sí misma, pero fallaría con `pytest-xdist` en hilos (no se usa); (2) los subprocesos de las pruebas heredan `TZ=UTC` (inofensivo hoy); (3) solo 4 pruebas piden `zona_sistema` (tres zonas), las demás corren solo en UTC: basta para el borde, pero una prueba futura que dependa de la zona deberá pedirla. Recomendación: **ignorar** salvo el arreglo de R-01.

### R-06 — Una sesión en curso desaparece de «Mis reservas» — informativa
El filtro exige `inicio > ahora`: durante los 50 minutos de la sesión la reserva no sale en el panel (la probé: 11:30 con ahora 12:00). Es consistente con «futuras» y con T-05 R-07 del backlog (el panel del profesional también oculta horas iniciadas). Recomendación: **backlog para T-11**: decidir si «próxima sesión» incluye la que está en curso.

### R-07 — Lo que T-09, T-10, T-11 y T-12 necesitan de `cancelar_reserva` — informativa
- T-09: el `SELECT` de `cancelar_reserva` trae `inicio`, `duracion_min`, `estado`, `paciente_id` y el nombre del profesional, pero **no `profesional_id` ni el nombre del paciente** (hace falta un `JOIN usuarios` más). `reservar_hora` tampoco trae `profesional_id`. Las notificaciones deben insertarse antes del `commit` sin que `notificaciones.py` haga `commit` propio (si no, se rompe la atomicidad); la escritura de `outbox.log` es un archivo y no se deshace con `rollback`: hacerla después del `commit`. El mensaje debe bastarse solo (D-016: `hora_id` queda NULL si la hora se elimina; yo comprobé que la fila de notificación sobrevive a cancelar).
- T-10: el reinicio de `recordatorio_enviado` a 0 al cancelar es correcto. Falta definir qué hace `send-reminders` con una reserva hecha con < 24 h (R-02): ¿la recuerda de inmediato o nunca? Y debe leer `estado` y marcar `recordatorio_enviado` dentro de `BEGIN IMMEDIATE`, para no mandar un recordatorio a una reserva que se cancela en el mismo instante (la cancelación permitida más tardía coincide con el momento del recordatorio, las 24 h exactas).
- T-11/T-12: no ordenar por `reservada_en` (texto con offset); reutilizar `listar_reservas_futuras` o su criterio. El historial de US-10 no tiene dónde mostrar reservas canceladas: no hay `cancelada_en` ni fila de cancelación, solo la notificación de T-09.
Recomendación: **notas en TASKS** (orquestador) para T-09 a T-12.

## Cierre de hallazgos de T-07

| Hallazgo | Estado |
|---|---|
| R-01 (sin «Mis reservas») | Cerrado: lista, botón, texto sin botón, CSRF (punto 4). |
| R-02 (reloj antes del bloqueo) | Cerrado: espera real comprobada en `reservar_hora` y `cancelar_reserva` (punto 3). |
| R-04 (rollback en cada salida) | Cerrado: N18, N19 y N20 mueren. |
| R-05 (prueba que dependía de `TZ=America/Santiago`) | Cerrado: N16 muere con el equipo en Santiago. Abre R-01 de esta revisión (Windows). |
| R-08 (D-029) | Sigue pendiente del humano (R-02 de esta revisión). |
