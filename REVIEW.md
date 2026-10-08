# REVIEW — T-02c (commit cd9f209) — Revisor

**APROBADO.** No hay hallazgos altos. El esquema implementa exactamente D-007 A–E, `ARCHITECTURE.md` cambió dentro de lo que autoriza F (con un matiz menor, hallazgo 8), `pytest` da 187 OK (6,0 s; antes 109 en 5,1 s), no hay `.db` ni procesos residuales. Los hallazgos 1 y 3 deben resolverse antes o durante T-05; el 2 conviene cerrarlo en T-03c o T-05.

Todo lo de abajo se ejecutó en copias en el scratchpad (SQLite 3.45.1). El repositorio no se modificó.

## Hallazgos (por severidad)

### 1. MEDIA — Una hora libre con historial no se puede eliminar (contradice US-5)
- **Archivo:** `app/schema.sql:31` (`hora_id INTEGER REFERENCES horas (id)`, sin `ON DELETE`); afecta a T-05 y T-09.
- **Comprobado:** con `PRAGMA foreign_keys=ON` (así abre `db.py`), reservar → crear notificación de confirmación → cancelar (UPDATE que limpia `paciente_id` y `reservada_en`, pasa el CHECK A) → crear notificación de cancelación → `DELETE FROM horas WHERE id=1 AND estado='libre'` falla con `IntegrityError: FOREIGN KEY constraint failed`. La hora está legítimamente `libre`, así que la regla "elimino una hora disponible que aún no esté reservada" (US-5) queda incumplida para toda hora que alguna vez se reservó. No es un defecto de T-02c (la FK existía), pero T-02c fijó el esquema y T-05 lo chocará.
- **Recomendación (decide el humano, porque cambiar el esquema aprobado exige decisión):**
  - Opción mínima sin tocar el esquema: en T-05, eliminar dentro de una transacción `UPDATE notificaciones SET hora_id = NULL WHERE hora_id = ?` y luego el `DELETE ... WHERE id=? AND estado='libre'`. El mensaje de la notificación conserva el contexto.
  - Opción en el esquema: `hora_id INTEGER REFERENCES horas (id) ON DELETE SET NULL` (verificado: la notificación queda con `hora_id` NULL). Requiere D-016, actualizar `ARCHITECTURE.md` y recrear `agenda.db`.
  - Resolver en **T-05** (antes de implementarla) y añadir una prueba "reservar, cancelar y eliminar la hora" que hoy fallaría. Ninguna de las 187 pruebas fija la política de borrado (mutación `ON DELETE SET NULL/CASCADE` sobrevive).

### 2. MEDIA — Mutaciones supervivientes: el conjunto exacto de valores no está fijado
- **Archivo:** `tests/test_esquema.py:167-177` (tipo), `:194-217` (dominios); `tests/test_db.py` (`rol`, `estado`).
- **Comprobado** (copia del proyecto, suite completa):
  - Sobreviven (187 OK): `tipo` con cuarto valor `'otro'`; `estado` con `'cancelada'`; `duracion_min` con tope superior extra (`< 100`); `rol` comparado con `lower(rol)` (aceptaría `'Paciente'`); `ON DELETE SET NULL/CASCADE` en FK; `AUTOINCREMENT` (inocuo).
  - No sobreviven pero con detección débil (1 o 2 pruebas): quitar D (1), `libre` sin chequear `reservada_en` (2), `duracion_min >= 0` (1), `reservada` sin exigir `paciente_id` (1), `lower(tipo)` (1).
  - Detectadas bien: quitar A (7), NOT NULL (3 cada uno, comprobado en `nombre` y `mensaje`), quitar NOCASE, quitar cada FK, `IN (0,1,2)`, `COLLATE BINARY`, `UNIQUE(inicio)`, `UNIQUE(profesional_id, paciente_id)`, `DEFAULT 60`, quitar `IF NOT EXISTS`, quitar `DEFAULT 'libre'`.
  - El informe del implementador ("ninguna mutación quedó en verde") es cierto solo para sus 15 mutaciones; no hay verificación de ampliaciones del conjunto.
- **Recomendación (técnica más simple):** una prueba que lea `SELECT sql FROM sqlite_master WHERE name=?` y compare con el `CREATE TABLE` esperado normalizado (espacios colapsados) fija todo de una vez, incluido el conjunto exacto de `tipo`, `rol` y `estado`, `ON DELETE`, `COLLATE` y el CHECK A, con el costo de que cualquier cambio legítimo de esquema obligue a editar la prueba (deseable aquí). Alternativa más granular: para cada CHECK de conjunto, probar un valor "vecino" inválido (`'otro'`, `'cancelada'`, `'admin'`, `'Paciente'`, `duracion_min=1` válido y `-1`/`0` inválidos). Añadir además un caso "A completo": reservada con todo + libre con todo vacío, ya existen, pero hoy no hay prueba que combine `libre` con solo `reservada_en` en un UPDATE.

### 3. MEDIA — `UNIQUE (profesional_id, inicio)` compara texto, no instantes
- **Archivo:** `app/schema.sql:23`; `ARCHITECTURE.md` (campo `inicio`: "ISO 8601, hora local de Chile").
- **Comprobado:** tras insertar `'2026-11-01T10:00'` se aceptan sin error `'2026-11-01 10:00'`, `'2026-11-01T10:00:00'`, `'2026-11-01T10:00:00-03:00'` y `'2026-11-01T10:00:00-04:00'` (5 filas, mismo instante o casi). Solo el texto idéntico es rechazado.
- **Riesgo:** D deja de proteger si T-05 acepta formatos distintos (el `<input type="datetime-local">` envía `YYYY-MM-DDTHH:MM`; `isoformat()` de Python agrega segundos y desfase). Peor, la comprobación de solape de la regla 3 y las consultas "futuras" (T-06) usarán comparación de texto: `'...T10:00'` vs `'...T10:00:00-03:00'` se ordena y compara mal, y el cambio de horario de Chile (desfase -03/-04) agrava las comparaciones con desfase.
- **Recomendación (solo propuesta, documentar en T-05 y en una D-0xx):** formato canónico único `YYYY-MM-DDTHH:MM:SS` en hora local de Chile **sin desfase**, normalizado con `datetime.fromisoformat(...).replace(tzinfo=None)` y `isoformat(timespec="seconds")` antes de guardar; comparar con el "ahora" convertido al mismo formato. Añadir una prueba que cree horas con las variantes anteriores y compruebe que la segunda se rechaza (por la aplicación o por UNIQUE). Opcional (humano): `CHECK (inicio GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]')` para forzarlo en el esquema. Nota: `creado_en` del registro sí lleva `-03:00`; la inconsistencia entre campos conviene resolverla en la misma decisión.

### 4. BAJA — `init-db` sobre una base antigua termina con éxito sin avisar
- **Archivo:** `app/db.py` (`init_db`), `README.md:35-48`, D-006.
- **Evaluación:** el riesgo es real pero acotado: quien actualiza el código y conserva `agenda.db` cree tener CHECK, UNIQUE y NOCASE y no los tiene; las pruebas no lo ven porque usan bases nuevas. Es baja mientras la base sea de práctica (D-007 lo acepta); sube a media si algún día hay datos reales o si T-05 asume que D protege.
- **Recomendación mínima (sin implementarla):** guardar `PRAGMA user_version = N` al final de `init-db` y, si la base existe con otro valor (o `user_version=0` con tablas), imprimir un aviso en rojo ("el esquema es de una versión anterior; borra agenda.db"). Alternativa aún más simple: comparar `SELECT sql FROM sqlite_master` contra el `CREATE TABLE` de `schema.sql` y avisar si difieren. Decide el humano; podría ir en T-02c-bis o junto al hallazgo 1 si ese cambio de esquema se aprueba.
- **README:** la nota es exacta y ejecutable (`rm agenda.db` en la raíz del proyecto, que es la ruta por defecto de `app/__init__.py:21-22`). Imprecisiones menores: no dice que con `DATABASE` definido el archivo a borrar es otro, ni que hay que parar el servidor antes.

### 5. BAJA — La afirmación de D-007 sobre la regla §4.5 es cierta solo en parte
- **Archivo:** `DECISIONS.md` D-007 opción D ("hace innecesario un índice propio para la regla §4.5").
- **Análisis:** con un único profesional, dos horas con el mismo `inicio` no pueden existir (D), por lo que un paciente no puede tener dos reservas a la misma hora **idéntica**. Pero (a) horas con inicios distintos que se solapan (10:00 y 10:30, ambas reservadas por el mismo paciente) son aceptadas por el esquema (comprobado) y quedan cubiertas solo si la aplicación impide el solape (regla 3) y sin carrera; (b) con un segundo profesional (hoy fuera de alcance, D-004) el mismo paciente puede reservar el mismo `inicio` con ambos (comprobado: aceptado), y habría que añadir una comprobación a nivel de paciente.
- **Recomendación:** en T-05 comprobar solape y hacer el INSERT en una sola transacción `BEGIN IMMEDIATE` (check-then-insert tiene carrera); en T-07 una prueba de "mismo paciente, dos horas solapadas" que documente qué capa la rechaza. No requiere cambio de esquema.

### 6. BAJA — Interacción con D-003 y el recordatorio (sin hallazgo, comprobado)
- El UPDATE atómico de D-003 cumple el CHECK A (rowcount 1). La cancelación solo funciona si limpia `paciente_id` y `reservada_en` a la vez; `UPDATE horas SET estado='libre'` o `SET estado='reservada'` solos fallan con `IntegrityError` (deseado). `UPDATE horas SET recordatorio_enviado=1` pasa (T-10 OK). Recomendación: en T-08, capturar `IntegrityError` en la cancelación como error interno (no como mensaje de usuario).

### 7. BAJA — NOCASE y `normalizar_email` son coherentes; el registro maneja el rechazo
- **Archivo:** `app/auth.py:96-98`, `app/correo.py`, `tests/test_registro.py:96-118`.
- **Comprobado:** `normalizar_email` siempre devuelve minúsculas casefold, así que para ASCII no hay correo que el normalizador deje distinto y NOCASE considere igual (probado con I/i/K/k/S/s y variantes Unicode: ß/ss, ſ/s, Σ/ς/σ, ancho completo). NOCASE solo actúa ante INSERT directos que eviten la normalización (p. ej. un futuro `create-professional` mal escrito); en ese caso el `IntegrityError` se captura igual.
- **Riesgo residual:** `except sqlite3.IntegrityError` es genérico y muestra el mensaje de "correo duplicado" ante cualquier violación (un NOT NULL o CHECK futuro mostraría un mensaje equivocado). No es nuevo, pero T-02c añade más restricciones. Recomendación (T-03c o T-04): distinguir por `str(e)` que contenga `UNIQUE constraint failed: usuarios.email` y relanzar el resto. Ninguna prueba de registro ejerce el rechazo por NOCASE como tal (todas pasan por el normalizador); lo cubre `test_email_con_otras_mayusculas_rechazado_por_la_base` en `test_esquema.py`, suficiente. Observación para T-03c: `normalizar_email('İ@x.cl')` produce `i̇` (con marca combinante Mn), que D-015 rechazará; no es un problema de esquema.

### 8. BAJA — Texto añadido a `ARCHITECTURE.md` por encima de lo autorizado
- **Archivo:** `ARCHITECTURE.md` (tabla de módulos, fila `seguridad.py`).
- La fila dice "No debe hacer: Reglas de negocio **ni acceso a la base de datos**"; D-007 F solo menciona "reglas de negocio". Es coherente con el código (`seguridad.py` no usa la base), pero es una restricción de diseño nueva. También se agregaron aclaraciones entre paréntesis a `email` y `UNIQUE`, dentro del espíritu de A–E. Recomendación: que el humano confirme o quite la frase añadida; no bloquea.
- Por lo demás, D-007 conserva su texto de decisión y solo añade la línea "Implementada"; el esquema no tiene ningún cambio fuera de A–E (el diff de `schema.sql` es exactamente A, B, C, D y E; no hay columnas nuevas ni cambios de DEFAULT/NOT NULL/FK). `ARCHITECTURE.md` coincide con `schema.sql` campo por campo. `correo.py` queda fuera de `ARCHITECTURE.md`, con la nota correcta en `PROGRESS.md` ("Bloqueos").

### 9. BAJA — Calidad y mantenibilidad de las pruebas nuevas
- **Archivo:** `tests/test_esquema.py`, `tests/test_db.py:83-133`.
- Legibles: helpers `insertar_hora`/`insertar_notificacion`/`rechazada`, secciones por opción, IDs de parámetros claros. La suite subió ~0,9 s (5,1 → 6,0 s), sin dependencia de orden. Estable ante versiones de SQLite: se compara con subcadenas (`"CHECK constraint failed"`, `"UNIQUE constraint failed: horas.profesional_id, horas.inicio"`, `"NOT NULL constraint failed: tabla.col"`), que no cambian entre 3.x.
- Mejoras:
  - Redundancia: `test_table_info_declara_not_null` (15 casos) duplica lo que ya comprueba `test_comando_init_db` con `COLUMNAS_ESPERADAS`, y `test_foreign_key_list_declara_cada_fk` es parcial frente al comportamiento ya probado; son una "triple cobertura" (por eso 3 fallos por NOT NULL, tal como informó el implementador). Podrían reemplazarse por la comparación de `sqlite_master` del hallazgo 2.
  - `rechazada(...)` solo comprueba el prefijo "CHECK constraint failed": no distingue cuál CHECK falló; en `test_hora_incoherente_rechazada` y las de dominio las filas son por lo demás válidas, así que está bien, pero la prueba del `tipo` pasaría si fallara otro CHECK.
  - `test_not_null_rechaza_null` para `usuarios` inserta y borra una fila de control con una rama distinta para cada tabla; es el caso menos legible (conviene tres pruebas pequeñas o fábricas por tabla).
  - `test_nocase_solo_cubre_ascii` fija una limitación de SQLite; aceptable, documenta D-007 E.
  - `test_el_solape_parcial_no_lo_controla_el_esquema` fija un comportamiento "negativo" que habrá que invertir si T-05 pasa la regla al esquema (comentario ya lo explica).

### 10. BAJA — Proceso
- Formato de commit correcto (`T-02c: ...`, atribuciones al final). `SPEC.md`, `REVIEW.md` anterior (solo lo reemplaza este revisor) y `app/correo.py` no se tocaron en el commit; tampoco otras pruebas ni código de `app/` aparte del esquema (`git diff 273c9c9 HEAD -- app/` solo muestra `schema.sql`).
- Afirmaciones del informe verificadas:
  - "Ninguna prueba existente tuvo que cambiarse": cierto; el único cambio en pruebas viejas es `test_comando_init_db`, que la tarea pedía.
  - "Un primer commit salió sin las ediciones de documentación y lo corregí con --amend": cierto; `git reflog` muestra `a8870b5` (6 archivos, sin `DECISIONS.md` ni `PROGRESS.md`) reemplazado por `cd9f209` (8 archivos) mediante `commit (amend)`. No se publicó (sin remoto).
  - "15 NOT NULL, 3 cada uno": cierto (comprobado con `nombre` y `mensaje`: 3 fallos cada uno; se explica por la triple cobertura del hallazgo 9).
  - "Nota sobre `correo.py` en PROGRESS.md": presente (sección "Bloqueos").
  - Mutaciones citadas (A: 7, D: 1, NOCASE y demás): reproducidas (A: 7, D: 1, NOCASE detectada).
  - Hora de la entrada de PROGRESS (`2026-10-08 00:50`) coincide con `git log` (00:50:00, posterior al commit anterior de las 00:38).
- `PROGRESS.md` indica "Próxima tarea: T-03c"; correcto según TASKS.md. Sin archivos `.db`, procesos ni cambios sin confirmar en el repositorio.
