# REVIEW.md — Revisión de T-05 (commit `511439c`)

Revisor, 2026-10-08. Python 3.13.16, SQLite 3.45.1, journal_mode `delete` (por defecto).
Todo experimento y mutación se hizo en copias bajo el scratchpad (`.../scratchpad/{repo,mut1,mut2,mr,mw}` y scripts `h.py`, `matriz.py`, `dst.py`, `carrera.py`, `lock.py`, `val.py`, `misc.py`, `del.py`, `mut.py`). El repo no se tocó.
Leído: `git show 511439c` completo, SPEC (US-4, US-5, §4), ARCHITECTURE, D-004, D-007, D-016, D-017, D-018, D-023, D-025, T-05 en TASKS.md, entrada de PROGRESS, `app/profesional.py` y las dos plantillas.

## Veredicto: APROBADA (sin hallazgos de severidad alta; un hallazgo medio, R-01, se recomienda como tarea pequeña antes de T-06)

Las reglas §4.2, §4.3 y §4.4 se cumplen y los requisitos (a), (b), (c) de T-05 también. Lo guardado fue siempre canónico, la carrera real se resuelve y la prohibición de `INSERT OR REPLACE` está vigilada. Lo que sigue son bordes.

## Qué se verificó ejecutando

- `pytest`: **805 passed** (35,2 s y 31 s en dos corridas); `test_horas.py` + `test_rutas_publicas.py` = 141 (138 + 3), 664 + 141 = 805. Coincide con PROGRESS.
- **Solape**: matriz de 400 casos (5 duraciones de la hora existente x 5 de la nueva x 16 desfases: mismo inicio, contenida, contiene, adyacente por ambos lados, +-1 min, 10 h) contra un modelo en Python: **0 discrepancias**; otro profesional nunca bloquea; la reservada bloquea; la medianoche (23:30+60 vs 00:10 sí, vs 00:30 no) bien.
- **Carrera real**: 12 procesos con `multiprocessing` y un `Event` de partida contra un archivo SQLite, todos con inicios solapados entre sí, llamando a `crear_hora`: 5 corridas, siempre **1 aceptada, 11 rechazadas, 0 transacciones abiertas**. Mutante sin `BEGIN` (`mut2`): 1 de 4 corridas dejó **2 horas solapadas** (la carrera es real y `BEGIN IMMEDIATE` la impide).
- **Espera larga**: otra conexión retiene `BEGIN IMMEDIATE` 6,5 s (hilo) mientras el cliente de pruebas agrega o elimina (R-02).
- **Validación**: ~60 entradas por el endpoint (fechas, horas, duraciones, ausentes, repetidas, multipart, archivo en lugar de campo, JSON, cuerpo de 2 MB, XSS en el eco); todo lo guardado casó con `^\d{4}-\d\d-\d\dT\d\d:\d\d:00$`.
- **Horario de verano** con `zoneinfo` para 2027 y 2028 (6 horas x 2 días x 4 fechas) y fin real de sesiones (R-03).
- **Eliminar**: propia libre, propia reservada, de otro, inexistente, ids `0`, `-1`, `abc`, `1.5`, `2**63-1`, `2**63`, 23 dígitos, GET, sin token, token falso, paciente con token propio, anónimo con token válido, doble envío, reservar -> cancelar -> eliminar con `PRAGMA foreign_keys=1` y `PRAGMA foreign_key_check` vacío; notificación queda con `hora_id` NULL y mensaje intacto.
- **Vigilancia REPLACE**: 9 variantes insertadas en un módulo nuevo de la copia (R-06).
- **Mutaciones**: 22 propias (R-05). **Rendimiento** de `buscar_solape` con 50 000 filas (R-10).
- **Panel**: HTML real con una libre, una reservada y otra de otro día: orden, botón solo en libres, token dentro de cada formulario, `no-store`.

## Qué NO se verificó

- Navegador real: `type="date"/"time"/"number"`, teclado, lector de pantalla. Lo dicho sobre ellos sale de leer la plantilla.
- Recorrido manual con `flask run` y curl que cita PROGRESS: no lo repetí tal cual; reproduje con el cliente de pruebas los mismos casos (todos coinciden), pero no puedo afirmar que el recorrido se hiciera como se describe.
- Las "36 mutaciones" del implementador: no hay lista ni script, no se pueden reproducir una a una. Mis 22 son distintas de las que PROGRESS nombra.
- gunicorn con varios workers/hilos y WAL: no probados (solo procesos que usan directamente `crear_hora`).
- `strftime`/`zoneinfo` con otras versiones de Python o de datos de zona.

## Hallazgos

### R-01 — Sin tope de fecha futura; el año 9999 provoca 500 (media)
`validar_formulario` acepta cualquier fecha real hasta `9999-12-31` y `_describir` suma la duración con `datetime + timedelta`, que desborda.
```
$ python3 ovf.py        # profesional logueado; agrega 9999-12-31 23:59 (50 min) y luego 9999-12-31 23:58
9999-12-31 23:59 302   ->  guardada
9999-12-31 23:58 500   ->  OverflowError: date value out of range  (app/profesional.py:205 _describir, desde crear_hora)
```
También se aceptaron `2500-01-01` y `2099-12-31`. Un año mal tecleado (Chrome permite años de 6 dígitos en `type=date`; `2206` por `2026` es muy plausible) publica una hora que T-06 mostrará al final de la lista de los pacientes durante siglos, y el profesional solo la ve si baja hasta ella. Pregunta del encargo (tope razonable): sí conviene uno.
Recomendación: **tarea nueva pequeña (T-05b) antes de T-06**: tope superior (p. ej. hoy + 2 años, o año <= 2100; decisión del humano o nota en D-025), mensaje en español, y `_describir` sin aritmética de `datetime` (calcular el fin con minutos enteros o atrapar `OverflowError`). Con el tope, el 500 desaparece porque ya no se llega a 9999.

### R-02 — Si el bloqueo de escritura dura más de 5 s, 500 en inglés (baja)
```
$ python3 lock.py
agregar con escritor ocupado 6.5 s: 500 tras 5.0 s   (OperationalError: database is locked)
eliminar con escritor ocupado: 500 5.0 s
panel durante BEGIN IMMEDIATE ajeno: 200 en 0.01 s    (journal 'delete': los lectores pasan)
despues (sin el escritor): 302, la hora se agrega
```
No queda transacción abierta ni dato corrupto: `BEGIN IMMEDIATE` va fuera del `try` pero, si falla, no hay transacción que cerrar; cualquier otra excepción dentro hace `rollback` y se re-lanza; y la conexión se cierra en el `teardown`. En Python 3.13 con `isolation_level` por defecto (modo heredado) un `execute("BEGIN IMMEDIATE")` explícito es válido y los `SELECT` previos (`usuario_actual()`) no abren transacción. Con 1 profesional y tráfico bajo la probabilidad es mínima (D-025 ya lo dice), pero T-08 añadirá escritores concurrentes (reservas). `login`/`registro` y `eliminar_hora` tienen el mismo comportamiento.
Recomendación: **backlog para T-08/T-14**: capturar `sqlite3.OperationalError` "locked" en un manejador central, responder 503 con mensaje en español («El sistema está ocupado, inténtalo de nuevo en unos segundos») y, si hace falta, bajar o subir `timeout` de `sqlite3.connect` por decisión explícita.

### R-03 — El solape en "reloj de pared" falla en las dos noches de cambio de hora (baja)
La pregunta del encargo, ejecutada con `zoneinfo` (Chile 2027: atraso `2027-04-03` 24:00, adelanto `2027-09-04` 24:00):
- Sesión de **50 min a las 22:30** la noche de abril: termina a las 23:20 reales; **no cruza** la hora repetida, el cálculo es correcto. Para que una sesión de 50 min cruce el cambio de abril debería empezar a las 23:xx, que está rechazado.
- Falso solape (abril): 120 min desde 22:30 del sábado terminan a las 23:30 reales (segunda pasada) pero el reloj de pared dice 00:30; el domingo 00:00 se rechazaría por solape sin serlo.
- Solape ausente (septiembre): 50 min desde **23:30** del sábado terminan a las 01:20 reales (en pared 00:20); una hora a las 01:00 se acepta aunque se pisan 20 min.
Gravedad baja: exige sesiones posteriores a las 23:10 en 2 noches al año, o duraciones largas desde las 22:xx. D-025 punto 5 dice "una hora que cruza la medianoche se compara bien": es cierto en pared, no en tiempo real esas dos noches; conviene matizar la frase.
Recomendación: **ignorar** en v1 o **backlog T-14** (junto con el recordatorio de 24 h de T-10, que sí depende del instante real). Corrección posible: convertir a UTC en Python antes de comparar y guardar nada más.

Filas corruptas (el esquema las impide salvo estas): `buscar_solape` sobre `2026-13-45T99:99:99` devuelve `None` (ignora la fila, como dice el docstring); `2027-02-30T10:00:00` se trata como 2 de marzo 10:00 (`strftime` normaliza); `duracion_min = 1e30` (que el esquema acepta, T-02e R-04) hace que **toda** hora posterior se rechace por solape; `'abc'` o `0.5` no bloquean casi nada. Ninguna la produce la aplicación. Informativa.

### R-04 — Doble envío: mensaje engañoso en "Agregar" y 404 en inglés al eliminar dos veces (baja)
```
POST /profesional/horas/nueva (mismos datos) x2  ->  302, luego 200 «Esa hora se solapa con otra que ya publicaste (01-01-2030 09:00 a 09:50)»
POST .../1/eliminar x2                           ->  302, luego 404 (página "Not Found" de Werkzeug, en inglés)
```
En el primer caso la hora sí quedó creada, pero el navegador muestra el error del segundo envío. Las dos condiciones son seguras (nada se duplica ni se borra de más); es solo el mensaje. Eliminar desde una pestaña vieja también da ese 404.
Recomendación: **backlog (T-13)**: si la fila solapada tiene el mismo inicio y duración decir «Esa hora ya está publicada»; para el 404 de eliminar, redirigir al panel con «Esa hora ya no existe» (sin distinguir ajena de inexistente, como decide D-025).

### R-05 — Calidad de pruebas: 22 mutaciones propias, 3 sobreviven (baja)
Corridas con `tests/test_horas.py` + `tests/test_rutas_publicas.py` (`-x`); las 3 sobrevivientes además con la suite completa (805 passed en las tres). Todas distintas de las que PROGRESS nombra.
Mueren: M01 fin existente `duracion*6`; M02 fin nuevo en segundos; M03 hora 24 aceptada; M04 minuto 60 aceptado; M05 duración por defecto 60; M06 480 excluido; M07 DELETE ignora `rowcount`; M08 consulta de "reservada" sin `profesional_id` (fuga 302/404); M09 panel descendente; M10 día/mes invertidos en pantalla; M11 `[0-9]{1,2}` en fecha; M13 redirección a `nueva_hora`; M14 sin aviso al eliminar; M15 panel con `OR 1=1`; M16 reservadas no cuentan en el solape; M17 `nueva_hora.html` sin CSRF; M19 mensaje con fin en horas; M20 pasado comparando solo la fecha; M22 `IntegrityError` devuelve éxito.
**Sobreviven**:
- **M18 (real)**: quitar `csrf_token` del formulario "Eliminar" de `profesional.html`. El botón dejaría de funcionar en la práctica (400) y nadie lo detecta, porque las pruebas sacan el token de la primera aparición en la página (la del formulario de logout, que es el mismo token de sesión). Reproducir: en `mw`, quitar la línea `<input type="hidden" ...>` dentro del `<form ... eliminar_hora ...>`; `pytest` -> 805 passed.
- M12: el mensaje de pasado/horario se muestra bajo "hora" en vez de "fecha"; las pruebas miran el texto, no el campo (cosmético).
- M21: quitar el `rollback` del `except BaseException` en `crear_hora`: equivalente en la práctica, la conexión se cierra al terminar la petición.
Recomendación: **backlog** (la próxima vez que se toque `tests/test_horas.py`; ideal junto con T-05b): una prueba que extraiga el token **del propio formulario de eliminar** (regex sobre el `<form>` con esa acción) y envíe el POST.

### R-06 — La vigilancia de `INSERT OR REPLACE` funciona; límites conocidos (informativa)
Inserté en un `.py` nuevo de `app/` cada variante y corrí `pytest -k replace`: `INSERT OR REPLACE INTO horas`, con tabulador, `REPLACE INTO`, `"horas"` entre comillas, `main.horas`, mayúsculas/minúsculas, `INSERT/**/OR/**/REPLACE`, texto partido `"INSERT "+"OR REPLACE INTO horas"` y en una plantilla `.html`: **todas hacen fallar** `test_ningun_codigo_de_la_app_usa_replace_sobre_horas`; `INSERT OR IGNORE` pasa (correcto). No detecta: un `.py` en un subpaquete (`glob` no es recursivo, hoy no hay), `schema.sql` (un `TRIGGER`), ni un `REPLACE` partido en dos literales (`"REPLACE" " INTO"`; no ejecutado, por lectura de la expresión regular). Bloquea `REPLACE INTO` de cualquier tabla (más estricto de lo pedido; aceptable). Grep en `app/` y `tests/`: ningún uso real.
Recomendación: **ignorar**; usar `rglob` si algún día hay subpaquetes.

### R-07 — El convertidor `int` de Werkzeug acepta dígitos Unicode en la URL (informativa)
`POST /profesional/horas/%D9%A1/eliminar` (dígito arábigo-índico) borró la hora 1 (302). No es un salto de autorización (sigue exigiendo ser el dueño, sesión y CSRF) pero es un alias de URL; mismo patrón en T-08/T-09. `0001` y `+1` no los probé (el script se detuvo en el primer 302).
Recomendación: **ignorar** o, si se quiere, convertidor propio con `[0-9]+` cuando lleguen T-08/T-09.

### R-08 — Accesibilidad y presentación (baja)
Por lectura del HTML real (sin navegador): todos los botones dicen "Eliminar" sin contexto (falta `aria-label` con la fecha); no hay confirmación antes de borrar (reversible: se puede volver a crear); la tabla no tiene `<caption>` ni `scope="col"`; el aviso `error` de «No se puede eliminar una hora reservada» sale con `role="status"` (debería ser `alert`); los errores de campo tienen `role="alert"` pero sin `aria-invalid` ni `aria-describedby`; el formulario no lleva `novalidate`, por lo que el navegador valida primero (bien: `required`, `min/max`; los mensajes del servidor son respaldo y salen igualmente, comprobado); sin estilos (`style.css` aún no existe, T-13). El token CSRF está en los 3 formularios (agregar, eliminar, cerrar sesión). XSS: el eco del formulario sale escapado (`value="&#34;&gt;&lt;script..."`), el nombre del profesional también.
Recomendación: **backlog T-13**.

### R-09 — El panel oculta las horas ya iniciadas (informativa)
`listar_horas_futuras` usa `inicio > ahora`: una sesión reservada que está en curso desaparece del panel; las pasadas no se ven. Es lo que dice D-025 (7) («T-12 lo rehace»). No hay hallazgo si T-12 cubre "próximas / libres / pasadas" (US-6). Eliminar por POST una hora libre pasada sí funciona (no hay regla en contra).

### R-10 — Interacción con T-06 a T-12 (informativa; para quien tome esas tareas)
- **D-023 (varios profesionales)**: con 1 o con N profesionales lo implementado es seguro: el solape y el `DELETE` filtran por `profesional_id` (matriz: otro profesional nunca bloquea; 404 al borrar la hora ajena, con 2 profesionales reales). Pendiente: con N, la regla §4.5 del SPEC (un paciente no puede tener dos reservas a la misma hora) ya no queda cubierta por la ausencia de solapes del profesional; T-08 debe comprobarla (solape entre horas de distintos profesionales). Con 1 profesional la UNIQUE y el solape la cubren.
- **Reservar vs eliminar**: ambos son sentencias únicas con `WHERE estado='libre'`, así que una de las dos gana; T-06/T-08 deben tratar «la hora ya no existe» (eliminada mientras el paciente miraba la lista) igual que «ya no está libre», con mensaje amable, no 404.
- **T-08**: `BEGIN IMMEDIATE` falla con "cannot start a transaction within a transaction" si algún `before_request` o código previo dejó una escritura sin `commit` en la misma conexión (modo heredado de `sqlite3`); hoy no ocurre.
- **T-08/T-09**: una hora libre que pasa su hora sigue `libre`; reservar/mostrar debe filtrar por futuro (T-06 ya lo pide para la lista; T-08 debe repetirlo en el `UPDATE`).
- **T-09/T-10/T-11/T-12**: tras eliminar, `notificaciones.hora_id` es NULL (verificado con FK activas): toda plantilla o recordatorio que haga `JOIN`/siga el enlace debe tolerarlo; `send-reminders` debe ignorar notificaciones sin hora.
- **Índices/rendimiento**: `buscar_solape` usa el índice `(profesional_id, inicio)` solo por el prefijo `profesional_id` y evalúa `strftime` en cada fila de ese profesional, **dentro del bloqueo de escritura**: 57 ms con 50 000 filas (`bench.py`). Irrelevante en v1 (un profesional crea unas miles de horas en años); si crece, acotar con `inicio BETWEEN` (texto canónico ordenable).
- **Fechas**: el texto canónico ordena igual que el tiempo, por eso `inicio > ?` y `ORDER BY inicio` son correctos; las consultas de T-06 pueden usarlas con el índice.

### R-11 — Veracidad de PROGRESS.md y D-025 (informativa)
Confirmado: 805 pruebas = 664 + 141 (138 + 3); `schema.sql`, SPEC y ARCHITECTURE intactos (`git show --stat`: 8 archivos, ninguno de ellos); archivos nuevos (`nueva_hora.html`, `test_horas.py`, `test_rutas_publicas.py`) justificados en D-025 con la regla 10; la fila R-12 de T-04 quitada del backlog como se afirma; la prueba de carrera descrita (`timeout=0.05`) es determinista y válida, y la de `set_trace_callback` es necesaria (la primera no distingue `BEGIN` diferido: con rollback-journal SQLite lo resuelve fallando con "database is locked", no duplicando; en mis 12 procesos el mutante diferido dio 0 duplicados pero 2 de 3 corridas con 500 por bloqueo, es decir, lo que `BEGIN IMMEDIATE` evita es el error espurio). La frase "No mutado: la prueba de carrera ..." y "no se probó concurrencia real" son honestas. Desviación menor: el contador "36 mutaciones" no se puede comprobar sin lista, pero la suma de las que PROGRESS nombra (32 muertas + 2 sobrevivientes corregidas + 2 equivalentes) es coherente y mis resultados no la contradicen. D-025 (5) "Una hora que cruza la medianoche se compara bien" debe matizarse por R-03.

### R-12 — Rendimiento de la suite (informativa)
`pytest` pasó de ~25 s (664 pruebas) a 31-35 s (805): T-05 aporta ~8 s (`test_horas.py`, 138 pruebas, ~0,06 s de preparación por prueba: `create_app` + `init_db` + login con hash rápido). Aceptable. Si T-06 a T-13 repiten ese costo la suite llegará a ~70-90 s; entonces valorar fixtures de ámbito `module` para la base inicializada o `pytest-xdist` (dependencia nueva = entrada en DECISIONS). **Ignorar** por ahora.

## Resumen para el orquestador

| ID | Sev. | Qué | Destino |
|---|---|---|---|
| R-01 | media | Sin tope de fecha; año 9999 -> 500 | Tarea nueva T-05b (antes de T-06) + decisión del tope |
| R-02 | baja | Espera >5 s por el bloqueo -> 500 | Backlog T-08/T-14 |
| R-03 | baja | Solape en reloj de pared en las 2 noches de cambio | Ignorar / T-14; matizar D-025 (5) |
| R-04 | baja | Mensajes en doble envío (solape engañoso, 404 inglés) | Backlog T-13 |
| R-05 | baja | M18 sobrevive: botón Eliminar sin CSRF no se detecta | Backlog (con T-05b) |
| R-06 a R-12 | info | Vigilancia REPLACE, URL con dígitos Unicode, accesibilidad, panel, interacción T-06..T-12, PROGRESS, rendimiento | Ver cada uno |

Nada de lo anterior contradice una decisión ya aprobada (D-016, D-017, D-018, D-025); R-01 es una laguna de D-025, no un incumplimiento.

**Veredicto: APROBADA.** Condición recomendada (no bloqueante): resolver R-01 y R-05 en una tarea corta antes de que T-06 muestre las horas a los pacientes.
