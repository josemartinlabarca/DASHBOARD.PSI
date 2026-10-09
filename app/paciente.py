"""Rutas del paciente: panel con «Mis reservas» (T-04, T-08), horas libres futuras (T-06, US-7),
reservar (T-07, US-8) y cancelar (T-08, US-9)."""
from datetime import datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, url_for

from . import notificaciones, tiempo
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
# D-029 (opción B, T-08e): reservar exige MÁS de 24 h de anticipación
# (inicio - ahora > 24 h, estrictamente, en instantes absolutos). Cancelar permite
# exactamente 24 h (>=): toda reserva aceptada tiene, al aceptarse, más de 24 h,
# así que siempre podría cancelarse en ese mismo instante.
ANTICIPACION_RESERVAR_S = 24 * 3600
MENSAJE_POCA_ANTICIPACION_RESERVA = (
    "Solo se puede reservar con más de 24 horas de anticipación, y a esa hora "
    "le falta menos. Elige otra de la lista."
)
MENSAJE_SOLAPE = (
    "No pudimos reservarla: se cruza con otra hora que ya reservaste ({otra}). "
    "Cancela esa reserva o elige otro horario."
)
MENSAJE_CONFIRMACION = "Listo, reservaste tu hora: {cuando} con {profesional}."

# US-9: se puede cancelar con «al menos 24 horas» de anticipación, es decir, con
# exactamente 24 h también (inicio - ahora >= 24 h, en instantes absolutos).
ANTICIPACION_CANCELAR_S = 24 * 3600
MENSAJE_RESERVA_NO_ENCONTRADA = (
    "No encontramos esa reserva entre las tuyas. Puede que ya esté cancelada."
)  # no existe, es de otra persona, ya está libre o no se puede interpretar: no se distingue
MENSAJE_POCA_ANTICIPACION = (
    "Solo puedes cancelar con al menos 24 horas de anticipación, y a esta sesión "
    "le falta menos (o ya pasó). Si necesitas cambiarla, comunícate con el profesional."
)
MENSAJE_CANCELADA = (
    "Cancelaste tu reserva del {cuando} con {profesional}. La hora quedó libre."
)


# T-09: la hora con lo necesario para avisar a ambas partes (el profesional es el DUEÑO de la
# hora, `horas.profesional_id`, no «el de rol profesional»). El paciente se une por el id de
# quien actúa, que es el que quedará en `horas.paciente_id`.
SELECT_HORA_Y_PARTES = (
    "SELECT h.inicio, h.duracion_min, h.estado, h.paciente_id, h.profesional_id,"
    " u.nombre AS profesional, u.email AS profesional_email,"
    " p.nombre AS paciente, p.email AS paciente_email"
    " FROM horas h JOIN usuarios u ON u.id = h.profesional_id"
    " LEFT JOIN usuarios p ON p.id = ? WHERE h.id = ?"
)


def listar_horas_libres_futuras(db, ahora):
    """Horas `libre` que todavía se pueden reservar, por inicio (T-08e, D-029).

    Solo se listan las que empiezan a MÁS de 24 h de `ahora` (con zona): las que
    faltan menos (o ya pasaron) se ocultan, porque `reservar_hora` las rechazaría.
    La decisión se toma con instantes absolutos (hora de Chile
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
        if inicio_s is None or inicio_s - ahora_s <= ANTICIPACION_RESERVAR_S:
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


def listar_reservas_futuras(db, paciente_id, ahora):
    """Reservas del paciente cuyo inicio es posterior a `ahora`, por instante (y luego id).

    Cada una trae `cancelable`: faltan al menos 24 h (instantes absolutos). Mismo
    criterio que `cancelar_reserva`, que es quien decide de verdad al enviar el
    formulario. Una sola consulta con JOIN (sin N+1); las filas con fecha o
    duración que no sirven no se muestran. Se ordena en Python por instante, no
    por el texto de `reservada_en` (no ordena bien en la noche de cambio de hora).
    """
    corte = ahora.replace(tzinfo=None) - timedelta(days=MARGEN_SQL_DIAS)
    filas = db.execute(
        "SELECT h.id, h.inicio, h.duracion_min, u.nombre AS profesional"
        " FROM horas h JOIN usuarios u ON u.id = h.profesional_id"
        " WHERE h.paciente_id = ? AND h.estado = 'reservada' AND h.inicio > ?",
        (paciente_id, corte.strftime(FORMATO_GUARDADO)),
    ).fetchall()
    ahora_s = ahora.timestamp()
    reservas = []
    for fila in filas:
        intervalo = tiempo.intervalo_guardado(fila)
        if intervalo is None or intervalo[0] <= ahora_s:
            continue
        reservas.append((intervalo[0], fila["id"], fila))
    reservas.sort(key=lambda t: (t[0], t[1]))
    return [
        {
            "id": fila["id"],
            "inicio": mostrar_inicio(fila["inicio"]),
            "duracion_min": fila["duracion_min"],
            "profesional": fila["profesional"],
            "cancelable": inicio_s - ahora_s >= ANTICIPACION_CANCELAR_S,
        }
        for inicio_s, _, fila in reservas
    ]


def listar_sesiones(db, paciente_id, ahora):
    """`(próxima, pasadas)` de las reservas del paciente, con instantes absolutos (T-11, US-10).

    Criterio (D-034): una sesión es «próxima» mientras no haya terminado, es decir,
    `fin > ahora` con `fin = inicio + duración`; así la que está en curso (ya empezó,
    aún no termina) sigue visible como próxima, marcada `en_curso`. Es «pasada» cuando
    `fin <= ahora` (la que termina justo ahora ya es pasada). La próxima es la de menor
    inicio entre las no terminadas (desempata el id); las pasadas van de la más reciente
    a la más antigua. Solo reservas propias en estado `reservada` (las canceladas vuelven
    a ser horas libres y no dejan rastro en `horas`). Filas con fecha o duración ilegibles
    se omiten. Las fechas se muestran en hora de Chile.
    """
    filas = db.execute(
        "SELECT h.id, h.inicio, h.duracion_min, u.nombre AS profesional"
        " FROM horas h JOIN usuarios u ON u.id = h.profesional_id"
        " WHERE h.paciente_id = ? AND h.estado = 'reservada'",
        (paciente_id,),
    ).fetchall()
    ahora_s = ahora.timestamp()
    por_venir, pasadas = [], []
    for fila in filas:
        intervalo = tiempo.intervalo_guardado(fila)
        if intervalo is None:
            continue
        sesion = {
            "id": fila["id"],
            "inicio": mostrar_inicio(fila["inicio"]),
            "duracion_min": fila["duracion_min"],
            "profesional": fila["profesional"],
            "en_curso": intervalo[0] <= ahora_s < intervalo[1],
        }
        if intervalo[1] > ahora_s:
            por_venir.append((intervalo[0], fila["id"], sesion))
        else:
            pasadas.append((intervalo[0], fila["id"], sesion))
    por_venir.sort(key=lambda t: (t[0], t[1]))
    pasadas.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return (por_venir[0][2] if por_venir else None), [t[2] for t in pasadas]


@bp.route("/paciente")
@solo_paciente
def dashboard():
    usuario = usuario_actual()
    db, ahora = get_db(), tiempo.ahora_chile()
    reservas = listar_reservas_futuras(db, usuario["id"], ahora)
    proxima, pasadas = listar_sesiones(db, usuario["id"], ahora)
    avisos, sin_leer = notificaciones.listar_de_usuario(db, usuario["id"])
    # Solo se enlaza a una reserva que sigue siendo de este paciente (está en su propia lista),
    # nunca por lo que diga `hora_id` (R-07 de T-10).
    propias = {r["id"] for r in reservas}
    for aviso in avisos:
        aviso["enlazable"] = aviso["hora_id"] is not None and aviso["hora_id"] in propias
    return render_template(
        "paciente.html", usuario=usuario, reservas=reservas, proxima=proxima,
        pasadas=pasadas, notificaciones=avisos, sin_leer=sin_leer,
    )


@bp.route("/notificaciones/leidas", methods=["POST"])
@solo_paciente
def marcar_notificaciones_leidas():
    """D-035: marca como leídas las del usuario en sesión; no lee ningún id del formulario."""
    cantidad = notificaciones.marcar_leidas(get_db(), usuario_actual()["id"])
    if cantidad == 1:
        flash("Marcaste 1 notificación como leída.", "exito")
    elif cantidad:
        flash(f"Marcaste {cantidad} notificaciones como leídas.", "exito")
    else:
        flash("No tenías notificaciones sin leer.", "exito")
    return redirect(url_for("paciente.dashboard"))


@bp.route("/paciente/horas")
@solo_paciente
def horas_libres():
    horas = listar_horas_libres_futuras(get_db(), tiempo.ahora_chile())
    return render_template("horas_libres.html", usuario=usuario_actual(), horas=horas)


# ------------------------------------------------------------- reservar ----


def reservar_hora(db, hora_id, paciente_id, reloj=None):
    """Reserva la hora para el paciente. Devuelve `(ok, mensaje)`.

    `reloj` es una función sin argumentos que devuelve «ahora» con zona (por
    defecto `tiempo.ahora_chile`, buscado al llamar). Se invoca **después** de
    obtener el bloqueo (T-08, R-02): si la petición esperó el bloqueo, «ahora» y
    `reservada_en` son los del instante real en que se decide, no los de antes de esperar.

    Todo ocurre en una transacción `BEGIN IMMEDIATE`: se toma el bloqueo de
    escritura **antes** de leer, así entre la comprobación de las reglas y el
    UPDATE nadie más puede escribir (ni otro paciente, ni el profesional que
    elimina la hora, ni el mismo paciente con otro clic). La sentencia que
    decide la regla 1 sigue siendo el UPDATE condicional de D-003 con revisión
    de `rowcount`. Regla 5: el paciente no puede tener dos reservas cuyos
    intervalos [inicio, fin) se solapen, medidos en instantes absolutos.
    Los mensajes no dicen quién tiene una hora ocupada. D-029: solo se reserva si
    faltan más de 24 h (`inicio - ahora > 24 h`, en instantes absolutos), con el
    reloj leído dentro del bloqueo.
    """
    db.execute("BEGIN IMMEDIATE")
    try:
        ahora = (reloj or tiempo.ahora_chile)()
        hora = db.execute(
            SELECT_HORA_Y_PARTES, (paciente_id, hora_id)
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
        faltan_s = inicio_s - ahora.timestamp()
        if faltan_s <= 0:
            db.rollback()
            return False, MENSAJE_YA_PASO
        if faltan_s <= ANTICIPACION_RESERVAR_S:  # D-029: más de 24 h, estrictamente
            db.rollback()
            return False, MENSAJE_POCA_ANTICIPACION_RESERVA
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
        # T-09: los avisos van dentro de la transacción, antes del commit (atómicos con la reserva)
        avisos = notificaciones.registrar(
            db, notificaciones.CONFIRMACION, hora_id, hora, paciente_id,
            ahora.isoformat(timespec="seconds"),
        )
        db.commit()
    except BaseException:
        db.rollback()
        raise
    notificaciones.escribir_outbox(avisos)  # después del commit: un fallo de disco no deshace nada
    cuando = mostrar_inicio(hora["inicio"])
    return True, MENSAJE_CONFIRMACION.format(cuando=cuando, profesional=hora["profesional"])


@bp.route(f"/horas/<int(min=1, max={ID_MAX}):hora_id>/reservar", methods=["POST"])
@solo_paciente
def reservar(hora_id):
    ok, mensaje = reservar_hora(get_db(), hora_id, usuario_actual()["id"])
    flash(mensaje, "exito" if ok else "error")
    return redirect(url_for("paciente.dashboard" if ok else "paciente.horas_libres"))


# ------------------------------------------------------------- cancelar ----


def cancelar_reserva(db, hora_id, paciente_id, reloj=None):
    """Cancela la reserva del paciente y deja la hora libre. Devuelve `(ok, mensaje)`.

    Misma estructura que `reservar_hora`: `BEGIN IMMEDIATE`, luego el reloj
    (después de esperar el bloqueo), luego las reglas y al final un UPDATE
    condicional `WHERE id = ? AND paciente_id = ? AND estado = 'reservada'` con
    revisión de `rowcount` (D-003): solo se cancela una reserva propia, y solo si
    sigue vigente. La hora vuelve al estado de una hora nueva: `libre`, sin
    paciente ni `reservada_en` y con `recordatorio_enviado` en 0 (D-030).
    Anticipación: `inicio - ahora >= 24 h` en instantes absolutos (no hora de pared).
    Una hora inexistente, ajena, ya libre o ilegible da el mismo mensaje.
    """
    db.execute("BEGIN IMMEDIATE")
    try:
        ahora = (reloj or tiempo.ahora_chile)()
        hora = db.execute(
            SELECT_HORA_Y_PARTES, (paciente_id, hora_id)
        ).fetchone()
        if hora is None or hora["estado"] != "reservada" or hora["paciente_id"] != paciente_id:
            db.rollback()
            return False, MENSAJE_RESERVA_NO_ENCONTRADA
        intervalo = tiempo.intervalo_guardado(hora)
        if intervalo is None:
            db.rollback()
            return False, MENSAJE_RESERVA_NO_ENCONTRADA
        if intervalo[0] - ahora.timestamp() < ANTICIPACION_CANCELAR_S:
            db.rollback()
            return False, MENSAJE_POCA_ANTICIPACION
        canceladas = db.execute(
            "UPDATE horas SET estado = 'libre', paciente_id = NULL, reservada_en = NULL,"
            " recordatorio_enviado = 0"
            " WHERE id = ? AND paciente_id = ? AND estado = 'reservada'",
            (hora_id, paciente_id),
        ).rowcount
        if canceladas != 1:
            db.rollback()
            return False, MENSAJE_RESERVA_NO_ENCONTRADA
        avisos = notificaciones.registrar(
            db, notificaciones.CANCELACION, hora_id, hora, paciente_id,
            ahora.isoformat(timespec="seconds"),
        )
        db.commit()
    except BaseException:
        db.rollback()
        raise
    notificaciones.escribir_outbox(avisos)
    cuando = mostrar_inicio(hora["inicio"])
    return True, MENSAJE_CANCELADA.format(cuando=cuando, profesional=hora["profesional"])


@bp.route(f"/horas/<int(min=1, max={ID_MAX}):hora_id>/cancelar", methods=["POST"])
@solo_paciente
def cancelar(hora_id):
    ok, mensaje = cancelar_reserva(get_db(), hora_id, usuario_actual()["id"])
    flash(mensaje, "exito" if ok else "error")
    return redirect(url_for("paciente.dashboard"))
