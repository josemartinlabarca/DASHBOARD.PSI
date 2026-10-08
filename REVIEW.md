# REVIEW — T-08e Reservar solo con más de 24 h (D-029) y correo con letras y números fuera de ASCII (D-020) (commit `ce472aa`)

Revisor: leí el diff completo (`git show ce472aa`), CLAUDE.md, SPEC.md (US-7 a US-9, §4), D-013, D-015, D-020, D-028, D-029, D-030, D-031, el texto de T-08e, T-09 a T-12 en TASKS, la entrada de PROGRESS, `app/correo.py`, `app/paciente.py`, `app/tiempo.py`, `app/auth.py`, las plantillas `horas_libres.html` y `paciente.html` y el README. Todo lo que ejecuté se hizo en copias bajo el scratchpad (`git archive ce472aa` → `new/`, `git archive ce472aa~1` → `old/`); en el repo no hice `checkout`, `reset` ni cambios de commit, y el árbol sigue limpio (solo se escribe este archivo).

## Veredicto: APROBADA

No encontré errores de comportamiento en D-029 ni en D-020, ni pérdida de cobertura. Las dos desviaciones respecto de lo prometido son de proceso: la regla 8 de SPEC (R-01) y que la suite supera el criterio firme de tiempo de T-08b (R-02). Ninguna impide cerrar la tarea. Quedan hallazgos de severidad baja o informativa para el backlog o para decidir.

| Id | Severidad | Tema | Recomendación |
|---|---|---|---|
| R-01 | baja | SPEC regla 8 (regla 5 = solape): alcance de la autorización | decisión humana (ratificar en una línea) |
| R-02 | baja | La suite pasó de 27,5 s a 34 s: supera el criterio firme de T-08b (31,5 s) | decisión humana o backlog |
| R-03 | baja | Un POST forzado a una hora oculta distingue «libre» de «ocupada» | backlog |
| R-04 | baja | `U+13441` y `U+13442` (jeroglíficos en blanco, `Lo`) siguen aceptados | backlog |
| R-05 | baja | Cuentas guardadas con la política antigua dejan de poder entrar | backlog (documentar) |
| R-06 | informativa | La lista de rellenos es casi toda código muerto (verificado) | decisión humana (el humano la aprobó) |
| R-07 | informativa | Correos legítimos rechazados por reglas que ya existían (marcas) o por NFKC (`·`, fracciones) | documentar / decisión humana |
| R-08 | informativa | La tabla de 26 casos acepta cualquiera de los dos mensajes de rechazo | ignorar (otras pruebas lo fijan) |
| R-09 | informativa | T-10: con reservas de más de 24 h, qué hacer con las hechas justo después del borde | nota para T-10 |
| R-10 | informativa | «Toda reserva aceptada puede cancelarse» vale en el mismo instante; el profesional puede crear horas que nadie podrá reservar | nota para T-09, T-11 y T-12 |
| R-11 | informativa | Redacción del mensaje a las 24 h exactas; el mensaje de solape sugiere cancelar algo que a veces no se puede; README sin la regla | backlog |
| R-12 | informativa | Veracidad de PROGRESS y de las mutaciones del implementador | sin acción |

## Lo que verifiqué ejecutando (resumen)

- Suite completa de `ce472aa`: 1456 passed en 34,1 s y 35,0 s. La de `ce472aa~1`: 1216 passed en 27,5 s.
- Ids de pruebas, antes y después: 1197 iguales, 19 quitadas, 259 nuevas (1216 − 19 + 259 = 1456).
- Modelo propio de D-029 con zoneinfo: 1200 casos aleatorios (un tercio pegado al borde de 24 h, un tercio alrededor de las cuatro transiciones de horario de 2026 y 2027) con el sistema en UTC, Tokio y Chile, más 1200 con otra semilla en UTC. Cero fallos.
- Modelo propio de D-020 sobre los 1.112.064 puntos de código, más 40.000 cadenas ASCII aleatorias comparadas con el commit anterior.
- 28 mutaciones propias sobre la suite completa (no sobre 7 archivos); detalle en R-12.
- `create-professional` con dos procesos reales: 10 de 10 pasa el original y el mutante `BEGIN` muere 8 de 8. Con 4 procesos ocupando la CPU, el original pasa 6 de 6 y el mutante muere 6 de 6.
- Recorrido real con `flask run` y `curl` contra una copia (puerto 5097, base temporal): reproduje el recorrido descrito en PROGRESS con los mismos resultados.

## Hallazgos

### R-01 (baja) — SPEC: la regla 8 documenta la regla 5 sin que la autorización lo cubra literalmente
**Qué hay.** `git show ce472aa -- SPEC.md` cambia solo 4 líneas (3 agregadas, 1 modificada):
- US-8 recibe «(que empiece en más de 24 horas)».
- Regla 7, la anticipación al reservar. Se agrega con detalle: instantes absolutos, 24 h exactas, coherencia con cancelar y lista de horas.
- Regla 8: «La regla 5 se entiende como solape de intervalos…».
- La regla 5 literal («Un paciente no puede tener dos reservas a la misma hora») no se tocó.

No hay nada más en SPEC.

**Evaluación.**
- La regla 8 no contradice la regla 5. Es una interpretación que la amplía: «a la misma hora» pasa a incluir cualquier cruce de intervalos. Un paciente con 10:00–10:50 puede reservar 10:30 según la letra de la regla 5 y no puede según la regla 8. El código ya hacía lo segundo desde T-07, así que SPEC pasa a describir lo implementado.
- El humano aprobó D-029 opción B, cuyo título dice «regla 5 = solape de intervalos». El texto de T-08e, en su punto (1), pide «dejarla documentada en SPEC».
- Pero la nota de autorización de la misma tarea dice «Autorizada a añadir la regla de anticipación … **solo** para esto». Hay una contradicción interna en TASKS entre la nota de autorización y el punto (1). El implementador la resolvió a favor del punto (1) y lo dijo en PROGRESS («Problemas / dudas» 3). Por CLAUDE.md regla 6 podía haber anotado la duda y detenerse.
- La regla 7 incluye detalles de implementación («instantes absolutos, no hora de pared», «la lista solo ofrece…»). Excede un poco una regla de negocio, aunque es coherente con US-9.

**Gravedad.** Baja. El fondo está aprobado por el humano y no hay contradicción de contenido. Es un exceso formal de alcance sobre SPEC, que CLAUDE.md protege.

**Recomendación.** Decisión humana de una línea: ratificar las reglas 7 y 8 tal como están, o pedir que la regla 8 pase a una nota de `DECISIONS.md`. El implementador no debe tocar SPEC de nuevo.

### R-02 (baja) — La suite supera el criterio firme de tiempo de T-08b
- **Medición.** `ce472aa~1`: 27,5 s. `ce472aa`: 34,1 s y 35,0 s en esta máquina (2 núcleos). El implementador midió 31–36 s. Son +24 % de tiempo por +240 pruebas, unos 28 ms por prueba.
- **Criterio.** D-031, punto «Criterio de tiempo (R-04)»: el 30 s es orientativo y el criterio firme es «no más de la mitad de 63 s», es decir 31,5 s. Ahora se supera por unos 2,5 a 3,5 s en mis dos corridas. El umbral de acción de TASKS (60 s) está lejos.
- **Dónde se va el tiempo.** `--durations` muestra dos recorridos de 1.112.064 puntos de código en `test_correo.py` (≈2,0 s el idempotente que ya existía y ≈1,7 s el modelo nuevo), la prueba de dos procesos de `create-professional` (1,5 s) y cientos de pruebas parametrizadas que montan app y base cada una.
- **Lo que reconoce PROGRESS.** Habla de un «objetivo de 35 s» que no figura en D-031, y el implementador mismo dice «en el límite».

**Recomendación.** Decisión humana: subir el criterio firme (con la medición nueva) o recortar. Recortar es posible sin perder cobertura: unir los dos recorridos exhaustivos en una sola pasada, o compartir la app entre los casos de las tablas de 26 y 39 casos. No bloquea.

### R-03 (baja) — Un POST forzado a una hora oculta revela si está ocupada
**Reproducción.** En una copia con «ahora» fijo en 2026-10-08 12:00:
- Una hora libre a 23 h da 302 y el mensaje «Solo se puede reservar con más de 24 horas…».
- La misma situación con una hora **ocupada por otro paciente** da «Esa hora ya no está disponible».
- Una hora pasada libre da «ya empezó o ya pasó»; ocupada y pasada da «no está disponible». Una id inexistente da «no está disponible».

Siempre responde 302, nunca 500, y no revela quién la tiene. La causa es el orden de las comprobaciones en `reservar_hora`: estado primero, anticipación después.

**Gravedad.** Baja. La distinción «libre y ocupada» ya existía para las horas pasadas (T-07) y la lista pública ya muestra qué horas están libres. Para las ocultas es información nueva, pero mínima: no se sabe quién la tomó. Ninguna prueba fija este comportamiento: la de POST forzado usa una hora libre.

**Recomendación.** Backlog. O se acepta y se documenta, o se comprueba la anticipación antes del estado. Con este segundo orden, «inexistente» sigue siendo distinguible de «existente y cercana».

### R-04 (baja) — Dos letras en blanco de Unicode 15 siguen aceptadas
`U+13441` y `U+13442` (EGYPTIAN HIEROGLYPH FULL BLANK y HALF BLANK) son `Lo`, pasan la regla L*/N* y no están en la lista. Revisé por nombre (FILLER, BLANK, INVISIBLE, SPACE, EMPTY, NULL) todos los puntos de código no ASCII aceptados y son los únicos. Se ven en blanco solo con fuentes que los dibujen, así que el riesgo real es mínimo y coherente con el riesgo aceptado de D-013.

**Recomendación.** Backlog: agregarlos a la lista y a la prueba exhaustiva si se mantiene la lista, y anotar que la defensa contra «letras vacías» depende de la versión de Unicode instalada (aquí 15.1).

### R-05 (baja) — Las cuentas guardadas con la política antigua pierden el acceso
Con `ce472aa` una cuenta ya guardada como `anaㅤ@example.cl` no puede iniciar sesión, porque el login normaliza lo que se escribe y lo rechaza (`buscar_usuario_por_credenciales` devuelve `None`; lo comprobé con una fila insertada). Lo mismo vale para cualquier correo con `·`, símbolos o guiones no ASCII que se hubiera registrado antes. Es coherente con D-006: no hay migraciones, y en v1 no debería haber usuarios reales.

**Recomendación.** Backlog: una línea en D-020 que diga que no hay migración y que las cuentas con esos caracteres deben recrearse. Si hay usuarios reales, decisión humana.

### R-06 (informativa) — La lista de rellenos es casi toda redundante (la afirmación del implementador es cierta)
Verificado con los 1.112.064 puntos de código: con `RELLENOS_RECHAZADOS = {0x115F, 0x1160}` el resultado es idéntico al de la lista completa, sin ninguna diferencia.
- Categorías de la lista: 38 `So`, 6 `Pd`, 1 `Po` y 3 `Lo`. Solo U+115F y U+1160 son `Lo` que la regla L*/N* dejaría pasar.
- U+3164 y U+FFA0 se convierten con NFKC en U+1160, que se rechaza.
- En la práctica, `U+3164` y los rangos de símbolos y guiones son código muerto. Las mutaciones R12 (quitar U+3164) y R24 (quitar los dos rangos) sobreviven; las dos son equivalentes. La mutación R28, que vacía la lista de 7 y deja los rangos, muere por U+115F y U+1160.
- La lista no protege de cambios futuros de Unicode: un carácter nuevo en blanco entra como `Lo` (ver R-04) y la lista no lo nombra.

**Evaluación.**
- Dejarla es inocuo y documenta la intención. Es lo que el humano aprobó en D-020, que la nombra explícitamente.
- Costo: 48 casos parametrizados + 11 en registro que en realidad prueban la categoría, no la lista; sensación de cobertura sobre código que no cambia el resultado.
- Alternativa sencilla: dejar `{0x115F, 0x1160}` (y 0x3164 si se quiere dejar explícito) con un comentario que diga que lo demás lo cubre la categoría. La prueba exhaustiva sigue siendo la que importa.

**Recomendación.** Decisión humana opcional. Hoy está documentado en D-020 y en un comentario del código, así que no es un defecto.

### R-07 (informativa) — Correos legítimos que se rechazan
Resultados con `old/` y `new/` (`s → antes | ahora`):
- **Igual que antes de T-08e** (regla D-015 de marcas, sin cambio): `राम@x.in` (hindi, vocal en `Mc`), `สวัสดี@x.th` (tailandés, vocales `Mn`) e `İ@x.tr` (casefold lo deja en `i` + U+0307 `Mn`) se rechazan. Esto afecta a muchos idiomas con marcas obligatorias y no está documentado como limitación en README ni en D-020. Dígitos devanagari solos (`१२३`), árabe, hebreo sin puntos, kanji y cirílico se aceptan.
- **Nuevo en T-08e:** `col·legi@x.cat` y `ŀ@x.cat` (catalán, el punto medio U+00B7 está en la lista aprobada) y `ana½@x.cl` (NFKC lo convierte en `1⁄2`, y U+2044 es `Sm`) pasan de aceptarse a rechazarse. Otros 7.594 puntos de código pasan de aceptados a rechazados, casi todos símbolos y puntuación (`So` 5.753, `Sm` 923, `Po` 565, entre otros).

Los ejemplos pedidos dan el resultado esperado (se aceptan `señor`, `josé`, `müller`, `ñandú`, `王`, `иван`, número árabe-índico y dígitos devanagari). El modelo propio, que usa categorías `L*`/`N*` más la lista pero con otro código, coincide con la aplicación en los 1.112.064 puntos de código (0 diferencias; 139.453 aceptados por la política nueva).

**Discrepancias entre registro, login y `create-professional`:** ninguna. Los tres llaman a la misma `normalizar_email`; el login transforma el `ValueError` en el mensaje genérico y los otros dos en `MENSAJE_EMAIL_INVALIDO`.

**Lo ASCII no cambió:** 40.000 cadenas ASCII aleatorias (20.000 de 0–127 y 20.000 imprimibles con `@.-_+`) dan exactamente el mismo resultado en `ce472aa~1` y `ce472aa`.

**Recomendación.** Documentar la limitación de las marcas (D-015) en README o D-020 y, si interesa, decidir si se admiten `Mn`/`Mc` en escrituras índicas. No es de esta tarea.

### R-08 (informativa) — La tabla de 26 casos admite dos mensajes de rechazo
`test_anticipacion_de_mas_de_24_horas_en_instantes_absolutos` comprueba, cuando no se permite, que el texto contenga «más de 24 horas de anticipación» **o** «ya empezó o ya pasó». No fija cuál corresponde en cada caso. No es una debilidad real: la mutación que cambia el mensaje (R15) y la que quita la rama «ya pasó» (R20) mueren por otras pruebas, y el mensaje correcto de la noche de abril lo fija `test_futuro_o_pasado_se_decide_…`. `test_la_tabla_de_reservas_coincide_con_la_referencia_independiente` compara la tabla con una función de referencia; no ejercita la aplicación.

### R-09 (informativa) — Interacción con T-10 (recordatorio a 24 h)
- Con reservas siempre de más de 24 h, el instante «24 h antes» nunca es pasado al reservar. Pero una reserva hecha entre 24 h y 24 h + el período del cron queda con el recordatorio vencido en cuanto se confirma: el paciente recibiría la confirmación y el recordatorio casi juntos.
- «Hora a <24 h» (criterio de término de T-10) ya no se puede obtener reservando por la aplicación. Las pruebas de T-10 tendrán que insertar la reserva por SQL, como hacen las de cancelar.
- El borde es el mismo número para tres reglas: cancelar permite 24 h exactas, reservar no, y el recordatorio debería salir cuando falten 24 h o menos. En el instante exacto de las 24 h se puede cancelar y se debe recordar; `cancelar_reserva` pone `recordatorio_enviado = 0`.

**Recomendación.** Nota en T-10: definir el recordatorio como «falta ≤ 24 h y la hora no empezó», con instantes absolutos, y probar el instante exacto. Cuando una cancelación y un recordatorio coinciden en el mismo instante, decidir quién gana.

### R-10 (informativa) — Interacciones con T-09, T-11 y T-12
- **«Toda reserva aceptada puede cancelarse en el momento de hacerla»** es cierto en el mismo instante (lo comprobé en 1200 casos: reservar y cancelar con el mismo reloj, cero inconsistencias). Una persona no cancela en el mismo instante: una reserva hecha a 24 h + 1 s queda sin cancelación posible un segundo después (el panel muestra «Ya no se puede cancelar»). Es inherente a cualquier umbral, pero la frase de la regla 7 de SPEC promete más de lo que ocurre en la práctica.
- **T-09:** el texto de confirmación podría decir hasta cuándo se puede cancelar (inicio − 24 h), con la hora local.
- **T-11:** el panel ya muestra «Ya no se puede cancelar (faltan menos de 24 horas)» y no cambia.
- **T-12:** el profesional puede crear (lo vi en el recorrido real) una hora a 23 h y la ve «libre», aunque ningún paciente podrá reservarla. Conviene marcarla en su agenda o avisarlo al crearla.
- **Carrera cancelar/reservar:** ambas toman `BEGIN IMMEDIATE` y leen el reloj después del bloqueo. Una hora cancelada con 24 h o más justo antes del borde puede quedar libre pero no reservable (≤ 24 h); es consistente con el diseño.

### R-11 (informativa) — Redacción y documentación
- A las 24 h exactas el mensaje dice «a esa hora le falta menos», pero faltan exactamente 24 h. Es un caso de un instante entre millones. Con una palabra como «no más» se evita.
- Los mensajes de «pasada», «24 h exactas» y «menos de 24 h» son solo **dos** (las dos últimas comparten el mensaje): `MENSAJE_YA_PASO` y `MENSAJE_POCA_ANTICIPACION_RESERVA`. No lo considero un defecto porque ambas situaciones se resuelven igual (elegir otra hora).
- `MENSAJE_SOLAPE` dice «Cancela esa reserva o elige otro horario» aunque la reserva propia con la que se cruza pueda tener menos de 24 h y no ser cancelable (caso raro: la nueva hora empieza a más de 24 h pero cruza una reserva que empieza antes).
- El README (línea 11) sigue diciendo solo que la cancelación exige 24 h; no menciona que reservar también.
- Los comentarios de D-013, D-015, D-020, D-028, D-029 y D-030 dicen «Implementada 20:12» y PROGRESS y el commit dicen 20:33; no encontré una contradicción real, solo que la hora de las notas de DECISIONS es anterior a la de cierre.

### R-12 (informativa) — Veracidad de PROGRESS y mutaciones
**Cobertura (prioridad). No encontré pérdida.** Revisé uno por uno los 19 ids que ya no existen:
- `test_horas_libres.py` (4): `test_no_aparecen_las_pasadas`, `test_no_aparece_la_que_ya_empezo_ni_la_que_empieza_justo_ahora`, `test_una_hora_de_hoy_aun_futura_aparece_aunque_en_utc_ya_paso` y `test_el_filtro_usa_el_instante_y_no_el_reloj_de_pared` se reemplazaron por versiones con el mismo borde movido 24 h (`…_ni_las_de_menos_de_24_horas`, `…_borde_de_24_horas_se_oculta_justo_en_24_h…`, `…_usa_la_hora_de_chile_y_no_la_de_utc` y una tabla de 13 casos con fold 0 y 1). El caso de la hora repetida de abril sigue en la tabla.
- `test_reservar.py`: `test_un_segundo_despues_de_ahora_si_se_reserva` pasó a «24 h + 1 s se reserva» y «+1 µs» (hay un caso a 1 µs). `test_la_hora_que_empieza_entre_la_carga_de_la_lista_y_el_clic_se_rechaza` pasó a ser `…_pasa_a_menos_de_24_h_…`. Los 4 + 8 ids de `horas_adyacentes…` y `solapes…` son los mismos casos con la fecha movida un día (las horas relativas dentro del día son iguales, así que el borde se conserva). Se agregan 26 + 78 + 13 casos de borde, el POST forzado, la coherencia con cancelar y el mensaje.
- `test_correo.py`: se eliminó una sola prueba, la que afirmaba lo contrario de la política nueva (los 4 rellenos «siguen aceptados»). Se reemplazó por su contraria.
- Asserts por archivo (cuenta con `grep -c assert`): reservar 80 → 99, horas_libres 33 → 37, cancelar 113 → 113, correo 20 → 31, registro 112 → 118, crear_profesional 65 → 76. Ninguna aserción debilitada; `skip` o `xfail` nuevos: ninguno. Los otros archivos de pruebas, `conftest.py` y `app/` (salvo `correo.py` y `paciente.py`) son idénticos a `ce472aa~1`.
- El cambio de la prueba del reloj tras el bloqueo (de 30 s a 24,5 h) es correcto: con «ahora» + 1 h tras la espera, la hora queda a 23,5 h y se rechaza. Con el reloj leído antes del bloqueo se reservaría. Lo confirmé: con esa mutación fallan tres pruebas, entre ellas la modificada (`test_reservar_usa_el_ahora_posterior_a_la_espera_del_bloqueo`).

**Mutaciones propias sobre la suite completa (28, con `-x`).** Murieron 26 y sobrevivieron 2, ambas equivalentes.
- **Murieron:** R1 reservar con `<` en lugar de `<=`; R2 lo mismo en la lista; R3 cancelar con `<=`; R4 sin la regla de 24 h; R5 reloj de pared del sistema al reservar y R6 en la lista; R7 sin exigir L*/N*; R8 solo L*; R9 solo N*; R10 sin U+115F; R11 sin U+1160; R13 filtro también sobre ASCII; R14 botón visible a menos de 24 h; R15 mensaje equivocado; R16 reloj leído antes del bloqueo; R17 umbral 23 h; R18 umbral 25 h; R19 `round()` (un microsegundo); R20 sin la rama «ya pasó»; R21 solape con `<=`; R22 sin ordenar la lista; R23 cancelar con 23 h; R25 `casefold` por `lower` (D-013); R26 aceptar P; R27 aceptar S; R28 lista vacía.
- **Sobrevivieron:** R12 quitar U+3164 (equivalente: NFKC lo lleva a U+1160) y R24 quitar los dos rangos de símbolos y guiones (equivalente: la categoría los rechaza). Ambas confirmadas con la verificación de R-06.

**PROGRESS.** Lo comprobé así:
- 1456 pruebas y 240 nuevas: correcto (1216 + 240). Tiempos 31–36 s: coherentes con mis 34–35 s.
- Recorrido manual: lo reproduje con el mismo script (copiado a una versión que usa mi copia y otro puerto) y obtuve las mismas salidas: registro con `señor@` 302, U+3164 200 con «correo válido», horas a 23 h y 25 h aceptadas, lista con un solo formulario, POST forzado con el mensaje de D-029, reserva de la de 25 h.
- Dos procesos reales con `BEGIN`: muere 8 de 8 (el implementador dice lo mismo). Lo que **no** reproduje: el orden aleatorio con semillas, la simulación sin `time.tzset` (1267 passed, 189 skipped) y sus 29 mutaciones sobre 7 archivos (hice las mías, más amplias). Los 8 sobrevivientes que informa el implementador (quitar U+3164, U+2800/U+FFFD/U+FFFC juntos, U+00B7, ambos rangos y los extremos de los rangos) son todos consistentes con mi verificación de equivalencia (R-06).
- La hora de la entrada de PROGRESS (20:33) coincide con la del commit (20:33:32).

## D-029 en detalle (todo ejecutado)

- **Modelo independiente con zoneinfo** (`modelo29.py`): 1200 casos con semilla 7 y el sistema en UTC, en Tokio y en Chile, más 1200 con otra semilla en UTC. Un tercio pegado al borde (±1 µs, ±1 s, ±ms), un tercio en las horas alrededor de las cuatro transiciones de 2026 y 2027 (abril y septiembre), el resto aleatorio. Resultado: 0 diferencias.
  - Reservar acepta solo si `inicio − ahora > 24 h` (611 aceptados, 582 por «menos de 24 h», 7 por «ya pasó»).
  - Cancelar acepta solo si `≥ 24 h`: comparé 1200 casos sobre reservas insertadas por SQL.
  - Toda reserva aceptada fue cancelable con el mismo reloj (0 inconsistencias).
  - La lista oculta exactamente las que `reservar_hora` rechaza.
- **Mensajes:** «pasada» tiene el suyo; «24 h exactas» y «menos de 24 h» comparten el de D-029 (ver R-11).
- **POST forzado** a una hora oculta: 302, mensaje de D-029, sin 500 y la hora sigue libre. Sobre lo que revela (ocupada o libre), ver R-03.
- **Regla 5:** la comprobación de anticipación va antes que la de solape. El solape se evalúa solo para horas de más de 24 h, con intervalos en instantes absolutos.
- **Reloj:** se lee tras `BEGIN IMMEDIATE`, confirmado con la mutación R16.
- **`float` y el microsegundo:** `ahora.timestamp()` es un `float` de ≈1,8×10⁹ con resolución de ≈2,4×10⁻⁷ s; el caso de 1 µs funciona (probado: modelo y R19).

## create-professional

Las tres pruebas nuevas son correctas. La de «dos procesos reales» arranca ambos con una barrera de tiempo y envía la contraseña a los dos antes de esperar a ninguno. Con `BEGIN` normal muere 8 de 8 veces; con `BEGIN IMMEDIATE` pasa 10 de 10 (y 6 de 6 con la CPU saturada). El README ahora dice que se niega a crear un segundo profesional, con el mensaje exacto, código 1 y la referencia a D-023; coincide con `MENSAJE_PROFESIONAL_EXISTE` y con el comportamiento.

## Qué no verifiqué

- Windows ni macOS reales; la simulación sin `time.tzset` y el orden aleatorio con semillas del implementador.
- Otras versiones de Python o de la base de datos de Unicode (aquí Python 3.13 con Unicode 15.1; la política depende de `unicodedata`).
- Ejecución con `SECRET_KEY` o `FLASK_DEBUG` definidos (el implementador dice que sí lo hizo).
- La interacción real con T-09 a T-12: todavía no existen; solo analicé las notas de TASKS.
