APROBADO

# REVIEW — T-01 (commit 41389e5)

Verificado: `pytest` pasa (1 prueba); `flask --app app run` responde 200 en `/`; no quedan procesos ni archivos `.db` en el repositorio; el árbol de trabajo está limpio.

## Comprobaciones pedidas
- Formato de commit: cumple (`T-01: esqueleto del proyecto con fábrica Flask y pruebas`, en español).
- SPEC.md y ARCHITECTURE.md: sin modificaciones en el commit.
- Archivos no pedidos: ninguno. Solo se tocaron `.gitignore`, `app/`, `requirements.txt`, `tests/`, `TASKS.md` y `PROGRESS.md`, todo dentro del alcance de T-01.
- Estructura vs ARCHITECTURE.md: coincide con lo que corresponde a T-01. Faltan `db.py`, `schema.sql`, `auth.py`, etc. y `static/`, que pertenecen a tareas posteriores.
- Criterio de término de T-01: cumplido.

## Hallazgos

1. **MEDIA** — `app/__init__.py:11`: `SECRET_KEY` tiene un valor por defecto público (`"dev-no-usar-en-produccion"`). Si la app se despliega sin definir la variable de entorno, las cookies de sesión y los tokens CSRF (que llegan en T-03 y siguientes) serían falsificables, lo que permitiría suplantar usuarios, incluido el profesional. No es explotable hoy porque aún no hay sesiones, pero conviene corregirlo antes de T-03/T-04. Recomendación: que el valor por defecto solo se use en modo debug o testing. Fuera de eso, exigir `SECRET_KEY` y fallar al arrancar si falta. Alternativa: generar una clave aleatoria con `secrets.token_hex()` cuando falte, con una advertencia. Documentar la decisión en `DECISIONS.md` y la variable en `README.md`.

2. **BAJA** — `requirements.txt:2`: `pytest` no tiene versión fijada, mientras que `flask` sí. Además, CLAUDE.md exige una entrada en `DECISIONS.md` por cada dependencia nueva. D-001 cubre Flask, pero no hay entrada para `pytest`. Recomendación: agregar una entrada breve en `DECISIONS.md` (por ejemplo, D-005) y fijar un rango de versiones. Otra opción es separar las dependencias de desarrollo.

3. **BAJA** — `PROGRESS.md:22`: el encabezado de la entrada usa solo la fecha. CLAUDE.md define el formato `[fecha hora] T-XX — título — rol` y falta la hora.

4. **BAJA** — `app/templates/base.html`: no enlaza `static/style.css`. Es aceptable para T-01 porque `static/` aún no existe. Hay que acordarse de añadirlo cuando se cree `static/`, ya que SPEC §6 pide un diseño que funcione bien en celular. El `viewport` ya está presente.

5. **BAJA (informativa)** — `app/__init__.py:12-14`: `DATABASE` apunta por defecto a `agenda.db` en la raíz del proyecto. El patrón `*.db` de `.gitignore` lo cubre, así que no hay riesgo. Se anota solo porque esa ruta es la que usará `init-db` en T-02.

No hay hallazgos de severidad alta. Las reglas de SPEC §4 aún no aplican a esta tarea.
