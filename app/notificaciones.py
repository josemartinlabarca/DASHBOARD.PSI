"""Notificaciones de confirmación y cancelación (T-09; US-11, US-13; SPEC §5).

Dos pasos, pensados para llamarse desde `reservar_hora` y `cancelar_reserva`:

1. `registrar(...)`: inserta las filas de `notificaciones` (paciente y profesional de la
   hora). Se llama **dentro** de la transacción `BEGIN IMMEDIATE`, antes del `commit`:
   reserva y aviso son atómicos (si el insert falla no queda reserva).
2. `escribir_outbox(...)`: añade una línea por aviso a `outbox.log` simulando el correo.
   Se llama **después** del `commit`: un fallo de disco no deshace la reserva ni da 500
   (se registra con `app.logger.error` y se sigue).

El profesional avisado es `horas.profesional_id` (el dueño de la hora), no «el profesional»
por rol. El mensaje se basta solo (fecha, hora de Chile, contraparte): `hora_id` queda NULL
si la hora se elimina (D-016).
"""
import os
import unicodedata
from datetime import datetime
from typing import NamedTuple

from flask import current_app

from . import tiempo
from .auth import zona_chile

NOMBRE_OUTBOX = "outbox.log"
ANTICIPACION_CANCELAR_S = 24 * 3600  # igual que paciente.ANTICIPACION_CANCELAR_S (US-9)

CONFIRMACION = "confirmacion"
CANCELACION = "cancelacion"

MSG_CONFIRMACION_PACIENTE = (
    "Confirmamos tu hora con {profesional} el {cuando} (hora de Chile), de {duracion} minutos. "
    "Puedes cancelarla hasta el {limite} (hora de Chile)."
)
MSG_CONFIRMACION_PROFESIONAL = (
    "{paciente} reservó una hora contigo el {cuando} (hora de Chile), de {duracion} minutos."
)
MSG_CANCELACION_PACIENTE = (
    "Cancelaste tu hora con {profesional} del {cuando} (hora de Chile). La hora quedó libre."
)
MSG_CANCELACION_PROFESIONAL = (
    "{paciente} canceló su hora contigo del {cuando} (hora de Chile). La hora quedó libre."
)


class Aviso(NamedTuple):
    """Lo que hace falta para escribir una línea del log."""

    creada_en: str
    destinatario: str  # correo
    tipo: str
    mensaje: str


def _cuando(inicio):
    """`2026-12-01T10:00:00` -> `01-12-2026 a las 10:00`."""
    fecha, hora = tiempo.mostrar_inicio(inicio).split(" ")
    return f"{fecha} a las {hora}"


def _limite_para_cancelar(inicio):
    """Hasta cuándo se puede cancelar: inicio - 24 h en instantes absolutos, en hora de Chile.

    Se resta sobre el instante, no sobre la hora de pared: en la noche de cambio de horario
    las dos cuentas difieren en una hora. `None` si el inicio no se puede interpretar.
    """
    try:
        local = datetime.strptime(inicio, tiempo.FORMATO_GUARDADO)
    except (ValueError, TypeError):
        return None
    inicio_s = tiempo.a_segundos_utc(local)
    if inicio_s is None:
        return None
    try:
        limite = datetime.fromtimestamp(inicio_s - ANTICIPACION_CANCELAR_S, zona_chile())
    except (OverflowError, OSError, ValueError):
        return None
    return _cuando(limite.strftime(tiempo.FORMATO_GUARDADO))


def _mensajes(tipo, hora):
    """`(mensaje para el paciente, mensaje para el profesional)` del aviso `tipo`."""
    datos = {
        "profesional": hora["profesional"],
        "paciente": hora["paciente"],
        "cuando": _cuando(hora["inicio"]),
        "duracion": hora["duracion_min"],
    }
    if tipo == CONFIRMACION:
        datos["limite"] = _limite_para_cancelar(hora["inicio"]) or "24 horas antes de la sesión"
        return (
            MSG_CONFIRMACION_PACIENTE.format(**datos),
            MSG_CONFIRMACION_PROFESIONAL.format(**datos),
        )
    return MSG_CANCELACION_PACIENTE.format(**datos), MSG_CANCELACION_PROFESIONAL.format(**datos)


def registrar(db, tipo, hora_id, hora, paciente_id, creada_en):
    """Inserta la notificación del paciente y la del profesional de la hora; devuelve los `Aviso`.

    `hora` es la fila leída dentro del bloqueo con `profesional_id`, `inicio`, `duracion_min`,
    `profesional`, `profesional_email`, `paciente` y `paciente_email`. No hace `commit`: lo hace
    quien llama, para que reserva (o cancelación) y avisos se confirmen juntos.
    """
    para_paciente, para_profesional = _mensajes(tipo, hora)
    destinos = [
        (paciente_id, hora["paciente_email"], para_paciente),
        (hora["profesional_id"], hora["profesional_email"], para_profesional),
    ]
    avisos = []
    for usuario_id, correo, mensaje in destinos:
        db.execute(
            "INSERT INTO notificaciones (usuario_id, tipo, mensaje, hora_id, creada_en)"
            " VALUES (?, ?, ?, ?, ?)",
            (usuario_id, tipo, mensaje, hora_id, creada_en),
        )
        avisos.append(Aviso(creada_en, correo, tipo, mensaje))
    return avisos


# ------------------------------------------------------------ outbox.log ----


def sanear(valor):
    """Texto seguro para UNA línea del log: nada que pueda terminarla o falsificar otra.

    Se escapan (como `\\uXXXX`) los caracteres de control (`C*`: saltos, NUL, ESC, tabulador...),
    los separadores de línea y párrafo (`Zl`, `Zp`: U+2028/2029), los espacios que no son el
    espacio normal (`Zs`: NBSP, U+3000...) y NEL (U+0085, ya `Cc`). La barra invertida se duplica
    para que un nombre no pueda imitar un escape. No se confía en que los nombres y correos ya
    hayan sido validados al registrarse.
    """
    if not isinstance(valor, str):
        valor = "" if valor is None else str(valor)
    salida = []
    for caracter in valor:
        categoria = unicodedata.category(caracter)
        if caracter == "\\":
            salida.append("\\\\")
        elif categoria[0] == "C" or categoria in ("Zl", "Zp") or (categoria == "Zs" and caracter != " "):
            salida.append(f"\\u{ord(caracter):04x}" if ord(caracter) <= 0xFFFF else f"\\U{ord(caracter):08x}")
        else:
            salida.append(caracter)
    return "".join(salida)


def linea_outbox(aviso):
    """Una sola línea: `fecha<TAB>destinatario<TAB>tipo<TAB>mensaje<LF>`. El tabulador no puede
    aparecer dentro de un campo porque `sanear` lo escapa."""
    campos = (aviso.creada_en, aviso.destinatario, aviso.tipo, aviso.mensaje)
    return "\t".join(sanear(campo) for campo in campos) + "\n"


def ruta_outbox(app=None):
    """`OUTBOX_PATH` si está configurada; si no, `outbox.log` junto a la base de datos."""
    app = app or current_app
    ruta = app.config.get("OUTBOX_PATH")
    if ruta:
        return os.fspath(ruta)
    return os.path.join(os.path.dirname(os.path.abspath(app.config["DATABASE"])), NOMBRE_OUTBOX)


def _escribir_completo(descriptor, datos):
    while datos:
        escritos = os.write(descriptor, datos)
        datos = datos[escritos:]


def escribir_outbox(avisos):
    """Añade una línea por aviso a `outbox.log` (UTF-8, modo append, un `write` por línea).

    Con `O_APPEND` y un único `write` por línea, dos procesos que escriben a la vez no
    entrelazan sus líneas. Crea la carpeta si falta. Nunca lanza `OSError`: si el disco falla
    lo registra con `app.logger.error` (sin el contenido de los mensajes) y sigue, porque la
    reserva ya está confirmada. Devuelve True si se escribió todo.
    """
    ruta = None
    try:
        ruta = ruta_outbox()
        carpeta = os.path.dirname(ruta)
        if carpeta:
            os.makedirs(carpeta, exist_ok=True)
        descriptor = os.open(ruta, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            for aviso in avisos:
                _escribir_completo(descriptor, linea_outbox(aviso).encode("utf-8"))
        finally:
            os.close(descriptor)
    except (OSError, ValueError) as error:  # ValueError: ruta con carácter nulo
        current_app.logger.error("No se pudo escribir en el outbox (%s): %s", ruta, error)
        return False
    return True
