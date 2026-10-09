# TUTORIAL — cómo se implementó Agenda Psi con agentes

Guía paso a paso de lo que se hizo en las dos primeras vueltas (T-01 y T-02),
para que puedas repetirlo tú con las tareas siguientes.

---

## 0. La idea en una frase

**Humano/orquestador decide → Implementador construye → Revisor critica → el humano decide qué hacer con los hallazgos.**
Cada agente empieza sin memoria; todo el estado vive en archivos y en git.

## 1. Preparación (una sola vez)

```bash
cd agenda-psi
python3 --version                     # 3.11 o superior
pip install flask pytest              # o: python -m venv .venv && pip install -r requirements.txt
git init -b main
git add -A && git commit -m "docs: documentación base"
git checkout -b agentes/loop          # los agentes NUNCA trabajan en main
```

Por qué: un commit limpio con la documentación te da un punto de retorno, y la
rama `agentes/loop` protege `main`.

## 2. Una vuelta completa (el ciclo que se repite)

### Paso A — Elegir la tarea
Abre `TASKS.md`. La siguiente es la primera `PENDIENTE` con todas sus
dependencias `HECHA`. Una tarea = una vuelta.

### Paso B — Lanzar al Implementador
Abre Claude Code en la carpeta del proyecto y pega:

```
Lee CLAUDE.md y sigue sus instrucciones de lectura.
Toma la primera tarea PENDIENTE de TASKS.md cuyas dependencias estén HECHAS.
Márcala EN CURSO, impleméntala con sus pruebas, verifica con pytest,
márcala HECHA, agrega la entrada en PROGRESS.md y haz commit.
Haz solo esa tarea y detente.
```

### Paso C — Verificar tú mismo (nunca confíes solo en el reporte del agente)

```bash
git status --short                 # ¿quedó algo sin commitear?
git log --oneline                  # ¿un commit por tarea, con el formato T-XX?
git show --stat HEAD               # ¿tocó solo los archivos esperados?
python3 -m pytest -q               # ¿pasan las pruebas?
find . -name "*.db" -not -path "./.git/*"   # ¿dejó bases de datos sueltas?
```

Si algo no coincide con lo que el agente dijo, es información valiosa: anótalo.

### Paso D — Lanzar al Revisor (contexto limpio, otro agente)
Abre una **sesión nueva** (o un subagente) y pega:

```
Lee CLAUDE.md, SPEC.md y ARCHITECTURE.md.
Revisa el último commit (git show HEAD) contra el criterio de término
de la tarea y las reglas de negocio de SPEC.md §4.
No modifiques código. Escribe en REVIEW.md una lista de hallazgos
con severidad (alta/media/baja) y el archivo y línea afectados.
Si no hay hallazgos altos, escribe "APROBADO".
```

Truco que funcionó bien: **agrega al prompt del revisor 3 o 4 puntos
específicos** de la tarea (por ejemplo "¿las pruebas fallarían si el esquema
estuviera mal?"). Un revisor con instrucciones genéricas encuentra menos.

### Paso E — Decidir qué hacer con los hallazgos (esto lo haces tú)

| Hallazgo | Acción |
|---|---|
| Alto | El Implementador lo corrige en una vuelta nueva. Máximo 3 rondas. |
| Medio / bajo que **no** cambia el diseño | Se agrega una tarea nueva a `TASKS.md` (ej. T-02b) |
| Cambia `SPEC.md` o `ARCHITECTURE.md` | Se propone en `DECISIONS.md` y **tú** decides (ej. T-02c) |

Luego haz commit de `REVIEW.md` y de los cambios en `TASKS.md`. El historial de
git conserva cada revisión aunque `REVIEW.md` se sobrescriba.

## 3. Qué pasó en cada vuelta (resultados reales)

### Vuelta 1 — T-01 Esqueleto del proyecto
- **Implementador creó:** `.gitignore`, `requirements.txt`, `app/__init__.py` (fábrica `create_app`), plantillas `base.html` e `inicio.html`, `tests/conftest.py`, `tests/test_inicio.py`.
- **Verificación:** 1 prueba pasa; `flask --app app run` responde 200 en `/`.
- **Revisor: APROBADO**, con hallazgos:
  - *Media:* `SECRET_KEY` con valor por defecto público → riesgo si se despliega así. Se convirtió en **T-02b**.
  - *Baja:* `pytest` sin versión ni entrada en `DECISIONS.md`; falta la hora en la bitácora; `base.html` aún no enlaza el CSS.

### Vuelta 2 — T-02 Base de datos
- **Implementador creó:** `app/schema.sql`, `app/db.py` (`get_db`, `close_db`, `init_db`, comando `init-db`), `tests/test_db.py` (8 pruebas) y la decisión **D-006** (`init-db` no destructivo).
- **Verificación:** 9 pruebas pasan en total; el esquema coincide con `ARCHITECTURE.md`.
- **Revisor: APROBADO**, con hallazgos:
  - *Media:* el esquema acepta `estado='reservada'` con `paciente_id` vacío, lo que debilita la regla de "no doble reserva".
  - *Media:* algunas pruebas no detectarían la pérdida de ciertos `NOT NULL` o claves foráneas.
  - *Baja:* faltan CHECK de dominio (`duracion_min` negativa) y de `notificaciones.tipo`.
  - Como cambian el esquema documentado, se convirtieron en **T-02c** y requieren **tu** decisión.

### Vuelta 3 — T-02b Endurecer configuración
- **Implementador:** `create_app` exige `SECRET_KEY` salvo en debug/testing; `pytest` con versión fija (D-005); sección de `SECRET_KEY` en el README; 5 pruebas nuevas.
- **Verificación:** 14 pruebas pasan; sin clave y sin debug, la app falla con un mensaje claro.
- **Revisor: APROBADO**, pero encontró un **defecto real**: `flask --app app init-db` también fallaba sin `SECRET_KEY`, y el README lo manda ejecutar primero. Lo reproduje antes de crear la tarea **T-02d**.
- **Lección:** una tarea puede cumplir su criterio de término y aun así romper algo que ya estaba documentado. Por eso el criterio de T-02d incluye recorrer el README literalmente en un entorno limpio.

### Vuelta 4 — T-02d Corregir efectos de T-02b
- **Implementador:** la validación pasó de `create_app` a un `before_request` (D-008). Así los comandos CLI funcionan sin clave, pero una app sin clave **nunca atiende una petición**, la sirva `flask run` o gunicorn. 25 pruebas; 11 fallan si se revierte el cambio.
- **Hallazgo propio del implementador:** el `pytest` literal del README fallaba en un venv limpio (`No module named 'app'`); lo arregló con `pytest.ini`. Solo lo descubrió porque recorrió el README de verdad.
- **Revisor: APROBADO**, solo hallazgos bajos. Pasaron al *backlog de baja prioridad* de `TASKS.md`, cada uno asignado a la tarea donde conviene absorberlo.
- **Dos sorpresas que enseñan más que el código:**
  1. **Los agentes inventan la hora.** Las horas de `PROGRESS.md` (`23:40`, `23:59`, `10:30`) no coincidían con los commits (`23:36`, `23:42`, `00:05`). Corregí los datos y añadí a `CLAUDE.md` las reglas 8–10: la hora se obtiene con `date`, se reporta solo lo realmente ejecutado y todo archivo no pedido se justifica.
  2. **Mi propio `pytest` falló** con `No module named 'flask'`. No era un defecto del proyecto: mi shell resolvía a una copia aislada de `uv` que no tiene Flask. Es exactamente el problema que evita un venv. Investigué antes de culpar al agente o al código.

### Vuelta 5 — T-03 Registro de pacientes (primera tarea con seguridad)
- **Implementador:** blueprint `auth` con `/registro`, CSRF propio y centralizado (`app/seguridad.py`, D-009), validaciones (D-010), hash `scrypt`, rol forzado a `paciente`, duplicados capturando `IntegrityError`. 62 pruebas (37 nuevas). Probó mutaciones: quitó CSRF, hash, rol… y comprobó que las pruebas fallaban.
- **Mi verificación:** recorrido real con curl contra un servidor. Añadí un ataque que el implementador no probó: **usar el token CSRF de una sesión en otra** (da 400, correcto). La base quedó con 1 usuario, hash `scrypt` y rol `paciente`.
- **Revisor (modo auditor de seguridad): APROBADO**, con 4 hallazgos medios reales:
  1. **Windows sin `tzdata`:** `ZoneInfo("America/Santiago")` rompe incluso `init-db`. Lo simuló y falló.
  2. **Normalización del correo:** `ana@…` en ancho completo, una «е» cirílica o un carácter de ancho cero se aceptan como cuentas distintas. La UNIQUE de SQLite distingue mayúsculas, así que la unicidad depende solo de esa función.
  3. **Sin `MAX_CONTENT_LENGTH`:** el límite de 128 caracteres de la contraseña no protege el cuerpo de la petición.
  4. **Sesión:** `SameSite` sin fijar y el token CSRF no rota al iniciar sesión (fijación de sesión).
- **Hallazgo sobre las pruebas:** de 8 mutaciones que el revisor intentó, **4 dejaron las 62 pruebas en verde** (por ejemplo, CSRF solo para POST, o `|safe` en el correo). Que las pruebas pasen no significa que protejan.
- **Mi decisión como orquestador:** los hallazgos 1–3 se agrupan en **T-03b**, que debe ir **antes** de T-04, porque el login reutilizará la normalización del correo. El hallazgo 4 se asigna a T-04, que es donde nace el login. El resto va al backlog con tarea asignada.
- **Lección:** el orden de las tareas es una herramienta. Arreglar los cimientos de la autenticación antes de construir el login sale más barato que corregirlos después.

### Vuelta 6 — T-03b Endurecer el registro (y tu primera decisión humana)
- **Implementador:** `normalizar_email()` (NFKC + `casefold`, rechaza caracteres invisibles), zona horaria creada al usarla y `tzdata` en `requirements.txt` (D-012), `MAX_CONTENT_LENGTH` de 16 kB (D-014) y pruebas reforzadas. 109 pruebas; ejecutó 10 mutaciones y reportó cuáles pruebas fallaban.
- **Mi verificación:** 109 pruebas en tres entornos (sin variables, con `SECRET_KEY`, con `FLASK_DEBUG=1`); comprobé que no tocó el esquema, `ARCHITECTURE.md` ni la propuesta D-007; y ejecuté yo mismo dos mutaciones (usar solo `lower()` en vez de la normalización; desactivar el límite de tamaño). Las dos fueron detectadas.
- **Revisor: APROBADO**, pero encontró una **afirmación falsa del implementador**: dijo que quitar la primera NFKC era equivalente. Lo reproduje: cambia el resultado en **637 puntos de código** y rompe la idempotencia. La suite seguía verde porque ninguna prueba cubría esos casos.
- **Tu primera decisión humana:** aceptaste las opciones A–F de **D-007** (refuerzos del esquema, más la autorización para editar `ARCHITECTURE.md`). Quedó registrada en `DECISIONS.md` con tu respuesta textual, y T-02c pasó a ser la siguiente tarea de esquema.
- **Decisión pendiente nueva:** **D-015** (qué caracteres se aceptan en un correo). Tres opciones con su costo; la recomendada es aceptar solo ASCII.
- **Lección:** el implementador no mintió con mala intención: razonó mal ("la segunda NFKC ya lo cubre") y lo dio por verificado sin ejecutarlo. Por eso existe la regla 9 de `CLAUDE.md` y por eso el revisor sigue siendo imprescindible.

### Vuelta 7 — T-02c Reforzar el esquema (lo que tú aprobaste en D-007)
- **Implementador:** `schema.sql` con exactamente las opciones A–E, `ARCHITECTURE.md` actualizado solo en lo autorizado, 78 pruebas nuevas (187 en total) y 15+ mutaciones ejecutadas y detectadas. Comprobó qué pasa con una base antigua: `init-db` termina con éxito **sin avisar** y deja las tablas sin las restricciones nuevas.
- **Mi verificación:** comparé el esquema, `ARCHITECTURE.md` y D-007 contra lo aprobado (todo coincidía, nada de más) y apliqué 6 mutaciones propias; una **sobrevivió**: ampliar el CHECK de `tipo` con un cuarto valor dejaba las 187 pruebas en verde. Las pruebas comprobaban cuatro valores inválidos concretos, no que el conjunto fuera *exactamente* tres.
- **Revisor: APROBADO**, con hallazgos que **solo se ven pensando en las tareas futuras**:
  1. Una hora que se reservó y se canceló **no se puede eliminar**: tiene notificaciones que la apuntan y la clave foránea lo impide. Contradice US-5. Lo reproduje.
  2. La UNIQUE sobre `inicio` compara **texto**: el mismo instante escrito de 5 formas distintas pasa 5 de 5 veces. Lo reproduje.
  3. Ampliar otros CHECK (`estado`, `rol`) también sobrevive a las pruebas.
- **Tus decisiones:** D-016 (`ON DELETE SET NULL`) y D-017 (formato canónico con CHECK en el esquema). Elegiste las recomendadas. Como cambian el esquema que ya habías aprobado, las apliqué como una tarea nueva (**T-02f**), no como un parche dentro de T-02c.
- **Un error mío, corregido:** el revisor detectó que la fila de `seguridad.py` en `ARCHITECTURE.md` decía "ni acceso a la base de datos", algo que tú no habías aprobado en D-007. La frase la puse yo en las instrucciones al implementador. La eliminé y quedó exactamente lo aprobado.
- **Lección:** un esquema puede estar perfecto y aun así chocar con una historia de usuario que todavía no se ha implementado. Preguntarle al revisor "¿cómo interactúa esto con las tareas futuras?" encontró más que revisar la tarea sola.

### Vuelta 8 — T-02f Aplicar D-016 y D-017 al esquema
- **Implementador:** `ON DELETE SET NULL` y el CHECK de formato de `inicio`; 45 pruebas nuevas (232 en total), 9 mutaciones detectadas, flujo reservar → cancelar → eliminar comprobado con claves foráneas activas. **Encontró por su cuenta un defecto de su propio trabajo**: un valor con un carácter nulo (`\x00`) pasa el `GLOB` y elude la UNIQUE. Lo reportó con claridad en vez de ocultarlo.
- **Pero afirmó algo falso:** sugirió `CHECK (length(inicio) = 19)` como arreglo "que lo cerraría" sin ejecutarlo. Lo probé: **no funciona**, porque `length()` se detiene en el primer NUL. Probé cuatro candidatos y dos sí funcionan.
- **Mi verificación:** el diff coincidía exactamente con lo aprobado, 232 pruebas en tres entornos, y tres mutaciones propias detectadas (en `ON DELETE` de otras claves y en el GLOB).
- **Revisor: APROBADO**, y confirmó mi hallazgo. Además descubrió dos consecuencias de D-016 que cambian las tareas futuras:
  1. `INSERT OR REPLACE` sobre `horas` borra y reinserta la fila, lo que **dispara `ON DELETE SET NULL` y pierde el vínculo de las notificaciones sin avisar**. Quedó prohibido en T-05.
  2. Como `hora_id` puede ser NULL, T-09, T-10, T-11 y T-12 deben tolerarlo (`LEFT JOIN`, mensajes autosuficientes). Quedó anotado en cada una.
- **Tu decisión (D-018):** añadir `instr(inicio, char(0)) = 0`, la opción recomendada. Como cambia lo que aprobaste en D-017, la dejé como tarea nueva (**T-02g**) y corregí en `PROGRESS.md` la afirmación falsa, con una nota visible.
- **Lección:** el mismo agente que encontró el defecto propuso un arreglo que no funcionaba. Encontrar un problema y arreglarlo bien son dos verificaciones distintas.

### Vuelta 9 — T-02g Cerrar el hueco del carácter nulo (D-018)
- **Ronda 1 del implementador:** añadió `instr(inicio, char(0)) = 0` al CHECK, reemplazó la prueba que "documentaba" el defecto por pruebas que exigen el rechazo y agregó una prueba por posición del formato. 326 pruebas, 8 mutaciones detectadas.
- **Mi verificación encontró un hueco que sus 8 mutaciones no veían:** hice yo una mutación sistemática (cambiar cada uno de los 14 dígitos del GLOB de `[0-9]` a `[0-8]`, `[1-9]`, `[0-4]` y `[5-9]`). Los 14 mutantes `[0-8]` **sobrevivían**: ninguna prueba usaba un 9 en cada posición. Lo devolví al implementador (ronda 2).
- **Ronda 2:** 31 pruebas nuevas con los dígitos de borde 0 y 9 en cada posición. 357 pruebas en tres entornos. Re-ejecuté mi script y las **56 de 56** mutaciones quedan detectadas; el diff solo toca `tests/` y `PROGRESS.md`.
- **Revisor: APROBADA.** Reprodujo el cierre del NUL con 23 valores (incluidos BLOB, enteros y NUL al inicio, medio y final). Hallazgos solo bajos: pruebas redundantes, un helper que no dice qué CHECK falló, y que T-02e debe incluir `instr(...)` al comparar el SQL. Todos quedaron en `TASKS.md`.
- **Lección:** las mutaciones que escribe el propio autor reflejan lo que ya pensó. Una mutación **sistemática** (todas las posiciones × todas las variantes) encuentra lo que no pensó.

### Vuelta 10 — T-02e Fijar el conjunto exacto del esquema
- **Implementador:** comparó el SQL de cada tabla en `sqlite_master` con el esperado, la fila completa de `foreign_key_list` y valores vecinos inválidos. 390 pruebas; 5 mutaciones pedidas y 2 extra detectadas. Además hizo que cada rechazo falle por el CHECK **concreto**, no por "algún CHECK".
- **Mi verificación:** diff solo en `tests/`, 3 entornos en verde, y 8 mutaciones propias (UNIQUE, DEFAULT, NOT NULL, ON DELETE, COLLATE…) todas detectadas.
- **Revisor: APROBADA.** Probó 49 mutaciones (36 semánticas, todas detectadas; 13 inocuas). Hallazgos bajos al backlog; el esquema acepta valores no enteros en `duracion_min`, así que T-05 debe validarlo.
- **Lección:** una prueba que compara el SQL exacto es una alarma de "esquema cambiado": falla también con reformateos inocuos, y eso es un costo de mantenimiento que conviene conocer.

### Vuelta 11 — T-03c Cerrar hallazgos de T-03b (9 ítems)
- **Implementador:** política de correo D-015 opción 2, `tzdata` incondicional, `ValueError` en entradas no `str`, `IntegrityError` distinguido, hash rápido en pruebas (D-019), pruebas exhaustivas de idempotencia NFKC. 470 pruebas.
- **Honestidad útil:** reportó que el criterio "suite notablemente más rápida" **no** se cumplió (la lentitud viene de otro archivo) y que D-015 no cubre el relleno hangul ni el braille en blanco.
- **Mi verificación:** diff dentro de lo autorizado, 3 entornos, 10 mutaciones propias: 9 detectadas y 1 sobrevive (quitar el registro del marcador `hash_real` solo da avisos; se pasa a T-04 con `--strict-markers`). También arreglé la plantilla de `DECISIONS.md`, que tragaba D-015…D-018 dentro de un bloque de código.
- **Revisor: APROBADA** (R-01…R-13). Dos cosas a tener en cuenta: el campo `type="email"` del navegador bloquearía `señor@…` y anula el motivo de elegir la opción 2 (pasa a T-04), y una **nueva decisión tuya, D-020**, sobre qué hacer con caracteres invisibles que D-015 no cubre (no bloquea nada).
- **Lección:** que un agente reporte con claridad lo que *no* logró es más valioso que un "todo bien". Premia esa conducta en tus prompts: "reporta lo que no se cumplió".

### Vuelta 12 — T-04 Login, logout y roles (la primera con seguridad "de verdad")
- **Implementador:** `/login`, `POST /logout`, decoradores por rol, `create-professional` con contraseña sin eco, hash falso para igualar tiempos, sesión solo con el id. 597 pruebas, recorrido real con `flask run` + curl, Chromium con Playwright para el correo con `ñ`, 24 mutaciones.
- **Corrigió al revisor del paso anterior:** el hallazgo "`type="email"` bloquea `señor@`" resultó ser parcialmente inexacto: el formulario ya tenía `novalidate`. Verificar en un navegador real evitó trabajo innecesario.
- **Revisor: APROBADA**, con mentalidad de auditor (sesión, tiempos con scrypt real, 46 mutaciones). Hallazgos: ninguna prueba cubría el CSRF de `/login`; faltaba `Cache-Control: no-store`; la cookie firmada sigue valiendo tras el logout (**D-022**, tuya); `create-professional` permite varios profesionales (**D-023**, tuya).
- **Lección:** el CSRF de `/login` estaba implementado pero sin prueba que lo protegiera: eximir esa ruta dejaba las 597 pruebas en verde. Una defensa sin prueba es una defensa que se perderá en la próxima refactorización.

### Vuelta 13 — T-04b Cerrar los hallazgos de T-04
- **Implementador:** pruebas del CSRF de login, `no-store` global (D-024), nombre sin caracteres de control, hash falso por app. 664 pruebas; 4 mutaciones del criterio y 14 propias.
- **Honestidad útil otra vez:** reportó que su recorrido con Chromium dio el mismo resultado con y sin `no-store`, o sea que **ese experimento no demuestra nada**; lo que protege son las pruebas de cabeceras.
- **Revisor: APROBADA.** Encontró que una frase de D-024 era falsa (Flask no deja `session.accessed` siempre en True): la corregí con una nota visible, como en otras ocasiones. Los hallazgos restantes son bajos y están en el backlog.
- **Lección:** también los documentos de decisión contienen afirmaciones técnicas que hay que verificar, no solo el código.

### Vueltas 14 a 19 — T-05 a T-08: la lógica de negocio (horas, reservas, cancelaciones)
Aquí el ciclo ya es rutina: implementador → mi verificación → revisor → triage. Lo que cambió es **qué** encuentra cada revisión. Resumen:
- **T-05 (agregar y eliminar horas):** 805 pruebas, 36 mutaciones. El revisor halló que `9999-12-31` se aceptaba y que un solape posterior daba 500 (`OverflowError`), y que el solape calculado en "reloj de pared" falla en las noches de cambio de horario. → **T-05b**: tope de 2 años (D-026) y solape con instantes absolutos. Después de eso, 17 748 casos alrededor de seis cambios de horario coinciden con un modelo independiente.
- **T-06 (el paciente ve horas libres):** 902 pruebas. Aparecieron por primera vez **horas inventadas**: el implementador escribió en PROGRESS una hora posterior al reloj real (segunda vez, regla 8); la corregí con nota visible. Lección: si una regla se rompe dos veces, la siguiente instrucción debe decir exactamente qué NO hacer ("jamás una hora posterior al commit"). En T-07 y T-08 ya no ocurrió.
- **T-07 (reservar):** el corazón de la concurrencia. `BEGIN IMMEDIATE` + `UPDATE ... WHERE estado='libre'` + revisión de `rowcount`. El revisor lanzó 12 procesos reales sobre la misma hora: siempre exactamente 1 éxito. Además comparó 800 decisiones de la regla 5 con un modelo independiente.
- **T-08 (cancelar, 24 h, «Mis reservas»):** 1117 pruebas, 51 mutaciones. **Primer CAMBIOS REQUERIDOS en mucho tiempo**: una fixture con `time.tzset()` rompía todas las pruebas en Windows, y el README promete Windows. Se corrigió en una segunda ronda (7 pruebas que simulan la ausencia de `tzset`). Es el ejemplo del límite de 3 rondas por tarea funcionando.
- **Lo que viene de tus decisiones:** D-020 (caracteres invisibles en el correo), D-022 (revocar cookie al cerrar sesión), D-023 (un solo profesional) y D-029 (reservar con menos de 24 h: hoy esa reserva no la puede deshacer nadie). Cuatro decisiones pendientes se acumulan: es un olor a que **decidir tarde cuesta**. Resuélvelas en lote.
- **Lección general:** las revisiones empezaron en la sintaxis (T-01) y ahora encuentran errores de *diseño* (la reserva que nadie puede cancelar). Mientras más avanza el proyecto, más valioso es el revisor que cruza el cambio con las historias de usuario.

### Vueltas 20 y 21 — T-08b y T-08c: cuidar la herramienta de verificación
- **T-08b:** la suite había crecido a 66 s y la gente deja de ejecutar pruebas lentas. Se redujo a ~28 s (base SQLite copiada de una plantilla, cachés compartidas) **sin borrar ninguna aserción**: el revisor comparó los 1124 identificadores de antes y confirmó que siguen idénticos. Se comprobó con 13 + 24 mutaciones que las pruebas siguen protegiendo.
- **T-08c:** el revisor encontró que el atajo `/dev/shm` se rompía con poco espacio (Docker trae 64 MB). Se resolvió con un umbral medido, una variable de entorno y un tmpfs real de 12 MB para reproducirlo. También arregló una prueba que **dependía del orden de ejecución**: se verificó en orden normal, inverso y aleatorio.
- **Lección:** las pruebas son código y también necesitan revisión. Acelerarlas es peligroso porque *un atajo mal hecho hace que todas pasen por la razón equivocada*; por eso cada atajo trae una prueba de aislamiento y se re-ejecutan mutaciones de tareas anteriores.
- **Nota de proceso:** T-08c lo verifiqué yo (diff, 3 entornos, orden aleatorio con otra semilla) pero **no** lancé un revisor aparte, porque solo toca la infraestructura de pruebas y el riesgo ya estaba acotado. Es una excepción consciente, no la norma.

### Vueltas 22 a 24 — T-08d, T-08e y T-09: tus decisiones aplicadas y las primeras notificaciones
- **T-08d y T-08e:** aplicaron lo que aprobaste (D-022 revocar la sesión al cerrar sesión, D-023 un solo profesional, D-020 correos sin caracteres invisibles, D-029 reservar solo con más de 24 h). Cada una se revisó y quedó aprobada; la suite pasó de 1157 a 1505 pruebas.
- **T-09 (notificaciones):** al reservar y al cancelar se crean avisos para paciente y profesional **dentro de la misma transacción** (si el aviso falla no queda reserva) y la línea de `outbox.log` se escribe **después** del commit (un disco lleno no deshace la reserva). El nombre y el correo se sanean antes de llegar al log para que nadie pueda inyectar líneas falsas.
- **Una vuelta interrumpida:** cuando retomé, encontré trabajo de T-09 sin commit y un proceso de pytest colgado desde hacía casi 2 horas. No lo di por bueno: lo cerré por su PID, devolví el trabajo a un implementador para que lo leyera y lo ejecutara crítico, y lo verifiqué yo (1507 pruebas en 4 entornos y 5 mutaciones propias). El implementador además corrigió un texto: decía «sin costo», que no existe en esta versión.
- **Revisor: APROBADA.** Probó 6 procesos reales compitiendo por 10 horas (10 reservas, 20 avisos, sin cruces). Su hallazgo más útil mira al futuro: las funciones de T-09 no sirven tal cual para los recordatorios de T-10 (cualquier tipo distinto de confirmación saldría con el texto de «Cancelaste tu hora»). Quedó escrito en T-10.
- **Lección:** el estado de un proyecto con agentes vive en git, no en la memoria de nadie. Tras una interrupción, lo primero es leer `git status`, `git log` y `TASKS.md`, y desconfiar del trabajo sin commit hasta ejecutarlo.

### Vuelta 25 — T-10 Recordatorios 24 h antes
- **Implementador:** comando `flask --app app send-reminders` (solo avisa al paciente, como dice SPEC US-12). Lee todo dentro de una transacción `BEGIN IMMEDIATE`, marca `recordatorio_enviado` y crea el aviso en la misma transacción, y escribe el log después del commit. Corrigió la trampa que el revisor de T-09 había señalado: ahora un tipo de aviso sin mensaje propio lanza un error en vez de salir con el texto de otra cosa. 74 pruebas nuevas (1581 en total), 14 mutaciones detectadas.
- **Mi verificación:** diff, 1581 pruebas en 4 entornos, y 6 mutaciones propias. **Dos sobrevivieron**; no las ignoré: pedí al revisor que comprobara si eran de verdad equivalentes.
- **Revisor: APROBADA.** Confirmó que son equivalentes por separado (dos guardas que se respaldan entre sí; juntas, 4 pruebas fallan). Probó los dos cambios de horario de Chile con 4 zonas del sistema, 4 procesos reales a la vez y un disco que falla: sin duplicados ni reenvíos. Hallazgos solo bajos (el comando muestra una traza si la base no existe; el README aún no explica el cron).
- **Lección:** *un mutante que sobrevive no siempre es una prueba que falta.* Si dos protecciones se cubren mutuamente, cada una por separado es redundante: hay que comprobarlo (¿juntas se detectan?) y dejarlo anotado, en lugar de añadir una prueba artificial.

### Vueltas 26 y 27 — T-11 y T-11b: el panel del paciente y tu primera decisión de experiencia de usuario
- **T-11:** `/paciente` con próxima sesión (la que está en curso cuenta como próxima), historial y notificaciones. Las notificaciones se muestran por su `mensaje` (que se basta solo) y el enlace «Ver la reserva» solo aparece si esa hora sigue siendo del propio paciente. 26 pruebas nuevas, 16 mutaciones detectadas y un recorrido real en Chromium a 390 y 1280 px.
- **Revisor: APROBADA, pero encontró algo que no era un error de código sino un hueco de diseño:** SPEC dice «campana con contador», pero no dice cuándo una notificación pasa a leída; el contador nunca bajaba. El implementador no inventó una regla: lo dejó anotado como duda. El revisor redactó una propuesta con 4 opciones, costo y riesgo.
- **Tu decisión (D-035):** botón «Marcar todas como leídas» (POST con CSRF) y tope de 20 notificaciones con el contador por una consulta aparte. La dejé como tarea nueva **T-11b**, antes de T-12, para que el panel del profesional use el mismo criterio.
- **T-11b:** 14 pruebas netas más (1621), 14 mutaciones; y el revisor confirmó que las 12 líneas de prueba eliminadas se reescribieron con aserciones iguales o más fuertes. Encontró además que una frase del reporte del implementador no era exacta (qué prueba mataba una mutación); la corregí en `PROGRESS.md` con una nota visible.
- **Lección:** cuando falta una regla de producto, *el agente correcto es el que se detiene y pregunta*. Aquí dos agentes lo hicieron bien (el implementador no inventó, el revisor propuso opciones) y por eso tu respuesta cabía en un mensaje.

### Vuelta 28 — T-12 Dashboard del profesional
- **Implementador:** `/profesional` con agenda (próximas sesiones e historial), horas libres con el rótulo «no reservable» cuando faltan 24 h o menos (usa la **misma** función `es_reservable` que el paciente, para que ambos paneles nunca discrepen), y notificaciones con el mismo criterio de D-035 (plantilla compartida y ruta POST delgada para el profesional). 1677 pruebas, 17 mutaciones detectadas, recorrido real en Chromium.
- **Dos hechos de proceso que vale la pena notar:** (1) al empezar, el árbol ya tenía un T-12 casi completo **sin commit** de una vuelta interrumpida; el implementador lo leyó, lo verificó y lo completó en vez de rehacerlo. (2) Escribió la hora de su entrada de PROGRESS como 09:45 cuando eran las 09:39: **otra hora inventada**, la tercera vez, a pesar de la regla 8. La corregí con nota visible en PROGRESS, TASKS y DECISIONS.
- **Mi verificación:** diff, 1677 pruebas en 4 entornos, 6 mutaciones propias (todas detectadas) y comparar la hora de la entrada con el reloj.
- **Revisor: APROBADA** (4 bajos, 9 informativos). Probó el servidor real con `curl` (anónimo, paciente, tokens falsos o de otro usuario) y comprobó que la suite lenta no la causó T-12 (el commit anterior ya tardaba lo mismo). Hallazgo curioso: si Ana reserva, cancela y Beto reserva la misma hora, los avisos viejos de Ana enlazan a la fila de Beto. Queda para T-13.
- **Lección:** una regla escrita no basta para evitar un error repetido; hay que comprobarlo mecánicamente. La próxima vez que se pueda, conviene que la verificación compare las horas de PROGRESS contra `git log` automáticamente.

### Vueltas 29 a 31 — T-13, T-13b y T-13c: la cara de la aplicación (y una prueba que fallaba "de vez en cuando")
- **T-13:** hoja de estilos con tonos calmados y tema oscuro, páginas de error en español para 400/403/404/413/500, favicon, enlace «Saltar al contenido», contrastes verificados con la fórmula WCAG (peor par de texto 5,07:1). Capturas a 360, 390 y 1280 px mirando los PNG de verdad. 1705 pruebas.
- **Lo que encontré yo, repitiendo la suite:** la suite falló 1 vez de 7 en el primer entorno. Repetí hasta capturar el fallo: el token CSRF (64 caracteres hexadecimales al azar) a veces contiene «abc» y una prueba de T-12 afirmaba que «abc» no aparecía en la página. Frecuencia real ~2 %. **El revisor de T-12 no lo vio porque corrió la suite una sola vez.** Lo convertí en **T-13b**: la prueba usa ahora un marcador imposible por azar, se auditaron 185 líneas de pruebas y se creó una guarda que reejecuta las pruebas de ausencia de texto con un token hostil.
- **Revisor de T-13: APROBADA.** Lo mejor: 58 capturas y un hallazgo real, a 360 px la columna «Cancelar» quedaba cortada y las fechas se partían a mitad. También que el flash decía «Listo: Listo, reservaste…», y que la guarda de T-13b dependía de nombres de variable.
- **Tu decisión (D-039):** el logo del encabezado lleva al panel del usuario cuando hay sesión.
- **T-13c:** a 640 px o menos cada fila de las tablas pasa a ser una tarjeta (con CSS y `data-label`, sin cambiar el HTML de las tablas), flash corregido, logo por rol, guarda más robusta, y pruebas para las 5 mutaciones de accesibilidad que sobrevivían. 1726 pruebas.
- **Mi verificación de T-13c:** diff, 47 líneas eliminadas de pruebas (la guarda se reescribió), suite 6 veces (3 seguidas + 3 variantes de entorno), y **mis propias capturas a 320 px** con un profesional y un paciente reales: tarjetas legibles, sin scroll horizontal. Aquí no lancé un revisor aparte (como en T-08c): el riesgo es acotado, hay verificación visual propia, y el revisor ya había comprobado todo salvo lo que cambió.
- **Lección:** *repite la suite varias veces antes de dar por buena una tarea;* las pruebas intermitentes no aparecen en la primera pasada y erosionan la confianza en todas las demás. Y una prueba que busca una cadena corta en una página completa es frágil si la página contiene datos aleatorios.

### Historial git resultante

```
D-018 aprobada, T-02g y notas de hora_id NULL (revisión de T-02f)
T-02f: aplicar D-016 (ON DELETE SET NULL) y D-017 (formato canónico de inicio) al esquema
D-016 y D-017 aprobadas por el humano: nueva tarea T-02f
T-02c revisión: REVIEW.md aprobado, tarea T-02e y propuestas D-016/D-017
T-02c: reforzar integridad del esquema (D-007 A-F)
D-015: quitar frase obsoleta de propuesta en una decisión ya aprobada
D-015 aprobada por el humano: opción 2 (rechazar categorías de riesgo)
T-03b revisión: REVIEW.md aprobado, tarea T-03c y propuesta D-015
D-007 aprobada por el humano: T-02c desbloqueada y antes de T-04
T-03b: endurecer el registro (tzdata, normalizar_email, límite de tamaño, pruebas)
D-007: propuesta de refuerzos de esquema pendiente de aprobación (T-02c)
T-03 revisión: REVIEW.md aprobado, tarea T-03b y backlog
T-03: registro de pacientes con CSRF propio y validación
T-02d revisión y backlog, reglas 8–10 de CLAUDE.md
T-02d: validar SECRET_KEY al servir peticiones, no en comandos CLI
T-02b revisión: REVIEW.md aprobado y tarea de seguimiento T-02d
T-02b: endurecer SECRET_KEY, fijar pytest y documentar
docs: TUTORIAL.md con el paso a paso de las vueltas T-01 y T-02
T-02 revisión: REVIEW.md aprobado y tarea de seguimiento T-02c
T-02: esquema SQLite, db.py y comando init-db
T-01 revisión: REVIEW.md aprobado y tarea de seguimiento T-02b
T-01: esqueleto del proyecto con fábrica Flask y pruebas
docs: documentación base del proyecto Agenda Psi
```

## 4. Estado actual y qué sigue

- Hecho: **T-01 a T-13** (incluidas las tareas «b/c/d/e/f/g» de endurecimiento; 1726 pruebas pasando).
- **Decisiones tuyas ya tomadas (D-035 incluida):** D-007 (esquema), D-015 (correo), D-016 (borrar horas), D-017 (formato de fecha), D-018 (carácter nulo). Pendientes: **D-020** (caracteres invisibles en el correo), **D-022** (revocar la cookie al cerrar sesión), **D-023** (un solo profesional) y **D-029** (reservar con menos de 24 h; conviene antes de T-09).
- Siguiente: **T-14** (recorrido de punta a punta y revisión final), que dividiré en partes porque acumula mucho backlog de seguridad.
- Pendiente solo tuyo: autorizar (o no) que `app/correo.py` figure en `ARCHITECTURE.md`; es una línea de documentación.

**Tu primer ejercicio:** lanza tú mismo la vuelta de T-14 con el prompt del Paso B y revisa el resultado con la lista del Paso C. Antes de dar por buena cualquier tarea, haz cinco preguntas extra: *¿rompió algo documentado?*, *¿las pruebas fallarían si quitara la protección?*, *¿el reporte afirma algo que no ejecutó?*, *¿cómo interactúa esto con las tareas futuras?* y *¿el arreglo propuesto realmente funciona?*

## 5. Consejos profesionales (lo que hace la diferencia)

1. **Los documentos mandan.** Si el agente tiene que adivinar, la documentación está incompleta. Arregla el documento, no solo el código.
2. **Tareas pequeñas con criterio de término verificable.** "Pruebas: X falla, Y pasa" es mejor que "que funcione bien".
3. **Verifica, no confíes.** Ejecuta tú `pytest` y `git status`. El reporte de un agente es una afirmación, no una prueba.
4. **Separa quien construye de quien revisa.** El revisor con contexto limpio encuentra lo que el autor ya dio por bueno.
5. **Los hallazgos se convierten en tareas.** Si quedan solo en `REVIEW.md`, se pierden.
6. **Los cambios de diseño los decide una persona.** Los agentes proponen en `DECISIONS.md`; no cambian `SPEC.md` ni `ARCHITECTURE.md` en silencio.
7. **Commits pequeños, uno por tarea.** Si algo sale mal, revertir es trivial (`git revert`).
8. **Pruebas que puedan fallar.** Pregúntate siempre: "¿esta prueba fallaría si el código estuviera roto?". Una prueba que pasa siempre no protege nada.
9. **Seguridad desde el día uno.** `SECRET_KEY`, contraseñas con hash, SQL parametrizado, CSRF. Es mucho más barato ahora que después.
10. **Mide el loop.** Antes de automatizar, mira cuántas rondas necesita cada tarea. Si necesita más de 2, la tarea era demasiado grande o la documentación ambigua.
11. **Límites siempre:** máximo de vueltas, rama aparte, sin comandos destructivos, revisión humana al final de cada fase.
12. **Cuidado con la herramienta que se detecta a sí misma.** Ejemplo real de esta sesión: `pgrep -af flask` "encontró" procesos, pero eran el propio comando de verificación. Antes de alarmarte, mira qué proceso es.
13. **Los agentes no tienen reloj.** Si les pides fecha u hora, las inventan. Dales un comando (`date`) y una regla en `CLAUDE.md`.
14. **Exige el recorrido literal.** El mejor criterio de término para algo documentado es ejecutar la documentación tal cual, en un entorno limpio. Encontró un defecto que 14 pruebas verdes no veían.
15. **Reproduce antes de crear una tarea.** Un hallazgo del revisor es una hipótesis hasta que lo reproduces.
16. **Cuando tu verificación contradice al agente, investiga la causa.** Puede ser tu entorno, el agente o el código; las tres cosas pasaron en esta sesión.
17. **"Todas las pruebas pasan" no es "está protegido".** Rompe el código a propósito (mutación) y comprueba que alguna prueba falla. En T-03, 4 de 8 mutaciones dejaron la suite en verde.
18. **No escribas tu propia seguridad sin motivo, y si lo haces, que te la ataquen.** El CSRF propio fue una decisión consciente (sin dependencias, D-009), pero por eso se revisó con mentalidad de auditor. Los fallos reales salieron de los casos límite: Unicode, Windows, tamaño de la petición.
19. **Prueba como un atacante, no solo como un usuario.** Reutilizar el token de otra sesión, enviar `rol=profesional`, mandar un correo en ancho completo: ninguno es un uso normal y todos son los que importan.
20. **El orden de las tareas es una herramienta de gestión.** Mover un arreglo antes de una tarea que lo reutiliza evita deuda sobre los cimientos.
21. **Reproduce las afirmaciones, también las de los agentes.** "Es equivalente" era una afirmación sin ejecutar. Reproducirla (637 casos) la desmontó en segundos.
22. **Separa qué decide el humano y qué decide el agente.** Un cambio de esquema, de política o de dependencia es del humano; un agente propone con opciones, costo y recomendación, y tú respondes. Deja la respuesta escrita en el repositorio, no solo en el chat.
23. **Prepara las decisiones para que sean fáciles de tomar.** Una propuesta con opciones marcables, SQL ya probado y el costo de cada una se resuelve en un mensaje. Una pregunta abierta, no.
24. **Los agentes hacen un recorrido mental, no una ejecución.** Cuando algo "es obvio", pide una prueba o una mutación que lo demuestre.
25. **Revisa también contra el futuro.** Pídele al revisor que cruce el cambio con las historias de usuario que aún no existen. Así aparecieron el borrado imposible y la UNIQUE sobre texto, que ninguna prueba presente podía ver.
26. **Una prueba que acepta lo válido y rechaza lo inválido todavía no fija el conjunto.** Si el CHECK permite un cuarto valor, nada falla. Para restricciones cerradas, prueba el conjunto exacto.
27. **Si un cambio toca algo ya aprobado, es una tarea nueva con su propia decisión.** No lo escondas dentro de otra tarea; deja la trazabilidad (qué decidiste, cuándo, qué cambió).
28. **Revisa también tu propio trabajo de orquestador.** La frase no aprobada en `ARCHITECTURE.md` salió de mis instrucciones, no del agente. Cuando el revisor señala algo, comprueba de dónde viene.
29. **Encontrar un defecto y arreglarlo bien son dos verificaciones distintas.** El implementador halló el NUL y propuso un arreglo que no funcionaba. Prueba el arreglo antes de proponerlo, y prueba varios candidatos.
30. **Una prueba que "documenta" un defecto aceptándolo es frágil.** Si el defecto se corrige, la prueba falla sin explicar por qué. Mejor una prueba que exija el comportamiento correcto o una marca `xfail(strict=True)` con instrucciones.
31. **Cada decisión de diseño tiene efectos laterales en el código futuro.** `ON DELETE SET NULL` hace peligroso `INSERT OR REPLACE`. Anota esas consecuencias en las tareas que las sufrirán.
32. **Conoce los límites de tu herramienta.** `length()` y `GLOB` de SQLite se detienen en un NUL; en otras bases de datos o lenguajes el mismo problema tiene otro nombre.
33. **Muta de forma sistemática, no solo con lo que se te ocurre.** Las 8 mutaciones del implementador dejaron vivos 14 mutantes; un script que probó todas las posiciones y variantes los encontró. Automatiza la mutación cuando el espacio es pequeño y regular.
34. **Cuando un agente corrige, vuelve a ejecutar tu propia verificación, no la suya.** Su "56/56" se confirmó porque yo lo corrí aparte, en una copia limpia.
35. **Tras una interrupción, lee el estado antes de actuar.** `git status`, `git log` y `TASKS.md` dicen dónde quedó todo; el trabajo sin commit es una hipótesis hasta que lo ejecutas.
36. **Pregunta a una pieza reutilizable si sirve para el siguiente caso.** Una función hecha para confirmaciones parecía genérica y no lo era; el revisor lo vio al cruzarla con T-10.
37. **Un mutante vivo no siempre es una prueba que falta.** Comprueba si es equivalente (¿otra protección hace lo mismo?) y si juntas se detectan; si lo son, anótalo como defensa redundante.
38. **Si falta una regla de producto, el agente se detiene y propone; no inventa.** Dos opciones, costo y riesgo bastan para que el humano decida en un mensaje.
39. **El reporte de un agente también se revisa.** Una frase inexacta sobre qué prueba mataba una mutación se corrigió con una nota visible, no en silencio.
40. **Automatiza lo que se repite.** Tres horas inventadas pese a una regla escrita: la regla no basta, hay que verificarlo con un comando.
41. **Repite la suite varias veces antes de aceptar.** Una prueba que falla el 2 % de las veces no aparece en una sola pasada; un revisor que corre la suite una vez no la ve.
42. **Una cadena corta buscada en una página completa es frágil** si la página lleva datos aleatorios (tokens, ids). Busca en la zona exacta o usa un marcador imposible por azar.

## 6. Trampas de principiante que ya viste en acción

- Dar por buena una tarea porque el agente dijo "listo" sin revisar el diff.
- Dejar que el revisor arregle el código (rompe la separación de roles).
- Aceptar cambios de esquema sin pasarlos por `DECISIONS.md`.
- Olvidar commitear la revisión y perder el rastro de por qué existe una tarea.

## 7. Cuándo pasar a la siguiente etapa de `LOOP.md`

| Etapa | Pasa a la siguiente cuando... |
|---|---|
| 1. Un agente, tú mirando | Has hecho 3 tareas y tus verificaciones del Paso C nunca encontraron sorpresas |
| 2. Generador / Crítico | El revisor encuentra problemas reales y el implementador los corrige en 1 ronda |
| 3. Loop automático | Tienes pruebas confiables y límites configurados; empieza con 2–3 vueltas, no 5 |
| 4. Paralelo | El loop automático corre limpio y tienes tareas realmente independientes (T-11 y T-12) |
