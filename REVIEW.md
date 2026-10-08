# REVIEW — T-02b (commit 7138c48)

**APROBADO**

No hay hallazgos de severidad alta. `pytest`: 14 pruebas pasan (también con `SECRET_KEY=abc FLASK_DEBUG=0` y con `FLASK_DEBUG=1` en el entorno). Sin archivos `.db` ni procesos residuales; árbol limpio.

## Cumplimiento del "Qué" / "Término" de T-02b
- (1) SECRET_KEY: cumplido. Falla fuera de debug/testing, funciona en testing y en debug. (2) `pytest>=9,<10` + D-005: cumplido (instalado 9.1.1). (3) README: sección añadida.
- Término: las pruebas cubren arranque sin clave fuera de debug/testing (falla) y en testing (funciona). Cumplido.
- Mutación en copia temporal (validación reemplazada por un valor por defecto): fallan 4 de 5 pruebas de `test_config.py`. Las pruebas limpian `SECRET_KEY` y `FLASK_DEBUG` con `monkeypatch` (autouse) y usan `tmp_path`: no dependen del entorno ni del orden.
- Formato de commit correcto (`T-02b: ...`, español). SPEC.md y ARCHITECTURE.md sin cambios. Sin dependencias nuevas (solo se acota pytest). PROGRESS.md tiene fecha y hora (`[2026-10-07 23:59]`) y sigue el formato de CLAUDE.md.

## Hallazgos

1. **MEDIA — `flask --app app init-db` falla sin `SECRET_KEY` (README.md:30, README.md:42-50; CLAUDE.md "Comandos").** `create_app` valida la clave también para comandos CLI, y `init-db` no corre en debug. Comprobado: sin `SECRET_KEY` ni `FLASK_DEBUG`, `init-db` lanza `RuntimeError`. El README muestra `init-db` (línea 30) antes de explicar la clave, y dice que solo hace falta fuera de debug "al iniciar la app", así que el paso a paso literal rompe en el segundo comando. Corrección sugerida: mover la sección `SECRET_KEY` antes de `init-db`, o indicar que `init-db` también la necesita. No hay prueba que cubra este caso.
2. **BAJA — `SECRET_KEY` con solo espacios se acepta (app/__init__.py:35).** `"   "` es verdadera, así que pasa la validación y queda como clave (comprobado, también con debug). Se puede usar `.strip()`. Faltan pruebas de este caso.
3. **BAJA — Riesgo residual en debug poco documentado (app/__init__.py:38-39, README.md:48-50).** Con `FLASK_DEBUG` verdadero (`1`, `true`, `on`...) o `DEBUG=True` la clave pasa a ser el valor público fijo `dev-no-usar-en-produccion`, que permite falsificar sesiones y tokens CSRF. El README dice "inseguro", pero no advierte que no se debe dejar `FLASK_DEBUG` activo en un entorno expuesto. El mensaje de error sí aclara que el valor de desarrollo es solo para debug/pruebas. Además la app no avisa por log al usar la clave de desarrollo.
4. **BAJA — Faltan pruebas de valores de `FLASK_DEBUG` (tests/test_config.py:38-43).** Solo se prueba `"1"`. No hay prueba de que `"0"`/`"false"` fallen sin clave (el comportamiento actual es correcto: `0`, `false`, `no` y vacío fallan; `1`, `true`, `on` permiten debug). Tampoco hay prueba con `test_config` que traiga `SECRET_KEY` (funciona: se respeta; vacía + TESTING cae a la clave de desarrollo).
5. **BAJA — Numeración/orden en DECISIONS.md (DECISIONS.md:31-34 y 37).** D-005 quedó después de D-006 (el orden es D-004, D-006, D-005). El formato respeta la plantilla y D-006 quedó intacta, pero su texto aún dice "D-005 queda reservada para T-02b", que ya está desactualizado. No se modificó (correcto); conviene ordenar en una tarea de documentación.
6. **BAJA — README.md:44.** `export SECRET_KEY=<el valor generado>` copiado literal con `<>` fallaría en bash por redirección. Es un marcador, pero se podría mostrar `export SECRET_KEY=$(python3 -c ...)`, como hace el propio mensaje de error.
