"""Protección CSRF centralizada (D-009).

El token vive en la sesión firmada de Flask. `init_app` registra un
`before_request` que exige un token válido en todo método que modifica estado,
de modo que los formularios futuros no pueden olvidar la verificación. También
fija las cabeceras de seguridad de toda respuesta (CSP, nosniff, anti-frame,
Referrer-Policy; T-14a).
"""
import hmac
import secrets

from flask import abort, request, session

CLAVE_SESION = "csrf_token"
CAMPO_FORMULARIO = "csrf_token"
METODOS_SEGUROS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
MENSAJE_CSRF = (
    "No pudimos verificar tu formulario (falta o no es válido el token de "
    "seguridad). Vuelve a cargar la página e inténtalo de nuevo."
)


def generar_token():
    """Devuelve el token CSRF de la sesión, creándolo si aún no existe."""
    token = session.get(CLAVE_SESION)
    if not token:
        token = secrets.token_hex(32)
        session[CLAVE_SESION] = token
    return token


def token_valido(recibido):
    esperado = session.get(CLAVE_SESION)
    if not esperado or not recibido:
        return False
    return hmac.compare_digest(str(esperado).encode(), str(recibido).encode())


def verificar_csrf():
    if request.method in METODOS_SEGUROS:
        return
    # Solo el campo del formulario (T-14a, D-046): la app no tiene JavaScript ni clientes que
    # envíen el token por cabecera, así que aceptarla era superficie sin uso.
    recibido = request.form.get(CAMPO_FORMULARIO)
    if not token_valido(recibido):
        abort(400, description=MENSAJE_CSRF)


def no_almacenar_paginas_de_sesion(respuesta):
    """`Cache-Control: no-store` y `Pragma: no-cache` en toda respuesta dinámica (R-03).

    Se aplica a todo lo que no sea un archivo estático, en vez de enumerar rutas
    privadas: así «atrás» tras el logout no muestra un panel guardado y una ruta
    futura queda cubierta sin acordarse de nada. No se puede decidir por "la
    vista leyó la sesión" porque Flask 3.1 marca `session.accessed` como True
    siempre, y de todos modos `base.html` lee los mensajes flash en cada página.
    Las respuestas dinámicas de esta app son pequeñas, así que perder su caché
    no cuesta nada; los estáticos (endpoint `static`) conservan la suya.
    """
    # Un error de un estático (404, 403) sí es una página dinámica de error: también no-store.
    if request.endpoint != "static" or respuesta.status_code >= 400:
        respuesta.headers["Cache-Control"] = "no-store"
        respuesta.headers["Pragma"] = "no-cache"
    return respuesta


# Política de contenido (T-14a, D-046). La app no tiene scripts, estilos en línea, fuentes
# ni recursos externos: todo sale de su propio origen (hoja y favicon en /static).
# `form-action 'self'` y `base-uri 'none'` no heredan de `default-src` y se declaran aparte;
# `frame-ancestors 'none'` es el equivalente moderno de `X-Frame-Options: DENY`.
POLITICA_CSP = (
    "default-src 'self'; base-uri 'none'; form-action 'self'; "
    "frame-ancestors 'none'; object-src 'none'"
)
CABECERAS_DE_SEGURIDAD = {
    "Content-Security-Policy": POLITICA_CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


def agregar_cabeceras_de_seguridad(respuesta):
    """Cabeceras de seguridad en TODA respuesta: páginas, redirecciones, errores y estáticos.

    Se asignan siempre (no `setdefault`): una vista no puede relajarlas por descuido. No
    toca `Cache-Control` (D-024), que decide `no_almacenar_paginas_de_sesion`.
    """
    for nombre, valor in CABECERAS_DE_SEGURIDAD.items():
        respuesta.headers[nombre] = valor
    return respuesta


def init_app(app):
    # Debe registrarse después de la exigencia de SECRET_KEY (D-008), que así
    # se ejecuta primero: sin clave no hay sesión que firmar.
    app.before_request(verificar_csrf)
    app.after_request(no_almacenar_paginas_de_sesion)
    app.after_request(agregar_cabeceras_de_seguridad)
    app.jinja_env.globals["csrf_token"] = generar_token
