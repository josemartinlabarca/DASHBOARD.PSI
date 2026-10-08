# REVIEW.md — Revisión de T-03c (commit `e50d5ea`)

Revisor, 2026-10-08. Python 3.13.16 (Unicode 15.1), SQLite 3.45.1, Werkzeug 3.1.8, tzdata 2026.5 instalado.
Todo lo ejecutado se hizo en copias bajo el scratchpad (`.../scratchpad/{c1,old,new,m}`); el repo no se tocó
(`git status --short` solo muestra `DECISIONS.md`, el cambio sin commitear del orquestador, ignorado).
Leído: `git show e50d5ea` completo, `CLAUDE.md`, texto de T-03c y T-04 en `TASKS.md`, D-010 a D-015 y D-019,
`app/correo.py`, `app/auth.py`, `tests/conftest.py`, `pytest.ini`, las pruebas nuevas y la entrada de PROGRESS (con "Bloqueos").

## Qué se verificó ejecutando

- `pytest` en el repo: **470 passed** (9,4 s). Conteo: 390 en `d8d00f3` (`git archive` + pytest) y 470 en `e50d5ea` = +80. Coincide con PROGRESS.
- Tiempos, `git archive` de ambos commits, dos corridas alternadas: antes 11,5 y 11,0 s; después 11,3 y 10,4 s;
  después sin la prueba exhaustiva 8,3 s; `tests/test_registro.py` 6,7 s (40) -> 2,7 s (52). Coinciden con PROGRESS.
- Mutaciones en copia con la **suite completa** (fallos; entre paréntesis lo que dice PROGRESS): sin 1.ª NFKC 3 (3), sin 2.ª NFKC 3 (3),
  `isspace()`->`== " "` 7 (7), sin `tzdata` en requirements 1 (1), solo Cc/Cf 11 (11), sin Mn/Mc/Me 13 (13), solo Mn 4 (4),
  sin `isinstance` 7 (7), sin Co 5 (5), sin Cn 5 (5), Cc/Cf/Cn (sin Co ni Cs) 7 (PROGRESS dice 9 para "sin Co/Cn/Cs": no es el mismo
  mutante, no hay discrepancia real), duplicado solo por mensaje 2 (2), cualquier `IntegrityError` como duplicado 9 (8; mi mutante
  es `return True`), `hash_real` ignorado 2 (2), sin `db.rollback()` **0 (0)**. Todos los números coinciden salvo diferencias de mutante.
- Las dos mutaciones de NFKC las atrapa la prueba exhaustiva Y las parametrizadas; la frase falsa de T-03b está corregida con nota visible.
- Sondeo de `normalizar_email` con ~90 casos reales y un barrido de los 1.112.064 puntos de código (ver R-01 a R-03).
- Hash: `auth.generate_password_hash('x')` sin conftest da `scrypt:32768:8:1`; con `hash_real` el hash guardado es de costo completo.
- Carrera real: 8 hilos registrando el mismo correo con la app real (3 repeticiones): siempre 1 x 302 + 7 x 200 (mensaje de duplicado), 1 fila.
- `in_transaction` tras un INSERT fallido por UNIQUE: `True`; tras `rollback()`: `False`.
- NO verifiqué: nada en navegador (R-04 es por especificación HTML), otras versiones de Python/SQLite, Windows (R-09), servidor con `flask run`
  (T-03c no lo exigía), ni comportamiento con Unicode distinto de 15.1.

## Hallazgos

### R-01 — D-015 opción 2 está bien implementada, pero deja una clase entera de invisibles y mudos: no solo 3 caracteres — media
Evidencia: `normalizar_email("a⠀@x.cl")`, `("aㅤ@x.cl")`, `("aᅟ@x.cl")`, `("aﾠ@x.cl")` (-> `aᅠ`), `("a�@x.cl")` se **aceptan**
(confirmado; el implementador tiene razón). Pero la lista de PROGRESS/D-013 (hangul, braille, U+FFFD) está **incompleta**. Barrido de los
140.888 puntos que pasan sin cambio: quedan, entre otros, U+FFFC (objeto de reemplazo), U+2400..U+2422 (símbolos de nulo/espacio/en blanco),
U+303F, U+1D159, U+13441/13442 (jeroglífico en blanco) y siete "gap filler" de puntuación (U+A8F9, U+1144E, U+11945, U+11C44/45, U+11F48, U+10AF6);
además todo el rango `Po/Pd/Sm/So/Sk/Sc` no ASCII: p. ej. U+2010 (guion) y U+00B7 (punto medio) se ven como `-` y `.`
(`juan‐perez@x.cl` != `juan-perez@x.cl`). Categorías aceptadas no ASCII: Lo 130.075, So 5.729, Ll 1.501, Sm 900, No 749, Nd 600, Po 552, etc.
Gravedad: no hay nuevo vector de seguridad respecto al riesgo ya aceptado (D-013: la «е» cirílica da el mismo duplicado visual) y el correo no se
muestra a terceros en ninguna plantilla actual (solo `registro.html`; SPEC no pide mostrarlo). Efecto real: cuentas duplicadas indistinguibles a la vista
y usuarios que no pueden reproducir su correo (p. ej. si pegan uno con relleno invisible). Un `a⠀@x.cl` tiene la misma apariencia que `a@x.cl`.
Opciones para la decisión humana (D-0xx nueva):
 A. Aceptar y dejarlo documentado como hoy (corregir en D-013 la lista: es una clase, no tres casos).
 B. Lista de permitidos por categoría: ASCII imprimible tal cual; no ASCII solo si `Ll/Lu/Lt/Lm/Lo/Nd/Nl/No` (se descartan So, Sk, Sm, P*, Sc, Zs) más una lista
    explícita corta de rellenos `Lo` (U+115F, U+1160, U+3164, U+FFA0, U+13441, U+13442). Cuatro líneas, sigue admitiendo `señor@`, `müller@`, caracteres CJK;
    elimina todos los blancos/guiones falsos de arriba. Costo: rechazar símbolos no ASCII (nadie los usa en correos reales).
 C. Volver a la opción 1 de D-015 (solo ASCII): cierra también los homoglifos, pero rechaza `señor@`.
Recomendación: **decisión humana**; B es el mejor equilibrio con lo ya aprobado. Hasta decidir, cambiar el texto de D-013/PROGRESS a "clase" (baja, ver R-10).

### R-02 — La opción 2 rechaza correos legítimos de escrituras que usan marcas o ZWNJ — informativa
Evidencia (rechazados): devanagari `कि` (Mc), tailandés `กิ` (Mn), árabe con `َ`, hebreo con niqqud, ZWNJ persa `‌` (Cf),
`क्` (virama), `İ` (por casefold -> `i`+U+0307). Aceptados: `ñ` pre/descompuesta, tildes `é`/`josé`, `ü` (`müller@x.de`), kana con dakuten
(`が`), dominio `münchen.de`, `a@b.cl`, puntos, guiones y `+`. Para el público chileno no hay rechazos razonables. Para correos internacionales en hindi, tailandés,
persa o jemer sí (D-015 lo implicaba: "el correo debe llegar precompuesto"). No hay falsos negativos de las categorías pedidas (el barrido no encontró ningún
carácter C*/Mn/Mc/Me aceptado). Recomendación: ignorar; opcionalmente una línea en D-015/D-013 diciendo que quedan excluidas esas escrituras.

### R-03 — Los Cn dependen de la versión de Python: riesgo concreto para el login de T-04 — baja
Evidencia: Python 3.13 = Unicode 15.1; el proyecto declara Python 3.11+ (Unicode 14). Un correo con un carácter asignado en 15.x se registra en 3.13 y
`normalizar_email` lo **rechaza** en 3.11 (es Cn allí): ese usuario no podría iniciar sesión tras un despliegue en un Python más viejo. La prueba
`test_un_punto_sin_asignar...` es sólida (no fija puntos), y la exhaustiva es autoconsistente. Recomendación: anotar en T-04 (ver R-08) que el login no debe
tratar `ValueError` como 500; no hace falta más hoy. Backlog.

### R-04 — `<input type="email">` impide escribir `señor@…` en el navegador, anulando el motivo de elegir la opción 2 — media (a confirmar en navegador)
Evidencia: `app/templates/registro.html` usa `type="email"` sin `novalidate`. La especificación HTML (`valid e-mail address`) solo admite ASCII en la parte local;
Chrome y Firefox marcan `señor@x.cl` como inválido y bloquean el envío. No lo ejecuté en un navegador (no tengo uno aquí), así que va como "a confirmar".
Si es cierto, el humano aprobó la opción 2 "para admitir correos con tildes o ñ" y en la práctica solo se aceptan por clientes que no validan (curl, pruebas).
Recomendación: **tarea nueva pequeña o incluirlo en T-04** (el formulario de login tiene el mismo campo): `type="text" inputmode="email"` (o `novalidate`) con la
validación del servidor como única autoridad, y una prueba del HTML; o decidir que no importa si se elige la opción C de R-01.

### R-05 — Hash rápido (D-019): no puede filtrarse a producción — informativa (confirmación)
Evidencia: el reemplazo vive solo en `tests/conftest.py` (`monkeypatch`); `app/` no importa `conftest`; `auth.generate_password_hash('x')` fuera de pytest da
`scrypt:32768:8:1`. La función de reemplazo conserva la firma de Werkzeug (`password, method, salt_length`) y solo acelera el `method` por defecto exacto (`"scrypt"`),
respetando cualquier método explícito. Las pruebas de seguridad que verifican algo del hash (`hash_usa_scrypt...`, `con_hash_real...`) llevan `hash_real` y, mutando el
marcador (ignorado), fallan 2: el marcador **funciona**. `check_password_hash` lee los parámetros del hash guardado, así que verificar hashes rápidos no debilita la
comprobación de contraseña. Lo que se pierde: ninguna prueba de login/registro corre con el costo real salvo las dos marcadas (aceptable).

### R-06 — Nada comprueba que el hash rápido esté realmente activo; el marcador sin registrar solo avisa — baja
Evidencia (copia): (a) dejar la fixture `hash_rapido` vacía (`pass`): **470 passed**, la suite solo se vuelve más lenta (9,4 -> ~16 s en esa corrida);
(b) parchear solo `werkzeug.security` y no `auth`: **470 passed**. Ninguna prueba falla si D-019 deja de funcionar. (c) Sin la línea `markers` de `pytest.ini`: 470 passed, "4 warnings"
(el marcador funciona igual, solo avisa); con `--strict-markers` y marcador registrado: 470 passed; con `--strict-markers` y sin registrar: error de colección (la protección que se busca).
Un error de tipeo (`@pytest.mark.hash_rael`) en una prueba futura daría hash rápido y un aviso fácil de ignorar.
Recomendaciones: (1) **backlog/tarea pequeña**: `addopts = --strict-markers` en `pytest.ini` (una línea, archivo de D-011; no cambia nada hoy);
(2) una prueba que verifique que sin `hash_real` `generate_password_hash('x')` da `scrypt:1024:8:1` en `werkzeug.security` y en `app.auth` (cierra (a) y (b)).

### R-07 — La fixture parcha por nombre en dos módulos: T-04 es el primer punto frágil — media (anotar en T-04)
`create-professional` y el login (módulo nuevo o `auth.py`) que hagan `from werkzeug.security import generate_password_hash` quedarán con la función **real** (lenta, y
en el CLI se ejecuta en `invoke`) sin que nada avise. D-019 y PROGRESS ya lo dicen, pero solo como nota. Mejoras baratas para decidir en T-04: la fixture recorre
`sys.modules` y reemplaza `generate_password_hash` en todo módulo `app.*` que lo tenga; o una prueba (AST/grep) que falle si un archivo de `app/` importa
`generate_password_hash` y no está en la lista de la fixture. Recomendación: **incluir en T-04** (ver R-08).

### R-08 — Qué anotar para T-04 — media
1. Login: capturar el `ValueError` de `normalizar_email` (incluye no-`str`, caracteres prohibidos, espacios internos) y responder **el mismo** mensaje genérico de credenciales
   inválidas, nunca 500 ni "correo inválido"; y ejecutar igualmente un `check_password_hash` contra un hash falso (tiempo uniforme), también cuando `normalizar_email` lanza o el correo no existe (enumeración por tiempo).
2. Acotar la longitud de la contraseña (128, D-010) antes de hashear en el login (coste de scrypt). El hash ficticio del punto 1 se crearía al importar con costo real (~0,14 s), no con el rápido.
3. `create-professional`: usar `normalizar_email` + las mismas reglas de longitud/regex que `validar_registro` (hoy viven en `auth.py`), `zona_chile()` para `creado_en`, y
   reutilizar `es_correo_duplicado` (hoy en `auth.py`: no duplicarlo ni importarlo con ciclos; moverlo a `correo.py` o `db.py` sería razonable) para decir "ya existe" frente a un 500 en otro error; mensaje de error en español por `click`.
4. La fixture de hash (R-07) y la prueba con `hash_real` de que el profesional se crea con scrypt real.
5. Bases `agenda.db` creadas antes de T-03c pueden tener correos con U+034F, selectores, U+FFFD, etc. que hoy el login rechaza: solo importa si queda una base de desarrollo con datos (D-006: se recrea).
6. R-04 (`type="email"`) afecta también al formulario de login.

### R-09 — `es_correo_duplicado`: sólido en el entorno actual, con una fragilidad futura — baja
Evidencia: SQLite 3.45.1 / Python 3.13: `IntegrityError('UNIQUE constraint failed: usuarios.email')`, `sqlite_errorcode == 2067 (SQLITE_CONSTRAINT_UNIQUE)`; el mismo
correo con otra capitalización (COLLATE NOCASE) da el mismo mensaje; un `id` duplicado da `SQLITE_CONSTRAINT_PRIMARYKEY` y no se confunde. `sqlite_errorcode` y la constante existen
desde Python 3.11 (el mínimo del proyecto). El formato `UNIQUE constraint failed: tabla.columna` es estable desde SQLite 3.8; **si algún día el UNIQUE pasa a un índice de expresión**
(p. ej. `lower(email)`), el mensaje será `index '…'` y todo duplicado daría 500: la prueba lo detectaría por un caso real solo si existe; las parametrizadas usan errores simulados.
`db.rollback()`: **es correcto y no sobra**: tras el INSERT fallido `db.in_transaction` es `True` (comprobado); sin rollback la conexión de la petición queda con una transacción abierta que
el cierre al final descarta, pero cualquier escritura posterior en la misma petición se mezclaría con ella. Sobrevive a mutación porque ninguna prueba lo observa; no es un defecto.
Carrera real: 8 hilos con el mismo correo, 3 repeticiones: un solo 302, siete 200 con mensaje de duplicado, una fila, sin 500 ni "database is locked" (con el timeout de 5 s por defecto un
bloqueo largo daría `OperationalError` -> 500, aceptable). Recomendación: backlog opcional: una prueba con el UNIQUE real (dos registros reales ya existen: `test_unique_de_usuarios_email...`) que asegure el mensaje, ya cubierta; ignorar el resto.

### R-10 — Pruebas de tzdata: correctas pero con tres detalles — baja
- `test_con_tzdata_instalado_y_sin_zonas_en_el_sistema_funciona` y `test_requirements_pide_tzdata...` pasan solo con `tzdata` instalado; el mensaje de fallo lo explica. El implementador hizo `pip install tzdata`
  (2026.5) en el entorno; **no está documentado en el repo más que en D-012 y en PROGRESS/Bloqueos**: `README`/`CLAUDE.md` ya mandan `pip install -r requirements.txt`, que lo instala, así que basta (informativa).
- `test_las_pruebas_anteriores_no_dejan_la_cache_poblada` depende del orden (pasa sola trivialmente: lo comprobé corriéndola aislada) y solo vigila la prueba contigua, no a las otras. Es la que atrapa la mutación
  "caché sin limpiar" (1 falla); suficiente, pero frágil con `pytest -p randomly` o `-k`. Backlog muy bajo.
- Las pruebas por subproceso usan `env={"PYTHONTZPATH", "PATH": "", "SECRET_KEY"}` sin `SYSTEMROOT`; en Windows (que D-012 cita) Python puede no arrancar sin esa variable (no verificado; la suite ya
  tenía este patrón desde T-03b). Backlog: copiar `SYSTEMROOT` si existe.
- Aislamiento de caché OK: la fixture limpia antes y después; `test_sin_zona_horaria_el_registro_da_500...` pasa con la caché sucia de `test_registro.py` (ejecutado en conjunto, 61 passed).

### R-11 — Criterio de término "notablemente más rápida" no se cumplió; la explicación es honesta pero el trabajo útil queda por hacer — baja
Evidencia: 390 pruebas 11,0-11,5 s -> 470 pruebas 10,4-11,3 s. La mejora real está en `test_registro.py` (6,7 -> 2,7 s con 12 pruebas más); se la come +2,4 s de la prueba exhaustiva nueva y +68 pruebas más.
La causa que da PROGRESS es cierta: con `--durations=0`, `setup` suma ~4,1 s (casi todo `test_esquema.py`, 281 pruebas con una base en disco por prueba) y `call` ~5,0 s. El texto de T-03c (0,2 s -> 5 s "por el scrypt") era una sobreestimación: el scrypt eran ~4 s de 11.
PROGRESS lo reporta sin maquillar (regla 9), pero marca HECHA una tarea cuyo término literal no se cumplió. Recomendación: **tarea nueva baja** ("T-03d suite rápida"): fixture de `test_esquema` que cree el esquema una vez (base `:memory:` o copia
de un archivo plantilla), marcar la exhaustiva como lenta o reducirla; meta realista ~6 s. O que el orquestador reescriba el criterio de T-03c como "registro más rápido" y cierre. No bloquea T-04.

### R-12 — Calidad y alcance de lo editado en la documentación — baja
- Dentro de lo permitido: D-010 (remite a D-012/D-013/D-015 y cambia `zona_chile()`), D-012, D-013 (plegados, `ValueError` no `str`, `isspace` incluye U+2028/2029/1680, y una línea "No cubierto por D-015"), D-014 (límite **global**: texto ahora correcto), D-019 nueva (justifica `conftest.py`/`pytest.ini` según la regla 10), TASKS (estado) y PROGRESS con nota de corrección. No toca SPEC, ARCHITECTURE, `schema.sql` ni REVIEW (`git diff` vacío para esos archivos).
- D-019: "scrypt:16:1:1 (OpenSSL rechaza)" **verificado** (`memory limit exceeded`); "~0,13 a 0,4 s" de scrypt real: medí 0,14 s por hash y 0,005 s con el rápido.
- D-013 dice "Hasta T-03b solo se rechazaban Cc y Cf" y el "No cubierto" nombra solo tres casos (ver R-01: es una clase). D-013 sí es larga; legible aún.
- PROGRESS "Bloqueos": D-015 vs el texto de TASKS (que listaba hangul/braille/U+FFFD como "pasan hoy", dando a entender que se querían rechazar) era una contradicción real; el implementador la anotó e implementó D-015 literal en vez de detenerse (regla 6). Defendible, porque D-015 es la decisión humana y es explícito; la pregunta quedó registrada. La frase falsa de T-03b se corrigió con nota visible sin borrar el original: bien.
- La pareja de pruebas `test_ni_el_relleno_hangul_ni_braille_ni_fffd_los_cubre_la_categoria` cierra el alcance en una prueba: si se adopta R-01 B hay que invertirla (ya lo dice el docstring).

### R-13 — Otras observaciones menores — informativa
- La prueba exhaustiva solo prueba un carácter aislado entre `a` y `b`; no cubre secuencias (p. ej. Hangul compuesto/jamo, que NFKC compone). Mutaciones relevantes las cubren las parametrizadas. Cuesta 2,4 s por corrida.
- `normalizar_email` ahora lanza `ValueError("el correo debe ser texto")` también para `bytes`; el registro nunca la llama con no-`str`.
- Si `normalizar_email` falla en el registro, el formulario devuelve `email_bruto.strip()` sin normalizar (correcto, se muestra tal cual escapado).

## Resumen de recomendaciones

| Id | Severidad | Destino |
|---|---|---|
| R-01 | media | decisión humana (opciones A/B/C); si B, tarea nueva |
| R-04 | media (a confirmar) | tarea nueva pequeña o dentro de T-04 |
| R-07, R-08 | media | anotar en T-04 |
| R-06 | baja | backlog (`--strict-markers` + prueba de que el hash rápido está activo) |
| R-11 | baja | tarea nueva baja (suite rápida) o reescribir el criterio |
| R-03, R-09, R-10, R-12 | baja | backlog / ignorar |
| R-02, R-05, R-13 | informativa | ignorar |

## Veredicto

**APROBADA.** La política D-015 opción 2 se implementó tal como D-015 la define (barrido exhaustivo sin C*/M* aceptados, `ñ` pre/descompuesta iguales), todas las mutaciones declaradas
se reproducen, el hash rápido no puede llegar a producción y el marcador funciona, `es_correo_duplicado` es correcto y la carrera no produce 500. Quedan decisiones para el humano (R-01) y
notas obligatorias para T-04 (R-04, R-07, R-08); el criterio de velocidad no se cumplió (R-11) pero está reportado con honestidad y no bloquea.
