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

# D-020 (opción B, T-08e): fuera de ASCII solo se aceptan letras (L*) y números
# (N*), y además se rechazan de forma explícita los rellenos que se ven como un
# espacio, un guion o un símbolo: relleno hangul (U+3164, U+115F, U+1160, letras
# `Lo` que la categoría deja pasar), braille en blanco (U+2800), U+FFFD, U+FFFC,
# los símbolos de control gráficos U+2400-U+2422, los guiones y rayas
# U+2010-U+2015 y el punto medio U+00B7. Algunos ya los frena la regla de
# categorías (no son L ni N): la lista los nombra para que la intención quede
# escrita y siga valiendo si cambia la versión de Unicode. Lo ASCII no cambia.
LETRAS_Y_NUMEROS = frozenset({"L", "N"})
RELLENOS_RECHAZADOS = frozenset(
    {0x3164, 0x115F, 0x1160, 0x2800, 0xFFFD, 0xFFFC, 0x00B7}
    | set(range(0x2400, 0x2423))
    | set(range(0x2010, 0x2016))
)


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

    D-020: un carácter no ASCII debe ser letra o número (`L*`, `N*`) y no estar
    en `RELLENOS_RECHAZADOS`; `señor@`, tildes, `ü`, kanji y cirílico siguen
    valiendo. Lo ASCII se juzga como antes (solo espacios, `C*` y marcas).

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
        if ord(caracter) > 127 and (
            categoria[0] not in LETRAS_Y_NUMEROS or ord(caracter) in RELLENOS_RECHAZADOS
        ):
            raise ValueError("el correo contiene caracteres no permitidos")
    return texto
