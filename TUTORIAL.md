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

### Historial git resultante

```
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

- Hecho: **T-01, T-02, T-02b, T-02d** (25 pruebas pasando).
- Pendiente de tu decisión: **T-02c** (refuerzos del esquema). Lee los hallazgos con `git log -p -- REVIEW.md`, decide cuáles aceptas, regístralos en `DECISIONS.md` como D-007 y actualiza `ARCHITECTURE.md`. Debe estar hecha antes de T-05, pero **no bloquea T-03 ni T-04**.
- Siguiente sin decisión tuya: **T-03** (registro de pacientes).
- Orden sugerido: T-03 → T-04 → T-02c → T-05 → ... (las dependencias en `TASKS.md` ya lo imponen).

**Tu primer ejercicio:** lanza tú mismo la vuelta de T-03 con el prompt del Paso B y
revisa el resultado con la lista del Paso C. Antes de dar por buena cualquier tarea, haz
una pregunta extra: *¿esto rompió algo que ya estaba documentado?* Hazlo antes de pensar en automatizar.

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
