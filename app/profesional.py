"""Rutas del profesional: panel con sus horas, agregar y eliminar horas (T-05).

Reglas de SPEC §4 que se aplican aquí: 2 (nada en el pasado), 3 (las horas del
profesional no se solapan) y 4 (no se elimina una hora reservada).
"""
import re
import sqlite3
from datetime import datetime, time, timezone

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from . import tiempo
from .auth import solo_profesional, usuario_actual, zona_chile
from .db import get_db
from .tiempo import FORMATO_GUARDADO, mostrar_inicio

bp = Blueprint("profesional", __name__)

DURACION_DEFECTO = 50  # US-4
DURACION_MAX = 480  # minutos (8 horas); límite de la aplicación, no del esquema
ID_MAX = 2**63 - 1  # mayor INTEGER de SQLite: un id mayor es 404, no 500 (R-10)
FORMATO_FECHA = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")  # solo dígitos ASCII
FORMATO_HORA = re.compile(r"[0-9]{2}:[0-9]{2}")
FORMATO_DURACION = re.compile(r"[0-9]{1,4}")
ANIOS_MAX = 2  # tope de fecha futura: hoy + 2 años (D-026); límite de la aplicación

MENSAJE_FECHA = "Escribe una fecha válida, por ejemplo 2026-12-01."
MENSAJE_HORA = "Escribe una hora válida, por ejemplo 10:00."
MENSAJE_DURACION = (
    f"La duración debe ser un número entero de minutos entre 1 y {DURACION_MAX}."
)
MENSAJE_FECHA_LEJANA = (
    "Esa fecha está demasiado lejos. Elige una fecha hasta el {limite} "
    f"(máximo {ANIOS_MAX} años desde hoy)."
)
MENSAJE_PASADO = "Esa hora ya pasó. Elige una fecha y hora futuras."
MENSAJE_HORA_INEXISTENTE = (
    "Esa hora no existe en Chile: por el cambio al horario de verano el reloj "
    "salta de las 23:59 a las 01:00. Elige otra hora."
)
MENSAJE_HORA_AMBIGUA = (
    "Esa hora ocurre dos veces en Chile por el cambio de horario (el reloj "
    "se atrasa a las 23:00). Elige otra hora para evitar confusiones."
)
MENSAJE_SOLAPE = "Esa hora se solapa con otra que ya publicaste ({otra}). Elige otro horario."
MENSAJE_YA_PUBLICADA = "Esa hora ya está publicada."
MENSAJE_NO_GUARDADA = "No pudimos guardar la hora. Revisa los datos e inténtalo de nuevo."
MENSAJE_RESERVADA = (
    "No se puede eliminar una hora reservada. Primero debe cancelarse la reserva."
)


# ------------------------------------------------------------ validación ----


def interpretar_fecha(texto):
    """`date` si `texto` es `AAAA-MM-DD` de un día real del calendario; si no, `None`."""
    if not FORMATO_FECHA.fullmatch(texto):
        return None
    try:
        return datetime.strptime(texto, "%Y-%m-%d").date()
    except ValueError:  # 2026-02-30, mes 13, año 0000...
        return None


def interpretar_hora(texto):
    """`time` si `texto` es `HH:MM` con hora 00-23 y minutos 00-59; si no, `None`."""
    if not FORMATO_HORA.fullmatch(texto):
        return None
    horas, minutos = int(texto[:2]), int(texto[3:])
    if horas > 23 or minutos > 59:
        return None
    return time(horas, minutos)


def interpretar_duracion(texto):
    """Entero de minutos entre 1 y `DURACION_MAX`; vacío significa el valor por defecto.

    Solo dígitos ASCII: nada de signos, decimales, notación científica ni
    dígitos de otros alfabetos (que `int()` sí aceptaría). Devuelve `None` si
    no es válida.
    """
    if texto == "":
        return DURACION_DEFECTO
    if not FORMATO_DURACION.fullmatch(texto):
        return None
    minutos = int(texto)
    return minutos if 1 <= minutos <= DURACION_MAX else None


def problema_de_horario(inicio, ahora):
    """Mensaje si el `datetime` ingenuo `inicio` (hora local) no sirve; si no, `None`.

    Chile cambia de hora a las 24:00 de un sábado: en septiembre el reloj salta
    de las 23:59 a las 01:00 (la hora 00:xx **no existe**) y en abril se atrasa
    de las 24:00 a las 23:00 (la hora 23:xx **ocurre dos veces**). En ambos
    casos se rechaza la hora en vez de adivinar cuál se quiso (D-025).
    """
    zona = zona_chile()
    primera = inicio.replace(tzinfo=zona, fold=0)
    segunda = inicio.replace(tzinfo=zona, fold=1)
    if primera.utcoffset() != segunda.utcoffset():
        ida_y_vuelta = primera.astimezone(timezone.utc).astimezone(zona)
        if ida_y_vuelta.replace(tzinfo=None) != inicio:
            return MENSAJE_HORA_INEXISTENTE
        return MENSAJE_HORA_AMBIGUA
    if primera <= ahora:
        return MENSAJE_PASADO
    return None


def fecha_limite(hoy):
    """Último día que se puede publicar: `hoy` más `ANIOS_MAX` años (29-feb -> 28-feb)."""
    try:
        return hoy.replace(year=hoy.year + ANIOS_MAX)
    except ValueError:
        return hoy.replace(year=hoy.year + ANIOS_MAX, day=28)


def validar_formulario(fecha_texto, hora_texto, duracion_texto, ahora):
    """Devuelve `(inicio, duracion, errores)`; `inicio` es un `datetime` ingenuo o `None`."""
    errores = {}
    fecha = interpretar_fecha(fecha_texto)
    hora = interpretar_hora(hora_texto)
    duracion = interpretar_duracion(duracion_texto)
    if fecha is None:
        errores["fecha"] = MENSAJE_FECHA
    if hora is None:
        errores["hora"] = MENSAJE_HORA
    if duracion is None:
        errores["duracion"] = MENSAJE_DURACION
    inicio = None
    if fecha is not None:
        limite = fecha_limite(ahora.date())
        if fecha > limite:
            errores["fecha"] = MENSAJE_FECHA_LEJANA.format(limite=f"{limite:%d-%m-%Y}")
        elif hora is not None:
            inicio = datetime.combine(fecha, hora)
            problema = problema_de_horario(inicio, ahora)
            if problema:
                errores["fecha"] = problema
                inicio = None
    return inicio, duracion, errores


def formatear_inicio(inicio):
    """El único camino hacia `horas.inicio`: `YYYY-MM-DDTHH:MM:SS` desde un `datetime`."""
    return inicio.isoformat(timespec="seconds")


# ----------------------------------------------------------------- horas ----


def _minutos_guardados(valor):
    """Minutos de una fila si son un entero positivo, o `None` (texto, decimal, cero...)."""
    if type(valor) is not int or valor <= 0:
        return None
    return valor


def _intervalo_guardado(fila):
    """`(inicio_s, fin_s)` en segundos UTC de una fila, o `None` si la fila no sirve."""
    try:
        local = datetime.strptime(fila["inicio"], FORMATO_GUARDADO)
    except (ValueError, TypeError):  # fecha imposible como 2026-13-45T99:99:99
        return None
    minutos = _minutos_guardados(fila["duracion_min"])
    inicio_s = tiempo.a_segundos_utc(local)
    if minutos is None or inicio_s is None:
        return None
    return inicio_s, inicio_s + minutos * 60


def es_la_misma(fila, inicio, duracion):
    """La fila tiene exactamente el mismo inicio y la misma duración que la hora nueva."""
    try:
        return datetime.strptime(fila["inicio"], FORMATO_GUARDADO) == inicio and (
            fila["duracion_min"] == duracion
        )
    except (ValueError, TypeError):
        return False


def buscar_solape(db, profesional_id, inicio, duracion):
    """Fila de una hora **del mismo profesional** que se solape con la nueva, o `None`.

    Inicio y fin son instantes absolutos (hora de Chile convertida a UTC) y se
    comparan en Python: así las dos noches de cambio de horario, en que la
    duración real no coincide con la del reloj de pared, salen bien (D-026).
    Dos intervalos [a, b) y [c, d) se solapan si a < d y c < b: las horas
    pegadas (una termina cuando empieza la otra) no se solapan. Si hay varias
    solapadas, devuelve la idéntica a la nueva (mismo inicio y duración) si
    existe y si no la primera por fecha. Las filas que el esquema deja pasar
    pero no son una fecha real o una duración entera positiva no se comparan.
    """
    inicio_s = tiempo.a_segundos_utc(inicio)
    if inicio_s is None:
        raise ValueError("inicio fuera del rango representable")
    fin_s = inicio_s + duracion * 60
    primera = None
    filas = db.execute(
        "SELECT inicio, duracion_min FROM horas WHERE profesional_id = ? ORDER BY inicio",
        (profesional_id,),
    ).fetchall()
    for fila in filas:
        intervalo = _intervalo_guardado(fila)
        if intervalo is None or not (intervalo[0] < fin_s and inicio_s < intervalo[1]):
            continue
        if es_la_misma(fila, inicio, duracion):
            return fila
        if primera is None:
            primera = fila
    return primera


def crear_hora(db, profesional_id, inicio, duracion):
    """Inserta la hora si no se solapa. Devuelve `None` o el mensaje de rechazo.

    La comprobación y el INSERT van en una transacción `BEGIN IMMEDIATE`: toma
    el bloqueo de escritura antes de mirar, así otra petición no puede insertar
    una hora solapada entre la comprobación y el INSERT. El esquema solo impide
    inicios idénticos (UNIQUE), no solapes parciales.
    """
    db.execute("BEGIN IMMEDIATE")
    try:
        otra = buscar_solape(db, profesional_id, inicio, duracion)
        if otra is not None:
            db.rollback()
            if es_la_misma(otra, inicio, duracion):
                return MENSAJE_YA_PUBLICADA  # doble envío del mismo formulario (R-04)
            return MENSAJE_SOLAPE.format(otra=_describir(otra))
        db.execute(
            "INSERT INTO horas (profesional_id, inicio, duracion_min) VALUES (?, ?, ?)",
            (profesional_id, formatear_inicio(inicio), duracion),
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        return MENSAJE_NO_GUARDADA
    except BaseException:
        db.rollback()
        raise
    return None


def _describir(fila):
    """`01-12-2026 10:00 a 10:50` para el mensaje de solape; nunca lanza excepción.

    El fin es la hora de reloj de Chile del instante final. Si la fila no
    permite calcularlo (fecha imposible, duración rara, año 9999) se muestra
    solo el inicio.
    """
    texto = str(fila["inicio"])
    try:
        _, fin_s = _intervalo_guardado(fila)
        fin = datetime.fromtimestamp(fin_s, zona_chile())
        return f"{mostrar_inicio(texto)} a {fin:%H:%M}"
    except (TypeError, ValueError, OverflowError, OSError):
        return mostrar_inicio(texto)


def listar_horas_futuras(db, profesional_id, ahora):
    ahora_local = formatear_inicio(ahora.replace(tzinfo=None))
    filas = db.execute(
        "SELECT id, inicio, duracion_min, estado FROM horas"
        " WHERE profesional_id = ? AND inicio > ? ORDER BY inicio",
        (profesional_id, ahora_local),
    ).fetchall()
    return [
        {
            "id": f["id"],
            "inicio": mostrar_inicio(f["inicio"]),
            "duracion_min": f["duracion_min"],
            "reservada": f["estado"] == "reservada",
        }
        for f in filas
    ]


# ----------------------------------------------------------------- rutas ----


@bp.route("/profesional")
@solo_profesional
def dashboard():
    usuario = usuario_actual()
    horas = listar_horas_futuras(get_db(), usuario["id"], tiempo.ahora_chile())
    return render_template("profesional.html", usuario=usuario, horas=horas)


@bp.route("/profesional/horas/nueva", methods=["GET", "POST"])
@solo_profesional
def nueva_hora():
    if request.method == "GET":
        return render_template(
            "nueva_hora.html", fecha="", hora="", duracion=str(DURACION_DEFECTO), errores={}
        )
    fecha = request.form.get("fecha", "").strip()
    hora = request.form.get("hora", "").strip()
    duracion_texto = request.form.get("duracion", "").strip()
    inicio, duracion, errores = validar_formulario(fecha, hora, duracion_texto, tiempo.ahora_chile())
    if not errores:
        rechazo = crear_hora(get_db(), usuario_actual()["id"], inicio, duracion)
        if rechazo is None:
            flash("La hora se agregó correctamente.", "exito")
            return redirect(url_for("profesional.dashboard"))
        errores["general"] = rechazo
    return render_template(
        "nueva_hora.html", fecha=fecha, hora=hora, duracion=duracion_texto, errores=errores
    )


@bp.route(
    f"/profesional/horas/<int(min=1, max={ID_MAX}):hora_id>/eliminar", methods=["POST"]
)
@solo_profesional
def eliminar_hora(hora_id):
    """Elimina una hora **libre y propia**; todo en una sola sentencia atómica.

    El `WHERE` incluye `profesional_id` y `estado = 'libre'`: no se puede borrar
    la hora de otro profesional ni una reservada, aunque se fuerce el POST. Una
    hora reservada y luego cancelada vuelve a `libre` y sí se borra; sus
    notificaciones quedan con `hora_id` NULL (`ON DELETE SET NULL`, D-016).
    """
    db = get_db()
    profesional_id = usuario_actual()["id"]
    borradas = db.execute(
        "DELETE FROM horas WHERE id = ? AND profesional_id = ? AND estado = 'libre'",
        (hora_id, profesional_id),
    ).rowcount
    db.commit()
    if borradas:
        flash("La hora se eliminó correctamente.", "exito")
        return redirect(url_for("profesional.dashboard"))
    propia_reservada = db.execute(
        "SELECT 1 FROM horas WHERE id = ? AND profesional_id = ? AND estado = 'reservada'",
        (hora_id, profesional_id),
    ).fetchone()
    if propia_reservada:
        flash(MENSAJE_RESERVADA, "error")
        return redirect(url_for("profesional.dashboard"))
    abort(404)  # no existe o es de otro profesional: no se distingue
