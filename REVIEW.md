# REVIEW.md — Revisión de T-12 (dashboard del profesional)

Revisor: commit `2f5bb74` (más `a06e9d9`, que solo corrige una hora en PROGRESS), rama `agentes/loop`.
Contrastado con SPEC (US-6, US-4, US-5, §4, §5, §6), D-016, D-029, D-033, D-034, D-035, D-036 y la entrada de PROGRESS.
Todo lo medido se ejecutó en copias bajo el scratchpad (`r12`, `r12p`, `mut12/*`, `r12nav`); el repo no se tocó.

## Resumen de lo que se verificó ejecutando

- Suite completa en copia de `HEAD`: **1677 OK** (47,96 s) y también con los archivos en orden inverso (1677 OK, 48,6 s). Sin `outbox.log` ni `agenda.db` residuales; `git status` del repo limpio.
- `tests/test_dashboard_profesional.py` también en orden inverso de pruebas (53 OK).
- 25 mutaciones propias sobre `app/` (ver R-07).
- Servidor real (Flask, puerto 5121, base y outbox en el scratchpad, cerrado por PID) + `curl` para roles/CSRF/`no-store`, y Chromium de `/opt/pw-browsers` con Playwright para el recorrido.
- Comparación byte a byte del HTML de `/paciente` antes (`8d85ee6`) y después del commit.

## Hallazgos

### R-01 (baja) «Ver la reserva» engañoso en avisos viejos cuando la hora se vuelve a reservar
`enlazable` solo comprueba que `hora_id` esté en la agenda propia (`proximas`), no que el aviso hable de esa reserva. Reproducido (copia, prueba ad hoc): Ana reserva la hora, la cancela y Beto la reserva. El profesional ve tres avisos y **los tres** llevan «Ver la reserva» apuntando a la fila de Beto, incluido «Cancelación: Ana Pérez canceló… **La hora quedó libre.** Ver la reserva» (contradictorio). No hay fuga de datos (la fila es propia) y el enlace es solo un ancla en la misma página; el mismo patrón existe en `/paciente` (si el paciente reserva de nuevo la misma hora).
Recomendación: backlog para T-13/T-14 (p. ej. no enlazar los avisos de tipo `cancelacion`, o solo el aviso más reciente por `hora_id`). No bloquea.

### R-02 (baja) El orden por fecha de agenda y de libres depende del plan de consulta y las pruebas no lo distinguen
Las mutaciones «quitar `horas.sort(...)` en `listar_horas_libres`» (M21), «quitar `por_venir.sort(...)` en `listar_agenda`» (M22) y «ordenar solo por inicio sin desempate» (M23) **sobreviven** las 423 pruebas de paneles/horas/notificaciones. Causa: el `SELECT` no tiene `ORDER BY` y SQLite devuelve las filas por el índice `UNIQUE(profesional_id, inicio)`, que ya está en orden de fecha; el `sort` de Python (instantes absolutos, D-034) solo cambia algo con datos que el flujo normal no produce (horas ambiguas/inexistentes insertadas por SQL). En la práctica son mutantes casi equivalentes, pero el orden «garantizado» hoy es accidental (un cambio de índice o de plan lo rompería sin aviso). Las pasadas sí están protegidas (`reverse=True`, M15 muere).
Recomendación: backlog (T-14): una prueba unitaria que alimente `listar_horas_libres`/`listar_agenda` con filas en orden distinto al del índice (p. ej. una base sin ese índice con `DROP INDEX`, igual que `permitir_varios_profesionales`) o un `ORDER BY` explícito además del `sort`.

### R-03 (baja) La hora inventada sigue en `TASKS.md` y en `DECISIONS.md` (regla 8)
`a06e9d9` corrigió solo PROGRESS (09:35, la hora real del commit). Quedan con **09:45** (posterior al propio commit): `TASKS.md` línea 230 («HECHA (2026-10-09 09:45)») y `DECISIONS.md` D-036 («Fecha: 2026-10-09 09:45»). Es la misma hora inventada; tres documentos ya no concuerdan. (Tercera vez que el implementador inventa la hora: T-06 R-07 dejó anotado endurecer con una comprobación automática «si reincide».)
Recomendación: el orquestador corrige las dos líneas (el revisor no edita esos archivos) y decide si abre la tarea de la comprobación automática del backlog (`T-06 R-07`), que ya reincidió.

### R-04 (baja) D-036 dice «función única» para las 24 h, pero `reservar_hora` conserva su propia comparación
`paciente.es_reservable` la usan `listar_horas_libres_futuras` y el rótulo del profesional, pero `reservar_hora` (`app/paciente.py:276`) sigue con `faltan_s <= ANTICIPACION_RESERVAR_S`. Son equivalentes hoy (revisé el borde a mano y con la prueba de 24 h exactas, que además compara con lo que ofrece `/paciente/horas`), pero la prueba nueva no ata el rótulo a la **acción** de reservar: si alguien cambia solo uno, el panel podría decir «reservable» y el POST rechazar.
Recomendación: backlog; que `reservar_hora` llame a `es_reservable` o una prueba de coherencia (POST a 24 h exactas y a 24 h + 1 s).

### R-05 (informativa) La suite ya era de ~48 s antes de T-12; las pruebas nuevas cuestan 1,3 s
Medido en la misma máquina: padre `8d85ee6` 1621 pruebas en 47,6 s; `HEAD` 1677 en 48,0 s. `--durations=0` sobre `test_dashboard_profesional.py`: 94 fases (setup+call) suman 1,32 s (máximo 0,03 s cada una). Las 25 más lentas de toda la suite son las de siempre (exhaustivas de `correo`, procesos, `tzset`). El «antes ~37 s» no se reproduce: no hay causa evitable en T-12; es variación de la máquina. El umbral de acción del backlog (60 s) no se alcanza.
Recomendación: ignorar.

### R-06 (informativa) Pruebas eliminadas/reescritas: iguales o más fuertes
- `test_con_pocas_notificaciones_no_hay_aviso_de_tope` → `test_aviso_de_tope_solo_si_hay_mas_que_el_tope[19/20/21]` (más fuerte: añade 20 → sin aviso, 21 → aviso, cuenta de `<li>` y contador) y `test_el_tope_del_panel_del_paciente_sale_de_la_constante`.
- Aserción de orden en `tests/test_horas.py`: pasó de «01-03 antes de 02-03» (orden por fecha entre libre y reservada) a «02-03 (reservada) antes de 01-03 (libre)» (solo orden de secciones). Es más débil en sí misma, pero el orden por fecha dentro de cada sección se prueba en el archivo nuevo (agenda, libres, pasadas; salvo la salvedad de R-02) y las secciones separadas hacen que la aserción antigua ya no tenga sentido.
- No hay pérdida de cobertura que detecte una mutación: todas las mutaciones relevantes mueren (R-07).

### R-07 (informativa) Mutaciones propias (25, sobre copias; pruebas: paneles, horas, horas libres y notificaciones)
Mueren por la razón declarada (primer fallo): `es_reservable` con `>=` (borde 24 h, test parametrizado); agenda y libres sin filtro de profesional (`test_la_agenda_filtra_por_profesional`); enlace sin comprobar propiedad y enlace por «hora_id no nulo» (`test_enlace_solo_a_una_reserva…`); `hay_mas` con `>=` (caso 20) y sin recorte (caso 21); `20` fijo en la plantilla (`test_el_tope_sale_de_la_constante`); `|safe` en el mensaje y en el nombre del paciente (prueba de XSS); ruta de leídas con `login_requerido` (`test_el_paciente_no_puede_usar_la_ruta…`); libres que incluyen las ya empezadas; «reservable» siempre verdadero; pasadas con `>=` (borde exacto de «termina ahora»); orden por `creada_en`; pasadas en orden ascendente; mostrar el correo en vez del nombre; singular del flash; `th scope="row"`; botón de leídas siempre visible; contador acotado al tope.
**Sobreviven:** M21, M22, M23 (ver R-02) y M16 (`en_curso` con `<= fin`), que es equivalente: una sesión que termina justo ahora ya es «pasada» y nunca llega a esa condición.
El truco `permitir_varios_profesionales` es honesto y está aislado: es un ayudante previo de `tests/test_login.py` (docstring explícito), hace `DROP INDEX IF EXISTS un_solo_profesional` solo en la base temporal de la prueba (una base nueva por prueba, fixture `app`); la suite en orden inverso pasa y `test_esquema`/`test_crear_profesional` siguen probando la regla real. Límite: esas pruebas modelan un escenario que la base real no admite (D-023), pero solo para comprobar el filtro por `profesional_id`.

### R-08 (informativa) Aislamiento y seguridad: sin hallazgos
Verificado con servidor real y `curl`: anónimo `GET /profesional` 302 a `/login`, `POST` ruta de leídas sin sesión 400 (CSRF antes que rol); paciente 403 en ambas rutas (el cuerpo no contiene datos del profesional); POST sin token 400, token falso 400, token de **otro usuario** 400; `GET` a la ruta POST 405; `Cache-Control: no-store` en `/profesional` (profesional y 403 del paciente). XSS: nombre de profesional `Dra. <i>Pro</i>`, pacientes `Ana <b>Pérez</b>` y `Beto <img src=x onerror=alert(1)>` salen como texto en agenda, avisos y saludo; ningún diálogo en Chromium. Solo se muestra el nombre del paciente (nunca el correo; prueba y mutación). Flujo T-05 intacto (comprobado con prueba ad hoc): reservar → eliminar da 302 sin borrar → cancelar → eliminar OK → los dos avisos quedan con `hora_id` NULL, sin enlace y sin «reserva-None».

### R-09 (informativa) Plantilla compartida y panel del paciente
Diff del HTML de `/paciente` (mismo estado, 3 no leídas + 1 leída, nombre con HTML) entre `8d85ee6` y `HEAD`: **idéntico salvo una línea en blanco** que añade el `include`. `th scope`, `caption`, `aria-label` de la campana y clases `campana`, `notificaciones`, `leida`, `no-leida` intactos. Aviso de tope: profesional con 19/20/21/25 (parametrizado) y `TOPE_PANEL` leído de Python (con 3 y con 5), paciente con 19/20/21 y constante; el 25 del paciente lo cubre la prueba de T-11b. El contador cuenta todas (consulta `COUNT` aparte) aunque solo se vean 20.

### R-10 (informativa) Detalles de contenido y UX (para T-13, sin tarea nueva)
- Con solo sesiones pasadas y ninguna hora libre, «Horas libres» dice «Aún no tienes horas publicadas» (el `elif proximas` ignora `pasadas`); inexacto, no grave.
- «Para eliminarla, el paciente debe cancelar primero.» se repite en cada fila de la agenda (ya lo dice el implementador).
- La hora libre ya empezada no aparece en ninguna parte y no se puede eliminar (T-05 R-07 del backlog, sin cambio); `Sesiones pasadas` no tiene tope ni paginación (como T-06 R-01 para libres del paciente): con años de uso crecerá sin límite.
- Las notificaciones quedan al final de la página; en 390 px hay que bajar tres secciones para ver «Confirmación» nueva (SPEC §6.5 lista agenda, libres y notificaciones en ese orden, así que cumple; decisión de diseño para T-13).

### R-11 (informativa) Navegador (Chromium + Playwright, servidor real)
Profesional con 5 horas (una a ~3 h «no reservable», cuatro más), dos pacientes que reservan 3. A 1280 y a 390 px: `scrollWidth == clientWidth` (sin scroll horizontal). La hora a menos de 24 h sale «Libre · no reservable (faltan 24 horas o menos…)»; la agenda lista pacientes y duraciones; avisos con «Ver la reserva» a las filas propias. Con Tab hasta «Marcar todas como leídas» y Enter: flash «Marcaste 3 notificaciones como leídas.», contador 0, botón ausente, avisos pasan a «leída». Sin estilos aún (T-13): las tablas a 390 px se ven apretadas (fechas en tres líneas) pero legibles. **No probé:** 25 notificaciones ni cancelación que borra la hora en navegador (cubiertas por pruebas), lector de pantalla, ni foco visible más allá del anillo por defecto.

### R-12 (informativa) Documentación
- PROGRESS es veraz en lo que pude reproducir (1677 OK; mutaciones; navegador; cambios en pruebas existentes). La hora de la entrada ya está corregida (ver R-03 para TASKS/DECISIONS). Admite que reutilizó trabajo sin confirmar de una vuelta interrumpida y que lo revisó; el diff final es coherente y completo (no encontré código muerto ni restos).
- «Estado actual» (Fase 5, T-12 hecha, próxima T-13) es coherente con TASKS. Sin contradicciones de contenido entre SPEC, D-029/D-034/D-035/D-036 y el código.
- **Pendientes del humano en `ARCHITECTURE.md`** (el agente no puede editarlo; conviene juntarlos en una sola edición): (1) `POST /profesional/notificaciones/leidas` (profesional) — D-036; (2) `POST /notificaciones/leidas` (paciente) — D-035, aún sin añadir; (3) plantilla `_notificaciones.html` (compartida) y las filas de `profesional.py` («dashboard con agenda, libres y notificaciones») y `paciente.py`/`notificaciones.py` (`marcar_leidas`, `mensaje_marcadas`, `listar_de_usuario`); (4) `app/correo.py` (D-013) y `app/tiempo.py` no figuran en el árbol de módulos; D-036 solo menciona (1) y la plantilla, así que (2) y (4) solo quedan en D-035/D-013.

### R-13 (informativa) Notas para T-13 y T-14
- **T-13:** las pruebas de T-12 dependen de HTML literal: `<h1>` sin atributos y `<h2` (cuatro), `<caption>` (3), `<th scope="col">` (11) y `<th scope="row">` (3), `<h2 ...>` + texto inicial («Próximas reservas», «Horas libres», «Sesiones pasadas», «Notificaciones»), cierre `</main>` en `base.html` y `class="no-leida"`/`"leida"`; si se añaden clases, actualizar a la vez `test_el_html_es_accesible`, `seccion()` y `mensajes_listados`. Las pruebas importan ayudantes de otros 5 archivos de pruebas (acoplamiento). Estilos pendientes: `.campana`, `li.leida`/`li.no-leida`, tablas a 390 px, el «no reservable» (hoy solo `<strong>` + texto, no depende del color: mantenerlo así), resumir el texto repetido de la agenda, anillo de foco. Favicon 404 (R-09 de T-11) y páginas 400/404 en español siguen en T-13. Orden de secciones: decidir si el profesional prefiere avisos primero (R-10).
- **T-14:** recorrido §9 con el profesional: crear horas, una a <24 h («no reservable»), reservar con dos pacientes, cancelar, eliminar y ver `hora_id` NULL; «Marcar todas como leídas» con más de 20; README: cron < 24 h, `DATABASE`/`OUTBOX_PATH` iguales a los del servidor y código de salida 1 (T-10 R-05/R-06); backlog: R-01, R-02, R-04 de este informe; comprobación automática de la hora (R-03).

## Resumen

| # | Severidad | Tema | Recomendación |
|---|---|---|---|
| R-01 | baja | «Ver la reserva» en avisos viejos tras re-reservar la hora | backlog T-13/T-14 |
| R-02 | baja | Orden de agenda/libres solo por índice; mutantes M21–M23 sobreviven | backlog T-14 |
| R-03 | baja | Hora 09:45 inventada aún en TASKS y D-036 | orquestador corrige; hora automática si reincide |
| R-04 | baja | «Función única» de 24 h no incluye `reservar_hora` | backlog |
| R-05 | informativa | Suite 48 s: no es de T-12 (+1,3 s) | ignorar |
| R-06 | informativa | Pruebas reescritas iguales o más fuertes | ignorar |
| R-07 | informativa | 25 mutaciones: mueren salvo R-02 y una equivalente | ignorar |
| R-08 | informativa | Aislamiento, CSRF, XSS, `no-store`, T-05: sin hallazgos | ignorar |
| R-09 | informativa | Panel del paciente intacto; tope 19/20/21/25 | ignorar |
| R-10 | informativa | Detalles de contenido/UX | T-13 |
| R-11 | informativa | Navegador a 390 y 1280 px sin scroll horizontal | ignorar |
| R-12 | informativa | Docs veraces; pendientes del humano en ARCHITECTURE | decisión humana |
| R-13 | informativa | Notas T-13 y T-14 | anotar en TASKS (orquestador) |

**Veredicto: APROBADA.** No hay hallazgos de severidad alta ni media; R-03 es una corrección de dos líneas de documentación que le toca al orquestador.
