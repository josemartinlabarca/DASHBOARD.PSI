# Revisión de T-16 (commit ede976b)

Veredicto: **CON OBSERVACIONES** (1 hallazgo S3 acotado a cuentas "legacy"; 1 S4). Scripts y bases en `scratchpad/revt16/` (s1.py, s2.py, s3.py); el repo no se tocó. `pytest tests/test_correo.py tests/test_login.py`: 339 pasan.

## 1. Login tolerante (C2) - OK
- Cuenta insertada por SQL con `m·ia@x.cl` (U+00B7, hoy rechazado): entra (302 /paciente), también con `M·IA@X.CL`.
- Fallos (clave mala, inexistente, ancho cero, espacio interno, sustituto suelto vía cuerpo crudo, vacío): todos 200 con el mismo mensaje "Correo o contraseña incorrectos.", y exactamente **1** `check_password_hash` cada uno (contado con parche). No-str (None, int, bytes, list) en `buscar_usuario_por_credenciales`: `None` y 1 hash.
- Tiempo, 25 pares: mediana cuenta existente 136,8 ms vs inexistente 134,7 ms (diferencia dentro del ruido; domina el scrypt).

## 2. Rendimiento/DoS - OK
- Hay límite previo: `MAX_CONTENT_LENGTH = 16 KiB` (`app/__init__.py:60`). Correos de 1 MB, 10 MB y 100 000 caracteres U+FDFA/U+FB2C/ß: **413 en ~1 ms con 0 llamadas a la normalización**, en /login y /registro, sin crecimiento de memoria (RSS 63 a 85 MB, estable). Se rechaza ANTES de normalizar.
- Lo peor que cabe en 16 KiB cuesta unos 130 ms de petición en login (scrypt incluido); la normalización directa de 100 000 U+FDFA tarda 0,24 s (solo alcanzable fuera de HTTP). S4: en login el correo se normaliza 2 veces (estricta para la clave del límite y tolerante para buscar) vs 1 en registro; es irrelevante por el tope de 16 KiB.

## 3. Límite de intentos - S3 (solo cuentas con carácter hoy rechazado)
Se refuta el temor general y se confirma el caso acotado. Medido con variantes del mismo correo (mayúsculas, U+FF41/U+FF21/U+FF20/U+FF38):
- Cuenta normal (`ana@x.cl`), 1 IP: **5** fallos y 429 (par). Con IP distinta en cada intento: **30** y 429 (correo). Las variantes comparten clave porque login y límite normalizan igual (la tolerante solo omite el rechazo): **no hay elusión en cuentas normales**.
- Cuenta legacy (`m·ia@x.cl`), 1 IP: **20** fallos antes del 429 (solo ámbito ip; el par de 5 no aplica). Con 300 IPs distintas: **276 fallos aceptados** (256 IPs válidas + 20 de la clave `desconocida`); no existen ni el tope de 5 por par ni el de 30 por correo. Solo frena el ip (20 por /64), así que un ataque repartido contra esa cuenta no tiene límite.
- Alcance: solo afecta cuentas cuyo correo guardado contenga hoy un carácter rechazado; el registro y `create-professional` (auth.py:474) usan la estricta, así que un atacante no puede crear esas cuentas. D-055 lo admite, pero no mide que cambia de "5 por par / 30 por correo" a "20 por IP / ilimitado repartido". Es S3 si existe alguna cuenta así, S4 si no.
- Sugerencia (no aplicada): usar `normalizar_email_login` también para la clave del límite, acotada a EMAIL_MAX. Riesgo: claves nuevas en `intentos_acceso`, pero el tope de 16 KiB y los límites ip lo acotan; o bien auditar con SQL si hay correos con caracteres rechazados antes de aceptar el riesgo.

## 4. B1 y ARCHITECTURE.md - OK
- U+13441 y U+13442 se rechazan en registro (`RELLENOS_RECHAZADOS`) y siguen aceptados por el login tolerante; U+13443 acepta (control).
- `git diff HEAD~1 HEAD --numstat -- ARCHITECTURE.md`: **42 añadidas, 0 borradas**. Todos los nombres citados existen en `app/` (módulos, funciones, constantes, claves de config, plantillas, static, `tests/esquemas_antiguos`, tabla `intentos_acceso` coincide con `schema.sql`, rutas `marcar_notificaciones_leidas`).
