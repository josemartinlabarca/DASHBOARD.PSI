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
- **Decisión:** Nombre recortado, 1 a 100 caracteres. Correo recortado y en minúsculas, máximo 254 caracteres, con formato `algo@dominio.tld` (regex simple `^[^@\s]+@[^@\s]+\.[^@\s]+$`; sin verificación por correo, fuera de alcance v1). Contraseña de 8 a 128 caracteres, sin recortar (los espacios cuentan). Rol fijado en el servidor a `paciente`; el formulario nunca se lee para el rol. Los errores de formulario responden 200 con el formulario y mensajes junto a cada campo, conservando nombre y correo, nunca la contraseña. `creado_en` con `datetime.now(ZoneInfo("America/Santiago")).isoformat(timespec="seconds")`.
- **Porqué:** Límites suficientes para personas reales y que acotan el costo del hash (máximo 128). El correo se normaliza antes de guardar para que la restricción UNIQUE cubra variantes de mayúsculas y espacios.
- **Correo duplicado:** no hay consulta previa; se captura `sqlite3.IntegrityError` del INSERT (sin condición de carrera). El mensaje es "No pudimos registrarte con ese correo. Si ya tienes una cuenta, inicia sesión; si no, prueba con otro correo.": no afirma explícitamente que exista, aunque sin verificación por correo es inevitable que quien lo prueba lo deduzca. Se acepta para v1.
- **Alternativas descartadas:** validar el correo con una librería (dependencia); exigir confirmación de contraseña (SPEC no lo pide); 409 para el duplicado (se prefiere el mismo flujo de formulario).

## D-011 — `pytest.ini` con `pythonpath = .` y `testpaths = tests`
- **Fecha:** 2026-10-08
- **Decisión:** Mantener `pytest.ini` (agregado en T-02d) con `pythonpath = .` y `testpaths = tests`.
- **Porqué:** Sin `pythonpath = .`, el comando literal `pytest` del README falla en un venv limpio con `ModuleNotFoundError: app`, porque `app` no está instalado como paquete. `testpaths = tests` evita que pytest recorra otras carpetas (venv, etc.). Registra el ítem de backlog "T-02d #4".
- **Alternativas descartadas:** `pip install -e .` con `pyproject.toml` (más archivos y empaquetado innecesario en v1); `conftest.py` en la raíz (más implícito).

## D-012 — `tzdata` para Windows y zona horaria creada al usarla
- **Fecha:** 2026-10-08
- **Decisión:** `requirements.txt` agrega `tzdata; sys_platform == "win32"` (dependencia nueva, sin tope de versión: son solo datos de zonas y se actualizan con las reglas horarias). El `ZoneInfo("America/Santiago")` ya no se crea al importar `app/auth.py`, sino la primera vez que se usa (`zona_chile()`, con `functools.lru_cache`). Si faltan los datos, lanza `RuntimeError` con un mensaje que nombra `tzdata` y `requirements.txt`; el registro responde 500 sin crear el usuario.
- **Porqué:** Windows no trae base de datos de zonas horarias; sin el paquete, `ZoneInfo(...)` fallaba al importar y rompía hasta `init-db` y `create_app()`. Linux y macOS usan la del sistema, por eso el marcador `sys_platform`. En este sistema (Linux) el paquete `tzdata` no está instalado y no hace falta: se usa `/usr/share/zoneinfo`.
- **Alternativas descartadas:** instalar `tzdata` en todas las plataformas (innecesario donde el sistema ya la trae); usar un `timezone(timedelta(hours=-3))` fijo (incorrecto: Chile cambia de hora); atrapar el error y guardar sin zona (datos ambiguos).

## D-013 — `normalizar_email()` en `app/correo.py`
- **Fecha:** 2026-10-08
- **Decisión:** Función pura `normalizar_email(valor)` en el archivo nuevo `app/correo.py`. Pasos: NFKC, recorte de espacios en los bordes, `casefold`, NFKC otra vez (`casefold` puede dejar texto sin normalizar). Lanza `ValueError` si queda algún espacio interno o un carácter de categoría Unicode Cc (control) o Cf (formato/invisible, p. ej. ancho cero, guion blando, BOM, inversión de texto). Cadena vacía devuelve `""` (el «falta el correo» lo valida el formulario). El registro la usa y, si lanza, muestra el mensaje de correo inválido conservando lo escrito. Se mantienen sin cambio el límite de 254 y la regex de D-010, aplicados al resultado.
- **Archivo nuevo:** `app/correo.py` no figura en `ARCHITECTURE.md` (que no puedo editar): se crea para que el login (T-04) y `create-professional` usen exactamente la misma normalización sin importar `auth.py`.
- **`ß` y `ss`:** colisionan a propósito (`casefold("ß") == "ss"`); `straße@x.cl` y `strasse@x.cl` son el mismo correo. Es el comportamiento estándar de comparación sin distinguir mayúsculas y evita dos cuentas «iguales». Costo: dos correos que existen por separado (muy improbable) no pueden coexistir. Lo fijan pruebas.
- **Riesgo aceptado:** una «е» cirílica (U+0435) visualmente idéntica a la «e» latina NO se une con NFKC y da un correo distinto. No se usa una lista de homoglifos: es larga, incompleta y mantenerla excede el alcance. Sin verificación por correo en v1, quien lo explote solo consigue otra cuenta con ese correo distinto (que no recibirá nada); una prueba documenta que no se resuelve.
- **Alternativas descartadas:** devolver una tupla (valor, error) en vez de lanzar (más torpe para quien la llame); `lower()` (no cubre `ß`); permitir los caracteres invisibles y solo recortarlos (permiten correos indistinguibles a la vista); la regex de D-010 como única defensa (`\s` no cubre ancho cero).

## D-014 — `MAX_CONTENT_LENGTH` de 16 kB
- **Fecha:** 2026-10-08
- **Decisión:** La fábrica fija `MAX_CONTENT_LENGTH = 16 * 1024` bytes (constante `TAMANO_MAX_PETICION`); `test_config` puede sobrescribirlo. Una petición mayor responde 413 y no llega a la vista.
- **Porqué:** Los formularios son cortos (nombre ≤ 100, correo ≤ 254, contraseña ≤ 128 caracteres); sin límite, un POST enorme se lee entero en memoria. En Flask el 413 se produce al leer el cuerpo, es decir al acceder a `request.form`; eso ocurre ya en el `before_request` del CSRF (D-009), de modo que un cuerpo grande da 413 también sin token (antes que el 400). Si una función futura necesita subir archivos, tendrá que subir el límite en su ruta o con una decisión nueva.
- **Pendiente:** el cuerpo del 413 por defecto de Werkzeug es en inglés; se anotó para T-13 (mensajes en español), no se cambia ahora.
- **Alternativas descartadas:** límite solo en el proxy inverso (la app no debe depender de él); 64 kB o más (sin necesidad).

## Plantilla para nuevas decisiones

```
## D-015 — Política de caracteres permitidos en el correo (T-03c) — **APROBADA por el humano (2026-10-08 00:38): opción 2**
- **Fecha:** 2026-10-08
- **Estado:** APROBADA el 2026-10-08 00:38 (hora de Chile): el humano eligió la **opción 2**. Origen: hallazgo 2 de la revisión de T-03b. Ningún agente puede implementarla hasta que el humano elija.
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

## D-00X — Título
- **Fecha:**
- **Decisión:**
- **Porqué:**
- **Alternativas descartadas:**
```
