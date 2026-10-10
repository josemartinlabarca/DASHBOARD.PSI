# REVIEW.md — Revisión final (Revisor)

Alcance: trazabilidad US-1..US-13, barrido de seguridad por ruta x rol, reglas críticas. No se modificó código, tests ni SPEC/ARCHITECTURE. Los 6 defectos S4 ya conocidos no se repiten. No se tocó `agenda.db` ni `outbox.log` (verificado: no existen en el repo).

## Veredicto: APROBADO

Sin hallazgos S1, S2 ni S3. Suite completa verde en UTC y con `TZ=Asia/Tokyo`. El barrido de seguridad no encontró desviaciones.

## Hallazgos

- Sin S1-S3.
- S4 (nuevo, informativo): `TZ=Asia/Tokyo python3 -m pytest -q` no ejercita realmente esa zona. `tests/conftest.py` fija la zona del sistema por prueba (UTC, y las pruebas de borde la parametrizan con `zona_sistema` = UTC/Tokyo/Santiago). La cobertura de zonas sí existe, pero la variable de entorno externa es irrelevante. Evidencia: ambas corridas dan `2249 passed, 1 skipped` (77.6 s y 76.3 s). El skip es `test_aislamiento.py:256` ("esta corrida no usa la memoria compartida"), esperado.
- S4 (nuevo, informativo): la regla 3 de SPEC (horas del profesional sin solape) se garantiza solo en código (`profesional.buscar_solape`); el esquema tiene `UNIQUE (profesional_id, inicio)` pero no impide solapes parciales. Aceptable con un único profesional y escritura serializada (D-003); cubierto por `test_horas.py::test_solapes_se_rechazan`.

## 1. Trazabilidad

| US | Ruta / función principal | Test que la cubre |
|---|---|---|
| US-1 registro | `POST /registro` · `auth.registro`, `validar_registro`, `crear_usuario` | `tests/test_registro.py` (41 pruebas); `test_roles.py::test_flujo_completo_registro_login_panel_logout` |
| US-2 login/logout | `/login` · `auth.login`; `POST /logout` · `auth.logout` | `tests/test_login.py` (62); `test_roles.py::test_flujo_completo_registro_login_panel_logout`; `test_limite.py` (límite de intentos) |
| US-3 aislamiento por rol | `auth._exigir` → `solo_paciente` / `solo_profesional` (403, o 302 a /login) | `test_roles.py::test_paciente_ve_su_panel_y_no_el_del_profesional`, `::test_profesional_ve_su_panel_y_no_el_del_paciente`, `::test_sin_sesion_se_redirige_al_login`; `test_dashboard_paciente.py::test_el_profesional_recibe_403`; `test_dashboard_profesional.py::test_el_paciente_no_accede_ni_ve_nada` |
| US-4 agregar hora | `/profesional/horas/nueva` · `profesional.nueva_hora`, `crear_hora`, `validar_formulario` | `test_horas.py` (93): `::test_no_se_crean_horas_en_el_pasado`, `::test_solapes_se_rechazan`, `::test_el_pasado_se_juzga_con_la_hora_de_chile_y_no_la_del_servidor` |
| US-5 eliminar hora libre | `POST /profesional/horas/<id>/eliminar` · `profesional.eliminar_hora` | `test_horas.py::test_eliminar_una_hora_libre`, `::test_no_se_elimina_una_hora_reservada`, `::test_reservar_cancelar_y_eliminar_conserva_las_notificaciones` |
| US-6 dashboard profesional | `/profesional` · `profesional.dashboard`, `listar_agenda`, `listar_horas_libres` | `test_dashboard_profesional.py` (42): `::test_el_profesional_ve_su_panel_sin_cache_ni_javascript`, `::test_orden_de_las_secciones` |
| US-7 horas libres futuras | `/paciente/horas` · `paciente.horas_libres`, `listar_horas_libres_futuras` | `test_horas_libres.py` (39): `::test_el_borde_de_las_24_horas_y_el_de_inicio`, `::test_la_fraccion_de_segundo_cuenta_en_el_borde` |
| US-8 reservar (>24 h) + confirmación | `POST /horas/<id>/reservar` · `paciente.reservar`, `reservar_hora` | `test_reservar.py` (56): `::test_a_las_24_h_exactas_no_se_reserva_y_un_segundo_mas_si`, `::test_una_hora_que_empieza_en_menos_de_24_h_se_rechaza_con_mensaje_claro`, `::test_el_update_condicional_decide_y_se_revisa_rowcount`, `::test_doble_clic_del_mismo_paciente_dice_ya_reservaste` |
| US-9 cancelar (≥24 h) | `POST /horas/<id>/cancelar` · `paciente.cancelar`, `cancelar_reserva` | `test_cancelar.py` (51): `::test_cancelar_con_mas_de_24_horas_deja_la_hora_libre`, `::test_una_fraccion_de_segundo_menos_de_24_horas_se_rechaza`, `::test_otro_paciente_no_puede_cancelar_la_reserva_ajena` |
| US-10 dashboard paciente | `/paciente` · `paciente.dashboard`, `listar_reservas_futuras`, `listar_sesiones` | `test_dashboard_paciente.py` (37): `::test_el_paciente_ve_su_panel_sin_cache`, `::test_el_html_es_accesible` |
| US-11 notificación al reservar | `notificaciones.registrar(CONFIRMACION)` dentro de `reservar_hora`; `escribir_outbox` | `test_notificaciones.py::test_reservar_crea_una_notificacion_para_el_paciente_y_otra_para_el_profesional`, `::test_el_mensaje_del_paciente_se_basta_solo_y_dice_hasta_cuando_cancelar`; `test_correo.py` |
| US-12 recordatorio 24 h | CLI `flask send-reminders` · `notificaciones.send_reminders_command` (`0 < faltan <= 24 h`, `recordatorio_enviado`) | `test_recordatorios.py` (46): `::test_ejecutar_dos_veces_envia_una_sola_vez`, `::test_el_borde_se_mide_en_instantes_al_empezar_el_horario_de_verano`, `::test_una_hora_cancelada_no_se_recuerda` |
| US-13 notificación al cancelar | `notificaciones.registrar(CANCELACION)` en `cancelar_reserva` | `test_notificaciones.py::test_cada_paciente_recibe_su_propio_aviso_y_la_contraparte_correcta` y pruebas de cancelación de ese archivo; `test_cancelar.py` |

Sin US sin test ni código claro. Las funciones y rutas existen (verificado con `grep` de decoradores) y los nombres de test se leyeron en los archivos.

## 2. Barrido de seguridad

Script: `scratchpad/revfinal/sweep.py` (base temporal en `scratchpad/revfinal/tmp*/t.db`; usuarios: profesional, paciente A, paciente B; horas: 1 reservada por A, 2-4 libres). Corrido con `python3 -I sweep.py` y con `TZ=Asia/Tokyo`; mismos resultados.

Rutas (`app.url_map`): `/` GET; `/login` GET/POST; `/registro` GET/POST; `POST /logout`; `/paciente`, `/paciente/horas` GET; `POST /notificaciones/leidas`; `POST /horas/<id>/reservar`; `POST /horas/<id>/cancelar`; `/profesional` GET; `/profesional/horas/nueva` GET/POST; `POST /profesional/horas/<id>/eliminar`; `POST /profesional/notificaciones/leidas`; `/static/...`.

Resultados (anónimo / A / B / profesional), solo lo observado, sin desviaciones:
- GET públicos (`/`, `/login`, `/registro`): 200 para todos.
- `/paciente`, `/paciente/horas`: 302 / 200 / 200 / 403. `/profesional`, `/profesional/horas/nueva`: 302 / 403 / 403 / 200.
- Todo POST sin token CSRF (los 9 POST, 4 actores): 400; el estado de `horas` no cambió.
- POST con CSRF a rutas de otro rol: 403 (anónimo: 302 a /login).
- IDOR: B cancela la hora 1 de A -> 302 con mensaje y la hora sigue `reservada` por A; profesional cancela -> 403; anónimo -> 302; sin cambios. Paciente eliminando horas (A, B) -> 403. Profesional eliminando hora reservada -> 302 con aviso, sin cambios. El dashboard de B no muestra el correo de A ni enlaces a la hora 1.
- IDs inválidos (`abc`, `0`, `-1`, `1'`): 404. ID inexistente (99999): 302 con mensaje genérico (cancelar/reservar) o 403 (eliminar, paciente), sin 500.
- Logout: 302 y `/paciente` pasa a 302 (sesión cerrada).
- Cabeceras: `Content-Security-Policy` (default-src 'self', frame-ancestors 'none'), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Cache-Control: no-store`.

## 3. Reglas críticas

- Doble reserva imposible: `reservar_hora` abre `BEGIN IMMEDIATE` (bloqueo de escritura antes de leer), decide con `UPDATE ... WHERE id = ? AND estado = 'libre'` y revisa `rowcount`; el esquema añade `CHECK` de coherencia estado/paciente y `UNIQUE (profesional_id, inicio)`. Sweep: A y B reservan la hora 3 en secuencia, queda solo con A. Pruebas: `test_reservar.py::test_el_update_condicional_decide_y_se_revisa_rowcount`, `::test_el_mismo_paciente_con_dos_horas_solapadas_a_la_vez_se_queda_con_una`. No ejecuté una carrera con hilos propia; me apoyo en esas pruebas (verdes).
- Regla >24 h estricta: `paciente.es_reservable` (`inicio - ahora > 24 h`, instantes absolutos, reloj leído dentro del bloqueo); la lista usa la misma función. Pruebas de borde: `test_reservar.py::test_a_las_24_h_exactas_no_se_reserva_y_un_segundo_mas_si`, `::test_una_fraccion_de_segundo_mas_de_24_h_se_reserva_y_menos_o_igual_no`; `test_horas_libres.py::test_el_borde_de_las_24_horas_y_el_de_inicio`. Cancelar con 24 h exactas permitido (coherente con SPEC regla 7).
- Recordatorio ≤24 h: `notificaciones.py:266` `0 < faltan_s <= ANTICIPACION_RECORDATORIO_S`, marcado con `UPDATE` condicional (`recordatorio_enviado = 0`); no recuerda libres, canceladas ni iniciadas; idempotente (`test_recordatorios.py::test_ejecutar_dos_veces_envia_una_sola_vez`).
- Zona horaria: se decide con instantes absolutos y `zoneinfo` de Chile, no con la zona del equipo. `python3 -m pytest -q` en UTC y con `TZ=Asia/Tokyo`: `2249 passed, 1 skipped` ambas (ver S4 sobre el alcance real del `TZ` externo). Cobertura de DST: `test_horas_libres.py::test_el_borde_se_mide_en_instantes_al_empezar_el_horario_de_verano` / `..._al_terminar_...`, `test_reservar.py::test_solape_entre_septiembre_con_instantes_absolutos`, `test_zona_horaria.py`.
