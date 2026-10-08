# REVIEW.md — Revisión de T-06 (commit `b372bb6`)

Revisor, 2026-10-08. Todo experimento y mutación se hizo en copias bajo el scratchpad (`.../scratchpad/r` = `git archive b372bb6`, `m` = copia mutada, scripts `e1.py`, `mut.py`, y `r/tests/test_rev.py` solo en la copia). El repo no se tocó. Leído: `git show b372bb6` completo, SPEC US-7 y §4, T-06 en TASKS, D-025, D-026, D-027, la entrada de PROGRESS (con la corrección de hora del orquestador, ignorada), `app/paciente.py`, `app/tiempo.py`, `app/profesional.py`, plantillas.

## Veredicto: APROBADA

No hay hallazgos de severidad alta ni media. El filtro «futuras» es correcto, independiente de la zona del servidor, y las dos mutaciones exigidas por la nota de T-05b (R-01) hacen fallar pruebas. Quedan deuda menor de pruebas, escala y UX (todo bajo o informativo), más notas para T-07.

## Qué se verificó ejecutando

- `pytest` sobre `b372bb6`: **902 passed en 41,2 s** (coincide con PROGRESS; 881 + 21 = 902, y `tests/test_horas_libres.py` tiene 21 pruebas).
- **Filtro «futuras»** (`listar_horas_libres_futuras` con base en memoria, mismo script con `TZ=UTC`, `TZ=Asia/Tokyo` y `TZ=America/Santiago`: salidas idénticas byte a byte):
  - Límite con ahora = 12:00:00: 11:59:59 y 12:00:00 no salen; 12:00:01 sale. Con ahora = 12:00:00,5 sale 12:00:01 y no 12:00:00. Medianoche (ahora 23:59:59): sale 00:00:00 del día siguiente, no 23:59:59 ni 23:59:58.
  - Franja «ahora .. ahora en UTC» (ahora 12:00 Chile = 15:00Z): salen 13:00 y 15:00 de hoy.
  - Cambio de horario: abril 2026 (hora repetida) y septiembre 2026 (hora inexistente): no hay excepción; la hora inexistente 00:30 no sale, 01:45 sí.
  - `tiempo.ahora_chile()` real con `TZ=UTC`, `Asia/Tokyo` y `Pacific/Kiritimati` da la misma hora de Chile (15:13:40 -03:00) y el mismo `timestamp()`.
  - Margen SQL de 1 día: no excluye ninguna hora válida. Una hora futura tiene reloj de pared >= ahora - 1 h (solo en la hora repetida de abril); el margen de 24 h cubre de sobra. Una hora de ayer (12:00:01) no sale aunque «dure» hasta hoy: solo salen las que empiezan en el futuro, como decide la tarea. Una hora ya iniciada nunca se muestra.
- **Contenido y privacidad** (cliente de pruebas): la respuesta solo lleva fecha, duración y nombre; no hay correos (probé con `x@x.cl`), ni ids, ni estado. Nombre de profesional `<script>alert(1)</script>"'&` sale escapado (`&lt;script&gt;...&#34;&#39;&amp;`). Cabeceras: `Cache-Control: no-store`, `Pragma: no-cache`, `Vary: Cookie`. Acceso: sin sesión 302 a `/login`, profesional 403, paciente 200. `HEAD` 200, `OPTIONS` 200; `POST` con CSRF válido 405; `PUT/PATCH/DELETE/POST` sin token 400 (la comprobación de CSRF global va antes que el 405; es el comportamiento de toda la app). Parámetros de consulta se ignoran (200). `/paciente/horas/` da 404. Con 2 profesionales el nombre de cada uno aparece en su fila.
- **Empates**: dos profesionales con el mismo instante salen por id de hora (Beto, id menor, primero). Las mutaciones de desempate (M6) mueren.
- **Escala**: 50 000 horas libres futuras de un profesional: **1,28 s y 6,55 MB** en una respuesta (cliente de pruebas, base en archivo). Ver R-01.
- **Refactor `app/tiempo.py`**: el diff de `profesional.py` es solo mover `ahora_chile`, `a_segundos_utc`, `mostrar_inicio` y las dos constantes; cuerpos idénticos; las llamadas pasaron a `tiempo.…`. Sin funciones duplicadas (`grep` de las cinco definiciones: una sola en `tiempo.py`), sin importaciones no usadas (comprobado con `ast` en los tres módulos) y sin ciclo: `tiempo` importa `auth`; `auth` importa `correo`, `db`, `seguridad`, no `tiempo`; `profesional` y `paciente` importan ambos. La suite completa (881 anteriores adaptadas + 21) pasa, así que el comportamiento del profesional (T-05/T-05b) no cambió.
- **`tests/test_horas.py`**: el diff real es **10 líneas eliminadas y 10 añadidas** (no 11): el `import` de `tiempo`, `AHORA_REAL`, los dos `monkeypatch.setattr(tiempo, "ahora_chile", …)` y las 8 llamadas a `a_segundos_utc`. Ninguna prueba ni aserción se perdió.
- **Mutaciones propias (16, distintas de las 21 del implementador)**, cada una en copia limpia; primero `tests/test_horas_libres.py`, y las que sobrevivieron, la suite completa:
  - Mueren (12): M1 tolerancia de 60 s (se muestra una hora ya iniciada), M3 duración sin « min», M4 `|safe` en el nombre (XSS), M6 desempate por id descendente, M8 sin `try/except` de fecha imposible, M9 sin comprobación de `None` (año 9999), M11 día/mes invertidos, M12 `JOIN … ON 1=1`, M13 sin filtro de estado, M14 margen SQL negativo, M16 duración fija 50.
  - Sobreviven (5): M2 `int(ahora.timestamp())` (equivalente: `inicio_s` es entero, `x > 12,5` y `x > 12` coinciden); M5 `fold=0` -> `fold=1` en `a_segundos_utc` (**sobrevive la suite completa**, R-02); M7 ordenar por el texto de `inicio` en vez del instante (solo difiere en horas repetidas que la app no crea); M10 quitar el enlace «Volver a mi panel» (sin prueba); M15 truncar a 100 filas (sin prueba de tope; R-01).
- **PROGRESS.md**: 902 pruebas y 21 nuevas, verificado. El resto de lo declarado (recorrido con `flask run`, 21 mutaciones del implementador, `mut_t06.py`) no lo repetí; las que sí reproduje coinciden en dirección con lo declarado (las tres de filtro y orden mueren). La afirmación «11 líneas eliminadas» es en rigor 10 (R-07). La hora de la entrada la corrigió el orquestador (15:12 -> 15:07; segunda vez que ocurre).

## Qué NO se verificó

- Recorrido real con `flask run` y navegador (usé el cliente de pruebas; la respuesta HTML se leyó completa).
- Concurrencia real (T-06 solo lee).
- Las 21 mutaciones del implementador y su script (no está en el repo).
- Lector de pantalla, diseño responsive (HTML sin estilos; T-13).
- gunicorn / varios workers.

## Hallazgos

### R-01 — Sin tope ni paginación en la lista — baja
La consulta trae todas las horas libres futuras y la plantilla las pinta todas. Reproducción: 50 000 filas libres de un profesional, `GET /paciente/horas` con paciente: **1,28 s y 6,55 MB** (lineal). SPEC no pide paginación. Realismo: el tope de 2 años (D-026) y la duración mínima de 1 minuto permiten en teoría ~1 millón de filas por profesional, pero una agenda real tiene unas pocas miles (~0,1-0,5 s y < 1 MB). Además la lista se vuelve inútil para el paciente mucho antes de eso (T-07 necesitará elegir una).
Recomendación: **backlog** (T-13/T-14). Opciones, de menor a mayor costo: ventana por fecha (p. ej. próximos 60 días con enlace «ver más»), o tope de N filas (100) con aviso «Mostrando las primeras N». Si se pone tope, ordenar con SQL por `inicio` y `LIMIT N + margen` y recién después decidir en Python (el texto ordena el reloj de pared, no el instante, solo en la hora repetida que la app no crea). Añadir la prueba que M15 deja sin cubrir.

### R-02 — `fold` de `a_segundos_utc` sin prueba que lo fije — baja
La mutación `fold=0` -> `fold=1` en `app/tiempo.py` pasa la suite completa (902). Las pruebas de `a_segundos_utc` con hora inexistente o repetida solo exigen «no es `None`» (`tests/test_horas.py`, heredadas de T-05b). No es un defecto de T-06: la app no guarda horas ambiguas (D-025 4) y solo afectaría filas insertadas por otro camino. Pero T-07/T-08 usarán la función para las reglas de 24 h.
Recomendación: **backlog** o incluir en T-07: una prueba que fije el valor exacto (`datetime(2027, 4, 3, 23, 30)` -> instante con desfase -03:00 si `fold=0`). Mismo criterio para el enlace «Volver» (M10): una aserción de una línea, **ignorar** si no se toca el archivo.

### R-03 — Hora repetida guardada por otro camino: la segunda pasada puede ocultarse — informativa
Con ahora = 04-abr-2026 23:30 en la segunda pasada (`fold=1`, -04:00), una fila `23:45` se interpreta con `fold=0` (primera pasada, -03:00) y se considera pasada, aunque su segunda ocurrencia es futura. No hay forma de crear esa fila desde la app (D-025 4). Documentado en `a_segundos_utc` y D-027. **Ignorar.**

### R-04 — La lista y el panel: UX mínima — baja
Español de Chile correcto («Horas disponibles», «Por ahora no hay horas disponibles. Vuelve a revisar más tarde.», «Volver a mi panel», «Ver horas disponibles»). Con 0 horas se muestra el mensaje y no la tabla. Observaciones para T-13 (diseño), no para esta tarea: la tabla no lleva `<caption>` ni `scope="col"` en los `<th>`; no se muestra la hora de término ni el día de la semana (con una duración de 50 min el paciente no ve a qué hora termina); la página no tiene el botón de cerrar sesión (solo el panel); sin estilos, como se esperaba. **Backlog** (T-13).

### R-05 — Respuesta 400 en vez de 405 para métodos con efecto sin token — informativa
`PUT/PATCH/DELETE/POST` sin `csrf_token` dan 400; con token, `POST` da 405. Es el comportamiento global (CSRF antes del enrutado) ya aceptado en T-04. **Ignorar.**

### R-06 — El margen SQL (`MARGEN_SQL_DIAS = 1`) es mucho mayor de lo necesario — informativa
Como se mostró, bastaría 1 hora; un día es inocuo (trae algunas filas de más, ninguna pasa a la lista). La mutación «margen 0» que el implementador dejó viva es defendible: sin margen solo se perdería la segunda pasada de la hora repetida (R-03). No requiere acción.

### R-07 — Precisión de PROGRESS.md — informativa
«Las 11 líneas eliminadas de `tests/test_horas.py`»: son 10 eliminadas y 10 añadidas, todas adaptaciones (no pérdida de cobertura). La entrada declaró una hora (15:12) posterior al reloj real; el orquestador la corrigió a 15:07. Es la segunda vez (regla 8 de CLAUDE.md). **Decisión humana** (opcional): si se repite, que el implementador pegue la salida de `TZ=America/Santiago date` en la entrada o que la hora la escriba el orquestador al integrar.

## Notas para T-07 (reservar) y T-08

La lista de T-06 no trae nada para reservar: `listar_horas_libres_futuras` devuelve `id`, `inicio` ya formateado, `duracion_min` y `profesional`. Lo que T-07 necesita y las carreras que aparecerán:

1. **Formulario por fila**: `<form method="post" action="{{ url_for('paciente.reservar', id=hora.id) }}">` con `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">` y un botón («Reservar»). Quitar la prueba `test_no_hay_boton_de_reservar_todavia` o adaptarla (hoy exige que no haya `<form` ni `reservar`). Ruta `<int(min=1, max=2**63-1):id>` (nota de T-04b R-10) con 404 para id inexistente o gigante.
2. **Doble reserva (regla 1)**: dos pacientes con la misma hora en pantalla. `UPDATE horas SET estado='reservada', paciente_id=?, reservada_en=? WHERE id=? AND estado='libre'` y mirar `rowcount`: el segundo recibe 0 filas; mostrar «Esa hora ya fue reservada por otra persona. Elige otra.» (200 o 302 a la lista con aviso, no 500 ni 404). Probar con dos procesos reales como en T-05b (una aceptada, el resto rechazadas).
3. **Hora que ya empezó entre la carga de la lista y el clic**: el UPDATE debe repetir el criterio «futura» con instantes (`tiempo.a_segundos_utc` y `tiempo.ahora_chile().timestamp()`), no confiar en que la lista era reciente. Como el filtro es en Python, o se hace dentro de `BEGIN IMMEDIATE` (leer la fila, comprobar, actualizar) o se acota con el texto canónico en el UPDATE y se confirma en Python; la nota de T-05b R-06 pide instantes absolutos.
4. **El profesional elimina la hora mientras el paciente la ve** (`DELETE … WHERE estado='libre'` vs `UPDATE … WHERE estado='libre'`): ambas sentencias son atómicas; solo una ve la fila libre. La perdedora debe dar un mensaje, no un 500. Si el paciente pierde, es 404/«esa hora ya no existe»; distinguir de «reservada» exige un `SELECT` posterior (cualquiera sirve, pero que el texto no revele datos de otros pacientes).
5. **Regla 5 (un paciente no puede tener dos reservas a la misma hora)**: ojo, es por **solape de intervalos** de sus propias reservas (duraciones distintas, distintos profesionales con D-023), no solo por igualdad de `inicio`; hay que calcularlo con instantes y dentro de la misma transacción que reserva (lectura de las reservas del paciente + UPDATE bajo `BEGIN IMMEDIATE`), o dos clics del mismo paciente en dos horas solapadas de dos profesionales pasarían ambos. Con un solo profesional (D-023 pendiente) basta la unicidad de la hora, pero la implementación debe ser correcta si hay más.
6. **Doble clic del mismo paciente en la misma hora**: el segundo UPDATE da 0 filas; el mensaje correcto es «Ya reservaste esta hora» (distinguir comprobando `paciente_id = sesión`), no «otra persona».
7. **Después de reservar**: la lista (que filtra `libre`) ya no muestra la hora; redirigir a una confirmación (US-8) y no re-renderizar con POST (recarga reenvía). `Cache-Control: no-store` ya está, así que «atrás» no muestra una lista vieja de forma persistente.
8. **Reloj**: usar `tiempo.ahora_chile()` (único parcheable); la prueba `test_el_reloj_es_un_unico_punto_parcheable` ya impide un segundo reloj.
9. **T-08 (cancelar con 24 h)**: la comparación es `inicio_s - ahora_s >= 24*3600` con `a_segundos_utc` (fijar `fold` con R-02 antes, para que la hora repetida tenga resultado determinista).
