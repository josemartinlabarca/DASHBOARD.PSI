"""Tiempo compartido: el reloj de Chile y la conversión a instantes absolutos (D-027).

`ahora_chile()` es el **único** reloj de la aplicación: quien necesite "ahora"
lo llama como `tiempo.ahora_chile()` (atributo del módulo, no `from ... import`)
para que las pruebas lo reemplacen en un solo lugar.
"""
from datetime import datetime, timezone

from .auth import zona_chile

EPOCA_UTC = datetime(1970, 1, 1, tzinfo=timezone.utc)
FORMATO_GUARDADO = "%Y-%m-%dT%H:%M:%S"


def ahora_chile():
    """Fecha y hora actuales en Chile (con zona). Las pruebas lo reemplazan."""
    return datetime.now(zona_chile())


def a_segundos_utc(local):
    """Segundos desde 1970 (UTC) del instante que es el `datetime` ingenuo `local` en Chile.

    `None` si el instante no se puede representar (años cercanos a 1 o a 9999).
    Una hora que no existe o se repite por el cambio de horario se interpreta
    con `fold=0`; la aplicación no las deja guardar (D-025), esto solo evita
    errores con filas insertadas por otro camino.
    """
    try:
        instante = local.replace(tzinfo=zona_chile(), fold=0).astimezone(timezone.utc)
        return int((instante - EPOCA_UTC).total_seconds())
    except (OverflowError, ValueError):
        return None


def mostrar_inicio(texto):
    """`2026-12-01T10:00:00` -> `01-12-2026 10:00` (la forma la garantiza el CHECK)."""
    return f"{texto[8:10]}-{texto[5:7]}-{texto[0:4]} {texto[11:16]}"


def _minutos_guardados(valor):
    """Minutos de una fila si son un entero positivo, o `None` (texto, decimal, cero...)."""
    if type(valor) is not int or valor <= 0:
        return None
    return valor


def intervalo_guardado(fila):
    """`(inicio_s, fin_s)` en segundos UTC de una fila de `horas`, o `None` si no sirve.

    No sirve una fecha imposible que el CHECK deja pasar (2026-13-45T99:99:99),
    una duración que no sea entero positivo o un año no representable. Usado por
    el solape del profesional (regla 3) y por la reserva (reglas 1 y 5).
    """
    try:
        local = datetime.strptime(fila["inicio"], FORMATO_GUARDADO)
    except (ValueError, TypeError):
        return None
    minutos = _minutos_guardados(fila["duracion_min"])
    inicio_s = a_segundos_utc(local)
    if minutos is None or inicio_s is None:
        return None
    return inicio_s, inicio_s + minutos * 60
