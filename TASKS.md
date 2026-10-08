# TASKS

Estados: `PENDIENTE` · `EN CURSO` · `HECHA` · `BLOQUEADA`

Cada tarea tiene un **criterio de término** verificable. Un agente solo marca
`HECHA` cuando ese criterio se cumple y `pytest` pasa.

---

## Fase 1 — Base

### T-01 — Esqueleto del proyecto
- **Estado:** HECHA
- **Depende de:** —
- **Qué:** Si no existe, `git init` con `.gitignore` (venv, `*.db`, `outbox.log`, `__pycache__`). Crear `app/` con fábrica Flask, `requirements.txt`, `tests/conftest.py` con app de prueba y base temporal.
- **Término:** `pytest` corre (aunque sea con una prueba trivial) y `flask --app app run` levanta una página de inicio.

### T-02 — Base de datos
- **Estado:** HECHA
- **Depende de:** T-01
- **Qué:** `schema.sql` según `ARCHITECTURE.md`, `db.py` y comando `init-db`.
- **Término:** Prueba que crea la base y verifica que existen las 3 tablas con sus restricciones.

### T-02b — Endurecer configuración (hallazgos de la revisión de T-01)
- **Estado:** HECHA
- **Depende de:** T-02
- **Qué:** (1) `SECRET_KEY`: el valor por defecto solo se acepta en modo debug/testing; en otro caso la app falla al arrancar si falta la variable de entorno. (2) Fijar versión de `pytest` en `requirements.txt` y registrar la dependencia en `DECISIONS.md` (D-005). (3) Documentar `SECRET_KEY` en `README.md`.
- **Término:** Pruebas: arranque sin `SECRET_KEY` fuera de debug/testing falla; en testing funciona. Debe quedar HECHA **antes** de T-03.
- **Origen:** REVIEW de T-01, hallazgos 1 (media) y 2 (baja).

### T-02d — Corregir efectos de T-02b en comandos CLI y README (hallazgos de la revisión de T-02b)
- **Estado:** HECHA
- **Depende de:** T-02b
- **Qué:** (1) **Defecto:** `flask --app app init-db` falla sin `SECRET_KEY` fuera de debug, y el README lo manda ejecutar primero. Hacer que los comandos CLI de mantenimiento (`init-db`, y luego `create-professional`, `send-reminders`) no exijan `SECRET_KEY` (que solo se necesita para servir peticiones), manteniendo la exigencia en `flask run` fuera de debug; registrar la decisión en `DECISIONS.md` (D-007 está reservada para T-02c, usa D-008). (2) Tratar una `SECRET_KEY` de solo espacios como ausente. (3) README: mostrar `export SECRET_KEY=$(python3 -c "...")` sin `<>`, y advertir que `FLASK_DEBUG` no debe activarse en un entorno expuesto. (4) `DECISIONS.md`: quitar la frase desactualizada de D-006 sobre D-005 y ordenar D-005 antes de D-006. (5) Pruebas: `init-db` sin clave ni debug funciona; `FLASK_DEBUG` con `0`/`false` sin clave falla; clave pasada por `test_config` se respeta; clave de espacios falla.
- **Término:** El recorrido literal del README (venv → pip install → init-db → run --debug) funciona en un entorno limpio sin `SECRET_KEY`; `pytest` pasa. Debe quedar HECHA **antes** de T-03.
- **Origen:** REVIEW de T-02b, hallazgos 1 (media), 2–6 (bajas).

### T-02c — Reforzar integridad del esquema (hallazgos de la revisión de T-02)
- **Estado:** PENDIENTE — **decisión humana APROBADA (D-007, opciones A–F, 2026-10-08)**. Autorizada a modificar `ARCHITECTURE.md` (opción F). Ejecutar **antes de T-04**.
- **Depende de:** T-02
- **Qué:** Tras aprobar el humano las propuestas en `DECISIONS.md` (D-007) y actualizar `ARCHITECTURE.md`: (1) CHECK que ate `estado`, `paciente_id` y `reservada_en` en `horas` (reserva consistente, regla §4.1); (2) CHECK de `notificaciones.tipo`; (3) CHECK de dominio en `duracion_min > 0` y `recordatorio_enviado IN (0,1)`; (4) evaluar `UNIQUE(profesional_id, inicio)` como refuerzo parcial de §4.3. Además, completar las pruebas de `NOT NULL` y de las FK `horas.paciente_id` y `notificaciones.hora_id`, y hacer que `test_comando_init_db` compare columnas. También decidir si `usuarios.email` lleva `COLLATE NOCASE` (la UNIQUE de SQLite distingue mayúsculas y hoy la unicidad depende solo de `normalizar_email()`; hallazgo 3 de la revisión de T-03) y, aprobado por el humano, añadir a `ARCHITECTURE.md` el módulo `seguridad.py` (`# protección CSRF global (token en sesión, before_request)`, y su fila en la tabla de módulos).
- **Término:** Pruebas nuevas fallan si se quita cualquiera de los CHECK/NOT NULL/FK; `pytest` pasa. Debe quedar HECHA **antes** de T-05.
- **Origen:** REVIEW de T-02, hallazgos 1–6 (ver historial git de `REVIEW.md`).

## Fase 2 — Usuarios

### T-03 — Registro de pacientes
- **Estado:** HECHA
- **Depende de:** T-02b, T-02d
- **Qué:** Ruta `/registro` con formulario, validación y hash de contraseña. Correo único.
- **Término:** Pruebas: registro válido, correo duplicado rechazado, contraseña guardada con hash.

### T-03b — Endurecer el registro (hallazgos de la revisión de T-03)
- **Estado:** HECHA
- **Depende de:** T-03
- **Qué:**
  1. **Windows sin `tzdata` (media):** `ZoneInfo("America/Santiago")` falla al importar `auth.py` en Windows sin el paquete, rompiendo incluso `init-db`. Añadir `tzdata; sys_platform == "win32"` a `requirements.txt` (D-012) y no crear el `ZoneInfo` al importar el módulo, sino en el momento de usarlo.
  2. **Normalización del correo (media):** extraer `normalizar_email()` (NFKC + `casefold` + rechazo de caracteres de control y de espacios internos) en un lugar reutilizable por el login y `create-professional` (D-013). Pruebas con las variantes que el revisor encontró: ancho completo, `ß`/`ss`, carácter de ancho cero.
  3. **Tamaño de la petición (media):** fijar `MAX_CONTENT_LENGTH` (~16 kB) con prueba (413) y entrada en `DECISIONS.md` (D-014).
  4. **Pruebas que no detectaban mutaciones (baja):** CSRF también para PUT/PATCH/DELETE; el escape de `email` en `value="..."` (no solo el nombre); que el hash use los parámetros de scrypt por defecto (prefijo y costo mínimo); que la prueba del duplicado falle si se añade un SELECT previo, o corregir su docstring.
  5. **Documentación (baja):** añadir a D-009 que un POST a una ruta inexistente responde 400 y no 404/405 porque el CSRF corre antes del enrutamiento.
- **Término:** Cada mutación citada en el punto 4 hace fallar al menos una prueba; `python3 -m pytest` pasa; el módulo importa sin error simulando ausencia de zona horaria del sistema (`PYTHONTZPATH` vacío) cuando `tzdata` está instalado, y `requirements.txt` lo declara para Windows. Debe quedar HECHA **antes** de T-04.
- **Origen:** REVIEW de T-03, hallazgos 1, 3, 4, 5 y 7 (ver historial git de `REVIEW.md`).

### T-03c — Cerrar los hallazgos de la revisión de T-03b
- **Estado:** PENDIENTE — el punto 2 **requiere decisión humana** (política de caracteres del correo); el resto puede hacerse sin ella.
- **Depende de:** T-03b
- **Qué:**
  1. **Pruebas de `normalizar_email` (media):** el implementador afirmó que quitar la primera NFKC era "equivalente"; es **falso** (cambia el resultado en 637 puntos de código y rompe la idempotencia, comprobado por el orquestador). Añadir pruebas con esos casos (p. ej. `ϒ` U+03D2) y una prueba **exhaustiva de idempotencia** sobre todos los puntos de código; corregir en `PROGRESS.md` la frase falsa de la entrada de T-03b.
  2. **Política de caracteres del correo (media, DECISIÓN HUMANA, ver D-015):** hoy solo se rechazan las categorías Cc, Cf y los espacios; pasan selectores de variación, U+034F, rellenos hangul, braille en blanco, U+FFFD, combinantes sueltos y puntos de uso privado o no asignados (los Cn dependen de la versión de Python). Implementar la opción que el humano elija en D-015.
  3. **D-014 (media):** corregir el texto: afirma que una ruta futura puede subir el límite, pero el `before_request` del CSRF lee el cuerpo antes y da 413 igualmente; indicar el mecanismo real (configuración global o excepción explícita).
  4. **`tzdata` incondicional (baja):** quitar el marcador `sys_platform == "win32"` (Alpine, distroless y Linux mínimos sin `/usr/share/zoneinfo` fallarían en el primer registro) y actualizar D-012. Añadir una prueba HTTP de "500 y cero usuarios" cuando faltan los datos de zona horaria, una prueba de la rama "con `tzdata` instalado y `PYTHONTZPATH` vacío funciona", que `test_zona_chile_se_crea_una_sola_vez` no deje la caché poblada para otras pruebas, y una prueba que falle si se borra la línea de `tzdata` de `requirements.txt`.
  5. **Separadores y plegados (baja):** pruebas con U+2028, U+2029, U+1680 y marcas bidi (cambiar `isspace()` por `== " "` hoy no rompe nada); ampliar D-013 con `ς`, `ſ`, `K` (kelvin), `İ` e `ı`.
  6. **Entradas no `str` (baja):** que `normalizar_email` lance `ValueError` (no `TypeError`) o documentar el contrato.
  7. **Suite lenta (baja):** pasó de 0,2 s a ~5 s por el scrypt real en cada registro. Fixture `autouse` con hash rápido, salvo en pruebas marcadas `hash_real` que verifican el hash; sin debilitar las pruebas de seguridad.
  8. **D-010 desactualizada (baja):** actualizarla para que remita a D-012 y D-013.
- **Término:** Las mutaciones "sin primera NFKC", "sin segunda NFKC", "`isspace()` por `== " "`" y "borrar `tzdata` de requirements.txt" hacen fallar al menos una prueba; la prueba de idempotencia pasa; `python3 -m pytest` pasa y es notablemente más rápida. Debe quedar HECHA **antes** de T-04.
- **Origen:** REVIEW de T-03b (ver historial git de `REVIEW.md`).

### T-04 — Login, logout y control de rol
- **Estado:** PENDIENTE
- **Depende de:** T-03b, T-03c, T-02c
- **Qué:** `/login`, `/logout`, decoradores `solo_paciente` y `solo_profesional`, comando `create-professional`. Debe además: (a) usar `normalizar_email()` de T-03b; (b) llamar a `session.clear()` y regenerar el token CSRF al iniciar y cerrar sesión (evita fijación de sesión); (c) guardar en la sesión **solo el id del usuario**; (d) fijar `SESSION_COOKIE_SAMESITE="Lax"`; (e) un mensaje **único** para credenciales inválidas, sin distinguir correo inexistente de contraseña errónea; (f) absorber los ítems del backlog T-02d #2 y #3.
- **Término:** Pruebas: login correcto/incorrecto, paciente no accede a `/profesional` (US-3), el token CSRF cambia tras el login, el mensaje de error es idéntico para correo inexistente y contraseña errónea.

## Fase 3 — Horas

### T-05 — Profesional agrega y elimina horas
- **Estado:** PENDIENTE
- **Depende de:** T-04, T-02c
- **Qué:** Formulario y rutas de US-4 y US-5 con reglas 2, 3 y 4.
- **Término:** Pruebas: crear hora válida, rechazar pasado, rechazar solape, no eliminar reservada.

### T-06 — Paciente ve horas libres
- **Estado:** PENDIENTE
- **Depende de:** T-05
- **Qué:** `/paciente/horas` con horas libres futuras ordenadas (US-7).
- **Término:** Prueba: solo aparecen horas libres y futuras.

### T-07 — Reservar hora
- **Estado:** PENDIENTE
- **Depende de:** T-06
- **Qué:** `POST /horas/<id>/reservar` con UPDATE atómico (D-003) y reglas 1 y 5.
- **Término:** Pruebas: reserva exitosa; segunda reserva de la misma hora falla; paciente no puede tener dos a la misma hora.

### T-08 — Cancelar reserva
- **Estado:** PENDIENTE
- **Depende de:** T-07
- **Qué:** `POST /horas/<id>/cancelar` con anticipación mínima de 24 h (US-9); la hora vuelve a `libre`.
- **Término:** Pruebas: cancelar con >24 h funciona, con <24 h se rechaza, la hora queda libre.

## Fase 4 — Notificaciones

### T-09 — Notificaciones de confirmación y cancelación
- **Estado:** PENDIENTE
- **Depende de:** T-08
- **Qué:** `notificaciones.py`; crear registros y escribir `outbox.log` al reservar y cancelar (US-11, US-13).
- **Término:** Pruebas: se crean notificaciones para ambas partes y aparece la línea en el log.

### T-10 — Recordatorios 24 h antes
- **Estado:** PENDIENTE
- **Depende de:** T-09
- **Qué:** Comando `send-reminders` (US-12); no repite recordatorios (`recordatorio_enviado`).
- **Término:** Pruebas con hora a <24 h: envía una sola vez aunque se ejecute dos veces.

## Fase 5 — Interfaz

### T-11 — Dashboard del paciente
- **Estado:** PENDIENTE
- **Depende de:** T-09
- **Qué:** `/paciente` con próxima sesión, historial y campana de notificaciones (US-10).
- **Término:** Prueba de contenido por rol; revisión visual en navegador.

### T-12 — Dashboard del profesional
- **Estado:** PENDIENTE
- **Depende de:** T-09
- **Qué:** `/profesional` con agenda, horas libres y notificaciones (US-6).
- **Término:** Prueba de contenido por rol; revisión visual en navegador.

### T-13 — Estilo y plantilla base amigable
- **Estado:** PENDIENTE
- **Depende de:** T-11, T-12
- **Qué:** `style.css` con tonos calmados, diseño responsivo, mensajes de error claros.
- **Término:** Revisión en pantalla de escritorio y de celular; sin texto ilegible.

## Fase 6 — Cierre

### T-14 — Recorrido de punta a punta y revisión final
- **Estado:** PENDIENTE
- **Depende de:** T-13
- **Qué:** Verificador ejecuta el recorrido completo de `SPEC.md` §9; Revisor contrasta código contra SPEC.
- **Término:** Todas las casillas de "Definición de terminado" marcadas; hallazgos en `REVIEW.md` resueltos.

---

## Backlog de baja prioridad (no bloquea nada; recoger cuando se toque la zona)

Hallazgos de severidad baja que las revisiones dejaron anotados. Cada uno indica
en qué tarea conviene absorberlo.

| Origen | Hallazgo | Absorber en |
|---|---|---|
| T-02d #1 | `FLASK_DEBUG=1` heredado en un servidor real usa la clave pública de desarrollo sin aviso | T-14 (revisión final de seguridad) |
| T-02d #2 | Aviso visible al arrancar si falta `SECRET_KEY` (el 500 solo aparece al llegar la primera petición); `app.logger.warning` una vez, sin molestar en `init-db` | T-04 |
| T-02d #3 | Las pruebas de D-008 solo hacen `GET /`; añadir `/static`, un 404 y un blueprint | T-04 (primer blueprint real) |
| T-02d #6 | README: aclarar "solo en tu máquina" junto a `--debug`; `FLASK_DEBUG=off` cuenta como verdadero en Flask | T-14 |
| T-01 #3–4 | `base.html` aún no enlaza `style.css` | T-13 |
| T-03 #2 | Cookie de sesión sin `Secure` (hace falta HTTPS para activarla) | T-14 |
| T-03 #4 | `/registro` sin límite de frecuencia: cada registro cuesta ~0,12 s de CPU por scrypt | T-14 |
| T-03 #6 | La página de error 400 de CSRF es la genérica de Werkzeug, en inglés y sin enlace para volver: añadir `errorhandler(400)` con plantilla en español | T-13 |
| T-03 #8 | El mensaje de duplicado casi confirma que el correo existe (aceptado en D-010) | T-14 (revisar de nuevo) |
| T-03 #9 | Los límites de longitud cuentan caracteres, no bytes (inocuo) | — |

---

## Tareas que pueden correr en paralelo (en ramas separadas)

- T-11 y T-12 (después de T-09).
- Dentro de la Fase 3 no: son secuenciales porque comparten `horas`.
