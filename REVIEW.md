# REVIEW — T-03 (commit 2cb7f02)

**APROBADO**

No hay hallazgos de severidad alta. El criterio de término de T-03 (registro válido, correo duplicado rechazado, contraseña con hash), US-1 y la regla 6 se cumplen. `python3 -m pytest -q`: 62 pruebas pasan, también con `SECRET_KEY=abc`, con `FLASK_DEBUG=1` y con ambas (copia temporal del commit). Árbol limpio, sin `.db` ni procesos residuales. SPEC.md y ARCHITECTURE.md no se tocaron; `requirements.txt` no cambió; el commit sigue el formato `T-XX: ...`; la hora de PROGRESS.md (00:14) coincide con la del commit (00:14:08); D-005, D-006, D-008 a D-011 en orden y D-007 sigue reservada.

## Verificación empírica (copia en directorio temporal, `test_client`)

- **CSRF:** `PUT`, `PATCH` y `DELETE` sin token responden 400, incluso en rutas inexistentes (`/nada`) y estáticas, y en rutas sin ese método (el 400 gana al 404/405). `GET`/`HEAD`/`OPTIONS` pasan; `TRACE` da 405. `?_method=` y `X-HTTP-Method-Override` no tienen efecto en Flask. Un token en la query string no vale. POST con cuerpo JSON o sin Content-Type: 400 (el token solo se lee de `request.form` o de la cabecera `X-CSRFToken`; con la cabecera, un POST JSON pasa). El token está ligado a la sesión (tokens distintos entre clientes; el de otro cliente da 400) y usa `hmac.compare_digest`. D-008 corre primero (hay prueba).
- **Cookie de sesión** (Flask 3.1.3 / Werkzeug 3.1.8): `HttpOnly=True`, `SameSite=None` (no se emite atributo), `Secure=False`. La cookie es solo firmada, no cifrada: decodificada contiene `{"csrf_token": "..."}` y, mientras hay un mensaje flash, el texto del mensaje. Nada sensible por ahora.
- **Hash:** `generate_password_hash` por defecto en esta versión es `scrypt:32768:8:1` con sal de 16 caracteres; un registro tarda unos 0,12 s, tanto si es nuevo como si es duplicado (la diferencia de tiempo no filtra existencia; la validación fallida sí es instantánea, lo que es inocuo).
- **Cuerpo grande:** una contraseña de 20 MB en un formulario urlencoded da 413 (límite `MAX_FORM_MEMORY_SIZE` de 500 kB de Flask 3.1, no de la app). Un multipart de 50 MB con archivo a una ruta inexistente y sin token se acepta y se procesa (400 tras 0,12 s), porque `MAX_CONTENT_LENGTH` es `None`.
- **ReDoS:** la regex `^[^@\s]+@[^@\s]+\.[^@\s]+$` con 1 000 000 de caracteres (`a*n@b*n`, `@*n`, `a@.*n`) tarda menos de 0,03 s. Sin riesgo de ReDoS (las clases `[^@\s]+` no se solapan, el backtracking es lineal); además `len(email) > 254` se evalúa primero y corta la regex en entradas largas.
- **Mutaciones** (copia, `pytest` completo): sin `lower()` falla; token estático global falla; sin cabecera `X-CSRFToken` falla; correo sin capturar `IntegrityError` falla; rol leído de `request.form` falla (1 prueba); contraseña como `sha1:` + texto plano falla; `|safe` en `value="{{ nombre }}"` falla. **No fallan** (62 pasan): CSRF solo en POST (PUT/PATCH/DELETE exentos); `|safe` en `value="{{ email }}"`; `generate_password_hash(..., method="pbkdf2:sha256:1")` (hash débil); `==` en lugar de `compare_digest`.
- **Zona horaria:** simulado con `PYTHONTZPATH` apuntando a una carpeta vacía (equivale a Windows sin `tzdata`): `create_app()` lanza `ZoneInfoNotFoundError` al importar `auth.py`.

## Hallazgos

### Medios

**1. `ZoneInfo("America/Santiago")` a nivel de módulo rompe toda la app en Windows sin `tzdata` (app/auth.py:12; README.md "Cómo ejecutarlo").**
Es real: Windows no trae base de datos IANA y Python no la incluye; el README indica `.venv\Scripts\activate`. Como `ZONA_CHILE` se crea al importar `auth`, y `create_app` importa `auth`, falla todo: `init-db`, `run` y `pytest` (no solo el registro). Viola SPEC §7 ("instalación en menos de 5 minutos") en esa plataforma. El implementador lo anotó como duda pero no lo resolvió.
Recomendación: agregar a `requirements.txt` la línea `tzdata; sys_platform == "win32"` con una entrada nueva en DECISIONS.md (D-012: dependencia condicional, solo Windows, sin código nuevo; alternativa descartada: calcular el offset a mano). Verificar la instalación en Windows; mientras no se decida, documentar en el README que en Windows se necesita `pip install tzdata`. Subsidiario: crear el `ZoneInfo` dentro de la función (no al importar) para que un fallo no impida `init-db`.

**2. Falta `SameSite` y `Secure` en la cookie de sesión; además no se rota la sesión (app/__init__.py, app/seguridad.py:25-30).**
Hoy la cookie solo guarda el token CSRF, así que el riesgo es bajo, pero en T-04 guardará la identidad. `SameSite=None` (sin atributo) deja a CSRF como única defensa; la defensa en profundidad es barata.
Recomendación (proponer en T-04, antes de guardar `user_id`): `SESSION_COOKIE_SAMESITE="Lax"`; en T-04, al iniciar sesión hacer `session.clear()` y que el token se regenere (hoy `generar_token` conserva el token anterior, y tras el registro tampoco rota: confirmado, mismo token antes y después). Esto evita la fijación de sesión. Hacer lo mismo al cerrar sesión. `SESSION_COOKIE_SECURE=True` cuando no sea debug (variable de entorno o `not DEBUG`), en T-14 junto con el backlog de seguridad. Mantener en la sesión solo el `id` del usuario, nunca el rol ni datos personales (la cookie es legible por el cliente).

**3. Normalización del correo insuficiente frente a variantes Unicode (app/auth.py:61 y 71; D-010).**
`strip().lower()` cubre mayúsculas ASCII y espacios Unicode en los extremos, y la regex rechaza espacios (incluido NBSP) en el interior. Pero se aceptan como cuentas distintas: `ａna@example.cl` (ancho completo), `ana@examplе.cl` (e cirílica), `ß@example.cl` y `ss@example.cl` (casefold los igualaría), y `ana3@example.cl​` (carácter de ancho cero final, invisible; no se elimina con `strip`). Esto permite cuentas suplantadas o duplicados invisibles y complicará el login de T-04 (quien escriba el correo normal no coincidirá con el guardado). La UNIQUE de SQLite es sensible a mayúsculas (`BINARY`), así que la unicidad depende solo de esta normalización en la capa de aplicación: cualquier otra vía de inserción (el futuro `create-professional`) debe usar la misma función.
Recomendación: extraer una función `normalizar_email()` reutilizable (T-04 la necesita igual para el login) que aplique `unicodedata.normalize("NFKC", ...)`, `casefold()` y rechace caracteres de categoría `C*`/`Z*` (control, formato y espacios); y que `create-professional` la use. Opcional, para decisión humana en T-02c: `email TEXT NOT NULL UNIQUE COLLATE NOCASE` como segunda barrera.

**4. Sin `MAX_CONTENT_LENGTH`: el límite de 128 caracteres de la contraseña no protege el cuerpo (app/__init__.py:15-21; D-010).**
El límite de 128 acota el costo del hash, pero se valida después de que Flask y `verificar_csrf` ya parsearon el cuerpo. Flask 3.1 limita campos de formulario a 500 kB (`MAX_FORM_MEMORY_SIZE`) y a 1 000 partes, pero archivos multipart y cuerpos de otros tipos no tienen tope; un multipart de 50 MB sin sesión a cualquier ruta se procesó (el archivo se escribe a un temporal). Ninguna defensa contra ello figura en D-010 ni en el backlog.
Recomendación: `app.config["MAX_CONTENT_LENGTH"] = 16 * 1024` (basta para el formulario) en `create_app`, con prueba de que un POST mayor da 413; registrarlo en DECISIONS.md. Además, `/registro` no tiene limitación de frecuencia y cada POST válido cuesta ~0,12 s de CPU y 32 MiB de memoria por el scrypt: añadir al backlog de T-14 un límite de intentos por IP/correo.

### Bajos

**5. Pruebas que no detectarían mutaciones de seguridad (tests/test_seguridad.py, tests/test_registro.py).**
Mutaciones que dejan las 62 en verde: (a) CSRF solo para POST: ninguna prueba envía PUT/PATCH/DELETE sin token; (b) `|safe` en `value="{{ email }}"` de registro.html: el único escape de XSS se prueba con `nombre`, y el correo `"malo"` no contiene HTML; (c) hash débil (`pbkdf2:sha256:1`): solo se prueba que no sea texto plano y que `check_password_hash` valide; (d) `==` en vez de `compare_digest` (no verificable por comportamiento, aceptable). Además `test_correo_duplicado_lo_detecta_la_restriccion_unique` afirma en su docstring que no hay consulta previa, pero un `SELECT` previo también lo haría pasar; el nombre promete más de lo que verifica. Las pruebas no dependen del entorno ni del orden (fixture `entorno_limpio` en test_config y `TESTING=True`); comprobado con `SECRET_KEY=abc` y `FLASK_DEBUG=1`.
Recomendación: parametrizar una prueba con PUT/PATCH/DELETE sobre una ruta añadida en la prueba; probar el escape del correo con `"><script>x</script>@e.cl` (rechazado por la regex pero reimpreso en `value`) y `"onfocus="x`; asegurar `startswith("scrypt:")` o `password_hash.split(":")[0] in {"scrypt","pbkdf2"}` con iteraciones mínimas; renombrar o ajustar el docstring de la prueba del duplicado.

**6. El error 400 de CSRF es la página genérica de Werkzeug (app/seguridad.py:40).**
`abort(400, description=...)` devuelve HTML con `<html lang=en>`, título "400 Bad Request" y encabezado en inglés, sin enlace para volver ni estilo; el mensaje en español queda en un párrafo. Es usable pero incoherente con SPEC §6 ("amigable") y con `lang="es-CL"`.
Recomendación: `@app.errorhandler(400)` que renderice una plantilla `error.html` (extiende `base.html`) con el mensaje y un enlace a "Volver al inicio"; encajaría en T-13.

**7. Los POST a rutas inexistentes o con método no permitido devuelven 400, no 404/405 (app/seguridad.py:37-41).**
Efecto de que el CSRF corra en `before_request` antes del enrutamiento; es seguro (no filtra rutas) pero puede desconcertar al depurar. Aceptable; sugerir una línea en D-009 que lo documente.

**8. Mensaje de duplicado y enumeración (app/auth.py:16-19, D-010).**
El texto "Si ya tienes una cuenta..." confirma casi explícitamente que el correo existe, y sin verificación por correo no hay forma de evitarlo sin cambiar el flujo; el tiempo de respuesta es igual para nuevo y duplicado (el hash se calcula antes del INSERT, bien). Está aceptado y documentado en D-010; para v1 vale. Dejar anotado para T-14: el login (T-04) debe dar un mensaje único para "correo o contraseña incorrectos" para no sumar un segundo canal.

**9. `len(email) > EMAIL_MAX or not PATRON_EMAIL.match(email)` y la restricción de 100 caracteres del nombre se cuentan en caracteres, no en bytes (app/auth.py:31-36).**
Inocuo para SQLite y el hash (scrypt no depende de la longitud); mencionado solo porque el criterio "128 caracteres" se cumple con hasta 512 bytes UTF-8. Ningún cambio necesario.

**10. Cambio de proceso: la afirmación "las pruebas de mutación del implementador" no se pudo reproducir exactamente (PROGRESS.md, línea de verificación de T-03).**
No contiene afirmaciones falsas: las cinco mutaciones citadas (sin `before_request` CSRF, rol desde el formulario, sin hash, sin `IntegrityError`, `|safe` en el nombre) se reprodujeron o son consistentes con lo observado (fallos de 1 a 4 pruebas, sin falsos verdes). Lo no comprobado se limita a los recuentos exactos de pruebas fallidas por mutación. La nota sobre `tzdata` se declaró honestamente como duda, ver hallazgo 1.

## Sin hallazgos

- **SQL:** el único `INSERT` de `app/auth.py` está parametrizado (`?`); no hay concatenación ni f-strings en SQL.
- **XSS/autoescape:** `registro.html`, `base.html` (flash) e `inicio.html` usan `{{ }}` con autoescape (plantillas `.html`); no hay `|safe`, `Markup` ni `autoescape false` en `app/`. Los mensajes flash son constantes (no incluyen datos del usuario).
- **Rol:** fijado en el literal SQL `'paciente'`; el formulario, cabeceras y JSON no intervienen (prueba y mutación lo confirman). No existe ruta para crear profesionales (D-004).
- **Contraseña:** nunca se registra, se pasa a `flash` ni se vuelve a mostrar (el `input` de contraseña no lleva `value`; se prueba). No se hace `app.logger` de formularios.
- **Orden D-008 → CSRF:** `_preparar_secret_key` precede a `seguridad.init_app` en `create_app`; sin clave el error es el de la clave.

## Propuesta para ARCHITECTURE.md (solo el humano la aplica)

En el árbol de carpetas, tras `auth.py`:

```
│   ├── seguridad.py       # protección CSRF global (token en sesión, before_request)
```

y en la tabla de módulos:

| `seguridad.py` | Generar y verificar el token CSRF de todo POST/PUT/PATCH/DELETE | Lógica de negocio ni autenticación |

También convendría que la fila de `auth.py` aclare "registro de pacientes (T-03); login y roles (T-04)".
