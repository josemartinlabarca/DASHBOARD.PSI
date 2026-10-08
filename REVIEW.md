# REVIEW.md — Revisión de T-04b (commit `5edc619`)

Revisor, 2026-10-08. Python 3.13, Flask 3.1.3, Werkzeug 3.1.8, gunicorn 26.2.0 (instalado solo en el scratchpad), Playwright 1.56 + Chromium headless.
Todo experimento y mutación se hizo en copias bajo el scratchpad (`.../scratchpad/{base,mut4,probe,nost,old5}`), a partir de `git archive 5edc619`. El repo no se tocó (`git status --short` vacío antes de escribir este archivo). Servidores cerrados por PID.
Leído: `git show 5edc619` completo (código, pruebas, DECISIONS, PROGRESS, TASKS), T-04b en `TASKS.md`, D-019, D-024, la revisión previa de T-04, `app/__init__.py`, `app/auth.py`, `app/seguridad.py`.

## Qué se verificó ejecutando

- `pytest`: **664 passed** (25,7 s y 24,6 s en dos corridas). `git diff 5edc619~1 5edc619 --stat`: **ningún archivo nuevo**. 664 - 597 = **67**. Coincide con PROGRESS.
- **CSRF** (cliente de pruebas, ~60 combinaciones): `POST|PUT|PATCH|DELETE|FOO|PROPFIND` a `/login`, `/registro`, `/logout`, `/paciente`, `/` sin token dan 400 (el CSRF corre antes que el 405); `OPTIONS/HEAD/TRACE` son métodos seguros (200/405 sin efecto). JSON, multipart sin token, token en la query (`?csrf_token=`), cabecera con otro nombre (`X-CSRF-Token`), `X-HTTP-Method-Override: GET`, método en minúscula, token con espacio final o no ASCII: todos 400. Cabecera `X-CSRFToken` correcta: pasa (diseño D-009). Formulario erróneo + cabecera correcta: 400 (el formulario manda; estricto, bien).
- **Cabeceras con servidor real** (`flask run`, curl, 20 rutas/variantes): `/`, `/login`, `/registro`, `/paciente` (302), `HEAD /login`, `/no-existe` (404), `POST /login` sin token (400), POST de 20 KB (413), `TRACE` (405), `OPTIONS`, `GET /logout` (405), `//login`, login correcto (302), `/profesional` (200), `/paciente` como profesional (403): todas `Cache-Control: no-store` + `Pragma: no-cache`. Sin `SECRET_KEY` (500 por `RuntimeError`): también las lleva. `/static/x.css` (200) sale con `Cache-Control: no-cache` + `ETag` (la propia de Flask) y `/static/nope.css` (404) sin ninguna cabecera de caché.
- **Nombre**: 40 casos con `validar_registro` (tabla en R-05/R-06) y 3 corridas reales del comando `create-professional` (ESC y U+2028 rechazados con el mensaje; «María Ñuñoa» aceptado).
- **Hash falso**: contador de llamadas a `generate_password_hash` en procesos reales: `init-db` 0, `routes` 0, `shell` 0 (`create-professional` 1 = el hash del usuario creado, no el falso); `flask run --no-reload` 1 al arrancar; `flask run --debug` 2 (proceso del recargador + hijo); gunicorn `-w 2` 2 (uno por worker), `-w 2 --preload` 1; gunicorn sin `SECRET_KEY`: 500 y 1 hash calculado en vano. Tiempos con hash real (gunicorn, curl): correo inexistente 0,166 / 0,126 / 0,129 s; contraseña errónea 0,167 / 0,127 / 0,133 s: **sin diferencia** y sin penalización del primer intento. `flask init-db` antes 0,32 a 0,46 s, ahora 0,35 a 0,42 s (sin regresión). Las pruebas de hilos y del CLI, repetidas 8 veces: estables.
- **Mutaciones** (suite completa con `-x`, 2 en paralelo): 25 propias; resultados en R-01, R-02 y la tabla del final.
- **Navegador**: mismo recorrido (login, panel, botón de logout, «atrás») con servidor real, con y sin el `after_request` de no-store, registrando las peticiones de red.

## Qué NO se verificó

- bfcache de un Chromium con interfaz, Firefox o Safari (ver R-04). Carga concurrente real contra gunicorn con hilos (`--threads`): el candado se probó con la prueba de 8 hilos y por mutación, no con carga. Mala conducta de proxies/CDN con `no-store`. Efecto de `Pragma` en clientes HTTP/1.0.

## Hallazgos

### R-01 — Huecos en las pruebas de CSRF de `/login` (baja)
Las pruebas pedidas por T-04b funcionan: eximir `/login` por ruta (`request.path == '/login'`) o por endpoint (`auth.login`) **mata** `test_login_sin_token_da_400_y_no_inicia_sesion`; eximir `/registro` o `/logout` también muere. La intención de R-01 de T-04 se cumple. Pero sobreviven tres mutaciones que debilitan el CSRF:
- `token_valido` con `esperado.startswith(recibido)` (acepta un prefijo del token: 1 carácter hex = 16 intentos): **sobrevive** (664 passed). Las pruebas usan `""`, `"X"`, `"0"*64` y el token de otra sesión; ninguna usa un prefijo/sufijo/longitud distinta del token real.
- Exención de `/login` cuando el cuerpo es JSON (`request.is_json`): sobrevive. Hoy es inofensivo (la vista lee `request.form`), pero ninguna prueba envía JSON, multipart o `text/plain` sin token a `/login`. Yo lo comprobé a mano (400).
- Exención de `/login` con cuerpo vacío y sin token: sobrevive (`test_el_fallo_de_login_y_el_400_de_csrf_no_se_almacenan` hace `POST /login` con `data={}` pero solo mira las cabeceras de caché, no el 400).
- Reproducir: aplicar en `app/seguridad.py` `return str(esperado).startswith(str(recibido))` y correr `pytest`.
- Recomendación: **backlog** (absorber en la próxima tarea que toque `app/seguridad.py` o en T-14): un parámetro con prefijo del token, token de longitud distinta, y POST vacío / JSON / multipart / `text/plain` a `/login` con 400. No bloquea.

### R-02 — `no-store`: cobertura de pruebas parcial y política demasiado rígida (baja)
- Las pruebas cubren 200, 302, 400, 403 y 404, y que `static` no lo recibe. **No cubren 405, 413, 500, `HEAD` ni `OPTIONS`**: las mutaciones «no aplicar a 405/413/500» y «no aplicar a HEAD/OPTIONS» **sobreviven** (664 passed). Con servidor real sí están cubiertos hoy (ver arriba), así que es un riesgo de regresión, no un fallo actual.
- El `after_request` **sobrescribe** `Cache-Control` (asignación directa). Hoy ninguna vista lo define, así que `setdefault` es equivalente (mutación sobrevive, equivalente por ahora). Consecuencia futura: una ruta que sirva una descarga o un recurso cacheable no puede optar por salirse; tendría que modificarse el hook. Ninguna tarea de TASKS/SPEC lo necesita hoy.
- Proporcionalidad (D-024): en esta app **toda** página HTML dinámica lleva token CSRF o mensajes flash, así que un `no-store` central sin enumerar rutas es razonable y es el diseño que no se olvida. Lo que se pierde es la caché de HTML pequeño y, en Chrome, la bfcache (la página se vuelve a pedir al volver con «atrás»; en formularios largos puede perderse lo ya escrito). Coste aceptable; no recomiendo hacerlo selectivo.
- Recomendación: **backlog**: una prueba parametrizada con 405 (`GET /logout`), 413 (cuerpo > 16 KiB), 500 (ruta que lanza), `HEAD` y `OPTIONS`; y, cuando aparezca la primera ruta que necesite otra política, decidirlo entonces (`setdefault` o exención explícita).

### R-03 — D-024 afirma algo inexacto sobre Flask (informativa)
D-024 (1) dice que «Flask 3.1 deja `session.accessed` siempre en True». No es cierto: una ruta que no toca la sesión (`@app.route("/f") def f(): return "hola"`) sale **sin** `Vary: Cookie` (comprobado), es decir, `accessed` es False. Lo que sí es cierto es la conclusión práctica (`base.html` lee los flash y los formularios llevan token, así que toda página HTML de la app toca la sesión). Además PROGRESS/D-024 dicen que los estáticos «conservan su caché»: Flask los sirve con `Cache-Control: no-cache` + `ETag` (revalidación), no con caché fuerte; y el 404 de `/static/…` sale sin cabecera.
- Recomendación: **ignorar** o, si se vuelve a tocar D-024, corregir la frase (el humano o el implementador en su próxima tarea; el revisor no edita DECISIONS).

### R-04 — Prueba del botón «atrás»: la afirmación de PROGRESS es honesta, pero el control real sigue sin existir (informativa)
PROGRESS dice que el recorrido en Chromium «no discrimina» porque dio igual con y sin no-store. Lo reproduje: con y sin el `after_request`, Chromium headless, al pulsar «atrás» tras el logout, **vuelve a pedir** `GET /profesional` al servidor (que responde 302 a `/login`) y termina en `/login` sin mostrar el panel; las peticiones de red son idénticas en ambas variantes. Es decir: la afirmación es veraz y no se vende como prueba. Lo que protege es el encabezado, comprobado por pruebas y por curl; si un navegador con bfcache (Chrome con interfaz, Safari, Firefox) mostraría o no el panel no se ha comprobado y no se puede comprobar en este entorno.
- Recomendación: **backlog T-14** (comprobación manual en navegadores reales); no bloquea.

### R-05 — ZWJ/ZWNJ rechazados: falso positivo para algunas escrituras, no para el público de Chile (informativa)
`unicodedata.category` de U+200C/U+200D es `Cf`, así que se rechazan: nombres persas con ZWNJ (`علی‌اکبر`), conjuntos devanagari con ZWJ/ZWNJ (`क्‌ष`) y emoji ZWJ. Con el mensaje actual («…caracteres de control o invisibles») la persona no entiende qué corregir. Para una clínica en Chile, con nombres en español y mapuzugun (ñ, ü, tildes, apóstrofe), el impacto es prácticamente nulo; los nombres CJK, árabes (sin ZWNJ) y devanagari básicos **sí** pasan. Tabla (ejecutada): aceptados: María José Ñancucheo, Müller Güiraldes, D’Angelo O’Higgins (U+2019), O'Higgins, Ana-María, Dra. M. Pérez, nombres compuestos largos, 王小明, محمد علي, प्रिया शर्मा, ñ descompuesta (NFD), NBSP e U+3000 internos, 100 caracteres exactos; rechazados: CR/LF, NUL, ESC, tab interno, NEL, U+2028/2029, RLO/LRI y demás bidi, U+00AD, ZWSP, BOM, ZWJ/ZWNJ, caracteres de etiqueta U+E00xx, uso privado, sin asignar, sustitutos; 101 caracteres rechazados; solo espacios o solo NBSP -> «Escribe tu nombre.» (se recorta antes). La regla está en `validar_registro`, usada por `/registro` y `create-professional` (comprobado en ambos); la longitud se comprueba antes del barrido, así que el barrido nunca recorre más de 100 caracteres.
- Recomendación: **decisión humana, baja prioridad**: aceptar la limitación y anotarla en D-024, o permitir U+200C/U+200D solo entre caracteres de escrituras que los usan (complejidad no justificada hoy).

### R-06 — Nombres «visualmente vacíos» o con basura combinante siguen pasando (baja)
Al no ser `C*`, pasan: U+3164 (relleno hangul), U+2800 (braille en blanco), U+115F/U+1160, un combinante suelto (`́`), U+034F, selectores de variación (U+FE0F, categoría `Mn`) y 99 combinantes sobre una letra («zalgo» dentro de los 100 caracteres). Un nombre `"ㅤ"` o `"́"` se guarda y se vería en blanco en listados y notificaciones. No hay inyección de líneas ni bidi (lo que pedía R-07 de T-04), pero es la misma familia que D-015/D-020 para el correo.
- Recomendación: **decisión humana**, junto con D-020 (alcance de la política de caracteres): exigir al menos una letra o número (`str.isalnum()` en algún carácter) y/o limitar combinantes consecutivos. Sin urgencia.

### R-07 — `HashFalso`: correcto; notas menores (informativa)
- Seguridad en hilos: candado con doble comprobación; la prueba de 8 hilos muere si se quita la segunda comprobación (mutación X10) o el candado. Un solo cálculo, `_valor` asignado una vez.
- Costo: usa el mismo `generate_password_hash` por defecto que el registro (`scrypt:32768:8:1`; la prueba `hash_real` lo fija); tiempos iguales a la contraseña errónea (ver arriba). No se filtra a producción: con la fixture D-019 el falso es rápido; sin ella es real (mutación «pbkdf2» muere, y la mutación de hash compartido por módulo muere).
- No se calcula en CLI (`init-db`, `routes`, `shell`, `create-professional`: medido en procesos reales). Sí en `flask run`, gunicorn y en cualquier `create_app()` sin contexto de click (scripts, `python -c`, `wsgi.py`), donde se calcula aunque no se sirva: aceptable.
- Detalles sin acción: `flask run --debug` lo calcula dos veces (proceso del recargador y el hijo); sin `SECRET_KEY` fuera de debug se calcula aunque cada petición dará 500; `create_app` con `@pytest.mark.hash_real` suma ~0,13 s por prueba (7 marcadas). La prueba del CLI usa un parche de `click.get_current_context` (no un `flask init-db` real); la verificación real la hice yo con procesos.
- Recomendación: **ignorar**.

### R-08 — Velocidad de la suite (informativa)
25 s para 664 pruebas (antes 20,4 s para 597). Distribución medida: `setup` 9,9 s, `call` 13,2 s; por archivo `test_esquema` 4,9, `test_login` 4,3, `test_config` 3,8 (3 s la prueba que lanza `flask run`), `test_registro` 3,7, `test_correo` 2,3 (una prueba exhaustiva). Sin una prueba dominante. No justifica una tarea de velocidad; sí un umbral.
- Recomendación: **backlog**: reabrir si supera ~60 s o antes de T-10; opciones sin dependencia nueva (marcar `slow` la de `flask run` y la exhaustiva); `pytest-xdist` exigiría una entrada en DECISIONS y en esta máquina (2 núcleos) ganaría poco.

### R-09 — Veracidad de PROGRESS (informativa)
- «664 pruebas, 67 nuevas»: cierto. «Archivos nuevos: ninguno»: cierto.
- «19 líneas eliminadas de tests/»: cierto (19). Revisadas una a una: 3 son importaciones/comentarios de `conftest.py` y `test_login.py`; 4 son el viejo `cache_clear` del `lru_cache` que ya no existe; el resto son 3 pruebas del hash falso reescritas con `app_context` (misma aserción), una prueba (`se_crea_al_usarlo_y_una_sola_vez`, de `cache_info`) sustituida por dos (existe al construir y no se recalcula; una sola vez con 8 hilos), y `test_id_de_sesion_con_tipo_o_valor_raro_no_autentica`: **conserva los 8 valores originales** (`"1"`, `True`, `1.0`, `None`, `[1]`, `{"a": 1}`, `-1`, `10**30`) y suma `0`, `2**63`, `2**63-1` y un id válido; la aserción de 302 se mantiene. **No se perdió cobertura.**
- Mutaciones declaradas: reproduje las que ejecuté de la lista (eximir `/login`, quitar `no-store`, `0 <= valor` sobrevive como equivalente, solo `Cc`, hash falso sin candado, calculado en CLI, etc.): mismos resultados.
- «Navegador: no discrimina»: veraz (R-04). «No verificado: bfcache»: veraz. Tiempos (scrypt 0,24 s): en esta corrida ~0,13 s (varía por máquina); sin importancia.
- Problemas menores de forma: la entrada no menciona las tres mutaciones que sobreviven (R-01, R-02), pero declara honestamente las que encontró.

### R-10 — Interacción con T-05 y siguientes (informativa)
- T-05 tiene formularios `POST` del profesional: heredarán CSRF y `no-store` sin hacer nada; los errores 400/403/405/413/500 también.
- El nombre se copiará a notificaciones y listados (T-09/T-10/T-11): sin saltos de línea ni ESC ya no hay inyección de líneas ni de secuencias de terminal en `outbox.log`/pantalla. Quedan los casos de R-06.
- `_es_id_valido` (`0 < valor < 2**63`) sirve de modelo para ids en sesión; las rutas `<int:id>` de T-07/T-08 deberían acotar igual el id (Flask pasa enteros arbitrarios y SQLite lanza `OverflowError` sobre `2**63`): anotar para T-07 un id gigante en la URL sin 500.
- Cualquier descarga o recurso con política de caché propia (R-02) pedirá tocar el hook central.
- D-022 (revocar sesión) y D-023 (un solo profesional) siguen pendientes y no se vieron afectadas; D-023 sí debe decidirse antes de T-05, como ya sugiere PROGRESS.

## Tabla de mutaciones propias (suite completa)

| Mutación | Resultado |
|---|---|
| Eximir `/login` por ruta / por endpoint | muere (`test_login_sin_token_da_400…`) |
| Eximir `/registro`; eximir `/logout` | mueren |
| Token válido si es prefijo del esperado | **sobrevive** (R-01) |
| Eximir `/login` si el cuerpo es JSON | **sobrevive** (R-01) |
| `/login` sin token y sin cuerpo no exige CSRF | **sobrevive** (R-01) |
| `no-store` solo si estado < 400 / solo GET / solo 200 / solo con sesión / `no-cache` en lugar de `no-store` / sin logout / `Pragma` solo en 200 | mueren (7) |
| `no-store` sin aplicar a 405/413/500; sin HEAD/OPTIONS | **sobreviven** (R-02) |
| `Cache-Control` con `setdefault` | sobrevive (equivalente hoy, R-02) |
| Exención de estáticos por prefijo del endpoint | sobrevive (equivalente) |
| Nombre: solo `Cc`+`Cf`+`Zl`+`Zp` (sin `Co`, `Cn`, `Cs`) | muere (uso privado) |
| Nombre: sin validar en el CLI; normalizado en la vista | mueren |
| Nombre: comprobar el barrido antes que el largo | sobrevive (equivalente en cuanto a seguridad; solo cambia qué mensaje sale si hay ambos fallos) |
| Candado sin segunda comprobación | muere (prueba de hilos) |
| Hash falso solo si no `TESTING`; con pbkdf2; compartido por módulo | mueren |
| Cota del id `<= 2**63` | muere (`[9223372036854775808-False]`) |

## Veredicto: **APROBADA**

La tarea cumple su criterio de término: las cuatro mutaciones exigidas («eximir `/login`», «quitar `no-store`», «nombre con salto de línea», «id `2**63`») hacen fallar pruebas; `pytest` pasa (664); el comportamiento se confirmó con servidores reales (cabeceras, hash falso, tiempos, nombre, CLI). No hay hallazgos de severidad media ni alta. Quedan solo mejoras de pruebas y decisiones menores (R-01, R-02, R-06 baja; el resto informativas). T-05 puede empezar; conviene decidir D-023 antes.
