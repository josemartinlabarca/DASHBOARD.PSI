"""Páginas de error en español (T-13; backlog T-03 #6).

Un solo manejador para cualquier `HTTPException` (400, 403, 404, 405, 413, 500, ...).
Reglas:
- Nunca se muestra `e.description` ni la excepción original: las descripciones de
  Werkzeug están en inglés y una excepción interna podría filtrar rutas o datos.
  La única descripción que se muestra es la del 400 de CSRF (`seguridad.MENSAJE_CSRF`,
  texto propio y sin datos).
- La plantilla no lee la sesión ni los mensajes flash: así también sale si el error
  nace de la sesión o de la clave (D-008).
- `Cache-Control: no-store` lo agrega el `after_request` de `seguridad.py` (D-024).
- Si ni siquiera se puede dibujar la plantilla, se devuelve un HTML mínimo en español.
"""
import sqlite3

from flask import render_template, request, url_for
from werkzeug.exceptions import HTTPException

from . import db, seguridad

ERRORES = {
    400: ("Solicitud no válida", "No pudimos procesar lo que enviaste. Vuelve al inicio e inténtalo de nuevo."),
    403: ("Acceso denegado", "No tienes permiso para ver esta página."),
    404: ("Página no encontrada", "La página que buscas no existe o ya no está disponible."),
    405: ("Acción no permitida", "Esta dirección no admite esa acción. Vuelve al inicio e inténtalo desde allí."),
    413: ("Envío demasiado grande", "Lo que enviaste es demasiado grande. Revisa los datos e inténtalo de nuevo."),
    500: ("Algo salió mal", "Tuvimos un problema de nuestro lado. Inténtalo de nuevo en unos minutos."),
    503: ("El sistema está ocupado", db.MENSAJE_BASE_OCUPADA),
}
GENERICO = ("No pudimos completar la solicitud", "Vuelve al inicio e inténtalo de nuevo.")

HTML_MINIMO = (
    '<!doctype html><html lang="es-CL"><meta charset="utf-8"><title>Algo salió mal</title>'
    "<h1>Algo salió mal</h1><p>Tuvimos un problema de nuestro lado. Inténtalo de nuevo en unos minutos.</p>"
)


def pagina_de_error(error):
    codigo = error.code or 500
    titulo, mensaje = ERRORES.get(codigo, GENERICO)
    detalle = seguridad.MENSAJE_CSRF if error.description == seguridad.MENSAJE_CSRF else None
    try:
        cuerpo = render_template(
            "error.html", codigo=codigo, titulo=titulo, mensaje=mensaje, detalle=detalle
        )
    except Exception:  # la página de error nunca debe fallar a su vez
        cuerpo = HTML_MINIMO
    respuesta = (cuerpo, codigo)
    if codigo == 405 and getattr(error, "valid_methods", None):
        return cuerpo, codigo, {"Allow": ", ".join(sorted(error.valid_methods))}
    if codigo == 503:
        return cuerpo, codigo, {"Retry-After": str(ESPERA_REINTENTO_S)}
    return respuesta


# ----------------------------------------------------- errores de la base (T-14b) ----

ESPERA_REINTENTO_S = 5  # el mismo `Retry-After` que el bloqueo de intentos (limite.py)

# Adónde lleva el enlace de reintento tras una acción que no se pudo completar: la página desde
# la que se envió (no hay `Referer`: la política es `no-referrer`). Se decide por la ruta, sin
# consultar la sesión ni la base, que en ese momento pueden no responder.
DESTINOS_DE_REINTENTO = {
    "paciente.reservar": ("paciente.horas_libres", "Volver a las horas disponibles"),
    "paciente.cancelar": ("paciente.dashboard", "Volver a mi panel"),
    "paciente.marcar_notificaciones_leidas": ("paciente.dashboard", "Volver a mi panel"),
    "profesional.eliminar_hora": ("profesional.dashboard", "Volver a mi panel"),
    "profesional.marcar_notificaciones_leidas": ("profesional.dashboard", "Volver a mi panel"),
    "profesional.nueva_hora": ("profesional.nueva_hora", "Volver al formulario"),
}


def _enlace_de_reintento():
    destino = DESTINOS_DE_REINTENTO.get(request.endpoint)
    if destino is None:
        return None
    return {"url": url_for(destino[0]), "texto": destino[1]}


def _pagina_con_estado(codigo, titulo, mensaje, volver=None, cabeceras=None):
    try:
        cuerpo = render_template(
            "error.html", codigo=codigo, titulo=titulo, mensaje=mensaje, detalle=None, volver=volver
        )
    except Exception:  # la página de error nunca debe fallar a su vez
        cuerpo = HTML_MINIMO
    return cuerpo, codigo, cabeceras or {}


def error_de_base(error):
    """Traduce los fallos de SQLite que no son un bug a una página en español.

    - Base ocupada (otro proceso retiene el bloqueo más de 5 s): 503 con `Retry-After` y el
      mismo mensaje que el bloqueo de intentos, más un enlace para reintentar (T-11b R-02).
    - Base de una versión anterior (falta una tabla o columna y `user_version` es menor): 503
      con el aviso de correr `init-db` (T-14a R-09); el detalle va al log.
    Cualquier otro `OperationalError` se vuelve a lanzar: sigue siendo un 500 (un bug).
    """
    if db.esta_ocupada(error):
        return _pagina_con_estado(
            503, *ERRORES[503], volver=_enlace_de_reintento(),
            cabeceras={"Retry-After": str(ESPERA_REINTENTO_S)},
        )
    if db.es_esquema_antiguo(error):
        return _pagina_con_estado(503, "Falta actualizar la base de datos", db.MENSAJE_BASE_ANTIGUA)
    raise error


def init_app(app):
    app.register_error_handler(HTTPException, pagina_de_error)
    app.register_error_handler(sqlite3.OperationalError, error_de_base)
