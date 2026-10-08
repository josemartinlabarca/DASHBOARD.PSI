"""Rutas del paciente. Por ahora solo el dashboard vacío (T-04)."""
from flask import Blueprint, render_template

from .auth import solo_paciente, usuario_actual

bp = Blueprint("paciente", __name__)


@bp.route("/paciente")
@solo_paciente
def dashboard():
    return render_template("paciente.html", usuario=usuario_actual())
