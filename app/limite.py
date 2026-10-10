"""Límite de intentos de login y registro con bloqueo temporal (D-041, D-045).

Cada intento se anota en la tabla `intentos_acceso` ANTES de comprobar la contraseña
(o de crear la cuenta), dentro de una transacción `BEGIN IMMEDIATE` que también cuenta
y limpia lo vencido. Así dos procesos o hilos simultáneos no pueden colarse entre el
conteo y la anotación: exactamente `límite` intentos pasan y el resto se rechaza. Si el
login acierta, `absolver` devuelve la anotación propia y borra las del par y del correo;
si falla, la anotación ya está hecha (un cierre inesperado del proceso cuenta como fallo).

Tres ámbitos de clave por acción (todos con la misma ventana deslizante):
- `ip`: la dirección del cliente (IPv6 recortada a su /64). Frena el barrido de muchos
  correos desde un mismo lugar y el costo de CPU del scrypt.
- `par`: dirección + correo normalizado (solo login). Es el bloqueo "de verdad" de una
  cuenta: quien falla desde otra dirección no la bloquea para su dueño.
- `correo`: el correo normalizado desde cualquier dirección (solo login), con un umbral
  mayor; frena el ataque repartido en muchas direcciones.

Nunca se confía en `X-Forwarded-For` por sí solo: la dirección es `request.remote_addr`,
y detrás de un proxy propio solo cambia si se configura `TRUSTED_PROXY_COUNT`
(ver `app/__init__.py`).
"""
import ipaddress
import math
import sqlite3

from flask import request

from .db import MENSAJE_BASE_OCUPADA, esta_ocupada, get_db

VENTANA_S = 15 * 60
LIMITES = {
    "login": {"ip": 20, "par": 5, "correo": 30},
    "registro": {"ip": 10},
}
# `par` y `correo` solo existen para el login y necesitan el correo.
AMBITOS_CON_CORREO = ("par", "correo")

# Cuántas filas vencidas se borran como máximo en cada intento (D-050): el borrado cabe en el
# bloqueo de escritura aunque la tabla sea enorme. Las vencidas que quedan no cuentan (la consulta
# filtra por la ventana) y se van borrando en los intentos siguientes.
LOTE_LIMPIEZA = 500


class Bloqueado(Exception):
    """El límite se alcanzó; `espera_s` son los segundos hasta que se libera."""

    def __init__(self, espera_s):
        super().__init__(espera_s)
        self.espera_s = espera_s


class BaseOcupada(Exception):
    """Otro proceso retiene el bloqueo de escritura de SQLite más tiempo que el de espera."""


def mensaje_bloqueo(espera_s):
    """Mismo texto para cualquier correo (D-010): no dice si la cuenta existe ni qué ámbito bloqueó."""
    minutos = max(1, math.ceil(espera_s / 60))
    unidad = "minuto" if minutos == 1 else "minutos"
    return f"Demasiados intentos. Por seguridad, espera {minutos} {unidad} antes de volver a intentarlo."


def clave_ip(direccion):
    """Clave estable de una dirección: IPv6 recortada a /64, IPv4-mapeada como IPv4.

    Un cliente con IPv6 recibe un /64 entero: sin este recorte cambiaría de dirección a
    cada intento y el límite por dirección sería trivial de evadir. Algo que no es una
    dirección (o `None`) comparte la clave `desconocida`, nunca queda sin límite.
    """
    try:
        ip = ipaddress.ip_address(direccion)
    except (ValueError, TypeError):
        return "desconocida"
    if ip.version == 6:
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


def _ahora_s():
    # Importación tardía: `tiempo` importa `auth` y `auth` importa este módulo.
    from . import tiempo

    return int(tiempo.ahora_chile().timestamp())


def _claves(accion, email):
    """Lista de (ámbito, clave, límite) que aplican a este intento."""
    ip = clave_ip(request.remote_addr)
    limites = LIMITES[accion]
    claves = [("ip", ip, limites["ip"])]
    if email:
        if "par" in limites:
            claves.append(("par", f"{ip}|{email}", limites["par"]))
        if "correo" in limites:
            claves.append(("correo", email, limites["correo"]))
    return claves


def _empezar(db):
    try:
        db.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as error:
        if esta_ocupada(error):
            raise BaseOcupada() from error
        raise


def reservar(accion, email=None):
    """Anota un intento de `accion`; lanza `Bloqueado` si algún ámbito ya llegó a su límite.

    `email` es el correo YA normalizado (o `None`/vacío si no es aceptable: entonces solo
    cuenta el ámbito `ip`). Devuelve los ids anotados, para `absolver`. Un intento
    rechazado no se anota: el bloqueo no se prolonga por insistir y la tabla no crece.
    """
    db = get_db()
    ahora = _ahora_s()
    claves = _claves(accion, email)
    _empezar(db)
    try:
        # Reloj atrasado (NTP, máquina virtual restaurada): las marcas "futuras" se reubican en
        # `ahora`, así la espera nunca pasa de la ventana (T-14a R-05). Usa el índice por `instante`.
        db.execute("UPDATE intentos_acceso SET instante = ? WHERE instante > ?", (ahora, ahora))
        # Limpieza acotada y con índice por `instante` (T-14a R-06): sin él recorría toda la tabla.
        db.execute(
            "DELETE FROM intentos_acceso WHERE id IN"
            " (SELECT id FROM intentos_acceso WHERE instante <= ? LIMIT ?)",
            (ahora - VENTANA_S, LOTE_LIMPIEZA),
        )
        espera = 0
        for ambito, clave, limite in claves:
            instantes = [
                f[0]
                for f in db.execute(
                    "SELECT instante FROM intentos_acceso"
                    " WHERE accion = ? AND ambito = ? AND clave = ? AND instante > ?"
                    " ORDER BY instante",
                    (accion, ambito, clave, ahora - VENTANA_S),
                )
            ]
            if len(instantes) >= limite:
                # Se libera cuando el intento que deja el conteo en `limite` sale de la ventana.
                libera = instantes[len(instantes) - limite] + VENTANA_S
                espera = max(espera, libera - ahora)
        ids = []
        if not espera:
            for ambito, clave, _ in claves:
                ids.append(
                    db.execute(
                        "INSERT INTO intentos_acceso (accion, ambito, clave, instante)"
                        " VALUES (?, ?, ?, ?)",
                        (accion, ambito, clave, ahora),
                    ).lastrowid
                )
        db.commit()
    except sqlite3.OperationalError as error:
        db.rollback()
        if esta_ocupada(error):
            raise BaseOcupada() from error
        raise
    except BaseException:
        db.rollback()
        raise
    if espera:
        raise Bloqueado(espera)
    return ids


def absolver(accion, ids, email):
    """Tras un login correcto: devuelve la anotación propia y borra las del par y del correo.

    No borra las anotaciones `ip` de intentos anteriores: quien tiene una cuenta propia no
    puede "limpiar" con un acierto los fallos que acumuló contra otras cuentas. Es
    de mejor esfuerzo: si la base está ocupada, el login igual vale (las anotaciones
    sobrantes caducan solas con la ventana).
    """
    db = get_db()
    claves = {ambito: clave for ambito, clave, _ in _claves(accion, email)}
    try:
        _empezar(db)
    except BaseOcupada:
        return
    try:
        db.executemany("DELETE FROM intentos_acceso WHERE id = ?", [(i,) for i in ids])
        for ambito in AMBITOS_CON_CORREO:
            if ambito in claves:
                db.execute(
                    "DELETE FROM intentos_acceso WHERE accion = ? AND ambito = ? AND clave = ?",
                    (accion, ambito, claves[ambito]),
                )
        db.commit()
    except sqlite3.OperationalError:
        db.rollback()
    except BaseException:
        db.rollback()
        raise
