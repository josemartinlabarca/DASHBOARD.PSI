# REVIEW — T-11b Marcar notificaciones como leídas, tope de 20 y orden del panel (commit `aa8719d`)

Revisor: lee el diff, contrasta con SPEC §5/§6.3, D-034 y D-035 y con el texto de T-11b en TASKS.md.
No se modificó código, pruebas, TASKS, PROGRESS, DECISIONS ni ARCHITECTURE. Todo lo ejecutado se hizo en
copias bajo el scratchpad (`rev/`, `m1`, `m2`, `m3`, `mut_*`, `nav2/`), nunca en el repo. El repo quedó
sin archivos nuevos (`git status` limpio, sin `agenda.db` ni `outbox.log`).

**Veredicto: APROBADA.** Sin hallazgos de severidad alta ni media. D-035 se cumple al pie de la letra.
Los hallazgos son bajos o informativos; ninguno bloquea T-12.

## Qué SÍ se ejecutó

- `python3 -m pytest -q` en copia de `HEAD`: 1621 OK.
- Pruebas de apoyo propias (en la copia, ya descartadas) con el cliente de Flask: métodos HEAD/PUT/DELETE/PATCH/OPTIONS,
  token de otro paciente, token por cabecera, cabeceras de respuesta, mensaje con `<script>`, profesional sin token,
  bloqueo de SQLite real con una segunda conexión `BEGIN IMMEDIATE` (1 s y 6 s) y notificación insertada después de renderizar.
- Mutaciones (copia por mutación, un archivo de pruebas): `<h2>` de «Mis reservas» con atributo (suite de `test_cancelar`
  y suite del panel por separado), `<h2>` de Historial, UPDATE sin filtro de usuario (y COUNT sin filtro), quitar
  `LIMIT`, `>= 20` por `> 20`, verificación CSRF desactivada, botón siempre visible, ruta que acepta GET,
  `@solo_paciente` por `@login_requerido`, filas ilegibles metidas al historial. Todas matan al menos una prueba (ver R-06).
- Navegador (Chromium de `/opt/pw-browsers`, Playwright Python, servidor Flask propio por PID, base/outbox en el scratchpad):
  Ana con 23 notificaciones y Beto con 3, a 390 y 1280 px; clic (1280) y Tab+Enter (390); captura de foco.
  Resultado: 20 filas, campana 23, aviso de tope presente, sin scroll horizontal, sin errores de consola, orden de `h2`
  = Próxima sesión, Mis reservas, Historial, Notificaciones; tras la acción: redirección a `/paciente`, flash
  «Marcaste 23 notificaciones como leídas.», campana 0, botón ausente; Beto sigue en 3; `<b>x</b>` del mensaje se ve como texto.
  Con teclado el botón se alcanza con 2 Tab (enlace «Reservar hora», luego botón) y tiene el anillo de foco por defecto (`outline: auto 1px`).

## Qué NO se verificó

Lector de pantalla real; el navegador contra profesional y anónimo (solo cliente de pruebas); dos procesos `flask` reales
compitiendo (el bloqueo se simuló con otra conexión SQLite); captura de 1280 px revisada solo por métricas del DOM.

## Cumplimiento de D-035 (punto 1)

- Solo filas del usuario en sesión: `UPDATE ... WHERE usuario_id = ? AND leida = 0`, id tomado de `usuario_actual()`. La mutación sin filtro la matan 6 pruebas.
- Ignora ids del formulario y de la query string: la vista no lee `request.form` ni `request.args` (más allá del CSRF global). Probado con `id`, `ids`, `usuario_id`, `?id=`.
- Idempotente: la segunda llamada devuelve 0 y flash «No tenías notificaciones sin leer.».
- Botón solo con no leídas (`{% if sin_leer %}`), formulario con `csrf_token` como único campo, sin `<script>`.
- Contador total (`COUNT(*)` aparte) frente a 20 visibles: probado con 25, y con 1 no leída fuera de las 20 visibles (botón sigue).
- Flash: solo interpola un entero (`cantidad`), nada del usuario; Jinja escapa el resto. Redirección a `url_for` fija: sin redirección abierta.

## Hallazgos

### R-01 (baja) «Marcar todas» marca también lo que el usuario nunca vio
**Evidencia:** con una notificación visible y otra insertada después de renderizar el panel, el POST deja ambas en `leida=1` (`[True, True]`).
No hace falta concurrencia fina: pasa siempre que llegue algo entre la carga de la página y el clic (confirmaciones, recordatorios del cron de T-10, o la
cancelación hecha desde otra pestaña). Además las no leídas fuera de las 20 visibles se marcan sin verse (D-035 lo acepta: «todas»).
La `UPDATE` es una sola sentencia, así que no hay lectura sucia ni estado a medias; el efecto es solo perder el estado «nueva» de un aviso. El contador del flash («Marcaste N») sí delata la diferencia si el usuario lo mira.
**Impacto:** bajo (avisos informativos; el mensaje sigue en la lista). Mitigarlo exigiría enviar un `hasta_id` (el mayor id visto) en el formulario, lo que choca con «ignora cualquier id recibido» de D-035.
**Recomendación:** decisión humana, no urgente; si se acepta, backlog con un campo oculto `hasta_id` validado como entero y acotado al propio usuario. Si no, ignorar.

### R-02 (baja) Bloqueo de SQLite sin `busy_timeout` propio: 500 tras 5 s
**Evidencia:** con otra conexión reteniendo `BEGIN IMMEDIATE`, el POST espera y responde bien si se libera en 1 s (302, `[True]*5`); si se retiene 6 s lanza
`OperationalError('database is locked')` a los 5,02 s (en producción, un 500). `sqlite3.connect` usa su espera por defecto (5 s) y `get_db` no configura nada.
No es específico de T-11b (reservar, cancelar y el cron comparten el patrón); aquí el riesgo es bajo porque la transacción es de una sentencia.
**Recomendación:** backlog para T-14 (decidir `timeout`/`busy_timeout` y una página 500 en español junto con el 413). No requiere acción en T-11b.

### R-03 (baja) Aviso de tope con exactamente 20 y el «20» duplicado en la plantilla
**Evidencia:** con 20 notificaciones en total aparece «Se muestran tus 20 notificaciones más recientes.», que da a entender que hay más. El implementador lo
declara (el texto no es falso, pero induce a buscar algo que no existe). Además la plantilla escribe `>= 20` a mano y `TOPE_PANEL` vive en Python: si se cambia uno,
el aviso se desincroniza (la mutación «tope 30» solo se detecta porque las pruebas también escriben 20).
**Recomendación:** tarea pequeña (puede ir en T-12 porque tocará la misma función): pedir `LIMIT TOPE_PANEL + 1`, recortar a 20 y mostrar el aviso solo si llegó la fila 21; pasar `tope` a la plantilla. Sin COUNT extra. Añadir una prueba con exactamente 20 (hoy solo hay 19 y 25).

### R-04 (informativa) Cabeceras globales: sin `X-Frame-Options`/CSP y CSRF aceptado por cabecera
**Evidencia:** ninguna respuesta lleva `X-Frame-Options` ni `frame-ancestors`; `verificar_csrf` acepta también `X-CSRFToken` (probado: 302 y marca). El panel podría
enmarcarse en otro sitio; el único efecto posible sobre esta ruta es marcar avisos como leídos (sin datos ni acciones destructivas), y la cookie es `SameSite=Lax`, que no viaja en un POST entre sitios. `no-store` y `Pragma` sí están en la redirección y en el panel.
**Recomendación:** backlog T-14 (cabeceras de seguridad globales); sin relevancia para esta tarea.

### R-05 (informativa) Anónimo y profesional: comportamiento coherente con T-04, orden CSRF antes del rol
**Evidencia:** profesional con token válido: 403 (plantilla `acceso_denegado`); anónimo con token de su sesión anónima: 302 a `/login`; sin token (profesional o anónimo): 400 antes de mirar el rol.
GET/HEAD/PUT/DELETE/PATCH: 405 (OPTIONS 200 con `Allow: POST, OPTIONS`, estándar). Ninguna escribió nada. Las pruebas cubren profesional 403, anónimo 302, y anónimo sin token 400.
**Recomendación:** ignorar.

### R-06 (informativa) Pruebas: reescrituras y mutaciones comprobadas
- **Las 12 líneas eliminadas** (`git show --numstat`: dashboard 212+/12−, cancelar 2+/1−, horas_libres 1+/1−): 
  - `filas_de_reservas`: se quitó el condicional `if seccion else None` y se añadió `assert seccion`. Más fuerte. Con la mutación del `<h2>`, **el ayudante falla por sí solo**: `pytest tests/test_cancelar.py` da 6 fallos y los 6 son `AssertionError: no existe la sección «Mis reservas» (R-04)`. R-04 cerrado, y la afirmación del implementador («la mató otra prueba») queda corregida: en la suite del panel la mata `test_orden_de_las_secciones...`, en la de cancelar la mata el ayudante.
  - `historial`: ahora falla si falta `<h2>Historial</h2>`; con el `<h2>` mutado fallan 11 pruebas. Más fuerte.
  - `mensajes_listados`: cambia `1` por `None` en `seccion(...)` porque «Notificaciones» ya es la última sección (hasta `</main>`). Equivalente adaptado; con el tope de 20 y 25 filas lo prueba `test_con_25...` (20 `<li>`).
  - `test_filas_ilegibles_se_omiten_sin_romper`: la prueba usaba `inicio='2026-13-45T99:99:99'` y solo exigía 200. La nueva conserva esa fila, agrega una de duración `'abc'`, y exige historial vacío, «No tienes una sesión próxima», «No tienes reservas próximas», que `2026-13-45` y `abc` no aparezcan, y que una fila sana siga apareciendo en próxima/reservas/historial. Estrictamente más fuerte. R-03 de T-11 cerrado: meter las filas ilegibles al historial (mutación propia, `m3`) falla solo esta prueba.
  - `test_no_hay_ninguna_accion_para_marcar_como_leida` (contradecía D-035): reemplazada por 13 pruebas; el contenido útil de su aserción de formularios («solo Cerrar sesión» sin no leídas) está cubierto por `formularios_de_leidas(...) == []` en `test_el_boton_solo_aparece_si_hay_no_leidas`. R-05 de T-11 cerrado.
  - `test_horas_libres`: solo cambia el rótulo a «Reservar hora»; igual de estricta.
- **Mutaciones (≥6) y razón del fallo:** sin filtro de usuario → 6 fallos (`test_ignora_los_ids…`, `test_con_25…`, `test_marcar_leidas_devuelve…`, entre otras); quitar `LIMIT` → 2 (`test_con_25…`, `test_el_contador_incluye…`); CSRF desactivado → 2 (`test_sin_token_csrf…`, `test_el_anonimo…`); botón siempre → 2 (`test_el_boton_solo_aparece…`, `test_marcar_todas…`); GET permitido → `test_la_ruta_no_acepta_get`; `@login_requerido` → `test_el_profesional_no_puede_usar_la_ruta`; `> 20` → `test_con_25…`; `<h2>` Historial → 11. Todas fallan por la razón declarada.
- **Debilidad menor:** las pruebas de orden e índices usan `html.index("Notificaciones\n")` y `<h2>Mis reservas</h2>` con coincidencia literal. Si T-13 añade `class`/`id` a esos `<h2>` (o cambia los saltos de línea), fallan 6 pruebas de `test_cancelar` más la de orden, con mensaje claro pero ruidoso. Anotado para T-13 (ver R-07).
- Sin archivos residuales; sin redundancia relevante (las 13 pruebas nuevas no se solapan salvo el flujo básico en `marcar_todas` y `con_25`, que cubren cosas distintas).

### R-07 (informativa) Documentación y notas para T-12 / T-13 / T-14
- PROGRESS es veraz en lo medido; corregir solo esta frase: «la mutación del `<h2>` … la mató la prueba de orden, no el ayudante»: el ayudante falla por sí mismo (R-06). «Estado actual» ya está al día (T-11b hecha, T-12 siguiente). Sigue pendiente del humano añadir `POST /notificaciones/leidas` a `ARCHITECTURE.md` (declarado).
- **Nota para T-12:** `@solo_paciente` devuelve 403 al profesional (probado). Diseño recomendado sin duplicar `marcar_leidas`: (a) una ruta delgada propia del profesional (`POST /profesional/notificaciones/leidas`, `@solo_profesional`) que llame a `notificaciones.marcar_leidas` con el id de sesión y redirija a su panel; (b) mover la redacción del flash («Marcaste N…», singular/plural, «No tenías…») a una función de `notificaciones.py` para que ambas vistas no la copien. Alternativa: una sola ruta con `@login_requerido` y redirección según rol, pero obliga a cambiar `test_el_profesional_no_puede_usar_la_ruta` y a que el humano decida (D-035 dice «solo rol paciente por ahora»). En ambos casos: reutilizar `TOPE_PANEL`/`listar_de_usuario` (tope 20 y COUNT aparte), reconstruir `enlazable` con las horas del propio profesional y `LEFT JOIN`/mensaje sin enlace si `hora_id` es NULL (D-016), y repetir las pruebas de D-035 (CSRF, ids ignorados, otro usuario no cambia, anónimo/paciente 403 o 302).
- **Nota para T-13:** estilos para `.campana`, `li.leida`/`li.no-leida`, el botón del formulario (mantener foco visible; hoy es el anillo por defecto), tabla de reservas/historial; los tests dependen de `<h2>Mis reservas</h2>` y `<h2>Historial</h2>` sin atributos, de `th scope`, `<caption>` y `aria-label` (R-06); si se cambian, actualizar `filas_de_reservas`/`historial` a la vez. Hay dos líneas en blanco sobrantes antes del formulario de «Cerrar sesión» (cosmético). R-09 (favicon) sigue en T-13.
- **Nota para T-14:** R-02 (bloqueo/500 en español) y R-04 (cabeceras) como backlog; añadir al recorrido: «Marcar todas como leídas» con más de 20 y comprobar el flash.

## Resumen

| # | Severidad | Tema | Recomendación |
|---|---|---|---|
| R-01 | baja | «Marcar todas» marca avisos llegados después de renderizar | decisión humana / backlog |
| R-02 | baja | `database is locked` tras 5 s sin página 500 | backlog T-14 |
| R-03 | baja | Aviso de tope con exactamente 20; `20` duplicado | tarea pequeña (T-12) |
| R-04 | informativa | Sin cabeceras anti-frame; CSRF por cabecera | backlog T-14 |
| R-05 | informativa | Rol/CSRF coherentes con T-04 | ignorar |
| R-06 | informativa | Reescrituras igual o más fuertes; mutaciones matan por la razón declarada | corregir frase de PROGRESS |
| R-07 | informativa | Notas T-12/T-13/T-14 | anotar en TASKS (orquestador) |

**Veredicto: APROBADA.**
