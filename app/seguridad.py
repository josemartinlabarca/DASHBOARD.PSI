"""Protección CSRF centralizada (D-009).

El token vive en la sesión firmada de Flask. `init_app` registra un
`before_request` que exige un token válido en todo método que modifica estado,
de modo que los formularios futuros no pueden olvidar la verificación.
"""
import hmac
import secrets

from flask import abort, request, session

CLAVE_SESION = "csrf_token"
CAMPO_FORMULARIO = "csrf_token"
CABECERA = "X-CSRFToken"
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
    recibido = request.form.get(CAMPO_FORMULARIO) or request.headers.get(CABECERA)
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
    if request.endpoint != "static":
        respuesta.headers["Cache-Control"] = "no-store"
        respuesta.headers["Pragma"] = "no-cache"
    return respuesta


def init_app(app):
    # Debe registrarse después de la exigencia de SECRET_KEY (D-008), que así
    # se ejecuta primero: sin clave no hay sesión que firmar.
    app.before_request(verificar_csrf)
    app.after_request(no_almacenar_paginas_de_sesion)
    app.jinja_env.globals["csrf_token"] = generar_token
