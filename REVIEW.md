# Revisión de T-15 (commit 6bad9a7)

Veredicto: **CON OBSERVACIONES** (sin S1–S3; 1 S4 de robustez y 2 S4 menores).

## 1. Corrección y seguridad
- Redirección GET /login y /registro: destino = `destino_marca()` (url_for fijo, sin parámetro `next`): sin open redirect. Sin bucle (los paneles no redirigen a /login con sesión válida). POST intacto (diff solo toca la rama GET). Medido con Playwright: ambos GET llevan a /paciente o /profesional.
- «Cancelada después»: la consulta empareja por mismo usuario, tipo cancelacion, misma hora_id y `c.id > n.id`. Medido: confirmación A, cancelación A, confirmación B -> solo A marcada; avisos de otro usuario no afectan; `hora_id` NULL queda sin marca. HTML escapado (`<b>x</b>` sale como `&lt;b&gt;`; el `<em>` es fijo).
- Mensaje de 24 h: mismo texto para libre y ocupada, solo antepone «Esa hora ya no está disponible»; no filtra nada nuevo.

## Hallazgos
- S4-1 (regresión de robustez): con cookie de sesión y base ilegible/sin tabla `usuarios`, GET /login y /registro dan **500** (antes 200: la plantilla usa `destino_marca()` con try/except, D-039). Evidencia: test_client con tabla borrada -> 500 con sesión, 200 sin sesión. El `usuario_actual()` agregado en auth.py:155 y :320 no está protegido; usar `destino_marca()` capturando `sqlite3.Error`.
- S4-2: «Esa hora ya no está disponible: solo se puede reservar con más de 24 horas…» para una hora libre ≤24 h es algo ambiguo (sigue siendo cierta), solo estilo.
- S4-3: la marca «cancelada» no cubre avisos de hora eliminada (documentado en D-053).

## 2. Campana móvil (Chromium, base temporal, servidor ya detenido)
- Paciente y profesional a 390 px: enlace visible («Ir a mis notificaciones (N sin leer)»), el clic salta a `#titulo-notificaciones`; sin desbordamiento horizontal. A 1280 px: oculto, sin desbordamiento. Conteos correctos (3 y 2 sin leer).

## 3. Mutación (copia `git archive HEAD`)
- Quitar las redirecciones: fallan 4 pruebas `test_t15a_*` (test_login.py). Quitar `and not n.cancelada` del enlace: fallan 2 `test_t15b_*` (test_dashboard_profesional.py). Ambas detectadas.
