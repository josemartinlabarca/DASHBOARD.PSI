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
from flask import render_template
from werkzeug.exceptions import HTTPException

from . import seguridad

ERRORES = {
    400: ("Solicitud no válida", "No pudimos procesar lo que enviaste. Vuelve al inicio e inténtalo de nuevo."),
    403: ("Acceso denegado", "No tienes permiso para ver esta página."),
    404: ("Página no encontrada", "La página que buscas no existe o ya no está disponible."),
    405: ("Acción no permitida", "Esta dirección no admite esa acción. Vuelve al inicio e inténtalo desde allí."),
    413: ("Envío demasiado grande", "Lo que enviaste es demasiado grande. Revisa los datos e inténtalo de nuevo."),
    500: ("Algo salió mal", "Tuvimos un problema de nuestro lado. Inténtalo de nuevo en unos minutos."),
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
    return respuesta


def init_app(app):
    app.register_error_handler(HTTPException, pagina_de_error)
