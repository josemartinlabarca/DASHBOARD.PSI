"""Notificaciones: confirmación, cancelación (T-09; US-11, US-13) y recordatorio (T-10; US-12; SPEC §5).

Dos pasos, pensados para llamarse desde `reservar_hora`, `cancelar_reserva` y `enviar_recordatorios`:

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
import sqlite3
import stat
import unicodedata
from datetime import datetime, timedelta
from typing import NamedTuple

import click
from flask import current_app
from flask.cli import with_appcontext

from . import tiempo
from .auth import zona_chile
from .db import MENSAJE_COMANDO_BASE_OCUPADA, abrir_base_existente, esta_ocupada

NOMBRE_OUTBOX = "outbox.log"
ANTICIPACION_CANCELAR_S = 24 * 3600  # igual que paciente.ANTICIPACION_CANCELAR_S (US-9)

CONFIRMACION = "confirmacion"
CANCELACION = "cancelacion"
RECORDATORIO = "recordatorio"
TIPOS = (CONFIRMACION, RECORDATORIO, CANCELACION)  # los mismos del CHECK de `notificaciones.tipo`

MSG_CONFIRMACION_PACIENTE = (
    "Confirmamos tu hora con {profesional} el {cuando} (hora de Chile), de {duracion} minutos. "
    "Puedes cancelarla hasta el {limite} (hora de Chile){repetida}."
)
# T-09 R-06: en abril el reloj marca dos veces la hora de la noche del cambio; si el límite cae
# ahí, la hora de pared sola es ambigua y se dice cuál de las dos es.
ACLARACION_HORA_REPETIDA = {
    0: ", la primera vez que el reloj marca esa hora",
    1: ", la segunda vez que el reloj marca esa hora",
}
MSG_CONFIRMACION_PROFESIONAL = (
    "{paciente} reservó una hora contigo el {cuando} (hora de Chile), de {duracion} minutos."
)
MSG_CANCELACION_PACIENTE = (
    "Cancelaste tu hora con {profesional} del {cuando} (hora de Chile). La hora quedó libre."
)
MSG_CANCELACION_PROFESIONAL = (
    "{paciente} canceló su hora contigo del {cuando} (hora de Chile). La hora quedó libre."
)
# US-12: el recordatorio es solo para el paciente (SPEC no pide avisar al profesional).
MSG_RECORDATORIO_PACIENTE = (
    "Recordatorio: tienes una hora con {profesional} el {cuando} (hora de Chile), "
    "de {duracion} minutos."
)

# T-10: se recuerda una reserva que empieza dentro de las próximas 24 h (inclusive) y aún no empezó.
ANTICIPACION_RECORDATORIO_S = 24 * 3600
MARGEN_SQL_DIAS = 1  # el SQL trae de más (hora de pared); Python decide con el instante exacto


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
    """`(texto, aclaración)` de hasta cuándo se puede cancelar: inicio - 24 h, en hora de Chile.

    Se resta sobre el instante, no sobre la hora de pared: en la noche de cambio de horario
    las dos cuentas difieren en una hora. Si ese instante cae en la hora que el reloj marca dos
    veces (noche de abril), `aclaración` dice cuál de las dos es (T-09 R-06); si no, es vacía.
    `None` si el inicio no se puede interpretar.
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
        repetida = limite.replace(fold=0).utcoffset() != limite.replace(fold=1).utcoffset()
    except (OverflowError, OSError, ValueError):
        return None
    aclaracion = ACLARACION_HORA_REPETIDA[limite.fold] if repetida else ""
    return _cuando(limite.strftime(tiempo.FORMATO_GUARDADO)), aclaracion


def _mensajes(tipo, hora):
    """`(mensaje para el paciente, mensaje para el profesional o None)` del aviso `tipo`.

    Un tipo sin mensaje propio es un error (`ValueError`): antes cualquier tipo distinto de
    `confirmacion` caía en el texto de cancelación (R-01 de la revisión de T-09).
    """
    datos = {
        "profesional": hora["profesional"],
        "paciente": hora["paciente"],
        "cuando": _cuando(hora["inicio"]),
        "duracion": hora["duracion_min"],
    }
    if tipo == CONFIRMACION:
        datos["limite"], datos["repetida"] = (
            _limite_para_cancelar(hora["inicio"]) or ("24 horas antes de la sesión", "")
        )
        return (
            MSG_CONFIRMACION_PACIENTE.format(**datos),
            MSG_CONFIRMACION_PROFESIONAL.format(**datos),
        )
    if tipo == RECORDATORIO:
        return MSG_RECORDATORIO_PACIENTE.format(**datos), None
    if tipo == CANCELACION:
        return MSG_CANCELACION_PACIENTE.format(**datos), MSG_CANCELACION_PROFESIONAL.format(**datos)
    raise ValueError(f"Tipo de notificación sin mensaje: {tipo!r}")


TOPE_PANEL = 20  # D-035: el panel muestra las últimas 20 notificaciones


def listar_de_usuario(db, usuario_id):
    """`(lista, sin_leer, hay_mas)`: las últimas `TOPE_PANEL` notificaciones, las no leídas en total
    y si había más que el tope (T-11, D-035; T-12).

    `hay_mas` sale de pedir `TOPE_PANEL + 1` filas y recortar: con exactamente `TOPE_PANEL`
    no hay más y el aviso «Se muestran tus N más recientes» no debe aparecer (R-03 de T-11b).

    Solo las de `usuario_id`. Orden por `id` descendente (R-09 de T-09): `creada_en` es
    texto con desfase y no ordena bien en la noche de cambio de horario. Se lee `mensaje`,
    que se basta solo; no se hace JOIN con `horas` porque `hora_id` puede ser NULL (D-016)
    o apuntar luego a la hora de otra persona (R-07 de T-10). `hora_id` se devuelve solo
    para que quien muestra decida si puede enlazar. Cada fila trae `creada` ya en hora de Chile.
    El contador sale de un `COUNT(*)` aparte: cuenta todas las no leídas, no solo las visibles.
    """
    filas = db.execute(
        "SELECT id, tipo, mensaje, hora_id, leida, creada_en FROM notificaciones"
        " WHERE usuario_id = ? ORDER BY id DESC LIMIT ?",
        (usuario_id, TOPE_PANEL + 1),
    ).fetchall()
    hay_mas = len(filas) > TOPE_PANEL  # la fila TOPE_PANEL+1 solo sirve para saber esto
    filas = filas[:TOPE_PANEL]
    lista = [
        {
            "id": f["id"],
            "tipo": f["tipo"],
            "mensaje": f["mensaje"],
            "hora_id": f["hora_id"],
            "leida": bool(f["leida"]),
            "creada": tiempo.mostrar_instante(f["creada_en"]),
        }
        for f in filas
    ]
    sin_leer = db.execute(
        "SELECT COUNT(*) FROM notificaciones WHERE usuario_id = ? AND leida = 0", (usuario_id,)
    ).fetchone()[0]
    return lista, sin_leer, hay_mas


def mensaje_marcadas(cantidad):
    """Texto del flash tras «Marcar todas como leídas»; lo comparten el panel del paciente y el del profesional."""
    if cantidad == 1:
        return "Marcaste 1 notificación como leída."
    if cantidad:
        return f"Marcaste {cantidad} notificaciones como leídas."
    return "No tenías notificaciones sin leer."


def marcar_leidas(db, usuario_id):
    """Marca como leídas todas las notificaciones sin leer de `usuario_id` y devuelve cuántas (D-035).

    Genérica: la usan el panel del paciente (T-11b) y el del profesional (T-12). Una sola
    sentencia, solo filas de ese usuario con `leida = 0`; repetirla no cambia nada (devuelve 0).
    """
    cantidad = db.execute(
        "UPDATE notificaciones SET leida = 1 WHERE usuario_id = ? AND leida = 0", (usuario_id,)
    ).rowcount
    db.commit()
    return cantidad


def registrar(db, tipo, hora_id, hora, paciente_id, creada_en):
    """Inserta la notificación del paciente y, si el tipo la tiene, la del profesional; devuelve los `Aviso`.

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
        if mensaje is None:  # este tipo no avisa a esa parte (recordatorio: solo el paciente)
            continue
        db.execute(
            "INSERT INTO notificaciones (usuario_id, tipo, mensaje, hora_id, creada_en)"
            " VALUES (?, ?, ?, ?, ?)",
            (usuario_id, tipo, mensaje, hora_id, creada_en),
        )
        avisos.append(Aviso(creada_en, correo, tipo, mensaje))
    return avisos


# ---------------------------------------------------------- recordatorios ----

SELECT_RECORDATORIOS = (
    "SELECT h.id, h.inicio, h.duracion_min, h.paciente_id, h.profesional_id,"
    " u.nombre AS profesional, u.email AS profesional_email,"
    " p.nombre AS paciente, p.email AS paciente_email"
    " FROM horas h JOIN usuarios u ON u.id = h.profesional_id"
    " JOIN usuarios p ON p.id = h.paciente_id"
    " WHERE h.estado = 'reservada' AND h.recordatorio_enviado = 0"
    " AND h.inicio > ? AND h.inicio < ?"
)


def enviar_recordatorios(db, reloj=None):
    """Envía el recordatorio de cada reserva pendiente que ya está a 24 h o menos. Devuelve cuántos.

    Recordatorio = estado `reservada`, `recordatorio_enviado = 0` y `0 < inicio - ahora <= 24 h`
    en instantes absolutos (a las 24 h exactas todavía se puede cancelar y SÍ se recuerda; a la
    hora de inicio exacta ya empezó y no). Una reserva hecha entre 24 h y 24 h + el período del
    cron queda pendiente y se envía en la siguiente ejecución.

    Igual que reservar y cancelar: `BEGIN IMMEDIATE` primero y se lee **todo** dentro (reloj y
    filas), así que una cancelación concurrente o una segunda ejecución ven el estado ya
    decidido. Por hora, el `UPDATE ... recordatorio_enviado = 1` es condicional y se revisa
    `rowcount`, y el aviso se inserta en la MISMA transacción; el log se escribe tras el `commit`.
    El resultado es verdad en `horas.recordatorio_enviado` y `notificaciones`, no en el log.
    """
    db.execute("BEGIN IMMEDIATE")
    try:
        ahora = (reloj or tiempo.ahora_chile)()
        ahora_s = ahora.timestamp()
        desde = ahora.replace(tzinfo=None) - timedelta(days=MARGEN_SQL_DIAS)
        hasta = ahora.replace(tzinfo=None) + timedelta(days=MARGEN_SQL_DIAS + 1)
        filas = db.execute(
            SELECT_RECORDATORIOS,
            (desde.strftime(tiempo.FORMATO_GUARDADO), hasta.strftime(tiempo.FORMATO_GUARDADO)),
        ).fetchall()
        pendientes = []
        for fila in filas:
            intervalo = tiempo.intervalo_guardado(fila)
            if intervalo is None:
                continue
            faltan_s = intervalo[0] - ahora_s
            if 0 < faltan_s <= ANTICIPACION_RECORDATORIO_S:
                pendientes.append((intervalo[0], fila["id"], fila))
        pendientes.sort(key=lambda t: (t[0], t[1]))
        avisos = []
        for _, hora_id, fila in pendientes:
            marcadas = db.execute(
                "UPDATE horas SET recordatorio_enviado = 1"
                " WHERE id = ? AND estado = 'reservada' AND recordatorio_enviado = 0"
                " AND paciente_id = ?",
                (hora_id, fila["paciente_id"]),
            ).rowcount
            if marcadas != 1:
                continue
            avisos += registrar(
                db, RECORDATORIO, hora_id, fila, fila["paciente_id"], ahora.isoformat(timespec="seconds")
            )
        db.commit()
    except BaseException:
        db.rollback()
        raise
    if avisos:  # sin recordatorios no se crea el log vacío
        escribir_outbox(avisos)  # después del commit
    return len(avisos)  # un aviso (el del paciente) por recordatorio


@click.command("send-reminders")
@with_appcontext
def send_reminders_command():
    """Envía el recordatorio a los pacientes cuya hora empieza en 24 horas o menos (sin repetir).

    Pensado para cron: ante cualquier problema con la base responde con un mensaje en español,
    sin traza, y termina con código 1 (T-10 R-01/R-02). No crea la base si no existe. Con la base
    bloqueada más de 5 s no cambia nada y la siguiente ejecución del cron reintenta.
    """
    db = abrir_base_existente()
    try:
        cantidad = enviar_recordatorios(db)
    except sqlite3.Error as error:
        if esta_ocupada(error):
            raise click.ClickException(MENSAJE_COMANDO_BASE_OCUPADA) from error
        raise click.ClickException(f"Error de la base de datos: {error}") from error
    click.echo(f"Recordatorios enviados: {cantidad}.")


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


# El log guarda nombres y correos: solo el dueño lo lee (T-09 R-02). El modo se aplica al CREAR el
# archivo (menos lo que quite el umask); uno que ya existe con permisos más amplios no se cambia
# (puede ser a propósito, p. ej. un grupo que lee el log) y se avisa una vez por proceso.
MODO_OUTBOX = 0o600
MODO_CARPETA_OUTBOX = 0o700  # solo si la aplicación crea la carpeta
_avisos_de_permisos = set()


def _avisar_si_es_legible_por_otros(descriptor, ruta):
    """Una sola vez por proceso y archivo: avisa si `outbox.log` es legible por grupo u otros."""
    if os.name != "posix" or ruta in _avisos_de_permisos:
        return
    try:
        modo = stat.S_IMODE(os.fstat(descriptor).st_mode)
    except OSError:  # el aviso es un extra: nunca impide escribir
        return
    if modo & 0o077:
        _avisos_de_permisos.add(ruta)
        current_app.logger.warning(
            "El outbox %s tiene permisos %s: contiene nombres y correos y otros usuarios del "
            "sistema pueden leerlo. Para dejarlo solo para su dueño: chmod 600 %s",
            ruta, oct(modo), ruta,
        )


def escribir_outbox(avisos):
    """Añade una línea por aviso a `outbox.log` (UTF-8, modo append, un `write` por línea).

    Con `O_APPEND` y un único `write` por línea, dos procesos que escriben a la vez no
    entrelazan sus líneas. Crea la carpeta si falta (modo 0700) y el archivo con modo 0600.
    El archivo se abre en CADA llamada: rotarlo (renombrarlo o moverlo) no necesita reiniciar
    nada, la siguiente escritura crea uno nuevo. Nunca lanza `OSError`: si el disco falla
    lo registra con `app.logger.error` (sin el contenido de los mensajes) y sigue, porque la
    reserva ya está confirmada. Devuelve True si se escribió todo.
    """
    ruta = None
    try:
        ruta = ruta_outbox()
        carpeta = os.path.dirname(ruta)
        if carpeta:
            os.makedirs(carpeta, mode=MODO_CARPETA_OUTBOX, exist_ok=True)
        descriptor = os.open(ruta, os.O_WRONLY | os.O_APPEND | os.O_CREAT, MODO_OUTBOX)
        try:
            _avisar_si_es_legible_por_otros(descriptor, ruta)
            for aviso in avisos:
                _escribir_completo(descriptor, linea_outbox(aviso).encode("utf-8"))
        finally:
            os.close(descriptor)
    except (OSError, ValueError) as error:  # ValueError: ruta con carácter nulo
        current_app.logger.error("No se pudo escribir en el outbox (%s): %s", ruta, error)
        return False
    return True
