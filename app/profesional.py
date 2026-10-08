"""Rutas del profesional. Por ahora solo el dashboard vacío (T-04)."""
from flask import Blueprint, render_template

from .auth import solo_profesional, usuario_actual

bp = Blueprint("profesional", __name__)


@bp.route("/profesional")
@solo_profesional
def dashboard():
    return render_template("profesional.html", usuario=usuario_actual())
