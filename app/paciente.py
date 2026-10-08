"""Rutas del paciente: panel (T-04), horas libres futuras (T-06, US-7) y reservar (T-07, US-8)."""
from datetime import datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, url_for

from . import tiempo
from .auth import solo_paciente, usuario_actual
from .db import get_db
from .tiempo import FORMATO_GUARDADO, mostrar_inicio

bp = Blueprint("paciente", __name__)

# El desfase de Chile con UTC nunca pasa de 4 horas: un día de margen basta para
# que el SQL traiga de más y Python decida con el instante exacto.
MARGEN_SQL_DIAS = 1

ID_MAX = 2**63 - 1  # mayor INTEGER de SQLite: un id mayor es 404, no 500 (R-10)

MENSAJE_NO_DISPONIBLE = (
    "Esa hora ya no está disponible. Elige otra de la lista."
)  # no existe (la eliminó el profesional) o la tiene otra persona: no se distingue
MENSAJE_YA_ES_TUYA = "Ya reservaste esta hora."
MENSAJE_YA_PASO = "Esa hora ya empezó o ya pasó. Elige otra de la lista."
MENSAJE_SOLAPE = (
    "No pudimos reservarla: se cruza con otra hora que ya reservaste ({otra}). "
    "Cancela esa reserva o elige otro horario."
)
MENSAJE_CONFIRMACION = "Listo, reservaste tu hora: {cuando} con {profesional}."


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


# ------------------------------------------------------------- reservar ----


def reservar_hora(db, hora_id, paciente_id, ahora):
    """Reserva la hora para el paciente. Devuelve `(ok, mensaje)`.

    Todo ocurre en una transacción `BEGIN IMMEDIATE`: se toma el bloqueo de
    escritura **antes** de leer, así entre la comprobación de las reglas y el
    UPDATE nadie más puede escribir (ni otro paciente, ni el profesional que
    elimina la hora, ni el mismo paciente con otro clic). La sentencia que
    decide la regla 1 sigue siendo el UPDATE condicional de D-003 con revisión
    de `rowcount`. Regla 5: el paciente no puede tener dos reservas cuyos
    intervalos [inicio, fin) se solapen, medidos en instantes absolutos.
    Los mensajes no dicen quién tiene una hora ocupada.
    """
    db.execute("BEGIN IMMEDIATE")
    try:
        hora = db.execute(
            "SELECT h.inicio, h.duracion_min, h.estado, h.paciente_id, u.nombre AS profesional"
            " FROM horas h JOIN usuarios u ON u.id = h.profesional_id WHERE h.id = ?",
            (hora_id,),
        ).fetchone()
        if hora is None:
            db.rollback()
            return False, MENSAJE_NO_DISPONIBLE
        if hora["estado"] != "libre":
            db.rollback()
            if hora["paciente_id"] == paciente_id:
                return False, MENSAJE_YA_ES_TUYA
            return False, MENSAJE_NO_DISPONIBLE
        intervalo = tiempo.intervalo_guardado(hora)
        if intervalo is None:
            db.rollback()
            return False, MENSAJE_NO_DISPONIBLE
        inicio_s, fin_s = intervalo
        if inicio_s <= ahora.timestamp():
            db.rollback()
            return False, MENSAJE_YA_PASO
        for propia in db.execute(
            "SELECT inicio, duracion_min FROM horas WHERE paciente_id = ? AND estado = 'reservada'"
            " ORDER BY inicio",
            (paciente_id,),
        ).fetchall():
            otro = tiempo.intervalo_guardado(propia)
            if otro is not None and otro[0] < fin_s and inicio_s < otro[1]:
                db.rollback()
                return False, MENSAJE_SOLAPE.format(otra=mostrar_inicio(propia["inicio"]))
        reservadas = db.execute(
            "UPDATE horas SET estado = 'reservada', paciente_id = ?, reservada_en = ?"
            " WHERE id = ? AND estado = 'libre'",
            (paciente_id, ahora.isoformat(timespec="seconds"), hora_id),
        ).rowcount
        if reservadas != 1:
            db.rollback()
            return False, MENSAJE_NO_DISPONIBLE
        db.commit()
    except BaseException:
        db.rollback()
        raise
    cuando = mostrar_inicio(hora["inicio"])
    return True, MENSAJE_CONFIRMACION.format(cuando=cuando, profesional=hora["profesional"])


@bp.route(f"/horas/<int(min=1, max={ID_MAX}):hora_id>/reservar", methods=["POST"])
@solo_paciente
def reservar(hora_id):
    ok, mensaje = reservar_hora(
        get_db(), hora_id, usuario_actual()["id"], tiempo.ahora_chile()
    )
    flash(mensaje, "exito" if ok else "error")
    return redirect(url_for("paciente.dashboard" if ok else "paciente.horas_libres"))
