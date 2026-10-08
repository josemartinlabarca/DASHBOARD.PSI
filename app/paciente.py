"""Rutas del paciente: panel (T-04) y lista de horas libres futuras (T-06, US-7)."""
from datetime import datetime, timedelta

from flask import Blueprint, render_template

from . import tiempo
from .auth import solo_paciente, usuario_actual
from .db import get_db
from .tiempo import FORMATO_GUARDADO, mostrar_inicio

bp = Blueprint("paciente", __name__)

# El desfase de Chile con UTC nunca pasa de 4 horas: un día de margen basta para
# que el SQL traiga de más y Python decida con el instante exacto.
MARGEN_SQL_DIAS = 1


def listar_horas_libres_futuras(db, ahora):
    """Horas `libre` cuyo instante de inicio es posterior a `ahora` (con zona), por inicio.

    La decisión «futura» se toma con instantes absolutos (hora de Chile
    convertida a UTC, contra `ahora.timestamp()`), no con el texto ni con la
    hora UTC en reloj de pared. El SQL solo acota por un margen de un día para
    no leer todo el historial. Una sola consulta con JOIN trae el nombre del
    profesional (sin N+1); no se lee ningún correo. El orden lo fija Python: instante y luego id.
    Las filas con una fecha que el esquema deja pasar pero no existe (o que no
    se puede representar) no se muestran.
    """
    corte = ahora.replace(tzinfo=None) - timedelta(days=MARGEN_SQL_DIAS)
    filas = db.execute(
        "SELECT h.id, h.inicio, h.duracion_min, u.nombre AS profesional"
        " FROM horas h JOIN usuarios u ON u.id = h.profesional_id"
        " WHERE h.estado = 'libre' AND h.inicio > ?",
        (corte.strftime(FORMATO_GUARDADO),),
    ).fetchall()
    ahora_s = ahora.timestamp()
    horas = []
    for fila in filas:
        try:
            local = datetime.strptime(fila["inicio"], FORMATO_GUARDADO)
        except (ValueError, TypeError):
            continue
        inicio_s = tiempo.a_segundos_utc(local)
        if inicio_s is None or inicio_s <= ahora_s:
            continue
        horas.append((inicio_s, fila["id"], fila))
    horas.sort(key=lambda t: (t[0], t[1]))
    return [
        {
            "id": fila["id"],
            "inicio": mostrar_inicio(fila["inicio"]),
            "duracion_min": fila["duracion_min"],
            "profesional": fila["profesional"],
        }
        for _, _, fila in horas
    ]


@bp.route("/paciente")
@solo_paciente
def dashboard():
    return render_template("paciente.html", usuario=usuario_actual())


@bp.route("/paciente/horas")
@solo_paciente
def horas_libres():
    horas = listar_horas_libres_futuras(get_db(), tiempo.ahora_chile())
    return render_template("horas_libres.html", usuario=usuario_actual(), horas=horas)
