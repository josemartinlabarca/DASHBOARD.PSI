# REVIEW — T-08b Acelerar la suite sin perder cobertura (commit `f9363e1`)

Revisor: leí el diff completo (`git show f9363e1`), TASKS (T-08b), D-019, D-030, D-031, la entrada de PROGRESS, `tests/conftest.py`, `tests/test_aislamiento.py` y los archivos de pruebas tocados. Todos los experimentos y mutaciones se hicieron en copias bajo el scratchpad (`new/` = `f9363e1`, `old/` = `90636f6`, ambas con `git archive`; `m/` para mutantes; `vx/` = venv con `pytest-xdist` y `pytest-randomly` solo para el experimento). El repositorio no se tocó salvo este archivo. Sin commit.

## Veredicto: APROBADA

El cambio es solo de infraestructura de pruebas y cumple el criterio de T-08b: mismas 1124 pruebas más 11 nuevas, mismas aserciones, suite en 24-28 s (antes 61-65 s), y todas las mutaciones que probé siguen muriendo. No encontré ninguna regresión de fiabilidad ni cobertura perdida. Hay un hallazgo **media** (R-01: `/dev/shm` sin tope de capacidad, falla con un error confuso en contenedores con `/dev/shm` pequeño) y varios menores; ninguno bloquea T-09, pero R-01 conviene resolverlo antes de que la suite crezca otro tanto.

## Qué verifiqué ejecutando

| Punto | Resultado |
|---|---|
| 1. Cobertura equivalente | `pytest --collect-only` en `old` y `new`: **los 1124 identificadores de antes siguen idénticos** y la única diferencia son los 11 de `test_aislamiento.py` (`diff ids_old ids_new`). Conteo de líneas con `assert`/`pytest.raises` por archivo en `90636f6` vs `f9363e1`: **no cambia en ningún archivo salvo `test_aislamiento.py` (0 → 19)**. Líneas eliminadas de `tests/` excluyendo `conftest.py`: 26 (6 `test_config`, 10 `test_conftest_sin_tzset`, 10 `test_correo`); revisadas una a una: firmas `tmp_path` → `tmp_path_factory`, `_correr` → `_corrida` (misma clave = mismos argumentos), `communicate(timeout=3)` → lectura de stderr hasta el aviso, y la función exhaustiva partida en `revisar_rango_de_puntos_de_codigo` (cuerpo idéntico). Ninguna aserción acortada o debilitada. |
| 1. Recorrido exhaustivo de correo | Cálculo propio: para 2 a 8 procesos, los rangos `[cortes[k], cortes[k+1])` unidos reproducen **exactamente los 1.112.064 puntos** (sin duplicados ni huecos). Mutaciones en `normalizar_email` que aceptan un solo punto de código raro (U+0001, U+7FFFF, U+88000 = inicio del 2.º rango con 2 núcleos, U+10FFFD = último): **las 4 mueren** y el mensaje de fallo llega con el punto (`AssertionError: ('0x10fffd', 'Co')`). Con `os.cpu_count()=1` y con `get_all_start_methods` sin `fork` (rama en proceso) pasa (92 OK). `-W error` en `test_correo.py` y en toda la suite: sin avisos (en un solo proceso). |
| 2. Fiabilidad | Suite completa **3 veces** seguidas: 27,8 / 26,9 / 27,1 s, 1135 OK; otras 4 corridas: 24,2-26,6 s. Con `SECRET_KEY=abc` (26,9 s), `FLASK_DEBUG=1` (30,0 / 26,6 / 24,5 s), `TZ=Asia/Tokyo` (27,1 s): 1135 OK. **Cada archivo por separado**: 19 archivos OK. **50 pruebas elegidas al azar, cada una sola**: 0 fallan. Orden inverso: 1135 OK. Orden aleatorio (plugin propio, semillas 11, 12, 13): 1134 OK + 1 falla, siempre `test_zona_horaria.py::test_las_pruebas_anteriores_no_dejan_la_cache_poblada`. Dos suites a la vez (pids distintos en `/dev/shm`): ambas OK en 28,6 s. Simulando Windows (`sitecustomize` con `del time.tzset`, `os.access('/dev/shm')` falso y solo `spawn`): **1063 passed, 72 skipped, 32,2 s**; en `90636f6` con la misma simulación: 1052 passed, 72 skipped (los mismos 72 saltos: `zona_sistema` y 3 de control). |
| 2. Prueba dependiente del orden | **Confirmado en el commit anterior**: `90636f6` con la semilla 11 da 1123 OK + 1 falla en esa misma prueba. Ver R-03. |
| 3. Esquema | 17 mutaciones de `schema.sql` en copias (CHECK de `rol` ampliado, DEFAULT 50→60, `nombre` sin NOT NULL, `email` sin UNIQUE, sin COLLATE NOCASE, ON DELETE SET NULL→CASCADE, ON UPDATE CASCADE en `horas`, columna extra, índice extra, sin `UNIQUE(profesional_id, inicio)`, CHECK de `tipo` ampliado, `leida` DEFAULT 1, GLOB sin `instr(inicio, char(0))`, FK de `paciente_id` quitada, `estado` DEFAULT `reservada`, comentario SQL añadido, doble espacio): **16 de 17 mueren en `test_esquema.py`** (la primera prueba que falla es de ese archivo en las 16); solo sobrevive el doble espacio, que es equivalente (el SQL guardado se normaliza en la comparación; igual en `90636f6`). Las tres pruebas `base_real` (`SQL exacto`, `otros objetos`, `FK completo`) usan el `init_db` real: `test_con_base_real_no_hay_atajo` lo comprueba y la copia de la plantilla se compara con la real en `test_aislamiento`. |
| 3. Plantilla desactualizada | No puede ocurrir: la plantilla vive en memoria y en `tmp_path_factory` de la sesión, se crea de nuevo en cada `pytest` desde el `schema.sql` actual (las mutaciones de arriba lo demuestran: cada copia mutada partió de una sesión nueva). Nada se persiste entre corridas (`-p no:cacheprovider` o no). |
| 3. `pytest-xdist` | Instalado en un venv de prueba: `-n 2` → **1135 OK en 17,7 s**, `/dev/shm` limpio después, pero **81 avisos** `DeprecationWarning: ... multi-threaded, use of fork() may lead to deadlocks` (R-05). `pytest-randomly` (2 corridas): 1135 OK (la prueba de R-03 pasó por azar). |
| 4. Mutaciones de la app | **24 propias** (T-04 a T-08), suite completa con `--maxfail=1`: **23 mueren**, 1 sobrevive (`MARGEN_SQL_DIAS = 0`; también sobrevive en `90636f6` en `test_horas_libres/cancelar/reservar`, y es un mutante equivalente en la práctica: ver R-07). Mueren: POST como método seguro de CSRF, sin `Pragma`, cookie `HttpOnly=False`, `SameSite=None`, `PASSWORD_MIN` 7, `EMAIL_MAX` 255, `DURACION_MAX` 481, `ANIOS_MAX` 3, pasado `<` en vez de `<=` al publicar, DELETE sin `estado='libre'`, duración por defecto 45, horas libres con `<`, sin filtro `libre`, orden por id, reservar con `<`, solape con `<=`, `reservada_en` en minutos, cancelar sin limpiar `recordatorio_enviado`, botón `>` en vez de `>=`, anticipación 23 h, redirección de cancelar a otra página, `fold=1`, cancelar sin comprobar dueño. Ninguna coincide con las 13 del implementador (solo las leí). |
| 4. `init_db` y `get_db` | 8 mutaciones de `app/db.py`/`schema.sql`: mueren sin script, DROP previo, `CREATE TABLE` sin `IF NOT EXISTS`, sin `foreign_keys=ON`, sin `row_factory`. Sobreviven `init_db` sin `commit` (equivalente: `executescript` ya confirma), `PRAGMA user_version=5` en el esquema y `close_db` sin cerrar: **los tres sobreviven igual en `90636f6`** (no es regresión; ver R-07). |
| 4. Mutaciones de la propia infraestructura | 6 mutaciones de `conftest.py` mueren a través de `test_aislamiento`/`test_hash_rapido`: copiar siempre sobre una base con tablas, `tmp_path` compartido, copia al revés (escribir en la plantilla), plantilla incompleta, clave de la caché de URL constante, hash rápido apagado. Además: con `DATABASE` fijo en la fixture `app`, **3 de las 11 pruebas de aislamiento fallan** (reproduce lo dicho en PROGRESS). |
| 5. `/dev/shm` | Ver R-01, R-02 y R-06. Medí pico de uso: **≈23,5 MB** por corrida (≈20 KB por prueba); permisos del directorio `drwx------`; dos corridas simultáneas usan directorios distintos y los dos se borran. Con `/dev/shm` de 12 MB (espacio de nombres de montaje propio con `unshare -m`) la suite **se rompe a las ≈650 pruebas** con `sqlite3.OperationalError: database or disk is full`. Con `kill -TERM` el directorio **queda** en `/dev/shm`. |
| 5. Dependencias / hash rápido | `requirements.txt` sin cambios; `conftest.py` importa `jinja2` y `werkzeug` (dependencias transitivas de Flask, ya instaladas). `app/` no importa nada de `tests/` ni de `conftest`; el hash rápido solo existe en una fixture `autouse`; las pruebas `hash_real` verifican `scrypt:32768:8:1` en `app.auth`, en `create-professional` y en `hash_falso`. No puede filtrarse a producción. |
| 6. Tiempos | Ver R-04 y la tabla de abajo. |

### Tiempos medidos (equipo de 2 núcleos, `TZ=America/Santiago` del equipo)

| Corrida | Tiempo |
|---|---|
| `90636f6` (antes), 1124 pruebas | 65,1 s (PROGRESS: 63,2 s) |
| `f9363e1` (después), 3 corridas seguidas | 27,8 / 26,9 / 27,1 s |
| `f9363e1`, 4 corridas más | 24,2 / 24,5 / 24,5 / 26,6 s |
| con `FLASK_DEBUG=1` (3 corridas) | **30,0** / 26,6 / 24,5 s |
| orden aleatorio (3 semillas) | 29,1 / **30,8** / 27,4 s |
| `pytest-randomly` | 29,6 / 27,9 s |
| simulando Windows (sin `/dev/shm` ni `fork`) | **32,2 s** |
| `-n 2` (xdist) | 17,7 s |

Por fase (`--durations=0`): antes setup 31,9 s + call 30,1 s; después setup 6,1 s + call 16,6 s (el resto es recolección e importación). `--durations=10` de lo que queda: el recorrido exhaustivo de correo 2,35 s, concurrencia con procesos 0,56-0,97 s, `create-professional` por subproceso 0,79 s, y el resto son subprocesos de `test_conftest_sin_tzset.py` y `test_hash_rapido.py` (0,6-0,74 s cada uno). No queda ninguna prueba sobre 2,4 s.

### Veracidad de PROGRESS.md

Coincide: 1124 → 1135 (+11), 63 → ~28 s (yo medí 65 → 24-28 s), «1134 OK y 1 falla» con orden aleatorio y la misma prueba (también falla en `90636f6`), «3 de 11 fallan con base compartida» (reproducido), hora de la entrada `18:06` frente a `18:07:00 -03` del commit. El `fork` del recorrido y el cambio a 4 corridas del subproceso están dichos en D-031 y son ciertos. Discrepancias menores: (1) la entrada dice «no ejecutado… ni la suite simulando Windows tras estos cambios»: yo sí la ejecuté (resultado arriba) y da 32,2 s, no menos de 30 s; (2) «27-29 s» es el rango favorable: con `FLASK_DEBUG=1` y en orden aleatorio medí 30,0 y 30,8 s.

## Hallazgos

### R-01 (media) — La carpeta temporal en `/dev/shm` no comprueba capacidad: con un `/dev/shm` pequeño la suite falla con «database or disk is full»

- **Evidencia:** `pytest_configure` usa `/dev/shm` si `os.access(..., W_OK)`; no mira el espacio libre. Cada prueba deja su base hasta el final de la sesión (≈20 KB; pico medido ≈23,5 MB para 1135 pruebas). Docker y muchos CI montan `/dev/shm` de 64 MB por defecto. Reproducido: `unshare -m sh -c 'mount -t tmpfs -o size=12m tmpfs /dev/shm && python3 -m pytest -q -x'` → `648 passed, 1 error` con `sqlite3.OperationalError: database or disk is full` (en `app/auth.py:89`, que parece un fallo de la aplicación). Con 64 MB se llegaría a ≈3.300 pruebas, unas 3 veces la suite actual (T-09 a T-14 suman cientos).
- **Impacto:** fallo de la suite sin relación aparente con el código, que además no ocurre en la máquina del desarrollador. Es el riesgo principal de la aceleración: vuelve la suite dependiente de un recurso del entorno.
- **Recomendación:** tarea nueva pequeña (puede ir con T-09): usar `/dev/shm` solo si `shutil.disk_usage('/dev/shm').free` es, por ejemplo, ≥ 256 MB, y/o borrar la carpeta de cada prueba al terminar (el directorio por prueba pesa lo mismo que se ahorra del `fsync`, pero así el uso no crece con el número de pruebas). Añadir una variable de entorno para desactivar tmpfs sin pasar `--basetemp`.

### R-02 (baja) — Directorio en `/dev/shm` con nombre predecible y que queda si el proceso muere por señal

- **Evidencia:** `kill -TERM <pid de pytest>` a los 8 s de la corrida: `/dev/shm/pytest-agenda-psi-<pid>` queda (4,3 MB y creciendo hasta ~23 MB si se corta tarde); `pytest_unconfigure` solo corre con salida normal o `KeyboardInterrupt`. El nombre usa el pid (predecible) en un directorio con bit sticky compartido. Permisos del propio directorio: `0700`. Colisión de pid con un resto de otra corrida: pytest borra y recrea el `basetemp` dado, así que se recupera; un directorio ajeno con ese nombre (otro usuario) haría fallar el arranque (no lo ejecuté: solo tengo un usuario).
- **Impacto:** RAM ocupada hasta reiniciar, en CI con tiempo límite (SIGTERM/SIGKILL). En equipos de varios usuarios, un posible fallo de arranque; no hay riesgo de datos: son bases de prueba.
- **Recomendación:** backlog. Usar `tempfile.mkdtemp(prefix='pytest-agenda-psi-', dir='/dev/shm')` (nombre aleatorio, `0700`, sin colisión) y limpiar los restos de otros pids ya muertos al iniciar. Combinar con R-01.

### R-03 (baja) — `test_las_pruebas_anteriores_no_dejan_la_cache_poblada` depende del orden: es un defecto real de la prueba, anterior a T-08b

- **Evidencia:** confirmado en `90636f6` (semilla 11: 1123 OK + 1 falla) y en `f9363e1` (semillas 11, 12, 13: siempre la misma prueba; sola o inmediatamente después de `test_zona_chile_se_crea_una_sola_vez` pasa). Afirma que el `lru_cache` global de `zona_chile` está vacío sin haberlo vaciado ella: depende de que la anterior (fixture `cache_de_zona_limpia`) corra justo antes.
- **Impacto:** no oculta regresiones; impide adoptar orden aleatorio (`pytest-randomly`) o ejecutar en paralelo con `-p xdist` agrupando distinto. Bajo xdist `-n 2` pasó por azar de reparto. El implementador acierta al decir que no es suyo, pero T-08b invita a reducir la dependencia de orden y esta prueba queda como la única.
- **Recomendación:** backlog (tarea de 3 líneas): que la prueba use la fixture `cache_de_zona_limpia`, ejecute una petición que use la zona y verifique que el teardown la deja vacía, o dentro de la prueba haga `cache_clear()` y compruebe que `zona_chile()` vuelve a poblarla. No es defecto de la entrega.

### R-04 (baja) — El margen frente a 30 s es estrecho y a veces no se cumple; el criterio depende del equipo

- **Evidencia:** 24,2-27,8 s en condiciones normales, pero 30,0 s (`FLASK_DEBUG=1`), 30,8 s (orden aleatorio) y 32,2 s (Windows simulado sin tmpfs ni `fork`). Las mediciones del implementador (27-29 s) son el extremo favorable. El ruido entre corridas idénticas es de ±2 s.
- **Impacto:** `python3 -m pytest` «en menos de 30 s» (criterio de TASKS) se cumple en lo normal pero no es robusto; un criterio absoluto en un equipo de 2 núcleos fallará por ruido, y las tareas siguientes que sumen 3-4 s lo romperán sin que nadie haya empeorado nada.
- **Recomendación:** decisión humana: reformular el criterio como relativo (p. ej. «no más de 30 s en el equipo de referencia o ≤ 45 % del tiempo de antes») o aceptar «≈ 30 s». Lo que queda es sobre todo subprocesos reales (≈ 12 s según D-031) y concurrencia; no hay ganancia fácil adicional.

### R-05 (baja) — El reparto con `fork` ahorra ≈ 0,7 s y trae un aviso/riesgo bajo `xdist` o en procesos con hilos

- **Evidencia:** el recorrido tarda 2,35 s en 2 núcleos frente a 2,36 s con `cpu_count=1` en la suite completa (la prueba sola: 1,83 s el archivo entero con 2 procesos frente a 2,53 s con 1). Bajo `-n 2` aparecen 81 `DeprecationWarning` («multi-threaded, use of fork() may lead to deadlocks»); sin xdist no hay aviso. Con muchos núcleos abre hasta 8 procesos por proceso de prueba.
- **Impacto:** ganancia casi nula frente a la complejidad; si algún día se corre con `-W error` o con xdist en un equipo cargado, es una posible fuente de fallos intermitentes (interbloqueos al hacer `fork` con hilos).
- **Recomendación:** ignorar por ahora; si crece el costo, preferir `forkserver`/`spawn` o volver a un único proceso. La corrección está bien: mutaciones y reparto verificados.

### R-06 (informativa) — Las carpetas temporales de las pruebas ya no se conservan al fallar

- **Evidencia:** `tmp_path` propio con contador ignora la política de retención de pytest (`tmp_path_retention_policy`) y `pytest_unconfigure` borra todo en `/dev/shm`. Antes, pytest conservaba las 3 últimas sesiones para inspeccionar la base de una prueba fallida.
- **Impacto:** depurar un fallo con la base en mano exige pasar `--basetemp=ruta` (única forma de evitar `/dev/shm`). No está documentado.
- **Recomendación:** documentar en README/TUTORIAL junto con la variable de R-01 (ignorar si se resuelve R-01).

### R-07 (informativa) — Supervivientes que no son regresión

- **Evidencia:** `MARGEN_SQL_DIAS = 0` sobrevive en `old` y `new` (es un margen defensivo del SQL que Python vuelve a filtrar; no construí un caso que lo distinga, por lo que lo trato como equivalente); `init_db` sin `commit`, `PRAGMA user_version` en el esquema y `close_db` sin cerrar sobreviven igual en `90636f6`. `test_aislamiento` compara `user_version` de la plantilla con la real, pero ninguna prueba exige un valor.
- **Impacto:** ninguno nuevo.
- **Recomendación:** ignorar; si se quiere, backlog para una prueba de `close_db` (cierra la conexión de la petición) cuando se toque `app/db.py`.

### R-08 (informativa) — Dependencias de la infraestructura con API privada y de hilo

- **Evidencia:** la caché de URL usa `Rule._compile_builder`, `Rule._trace`, `Rule._converters` (privados de Werkzeug 3.1.8 instalado; `requirements.txt` solo exige Flask `>=3.1,<3.2`, que admite otras versiones de Werkzeug 3.x). La plantilla es una conexión `:memory:` creada en el hilo principal: usarla desde otro hilo da `ProgrammingError` (verifiqué el comportamiento con un script); hoy ninguna prueba llama `init_db()` desde un hilo (los hilos de `test_cancelar`, `test_login` usan archivos ya creados).
- **Impacto:** un cambio interno de Werkzeug rompería la suite con `AttributeError` visible (no silencioso). Una prueba futura que cree su base dentro de un hilo fallará con un mensaje que no apunta a `conftest`.
- **Recomendación:** backlog: anotar la restricción en D-031 o hacer que la caché de URL se desactive sola si falta el atributo; `plantilla.backup` puede usar `check_same_thread=False`.

### R-09 (informativa) — Lo demás que revisé sin hallazgos

- Base plantilla: `Connection.backup` copia páginas e `user_version`; `PRAGMA foreign_keys` es por conexión y `get_db` lo activa igual; el atajo solo actúa con la base vacía y si hay tablas ejecuta el `init_db` real (probado en `test_aislamiento` y por mutación).
- Caché de plantillas Jinja: la clave incluye el hash del fuente; no puede servir una plantilla obsoleta dentro de una sesión (el fuente no cambia) ni entre sesiones (vive en memoria).
- Caché de constructores de URL: la clave incluye `append_unknown`, el trazado de la regla, los convertidores con sus atributos y los valores por defecto; lo demás que usa `_compile_builder` sale de esos mismos datos. Mutación de la clave a constante muere.
- `test_conftest_sin_tzset.py`: las 4 corridas distintas cubren los 4 argumentos distintos que usaban las 6; ninguna aserción pierde fuerza. Efecto colateral: si falla una corrida fallan en bloque las pruebas que la comparten (correlación, no pérdida).
- `test_flask_run_real_avisa...`: la lectura de stderr con hilo termina cuando aparece el aviso, el proceso se detiene y se espera; no queda proceso vivo (`finally` + `kill`).
- Doble importación de `conftest` (como `conftest` y como `tests.conftest` en `test_aislamiento`/`test_hash_rapido`): ya existía; `tests.conftest` se importa al recolectar, cuando `init_db` y `Rule._compile_builder` aún son los reales, así que `cf._init_db_real` y `cf._compilar_constructor_real` son lo que dicen ser.

## Qué NO verifiqué

- Windows ni macOS reales (solo la simulación descrita: sin `tzset`, sin `/dev/shm`, sin `fork`).
- Python 3.11/3.12 (solo 3.13.16); Werkzeug distinto de 3.1.8.
- Colisión o ataque con un directorio de otro usuario en `/dev/shm` (un solo usuario), ni `SIGKILL` (solo `SIGTERM`).
- Las 13 mutaciones del implementador (las leí; las mías son otras).
- La suite con `pytest` a secas del `PATH` (el ejecutable `/root/.local/bin/pytest` usa un intérprete sin `jinja2`; `python3 -m pytest` sí funciona; no comprobé si en `90636f6` ocurre lo mismo con `flask`: es un detalle del equipo).
- Rendimiento con 8 o más núcleos.
