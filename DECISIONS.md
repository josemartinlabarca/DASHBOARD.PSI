# DECISIONS — registro de decisiones

Formato: una entrada corta por decisión. Los agentes agregan aquí cualquier
decisión técnica que no esté ya cubierta, en lugar de tomarla en silencio.

## D-001 — Flask + SQLite + Jinja2
- **Fecha:** 2026-10-07
- **Decisión:** Usar Flask, SQLite y plantillas del lado del servidor.
- **Porqué:** Mínimas dependencias, un solo archivo de base de datos, nada que
  instalar aparte de Python. Ideal para aprender el flujo con agentes sin
  pelear con herramientas.
- **Alternativas descartadas:** Django (más pesado), React + API (dos proyectos
  en uno), Postgres (requiere servidor).

## D-002 — Notificaciones simuladas
- **Fecha:** 2026-10-07
- **Decisión:** Guardar notificaciones en base de datos y en `outbox.log`; sin correo real.
- **Porqué:** Evita credenciales y servicios externos; el comportamiento se
  puede probar de forma determinista.

## D-003 — Reserva atómica con un solo UPDATE
- **Fecha:** 2026-10-07
- **Decisión:** Reservar con `UPDATE ... WHERE estado='libre'` y revisar `rowcount`.
- **Porqué:** Garantiza que no haya doble reserva sin lógica de bloqueo.

## D-004 — Un solo profesional en v1
- **Fecha:** 2026-10-07
- **Decisión:** El profesional se crea por CLI; no hay registro público de profesionales.
- **Porqué:** Simplifica permisos y evita decidir un flujo de verificación.

## D-005 — Versión de pytest acotada en `requirements.txt`
- **Fecha:** 2026-10-07
- **Decisión:** Fijar `pytest>=9,<10` (versión probada: 9.1.1), igual que Flask (`>=3.1,<3.2`).
- **Porqué:** Una instalación nueva no debe traer un cambio mayor de pytest que rompa las pruebas sin aviso. Es una dependencia ya existente; solo se acota su rango (hallazgo 2 de la revisión de T-01).
- **Alternativas descartadas:** dejar `pytest` sin versión (no reproducible); fijar versión exacta con `==` (demasiado rígido para v1).

## D-006 — `init-db` no destructivo (`CREATE TABLE IF NOT EXISTS`)
- **Fecha:** 2026-10-07
- **Decisión:** `schema.sql` usa `CREATE TABLE IF NOT EXISTS` y `init-db` nunca borra datos; ejecutarlo sobre una base existente solo crea las tablas que falten. No modifica tablas ya existentes (los cambios de esquema futuros requerirán otra decisión).
- **Porqué:** Es lo más simple y seguro: evita perder citas o usuarios por ejecutarlo dos veces.
- **Alternativas descartadas:** `DROP TABLE` + recrear (destructivo, exigiría confirmación); sistema de migraciones (excesivo para v1).

## D-007 — Refuerzos del esquema de base de datos (T-02c) — **APROBADA por el humano (2026-10-08)**
- **Fecha:** 2026-10-08
- **Estado:** APROBADA el 2026-10-08 00:25 (hora de Chile): el humano aceptó las opciones A, B, C, D, E y F por mensaje en la sesión. Se implementa en T-02c, que además queda explícitamente autorizada a modificar `ARCHITECTURE.md` (opción F).
- **Origen:** revisiones de T-02 (hallazgos 1–6) y de T-03 (hallazgo 3).
- **Porqué:** hoy el esquema acepta datos incoherentes (una hora "reservada" sin paciente, una duración negativa, un tipo de notificación cualquiera). Las reglas de `SPEC.md` §4 dependen solo del código de la aplicación; el esquema puede ser la segunda línea de defensa.
- **Costo común a todas las opciones:** por D-006, `init-db` **no modifica tablas ya existentes**. Para aplicar un cambio de esquema hay que **borrar el archivo `agenda.db` y volver a ejecutar `init-db`**. Es aceptable mientras la base sea de práctica y no tenga datos reales; en producción haría falta un sistema de migraciones.

### Opciones (el humano marca cada una: SÍ / NO / CAMBIAR)

**A. Coherencia de la reserva en `horas`** — Recomendación: **SÍ** (protege la regla §4.1)
```sql
CHECK (
  (estado = 'libre'     AND paciente_id IS NULL     AND reservada_en IS NULL) OR
  (estado = 'reservada' AND paciente_id IS NOT NULL AND reservada_en IS NOT NULL)
)
```
Impide una hora "reservada" sin paciente o una "libre" con paciente. Obliga a que cancelar limpie `paciente_id` y `reservada_en` (ya lo dice `ARCHITECTURE.md`).
- [x] SÍ   - [ ] NO   - [ ] CAMBIAR

**B. Valores válidos de `notificaciones.tipo`** — Recomendación: **SÍ**
```sql
CHECK (tipo IN ('confirmacion', 'recordatorio', 'cancelacion'))
```
Costo: un tipo nuevo en el futuro exigirá cambiar el esquema.
- [x] SÍ   - [ ] NO   - [ ] CAMBIAR

**C. Valores de dominio** — Recomendación: **SÍ**
```sql
horas.duracion_min          CHECK (duracion_min > 0)
horas.recordatorio_enviado  CHECK (recordatorio_enviado IN (0, 1))
notificaciones.leida        CHECK (leida IN (0, 1))
```
- [x] SÍ   - [ ] NO   - [ ] CAMBIAR

**D. No repetir el inicio de una hora del mismo profesional** — Recomendación: **SÍ**
```sql
UNIQUE (profesional_id, inicio)
```
Impide dos horas idénticas. **No** impide el solape parcial (10:00–10:50 y 10:30–11:20), que sigue controlando la aplicación en T-05 (regla §4.3). Con un único profesional (D-004), esto además hace innecesario un índice propio para la regla §4.5.
- [x] SÍ   - [ ] NO   - [ ] CAMBIAR

**E. Correo sin distinguir mayúsculas en `usuarios.email`** — Recomendación: **SÍ** (defensa en profundidad)
```sql
email TEXT NOT NULL UNIQUE COLLATE NOCASE
```
Hoy la unicidad depende solo de `normalizar_email()` (T-03b). Limitación: `NOCASE` de SQLite solo cubre letras ASCII; no sustituye a la normalización Unicode, la complementa.
- [x] SÍ   - [ ] NO   - [ ] CAMBIAR

**F. Actualizar `ARCHITECTURE.md`** (autorización de edición) — Recomendación: **SÍ**
Autorizas a que se modifique `ARCHITECTURE.md` (que `CLAUDE.md` reserva al humano) para: (1) reflejar en el "Modelo de datos" las opciones A–E aprobadas; (2) añadir el módulo ya existente `seguridad.py` al árbol (`# protección CSRF global (token en sesión, before_request)`) y su fila en la tabla de módulos (responsabilidad: token CSRF y verificación; no debe hacer: reglas de negocio).
- [x] SÍ   - [ ] NO

### Resolución
- **Aprobada por:** el humano (usuario de la sesión), mensaje de las 00:25 del 2026-10-08: "a acepto, b acepto, c acepto, d acepto, e acepto, f acepto".
- **Resultado:** A, B, C, D, E y F aprobadas sin cambios.
- T-02c queda desbloqueada y es la siguiente tarea de esquema; debe ejecutarse **antes de T-04** (el login consultará `usuarios.email`, que cambia por la opción E) y en todo caso antes de T-05.
- **Implementada:** T-02c, 2026-10-08 00:50

## D-008 — `SECRET_KEY` se exige al atender peticiones, no al crear la app
- **Fecha:** 2026-10-08
- **Decisión:** `create_app` ya no lanza error por falta de `SECRET_KEY`. Si la clave falta, está vacía o es solo espacios (se decide con `strip()`, sin modificar una clave válida) y no hay `TESTING`/`DEBUG`, se registra un `before_request` que lanza `RuntimeError` con el mensaje claro; con `TESTING`/`DEBUG` se usa el valor de desarrollo. Toda petición sin clave fuera de debug responde 500 y el log muestra el mensaje.
- **Porqué:** La clave solo hace falta para firmar sesiones y CSRF, es decir, al servir peticiones; los comandos CLI (`init-db` y los futuros `create-professional`, `send-reminders`) crean la app pero no atienden peticiones, así que heredan la regla sin trabajo extra. `before_request` vive en la app, no en `flask run`: gunicorn u otro servidor WSGI también pasa por él, de modo que una app sin clave fuera de debug/testing nunca atiende una petición (se ejecuta antes de cualquier vista, también 404 y estáticos). No depende de `sys.argv`. Costo aceptado: con `flask run` sin clave el servidor arranca y falla en cada petición en vez de abortar al inicio.
- **Alternativas descartadas:** detectar el comando por `sys.argv` (frágil, no cubre WSGI); validar solo en `flask run` (no protege gunicorn); validar al primer request (más estado y no cubre todos los casos que `before_request`); una fábrica separada para la CLI (duplica configuración).

## D-009 — CSRF propio y centralizado en `app/seguridad.py` (sin dependencias)
- **Fecha:** 2026-10-08
- **Decisión:** Token aleatorio (`secrets.token_hex(32)`) guardado en la sesión firmada de Flask; las plantillas lo obtienen con `{{ csrf_token() }}` (global de Jinja) y lo envían en el campo `csrf_token` (o en la cabecera `X-CSRFToken`). Un `before_request` verifica con `hmac.compare_digest` en todo método que no sea GET/HEAD/OPTIONS/TRACE y responde 400 con un mensaje claro si falta o no coincide. Se registra después del `before_request` de D-008, así que sin `SECRET_KEY` el error sigue siendo el de la clave (hay prueba).
- **Porqué:** Son unas 40 líneas, sin dependencia nueva, y al ser global los formularios futuros (login, reservas, horas) no pueden olvidar la verificación. Se crea el archivo `app/seguridad.py` (no previsto en ARCHITECTURE.md) para que sea reutilizable y no quede dentro de `auth.py`.
- **Consecuencia:** un POST a una ruta inexistente responde 400 y no 404/405, porque el CSRF (`before_request`) corre antes del enrutamiento; un GET a la misma ruta sí responde 404. Hay prueba.
- **Alternativas descartadas:** Flask-WTF (dependencia nueva con versión fija; trae formularios y validadores que no usamos); verificar en cada vista (fácil de olvidar).

## D-010 — Validaciones y mensajes del registro
- **Fecha:** 2026-10-08
- **Decisión:** Nombre recortado, 1 a 100 caracteres. Correo normalizado con `normalizar_email()` (D-013, política de caracteres D-015: NFKC, recorte, `casefold`; rechaza espacios internos, categorías `C*` y marcas `Mn`/`Mc`/`Me`), máximo 254 caracteres, con formato `algo@dominio.tld` (regex simple `^[^@\s]+@[^@\s]+\.[^@\s]+$`; sin verificación por correo, fuera de alcance v1). Contraseña de 8 a 128 caracteres, sin recortar (los espacios cuentan). Rol fijado en el servidor a `paciente`; el formulario nunca se lee para el rol. Los errores de formulario responden 200 con el formulario y mensajes junto a cada campo, conservando nombre y correo, nunca la contraseña. `creado_en` con `datetime.now(zona_chile()).isoformat(timespec="seconds")`, donde `zona_chile()` crea la `ZoneInfo("America/Santiago")` al usarla (D-012).
- **Porqué:** Límites suficientes para personas reales y que acotan el costo del hash (máximo 128). El correo se normaliza antes de guardar para que la restricción UNIQUE cubra variantes de mayúsculas, espacios y formas Unicode equivalentes (ver D-013 y D-015).
- **Correo duplicado:** no hay consulta previa; se captura `sqlite3.IntegrityError` del INSERT (sin condición de carrera) y solo se trata como duplicado la violación de `UNIQUE` sobre `usuarios.email` (código `SQLITE_CONSTRAINT_UNIQUE` y `usuarios.email` en el mensaje); cualquier otra `IntegrityError` se relanza y da error interno 500 (T-03c). El mensaje es "No pudimos registrarte con ese correo. Si ya tienes una cuenta, inicia sesión; si no, prueba con otro correo.": no afirma explícitamente que exista, aunque sin verificación por correo es inevitable que quien lo prueba lo deduzca. Se acepta para v1.
- **Alternativas descartadas:** validar el correo con una librería (dependencia); exigir confirmación de contraseña (SPEC no lo pide); 409 para el duplicado (se prefiere el mismo flujo de formulario).

## D-011 — `pytest.ini` con `pythonpath = .` y `testpaths = tests`
- **Fecha:** 2026-10-08
- **Decisión:** Mantener `pytest.ini` (agregado en T-02d) con `pythonpath = .` y `testpaths = tests`.
- **Porqué:** Sin `pythonpath = .`, el comando literal `pytest` del README falla en un venv limpio con `ModuleNotFoundError: app`, porque `app` no está instalado como paquete. `testpaths = tests` evita que pytest recorra otras carpetas (venv, etc.). Registra el ítem de backlog "T-02d #4".
- **Alternativas descartadas:** `pip install -e .` con `pyproject.toml` (más archivos y empaquetado innecesario en v1); `conftest.py` en la raíz (más implícito).

## D-012 — `tzdata` siempre instalado y zona horaria creada al usarla
- **Fecha:** 2026-10-08
- **Decisión:** `requirements.txt` agrega `tzdata` **sin marcador de plataforma** (dependencia nueva, sin tope de versión: son solo datos de zonas y se actualizan con las reglas horarias). Antes (T-03b) llevaba `; sys_platform == "win32"`; T-03c lo quitó. El `ZoneInfo("America/Santiago")` ya no se crea al importar `app/auth.py`, sino la primera vez que se usa (`zona_chile()`, con `functools.lru_cache`). Si faltan los datos, lanza `RuntimeError` con un mensaje que nombra `tzdata` y `requirements.txt`; el registro responde 500 sin crear el usuario.
- **Porqué:** Windows no trae base de datos de zonas horarias; sin el paquete, `ZoneInfo(...)` fallaba al importar y rompía hasta `init-db` y `create_app()`. El marcador `win32` suponía que Linux siempre la trae, pero Alpine, imágenes distroless y otros Linux mínimos no tienen `/usr/share/zoneinfo`: allí el primer registro habría fallado. Instalarlo en todas partes cuesta unos cientos de kB y quita la suposición; si el sistema tiene zonas, `zoneinfo` las usa primero y el paquete queda de respaldo. Pruebas: `requirements.txt` debe listar `tzdata` sin marcador; con `tzdata` y `PYTHONTZPATH` vacío funciona; sin ninguno de los dos el registro responde 500 y no crea el usuario.
- **Alternativas descartadas:** mantener el marcador `win32` (descartado en T-03c por lo dicho); usar un `timezone(timedelta(hours=-3))` fijo (incorrecto: Chile cambia de hora); atrapar el error y guardar sin zona (datos ambiguos).

## D-013 — `normalizar_email()` en `app/correo.py`
- **Fecha:** 2026-10-08
- **Decisión:** Función pura `normalizar_email(valor)` en el archivo nuevo `app/correo.py`. Pasos: NFKC, recorte de espacios en los bordes, `casefold`, NFKC otra vez (`casefold` puede dejar texto sin normalizar). Lanza `ValueError` si queda algún espacio interno (`isspace()`, que incluye U+2028, U+2029 y U+1680), si el valor no es `str` (contrato: nunca `TypeError`) o si algún carácter, ya normalizado, es de una categoría que D-015 prohíbe: toda `C*` (Cc control, Cf formato/invisible como ancho cero, guion blando, BOM, marcas bidi e inversión de texto, Cs sustitutos, Co uso privado, Cn sin asignar) y las marcas `Mn`, `Mc` y `Me`. Hasta T-03b solo se rechazaban Cc y Cf. El `ñ` precompuesto y el descompuesto (`n` + U+0303) dan el mismo resultado porque NFKC compone antes de revisar. Los Cn dependen de la versión de `unicodedata` de Python (hoy Unicode 15.1 en Python 3.13): se juzgan por categoría y no por lista de puntos de código, de modo que un punto que esa versión no conoce se rechaza y uno que conoce se juzga por su categoría real. Cadena vacía devuelve `""` (el «falta el correo» lo valida el formulario). El registro la usa y, si lanza, muestra el mensaje de correo inválido conservando lo escrito. Se mantienen sin cambio el límite de 254 y la regex de D-010, aplicados al resultado.
- **Archivo nuevo:** `app/correo.py` no figura en `ARCHITECTURE.md` (que no puedo editar): se crea para que el login (T-04) y `create-professional` usen exactamente la misma normalización sin importar `auth.py`.
- **`ß` y `ss`:** colisionan a propósito (`casefold("ß") == "ss"`); `straße@x.cl` y `strasse@x.cl` son el mismo correo. Es el comportamiento estándar de comparación sin distinguir mayúsculas y evita dos cuentas «iguales». Costo: dos correos que existen por separado (muy improbable) no pueden coexistir. Lo fijan pruebas.
- **Plegados y casos especiales (fijados por pruebas):** `casefold` lleva `ς` (sigma final) a `σ`; NFKC lleva `ſ` (s larga) a `s` y `K` (signo kelvin, U+212A) a `k`. `İ` (U+0130) se minusculiza a `i` + U+0307, un combinante `Mn`: se **rechaza** (con la política de D-015). `ı` (i sin punto, U+0131) se conserva y **no** es igual a `i`: son correos distintos. Las dos pasadas de NFKC son necesarias: sin la primera cambia el resultado (p. ej. `ϒ` U+03D2 queda `Υ` en vez de `υ` y la función deja de ser idempotente); sin la segunda, `ǰ` (U+01F0) deja una `j` con un combinante.
- **Riesgo aceptado:** una «е» cirílica (U+0435) visualmente idéntica a la «e» latina NO se une con NFKC y da un correo distinto. No se usa una lista de homoglifos: es larga, incompleta y mantenerla excede el alcance. Sin verificación por correo en v1, quien lo explote solo consigue otra cuenta con ese correo distinto (que no recibirá nada); una prueba documenta que no se resuelve.
- **No cubierto por D-015 opción 2 (aceptado, ver PROGRESS):** el relleno hangul (U+3164, U+115F), el braille en blanco (U+2800) y U+FFFD no son categorías `C*` ni `M*`, así que siguen pasando.
- **Alternativas descartadas:** devolver una tupla (valor, error) en vez de lanzar (más torpe para quien la llame); `lower()` (no cubre `ß`); permitir los caracteres invisibles y solo recortarlos (permiten correos indistinguibles a la vista); la regex de D-010 como única defensa (`\s` no cubre ancho cero).

## D-014 — `MAX_CONTENT_LENGTH` de 16 kB
- **Fecha:** 2026-10-08
- **Decisión:** La fábrica fija `MAX_CONTENT_LENGTH = 16 * 1024` bytes (constante `TAMANO_MAX_PETICION`); `test_config` puede sobrescribirlo. Una petición mayor responde 413 y no llega a la vista.
- **Porqué:** Los formularios son cortos (nombre ≤ 100, correo ≤ 254, contraseña ≤ 128 caracteres); sin límite, un POST enorme se lee entero en memoria. En Flask el 413 se produce al leer el cuerpo, es decir al acceder a `request.form`; eso ocurre ya en el `before_request` del CSRF (D-009), de modo que un cuerpo grande da 413 también sin token (antes que el 400). El límite es **global**: no se puede subir solo en una ruta, porque el `before_request` del CSRF lee el cuerpo antes de que corra la vista y da 413 igualmente. Si una función futura necesita subir archivos habrá que (a) subir `MAX_CONTENT_LENGTH` en la configuración global, o (b) hacer una excepción explícita en el `before_request` (p. ej. no leer `request.form` para esa ruta y validar el token de otro modo, o fijar `request.max_content_length` antes de acceder al cuerpo); cualquiera de las dos requiere una decisión nueva.
- **Pendiente:** el cuerpo del 413 por defecto de Werkzeug es en inglés; se anotó para T-13 (mensajes en español), no se cambia ahora.
- **Alternativas descartadas:** límite solo en el proxy inverso (la app no debe depender de él); 64 kB o más (sin necesidad).

## D-019 — Hash de contraseña rápido en la suite de pruebas (T-03c)
- **Fecha:** 2026-10-08
- **Decisión:** `tests/conftest.py` (archivo existente, ampliado) define una fixture `autouse` que sustituye `generate_password_hash` (en `werkzeug.security` y en `app.auth`) por una versión que, cuando se pide el método por defecto `scrypt`, usa `scrypt:1024:8:1` en lugar de `scrypt:32768:8:1` (sigue siendo scrypt con sal propia; solo baja el costo). Las pruebas marcadas `@pytest.mark.hash_real` no la usan y verifican el hash real. El marcador se registra en `pytest.ini` (archivo de D-011) para que `pytest` no avise de marcador desconocido. Un módulo nuevo que importe `generate_password_hash` por su cuenta (T-04, `create-professional`) debe añadirse a la fixture.
- **Porqué:** cada registro de prueba pagaba ~0,13 a 0,4 s de scrypt real; `tests/test_registro.py` pasó de 6,3 s a 2,8 s (con 12 pruebas más). No debilita lo que se prueba de seguridad: `check_password_hash` sigue verificando contra el hash guardado, hay sal distinta por usuario, el hash no contiene la contraseña, y las pruebas de método y costo del hash real están marcadas `hash_real` (más una guarda que falla si el marcador deja de desactivar la fixture).
- **Alternativas descartadas:** bajar el costo en la aplicación con una variable de configuración (cambia código de producción por las pruebas); `pbkdf2:sha256:1` (cambia el algoritmo, y D-010 exige scrypt); `scrypt:16:1:1` (OpenSSL rechaza por memoria).

## D-015 — Política de caracteres permitidos en el correo (T-03c) — **APROBADA por el humano (2026-10-08 00:38): opción 2**
- **Fecha:** 2026-10-08
- **Estado:** APROBADA el 2026-10-08 00:38 (hora de Chile): el humano eligió la **opción 2**. Origen: hallazgo 2 de la revisión de T-03b. Se implementa en el punto 2 de T-03c.
- **Problema:** `normalizar_email` (D-013) solo rechaza espacios y las categorías Unicode Cc y Cf. Siguen pasando caracteres invisibles o engañosos (selectores de variación, relleno hangul, braille en blanco, combinantes sueltos, uso privado) y los homoglifos de otros alfabetos (una «е» cirílica idéntica a la «e» latina), que D-013 aceptó como riesgo.
- **Efecto en el usuario:** el riesgo real es de **suplantación visual** (dos cuentas que se ven iguales) y de cuentas que el usuario no puede reproducir al escribir.

### Opciones
- **1. Solo ASCII (recomendada).** Tras NFKC y `casefold`, todo carácter debe ser ASCII imprimible. Elimina de raíz invisibles, combinantes, uso privado y **también los homoglifos**, y vuelve irrelevantes las diferencias entre versiones de Python. Costo: rechaza correos con caracteres no ASCII en el nombre o el dominio (por ejemplo `señor@…`), muy poco frecuentes y que la mayoría de los proveedores no emiten. Mensaje al usuario: "Usa un correo con letras sin tildes ni caracteres especiales."
- **2. Rechazar categorías Unicode de riesgo.** Rechazar todas las categorías `C*` (control, formato, uso privado, sin asignar, sustitutos) y las marcas `Mn/Mc/Me`. Permite `señor@…` si viene precompuesta, pero **no resuelve los homoglifos** y mantiene cierta dependencia de la versión de Python.
- **3. Mantener como está.** Sin cambios; el riesgo queda aceptado en D-013 y documentado. Solo se añaden las pruebas del punto 1 de T-03c.

### Resolución
- **Elegida:** opción 2 — rechazar todas las categorías `C*` (Cc, Cf, Co, Cn, Cs) y las marcas `Mn`, `Mc` y `Me`.
- **Aprobada por:** el humano (usuario de la sesión), respuesta a la pregunta de D-015.   **Fecha:** 2026-10-08 00:38
- **Se recomendaba la opción 1 (solo ASCII).** El humano prefirió la opción 2 para admitir correos con tildes o `ñ` precompuestas.
- **Riesgo aceptado conscientemente:** los homoglifos de otros alfabetos (p. ej. la «е» cirílica idéntica a la «e» latina) **siguen siendo aceptados**: la opción 2 no los resuelve. Se mantiene el riesgo ya aceptado en D-013 y debe revisarse en T-14 (revisión final de seguridad).
- **Consecuencias para la implementación:** las marcas combinantes se rechazan, así que el correo debe llegar **precompuesto** (NFKC ya lo compone; p. ej. `ñ` U+00F1). Las pruebas deben cubrir que `señor@x.cl` precompuesto y descompuesto (`n` + U+0303, que NFKC compone) se normalizan igual y se aceptan, que un combinante suelto se rechaza, y que los puntos de uso privado, no asignados y sustitutos se rechazan. Los Cn dependen de la versión de Python: documentarlo y fijar la prueba a categorías, no a una lista de puntos de código.

## D-016 — Eliminar una hora que llegó a reservarse (T-05) — **APROBADA por el humano (2026-10-08 01:04)**
- **Fecha:** 2026-10-08
- **Estado:** APROBADA el 2026-10-08 01:04 (hora de Chile). Origen: hallazgo 1 de la revisión de T-02c (reproducido por el orquestador y el revisor).
- **Problema:** una hora que se reservó y luego se canceló vuelve a `libre`, pero conserva notificaciones (confirmación y cancelación) con `hora_id` apuntando a ella. Con `PRAGMA foreign_keys = ON` y sin `ON DELETE`, `DELETE FROM horas ...` falla con `FOREIGN KEY constraint failed`. Eso contradice US-5 ("elimino una hora disponible que aún no esté reservada"), porque una hora cancelada está disponible.

### Opciones
- **1. `ON DELETE SET NULL` en `notificaciones.hora_id` (recomendada).** La garantía vive en la base de datos: ninguna ruta de borrado, presente o futura, puede olvidarla. La notificación conserva su mensaje, solo pierde el enlace a la hora. Costo: **cambia el esquema aprobado en D-007** (hay que editar `schema.sql`, `ARCHITECTURE.md` y `agenda.db` de práctica se borra y recrea) y requiere una prueba nueva.
- **2. La aplicación limpia antes de borrar.** T-05 ejecuta `UPDATE notificaciones SET hora_id = NULL WHERE hora_id = ?` y luego el `DELETE`, en la misma transacción. No cambia el esquema. Riesgo: cualquier otra ruta de borrado futura debe acordarse de hacerlo.
- **3. No permitir eliminar horas con historial.** Solo se eliminan las que nunca se reservaron; el profesional recibe un mensaje explicativo. Es lo más simple, pero **restringe US-5** en el caso de una hora cancelada.

### Resolución
- **Elegida:** opción 1 — `ON DELETE SET NULL` en `notificaciones.hora_id`.
- **Aprobada por:** el humano (usuario de la sesión), respuesta a la pregunta de la sesión.   **Fecha:** 2026-10-08 01:04
- **Se recomendaba esta opción.**
- **Implementación:** T-02f. Cambia el esquema aprobado en D-007: `notificaciones.hora_id INTEGER REFERENCES horas (id) ON DELETE SET NULL`. Autorizada a editar `schema.sql` y `ARCHITECTURE.md` (modelo de datos) solo para esto. Consecuencia ya conocida (D-006): hay que borrar `agenda.db` y volver a ejecutar `init-db`. Prueba requerida: reservar → cancelar → eliminar la hora funciona y las notificaciones quedan con `hora_id` NULL y su mensaje intacto.
- **Implementada:** T-02f, 2026-10-08 01:09


## D-017 — Formato canónico del campo `horas.inicio` (T-05) — **APROBADA por el humano (2026-10-08 01:04)**
- **Fecha:** 2026-10-08
- **Estado:** APROBADA el 2026-10-08 01:04 (hora de Chile). Origen: hallazgo 3 de la revisión de T-02c (reproducido por el orquestador y el revisor).
- **Problema:** `UNIQUE (profesional_id, inicio)` compara **texto**. `2026-12-01T10:00`, `2026-12-01 10:00`, `2026-12-01T10:00:00`, `...-03:00` y `...-04:00` son el mismo instante para una persona y cinco valores distintos para SQLite (aceptados 5 de 5). La regla 3 de SPEC (no solapar) y D-007 D quedarían eludibles. ARCHITECTURE.md solo dice "ISO 8601, hora local de Chile".
- **Limitación conocida (cualquier opción local):** Chile tiene horario de verano, así que una hora local puede ser ambigua (cuando se retrasa el reloj) o no existir (cuando se adelanta). Hay que revisarlo en T-10 (recordatorio de 24 h) y T-14.

### Opciones
- **1. Texto canónico `YYYY-MM-DDTHH:MM:SS`, hora local de Chile, sin desfase, validado solo en la aplicación.** Simple; ordena bien como texto. Riesgo: una ruta que no valide puede insertar otro formato.
- **2. Lo mismo que la opción 1, más un CHECK en el esquema (recomendada).** `CHECK (inicio GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]')` en `horas`. La base rechaza cualquier otro formato, así que la UNIQUE no se puede eludir. Costo: **cambia el esquema aprobado en D-007** (misma consecuencia que D-016, opción 1: editar `schema.sql` y `ARCHITECTURE.md`, recrear `agenda.db`). Nota: el CHECK valida la forma, no que la fecha exista (p. ej. mes 13); eso lo valida la aplicación.
- **3. UTC con sufijo `Z` (`YYYY-MM-DDTHH:MM:SSZ`).** Elimina la ambigüedad del horario de verano en el almacenamiento, pero contradice "hora local de Chile" de ARCHITECTURE.md y complica el resto (conversiones en cada pantalla y en el recordatorio).

### Resolución
- **Elegida:** opción 2 — formato canónico `YYYY-MM-DDTHH:MM:SS` (hora local de Chile, sin desfase) validado en la aplicación **y** con un `CHECK ... GLOB` en el esquema.
- **Aprobada por:** el humano (usuario de la sesión), respuesta a la pregunta de la sesión.   **Fecha:** 2026-10-08 01:04
- **Se recomendaba esta opción.**
- **Implementación:** T-02f (el CHECK en `horas.inicio` y su prueba) y T-05 (validación en la aplicación: la fecha debe existir, no ser pasada, y se guarda siempre en este formato). Cambia el esquema aprobado en D-007. Autorizada a editar `schema.sql` y `ARCHITECTURE.md` (modelo de datos) solo para esto. Consecuencia ya conocida (D-006): hay que borrar `agenda.db` y volver a ejecutar `init-db`. Pruebas requeridas: los 5 formatos del hallazgo de la revisión son rechazados por la base excepto el canónico; el canónico se acepta; un duplicado en formato canónico lo rechaza la UNIQUE. La limitación del horario de verano (hora ambigua o inexistente) sigue pendiente de revisar en T-10 y T-14.
- **Implementada:** T-02f, 2026-10-08 01:09


## D-018 — Cerrar el hueco del carácter nulo en `horas.inicio` (T-02g) — **APROBADA por el humano (2026-10-08 01:16)**
- **Fecha:** 2026-10-08
- **Estado:** APROBADA el 2026-10-08 01:16 (hora de Chile): el humano eligió la opción recomendada. Origen: hallazgo 1 de la revisión de T-02f (reproducido por el orquestador y confirmado por el revisor).
- **Problema:** el CHECK de D-017 usa `GLOB`, que trabaja sobre cadenas C: `2026-12-01T10:00:00` seguido de un NUL (`\x00`) y cualquier texto **pasa** el CHECK y es un valor distinto del canónico, de modo que también **elude la UNIQUE**. D-017 prometía que "la base rechaza cualquier otro formato". Con SQLite 3.45.1.
- **Decisión:** añadir `AND instr(inicio, char(0)) = 0` al CHECK de formato de `horas.inicio`, de modo que quede `CHECK (inicio GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]' AND instr(inicio, char(0)) = 0)`.
- **Porqué:** es la corrección mínima y legible; el orquestador probó 4 candidatos y el revisor confirmó que esta cierra el hueco (rechaza NUL al final, solo, al inicio y en medio, y acepta el canónico).
- **Alternativas descartadas:**
  - `CHECK (length(inicio) = 19)`: **no funciona**; `length()` sobre TEXT se detiene en el primer NUL (comprobado). Fue la sugerencia inicial del implementador, que la afirmó sin ejecutarla.
  - `length(CAST(inicio AS BLOB)) = 19`: funciona, pero fija la longitud y es menos obvio de leer.
  - No cambiar el esquema y confiar en la aplicación: descartada por el humano.
- **Implementación:** T-02g. Autorizada a modificar `app/schema.sql` y la línea `inicio` del "Modelo de datos" de `ARCHITECTURE.md` **solo** para esto. Consecuencia ya conocida (D-006): borrar `agenda.db` y volver a ejecutar `init-db`.
- **Implementada:** T-02g, 2026-10-08 01:21

## D-020 — Alcance de la política de caracteres del correo (PROPUESTA, pendiente del humano)
- **Fecha:** 2026-10-08
- **Estado:** PROPUESTA. No bloquea T-04. Origen: revisión de T-03c, R-01.
- **Problema:** D-015 (opción 2) rechaza las categorías `C*` y las marcas `Mn/Mc/Me`, pero aún se aceptan caracteres visualmente vacíos o engañosos que no pertenecen a esas categorías: relleno hangul (U+3164, U+115F), braille en blanco (U+2800), U+FFFD, U+FFFC, símbolos U+2400–U+2422, guiones y puntos medios no ASCII (U+2010, U+00B7). Permiten crear cuentas que se ven iguales a otras. No es un vector nuevo (D-013 ya aceptó los homoglifos cirílicos).
- **Opciones:**
  - **A.** Aceptar y documentar que es una clase de casos, no tres.
  - **B (recomendada).** Fuera de ASCII solo letras y números (categorías `L*` y `N*`) más una lista corta de rellenos; rechaza el resto.
  - **C.** Solo ASCII (opción 1 de D-015): la más simple, pero rechaza `señor@…`.
- **Implementación si se aprueba B o C:** tarea nueva pequeña (cambia `app/correo.py` y sus pruebas).

## D-021 — Login, roles y archivos nuevos de T-04
- **Fecha:** 2026-10-08
- **Decisión:** (1) `/login` responde **200** con el formulario y el mensaje único «Correo o contraseña incorrectos.» (mismo criterio que D-010); correo inexistente, contraseña errónea, correo con caracteres no permitidos (el `ValueError` de `normalizar_email` se atrapa), correo o contraseña demasiado largos y correo vacío dan exactamente la misma respuesta (el correo escrito se devuelve escapado, la contraseña nunca). `buscar_usuario_por_credenciales` ejecuta **siempre exactamente un** `check_password_hash`: contra el hash del usuario si existe o contra `hash_falso()` si no; una contraseña de más de 128 caracteres se verifica como cadena vacía (no se paga el costo de hashear texto largo) y se rechaza igual. `hash_falso()` se crea al usarlo (cache, como `zona_chile`) con el mismo `generate_password_hash` del registro, así que tiene el costo real de producción. (2) La sesión guarda **solo** `usuario_id`; el rol y el nombre se leen de la base en cada petición protegida (`usuario_actual()`), de modo que un cambio de rol o un usuario borrado surte efecto de inmediato; un id que no sea un entero positivo que quepa en SQLite se trata como sin sesión. `iniciar_sesion` y `cerrar_sesion` hacen `session.clear()` y crean un token CSRF nuevo (fijación de sesión). (3) **No hay parámetro `next`**: tras el login se redirige al panel del rol (`paciente.dashboard` / `profesional.dashboard`); sin sesión los decoradores redirigen a `/login` a secas (no hay open redirect posible). (4) Decoradores `login_requerido`, `solo_paciente`, `solo_profesional` (en `auth.py`, sobre una fábrica privada): sin sesión 302 a `/login`; rol incorrecto 403 con la plantilla en español `acceso_denegado.html` (no el texto de Werkzeug). `/logout` es solo POST (con CSRF por D-009) y exige sesión; sin ella redirige a `/login`. (5) `SESSION_COOKIE_SAMESITE="Lax"` y `SESSION_COOKIE_HTTPONLY=True` explícitos; `Secure` requiere HTTPS y queda para T-14 (documentado en README y en `app/__init__.py`). (6) `create-professional` está en `auth.py` y se registra en `create_app`; pide la contraseña con `click.prompt(hide_input=True, confirmation_prompt=True)` y **no** acepta `--password` (no queda en argv ni en el historial; límite: con stdin por tubería el texto de esa línea sí queda en el historial del intérprete, ver README). Usa `normalizar_email`, `validar_registro`, `es_correo_duplicado` y el nuevo `crear_usuario` (el INSERT del registro se movió ahí para tener un solo lugar que hashea). No imprime la contraseña. No limita a un solo profesional (D-004 lo dice en palabras, la tarea no pide el límite): ver «Bloqueos». (7) El aviso por falta de `SECRET_KEY` (backlog T-02d #2) se emite con `app.logger.warning` al crear la app **solo si se va a servir**: no hay contexto de click (gunicorn y similares) o el comando es `run`. `init-db`, `create-professional`, `routes`, etc. cargan la app dentro del grupo `flask` y no avisan. Es solo un aviso: la exigencia sigue siendo el `before_request` de D-008. (8) Campo de correo de login y registro: `type="text" inputmode="email" autocomplete="email"` (R-04).
- **Archivos nuevos no pedidos literalmente (regla 10):** `app/paciente.py` y `app/profesional.py` (previstos en `ARCHITECTURE.md`; solo el dashboard vacío que necesita el criterio de término de T-04); plantillas `paciente.html`, `profesional.html` (panel mínimo con saludo y botón de cerrar sesión) y `acceso_denegado.html` (el 403 en español); `tests/test_login.py`, `tests/test_roles.py`, `tests/test_crear_profesional.py`, `tests/test_hash_rapido.py`. `login.html` lo pide la tarea.
- **Fixture de hash (R-06, R-07):** `tests/conftest.py` importa todos los módulos de `app/` y parchea `generate_password_hash` en **todo** módulo `app.*` que lo tenga (no por nombre fijo); `tests/test_hash_rapido.py` falla si el hash rápido no está activo en esos módulos o si `pytest.ini` pierde `--strict-markers`, y comprueba por subproceso que un marcador mal escrito aborta la colección.
- **Porqué:** mensajes y tiempos iguales impiden enumerar cuentas; leer el rol de la base evita roles obsoletos en una cookie firmada de larga vida; sin `next` se elimina la clase de ataque; el aviso solo al servir evita ruido en los comandos de mantenimiento.
- **Alternativas descartadas:** 401 para el login fallido (rompe el flujo de formulario de D-010); guardar el rol en la sesión; un `next` validado contra una lista (más código y superficie, la tarea no lo pide); `--password` u `--password-file` en `create-professional`; un `errorhandler(403)` global (es trabajo de T-13); detectar el comando por `sys.argv`.

## Plantilla para nuevas decisiones

```
## D-00X — Título
- **Fecha:**
- **Decisión:**
- **Porqué:**
- **Alternativas descartadas:**
```
