# REVIEW — T-02d (commit f4a66d8)

**APROBADO**

No hay hallazgos de severidad alta. Los puntos 1–5 de "Qué" y el "Término" se cumplen. `python3 -m pytest -q`: 25 pruebas pasan, también con `SECRET_KEY=abc`, `FLASK_DEBUG=0`, `FLASK_DEBUG=1` y ambas a la vez (el fixture autouse `entorno_limpio` aísla el entorno). Árbol limpio, sin `.db` ni procesos residuales.

## Verificación empírica

- **Reversión (copia temporal con `app/__init__.py` de HEAD~1):** fallan 11 de las 25 pruebas, 14 pasan. Las pruebas nuevas detectan el cambio.
- **D-008 con `test_client`, sin clave y sin debug:** `/`, `/static/a.txt`, `/nada` (404) y una ruta de blueprint con su propio `before_request` responden 500. Un `errorhandler(500)` personalizado no lo evade (sigue siendo 500) y `before_request` registrados después no se ejecutan antes que el hook, porque se registra dentro de `create_app`. `TESTING=True` puesto después de crear la app no cambia nada (la clave queda `None`).

## Hallazgos

1. **Baja — `app/__init__.py:19-26` (DEBUG/TESTING activos por error).** El diseño no mitiga `FLASK_DEBUG=1` heredado del entorno en un servidor real (por ejemplo gunicorn): `Flask()` lo lee solo, se usa la clave pública y el 500 desaparece sin ningún aviso. Solo lo cubre la advertencia del README (`README.md`, sección `SECRET_KEY`). `TESTING` no se lee del entorno, solo de `test_config`, así que el riesgo es menor. Tampoco se rechaza una clave débil o igual a `SECRET_KEY_DESARROLLO` definida a mano. Propuesta: un `app.logger.warning` cuando se use la clave de desarrollo, y en una tarea futura una configuración de producción explícita.
2. **Baja — `app/__init__.py:53-58` (costo aceptado de D-008).** El mensaje sí llega al operador: cada petición registra `ERROR` con traceback y el texto completo, con la forma de generar la clave. Pero solo aparece al llegar la primera petición. Con `flask run` el arranque parece normal, y el cliente recibe un 500 genérico sin pista. Es más ruidoso que un aborto limpio (un traceback por petición). **Mejora propuesta (no implementada):** al crear la app, si la clave falta y no hay debug/testing, emitir `app.logger.warning(MENSAJE_SIN_SECRET_KEY)` una vez. Habría que excluir `init-db`, que usa la misma fábrica, por ejemplo con el nivel `INFO` o un texto del tipo "se exigirá al servir peticiones".
3. **Baja — `tests/test_config.py` (cobertura de D-008).** Las pruebas solo hacen `GET /`. Ninguna cubre `/static/...`, un 404 ni un blueprint, que es justo la garantía que D-008 afirma ("también 404 y estáticos"). Hoy es cierto (verificado arriba), pero no está protegido contra regresiones. Basta una prueba parametrizada sobre `/nada` y `/static/x`.
4. **Baja — `pytest.ini`.** La justificación es válida: el `pytest` literal del README falla en un venv limpio con `ModuleNotFoundError: app`, y el "Término" exige que el recorrido literal funcione. `pythonpath = .` es adecuado y simple (exige pytest>=7, y está fijado en >=9). Alternativas igual de simples: un `conftest.py` vacío en la raíz, o `python -m pytest` en el README y CLAUDE.md. El archivo estaba fuera del alcance declarado y `testpaths = tests` es un extra no pedido. Se avisó en PROGRESS.md pero no hay entrada en `DECISIONS.md`. No agrega dependencias, así que CLAUDE.md no lo exige. Aun así convenía una línea en D-008 o una decisión corta.
5. **Baja — `PROGRESS.md` (entrada T-02d).** Tiene fecha y hora, pero `10:30` no coincide con la hora del commit (00:05 -03). Además, dice que verificó con `git stash` y en el último commit de la sección se menciona el stash, aunque el procedimiento fue otro. Formato de entrada correcto salvo la hora.
6. **Baja — `README.md` (comandos).** Los comandos funcionan tal cual: `export SECRET_KEY=$(python3 ...)` sin `<>`, bloque PowerShell con `python -c` (en PowerShell `python` es lo habitual) y la advertencia de `FLASK_DEBUG` es exacta. Es coherente con CLAUDE.md. Detalle menor: la advertencia dice "ni `--debug`" y el recorrido principal usa `run --debug`, lo cual es correcto para desarrollo, pero conviene aclarar "solo en tu máquina". La nota de PROGRESS (`FLASK_DEBUG=off` no cuenta como falso) no está en el README.

## Otros puntos revisados (sin hallazgos)

- **DECISIONS.md:** orden D-001…D-006, D-008. D-007 sigue sin usarse (reservada en TASKS.md para T-02c). D-006 conserva su significado y perdió solo la frase obsoleta. D-008 coincide con el código (`strip()`, no se modifica una clave válida, `before_request`, `RuntimeError`).
- **Commit:** `T-02d: descripción corta`, en español, con las líneas de atribución. `SPEC.md`, `ARCHITECTURE.md` y `requirements.txt` sin cambios; sin dependencias nuevas. SQL y CSRF no tocados.
