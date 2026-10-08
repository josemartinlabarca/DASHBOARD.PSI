"""Normalización de correos (D-013). Función pura, sin Flask ni base de datos.

La usan el registro y, más adelante, el login y `create-professional`, de modo
que un mismo correo escrito de formas distintas siempre dé la misma clave.
"""
import unicodedata

# D-015 (opción 2): se rechaza toda la categoría general C* (Cc control, Cf
# formato/invisibles, Cs sustitutos, Co uso privado, Cn sin asignar) y las
# marcas combinantes Mn, Mc y Me. Se decide por la categoría que informa el
# `unicodedata` de la versión de Python instalada, no por listas de puntos de
# código: un punto sin asignar (Cn) en esta versión se rechaza aunque otra
# versión de Unicode ya lo haya asignado (falla del lado seguro), y un
# carácter nuevo que la versión instalada sí conoce se juzga por su categoría.
GRUPOS_PROHIBIDOS = frozenset({"C"})
MARCAS_PROHIBIDAS = frozenset({"Mn", "Mc", "Me"})


def normalizar_email(valor):
    """Devuelve el correo normalizado o lanza `ValueError` si es inaceptable.

    Pasos: NFKC (ancho completo -> ASCII), recorte de espacios en los bordes,
    `casefold` (más completo que `lower`: `ß` -> `ss`) y NFKC otra vez, porque
    `casefold` puede dejar texto sin normalizar. Se rechazan los espacios
    internos, todas las categorías `C*` y las marcas `Mn`, `Mc` y `Me`
    (D-015), ya sobre el texto normalizado: un `ñ` precompuesto o descompuesto
    (`n` + U+0303) da el mismo resultado, y un combinante suelto se rechaza.
    Una cadena vacía o solo con espacios devuelve `""`: de "falta el correo" se
    encarga la validación. Si `valor` no es `str` lanza `ValueError` (no
    `TypeError`), de modo que quien la llame solo atrape un tipo de error.

    No resuelve homoglifos de otros alfabetos (D-013, riesgo aceptado).
    """
    if not isinstance(valor, str):
        raise ValueError("el correo debe ser texto")
    texto = unicodedata.normalize("NFKC", valor).strip()
    texto = unicodedata.normalize("NFKC", texto.casefold())
    for caracter in texto:
        if caracter.isspace():
            raise ValueError("el correo no puede contener espacios")
        categoria = unicodedata.category(caracter)
        if categoria[0] in GRUPOS_PROHIBIDOS or categoria in MARCAS_PROHIBIDAS:
            raise ValueError("el correo contiene caracteres no permitidos")
    return texto
