# REVIEW.md — Revisión de T-13 (estilo, errores, favicon) y T-13b (guarda del token CSRF)

Revisor: commits `b386820` (T-13) y `33a614b` (T-13b), rama `agentes/loop`. Contrastado con SPEC §6, TASKS (T-13 con las notas a–f, T-13b), D-008, D-009, D-014, D-024, D-037, D-038 y las últimas entradas de PROGRESS.
Todo lo medido se ejecutó en copias bajo el scratchpad (`base`, `rep1..6`, `shot`, `f500`, `mut_*`, `iso`); el repo no se tocó (`git status` limpio, sin `agenda.db` ni `outbox.log`). Servidor de capturas en el puerto 5191, cerrado por PID.

## Qué se verificó ejecutando

- Suite completa sobre copias de `HEAD`: **9 corridas, 9 × 1711 OK** (6 repeticiones sin variables, 1 de control, 1 con los archivos de `tests/` en orden inverso, 1 con `AGENDA_PSI_CSRF_TOKEN=abcdeadbeef0000cabc00abcdeadbeef0000cabc00abcdeadbeef0000cabc00a`). Tiempos 50–62 s (las más lentas, mientras yo corría capturas en paralelo en una máquina de 2 núcleos). Con 9 corridas no se puede *medir* una intermitencia del ~8 %; la garantía real es que no queda ninguna aserción vulnerable (ver abajo). `tests/test_estilo.py` y `tests/test_token_csrf_hostil.py` pasan solos y en cualquier orden; sin archivos residuales.
- Capturas reales con Chromium + Playwright a **360, 390 y 1280 px, tema claro y oscuro**: inicio, registro (y con errores), login (y con error), 404, 405, panel del paciente (reservas, historial, 4 notificaciones, nueva/leída), horas libres, panel del profesional (agenda, libres, una «no reservable», pasadas, notificaciones), agregar hora (y con error), flash de reserva, foco con Tab. Mirados los PNG; medí con JavaScript el desbordamiento de página y de cada `.tabla-scroll` y el tamaño de todos los enlaces/botones/campos.
- Contraste WCAG con mi propio script sobre los colores reales de `style.css` (29 pares × 2 temas). Texto: peor par 5,07 (primario sobre `nueva-fondo`, claro) y 5,93 (blanco sobre botón); texto principal 11–15; borde de campos 3,84–4,33 (claro) y 5,25–5,90 (oscuro); foco ≥ 5,46. Coincide con lo declarado en PROGRESS. Sin hallazgos de contraste.
- Errores contra servidor real y en copia: 404, 405 (con `Allow`), 400 de CSRF (D-009 intacto: un POST a ruta inexistente o con `PUT` sigue dando 400), 413 (cuerpo de 20 kB), 403, todos en español, con `Cache-Control: no-store` y sin trazas. 500 forzado con una excepción propia y con `sqlite3.OperationalError` de ruta inexistente, con `create_app()` de producción (sin TESTING): la página (889 bytes) no contiene el texto de la excepción, la ruta, «Traceback» ni «nonexistent». Con `render_template` roto sale el HTML mínimo en español. Sin `SECRET_KEY` el 500 sale en español y sin «SECRET_KEY»/«RuntimeError».
- `/static`: `/static/../app/schema.sql`, `%2e%2e`, `..%2f`, `..\`, `%00`, `/static/` y `/static` dan 404 en español (sin listado de directorio, sin lectura fuera de `static/`); `/static//etc/passwd` redirige (308) sin leer nada. `/favicon.ico` sigue en 404 pero el `<link rel="icon">` evita la petición. Sin `style=` ni `<script>` en `/`; sin URL externas en HTML ni en la hoja.
- 18 mutaciones propias (ver R-05 y la tabla al final).
- Fechas de PROGRESS/DECISIONS/TASKS contra `git log` (comprobado mecánicamente, ver R-08).

## Qué vi en las capturas

Diseño limpio y calmado, coherente en claro y oscuro; jerarquía clara; botones de ≥ 44 px (ningún enlace, botón ni campo de las páginas medidas mide menos de 44 px); sin scroll horizontal de página en ningún ancho (`scrollWidth == clientWidth` en las 58 capturas); formularios y errores legibles (borde + prefijo «Error:», no solo color); nueva/leída se distinguen por texto «(nueva)/(leída)», subrayado del título y borde, no solo por color; el enlace «Saltar al contenido» aparece al primer Tab con anillo de foco; el foco es visible en tablas, botones y campos. A 390 y 1280 px no vi defectos. A **360 px** vi los defectos R-01 y R-02. No probé 320 px, Firefox/Safari, lector de pantalla ni un celular real.

## Hallazgos

### R-01 (media) A 360 px la columna «Cancelar»/«Eliminar» queda cortada, también con el foco, y las fechas se parten
Medido: `Tabla de mis reservas` 339 px de contenido en 311 visibles (paciente); `Tabla de próximas reservas` 317>311 y `Tabla de horas libres` 337>311 (profesional), en claro y oscuro. Se ve el encabezado «Cancelar» recortado y el botón como «Cancela» (`png/light-360-pac-panel.png`, `dark-360-pro-panel.png`); al tabular hasta el botón, el anillo de foco también queda cortado por el borde derecho (`f-light-tab-cancelar.png`). No hay pista visual de que se puede deslizar (en celular la barra no se ve). Además las fechas se parten a mitad («12-10-» / «2026 11:00»), lo que a esta anchura cuesta leerlas. El implementador lo reconoció como «respaldo previsto»; contra el Término («sin texto ilegible») es un defecto menor pero real: la acción más destructiva de la pantalla es la que se ve cortada. A 390 px no ocurre.
Recomendación: tarea nueva chica antes o dentro de T-14 (solo CSS): quitar `white-space: nowrap` de la 2.ª columna o acortar «50 min», reducir `padding` y `min-width` de `tbody th`, no partir la fecha (`white-space: nowrap` en la primera columna con fuente menor) o mostrar el botón bajo la fecha en móvil; medir también 320 px.

### R-02 (baja) Flash de reserva dice «Listo: Listo, reservaste tu hora…»
La hoja antepone «Listo: » a todo flash de éxito (`.mensaje.exito::before`) y `paciente.MENSAJE_CONFIRMACION` ya empieza con «Listo,». Capturado en `f-dark-flash-reserva.png`. Es el único flash que repite la palabra.
Recomendación: tarea nueva (una línea: quitar «Listo, » del mensaje y ajustar las pruebas que lo fijan) o backlog.

### R-03 (media-baja) Con sesión iniciada, la marca del encabezado y «Volver al inicio» llevan a un inicio que parece de visitante
Reproducido con `curl` con la cookie de Ana: `GET /` muestra «Crear cuenta» e «Iniciar sesión»; la cabecera nueva (T-13) solo tiene un enlace, la marca, que va a `/`. Desde `/paciente/horas`, `/profesional/horas/nueva` o una página de error no hay forma visible de volver al panel (solo «Volver a mi panel» en las dos primeras) ni de cerrar sesión. El implementador anotó solo lo de las páginas de error; el problema es mayor porque la marca está en todas las páginas. Las páginas de error no pueden leer la sesión (D-008), así que la solución no está allí.
Recomendación: **decisión humana** (SPEC §6.1 dice «Inicio / login»): redirigir `/` al panel si hay sesión, o mostrar «Ir a mi panel» en `inicio.html` si la hay; luego tarea pequeña con prueba. Entra también «cierre de sesión en `/paciente/horas`» (T-06 R-04).

### R-04 (media) La guarda de T-13b tiene falsos negativos por detectar nombres de variable
`tests/test_token_csrf_hostil.py` selecciona pruebas con la regex `not in <…>(html|.text|texto|cuerpo|.data)`. Mutación en copia (3 pruebas nuevas añadidas a `test_dashboard_paciente.py`, token hostil forzado; las tres fallan al forzarlo): solo se selecciona la que usa `html`; **no** se detectan `assert "abc" not in ana.get("/paciente").get_data(as_text=True)` ni `pagina = ana.get(...).text; assert "dead" not in pagina`. Hoy hay también 7 aserciones reales de ausencia sobre `x.get(...).text`/`panel(pro)` que la regex no selecciona (`test_dashboard_profesional.py:354,355,421,453`, `test_cancelar.py:123`, `test_reservar.py:407`, `test_estilo.py:210,269,292`); revisé las 9: ninguna usa un texto hexadecimal, así que **no hay riesgo vigente**. Mi barrido con `ast` de *todas* las constantes de texto de `tests/` en `not in`/`.count()` que sean solo `0-9a-f` encontró una sola (`'db'`, `test_crear_profesional.py:353`, que mira una lista de sentencias SQL, no una página). La guarda sí mata la mutación declarada (volver a `"abc" not in html`: falla `...[abc-dead-beef-ceros]`) y suma ~9 s a la suite (que ya anda en ~57 s; el umbral del backlog T-04b R-08 es 60 s). El nombre `AGENDA_PSI_CSRF_TOKEN` solo se lee en `tests/conftest.py` (grep en `app/`: ninguna ruta lee esa variable; `app/` solo lee `SECRET_KEY`, `DATABASE`, `OUTBOX_PATH`) y el marcador `token_aleatorio` es de pytest: no hay filtración a producción.
Recomendación: backlog / tarea chica en T-14: añadir una prueba determinista sin subproceso que recorra `tests/` con `ast` y falle ante cualquier `x not in …`/`.count(x) == 0` cuyo literal sea hexadecimal corto (sin depender de nombres de variable), o correr la suite completa con un token hostil en el recorrido final (+~55 s).

### R-05 (baja) Funciones de accesibilidad sin prueba: sobreviven 5 mutaciones
Con `tests/test_estilo.py` + paneles + `test_horas`/`test_roles`/`test_seguridad` (358 pruebas) NO falla nada al: (a) quitar el enlace «Saltar al contenido»; (b) quitar `id="contenido"` (deja el enlace roto); (c) quitar `tabindex="0"` de las tablas con scroll (no se podrían recorrer con teclado); (d) quitar el subrayado de las notificaciones nuevas (queda el texto «(nueva)», pero la prueba no lo ata a la hoja); (e) quitar `aria-invalid` de los campos de «Agregar hora» (solo se prueba el de registro; login sin prueba, como ya anotaba T-04 R-09). Las pruebas de la hoja son de subcadena (`min-height: 2.75rem in CSS` basta con que aparezca en cualquier regla). Mueren, con el motivo declarado: `description` de Werkzeug visible, estado 200 en error, sin `Allow` en el 405, sin `no-store` en error de estático, `lang="en"`, enlazar avisos de cancelación, sin tope de pasadas, contraste bajo, sin `prefers-reduced-motion: reduce`, `style=` en línea, `outline` de foco en 0, 500 que filtra la excepción, sin `<link rel="icon">`.
Recomendación: backlog (T-14 o cuando se toque `test_estilo.py`).

### R-06 (informativa) Filas del backlog etiquetadas «T-13» que no se absorbieron ni se re-etiquetaron
Hechas: T-01 #3–4, T-03 #6, T-05 R-04, T-06 R-04 (caption/scope en horas libres), T-12 R-01. Sin hacer ni mencionadas en PROGRESS: **T-06 R-01** (`/paciente/horas` sin tope), **T-06 R-04** (cierre de sesión, día de la semana, hora de término), **T-08e R-11** (mensaje de las 24 h exactas «menos» → «no más de», mensaje de solape, README regla 7), **T-04 R-09** (mensajes de Click, pruebas de accesibilidad del login). La tarea T-13 no las exigía, pero la tabla las dejó con «T-13».
Recomendación: orquestador las reetiqueta a T-14/backlog.

### R-07 (informativa) Los «cambios fuera del alcance» son legítimos y están probados
`app/profesional.py` (`TOPE_PASADAS = 20` y `hay_mas_pasadas`) cumple la nota (e) de T-13; la mutación «quitar el tope» muere (`test_las_sesiones_pasadas_del_profesional_tienen_tope`). `app/seguridad.py` (`or respuesta.status_code >= 400`) hace que el 404/403 de `/static` lleve `no-store` (D-024); la mutación de revertirlo muere (`test_404_de_un_estatico_tambien_es_no_store`) y los 200 de estáticos conservan su caché (`Cache-Control: no-cache` con ETag, comprobado). `_notificaciones.html` (sin «Ver la reserva» en cancelaciones, R-01 de T-12) probado y la mutación muere. Todo está descrito en D-037. `errores.py` no cambia códigos de estado (mutación a 200 muere), conserva `Allow` y deja el 400 de CSRF (D-009) y el 413 (D-014, `MAX_CONTENT_LENGTH` = 16 kB) como estaban. Una observación menor: `HTML_MINIMO` usa `lang="es-CL"` sin `<head>`/viewport (aceptable como último recurso).

### R-08 (informativa) Documentación: veraz; horas coinciden con `git log`
Comprobado mecánicamente: cada encabezado `### [fecha hora]` de PROGRESS coincide al minuto con el commit que lo introdujo (`T-13 10:55` = `b386820` 10:55:39; `T-13b 11:35` = `33a614b` 11:35:32), igual `Fecha` de D-037/D-038 y `HECHA (…)` de TASKS (T-13 10:55, T-13b 11:35); ninguna es posterior a su commit (la hora real al revisar es 11:51). Las cifras de PROGRESS que pude comprobar son ciertas: 1711 pruebas, contrastes (5,93; 3,84–4,33), 28 pruebas en `test_estilo.py`, 7 pruebas con `token_aleatorio` (1 + 2 + 4), reproducción de `abc` con el token hostil. Una imprecisión leve: PROGRESS dice «capturas a 390 y 1280 px» y luego cita el problema de 360 px (medido a mano, no capturado); y T-13b afirma «revisadas 185 líneas»: mi barrido independiente confirma su conclusión.
**Pendientes del humano en `ARCHITECTURE.md`** (el archivo no se actualiza desde T-08d): `errores.py`, `error.html`, `_notificaciones.html`, `static/style.css` y `favicon.svg` (solo figura `static/ # style.css`), `correo.py`, `tiempo.py`, `notificaciones.py`, y las rutas `POST /notificaciones/leidas` (paciente) y `POST /profesional/notificaciones/leidas`, más el comando `send-reminders`. Solo `seguridad.py` y `static/` están.

## Para T-14

1. Recorrido §9 (registro → reserva → confirmación → recordatorio → cancelación): el recordatorio exige adelantar `inicio` por SQL o ajustar la redacción de §9 (D-029; nota de T-10). Hacerlo también a 360/390 px con la hoja real y mirar R-01.
2. README: cron con periodicidad < 24 h (p. ej. cada 15 min) y ejemplo de crontab; `DATABASE` y `OUTBOX_PATH` iguales a los del servidor web; el comando sale con código 1 si falla; `OUTBOX_PATH` relativo/enlaces (T-09 R-04); regla 7 de la cancelación; «solo en tu máquina» junto a `--debug`.
3. Cabeceras/CSP: no hay `style=` ni scripts en línea ni recursos externos, así que una CSP `default-src 'self'` debería funcionar (probarlo de verdad; el SVG del favicon es propio); faltan `X-Content-Type-Options`, `X-Frame-Options`/`frame-ancestors`, cookie `Secure` (T-03 #2, T-11b R-04).
4. Backlog completo con severidad «T-14» más R-03 (inicio con sesión), R-04 y R-05 de esta revisión, y las filas de R-06.
5. `AGENDA_PSI_CSRF_TOKEN` es solo de pruebas: no documentarla en el README de usuario; correr una vez la suite con token hostil en el cierre.

## Mutaciones ejecutadas (copia de `HEAD`, `-x`, 358 pruebas de estilo/paneles/horas/roles/seguridad)

| Mutación | Resultado |
|---|---|
| mostrar `error.description` | muere (`test_404_en_espanol`) |
| error con estado 200 | muere (`test_404_en_espanol`) |
| 405 sin `Allow` | muere (`test_405_en_espanol_conserva_allow`) |
| error de estático sin `no-store` | muere (`test_404_de_un_estatico_tambien_es_no_store`) |
| `lang="en"` | muere (`test_todas_las_paginas_enlazan_la_hoja_y_el_favicon`) |
| enlazar avisos de cancelación | muere (`test_los_avisos_de_cancelacion_no_enlazan_a_la_reserva`) |
| sin tope de pasadas | muere (`test_las_sesiones_pasadas_del_profesional_tienen_tope`) |
| `--suave` #aaaaaa | muere (`test_contraste_de_la_paleta[claro]`) |
| sin `prefers-reduced-motion: reduce` / foco con `outline: 0` | mueren (`test_la_hoja_cuida_foco_movimiento_y_tema`) |
| `style=` en línea en `login.html` | muere (`test_ninguna_plantilla_usa_estilos_ni_scripts_en_linea`) |
| 500 que añade la excepción | muere (`test_500_en_espanol_sin_filtrar_la_excepcion`) |
| sin `<link rel="icon">` | muere |
| sin enlace «Saltar», sin `id="contenido"`, sin `tabindex`, sin subrayado de «nueva», sin `aria-invalid` en `nueva_hora` | **sobreviven** (R-05) |
| guarda T-13b: `get_data(as_text=True)` y variable intermedia | **no detectadas** (R-04) |

## Veredicto

**APROBADA.** T-13 cumple el Término en 390 y 1280 px y en ambos temas, y casi en 360 px (R-01); las páginas de error, `no-store`, `/static` y los códigos de estado funcionan como D-009/D-014/D-024 piden, sin fugas; T-13b elimina la intermitencia de raíz (no queda ninguna aserción hexadecimal vulnerable; 9 corridas completas sin fallos). Ningún hallazgo es alto. Antes de cerrar el proyecto conviene abrir tarea para R-01 y R-02, decidir R-03 con el humano, y absorber R-04/R-05/R-06 en T-14 o el backlog.
