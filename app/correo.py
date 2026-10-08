"""Normalización de correos (D-013). Función pura, sin Flask ni base de datos.

La usan el registro y, más adelante, el login y `create-professional`, de modo
que un mismo correo escrito de formas distintas siempre dé la misma clave.
"""
import unicodedata

# Cc: caracteres de control; Cf: de formato e invisibles (p. ej. ancho cero).
CATEGORIAS_PROHIBIDAS = frozenset({"Cc", "Cf"})


def normalizar_email(valor):
    """Devuelve el correo normalizado o lanza `ValueError` si es inaceptable.

    Pasos: NFKC (ancho completo -> ASCII), recorte de espacios en los bordes,
    `casefold` (más completo que `lower`: `ß` -> `ss`) y NFKC otra vez, porque
    `casefold` puede dejar texto sin normalizar. Se rechazan los espacios
    internos y los caracteres de categoría Cc o Cf. Una cadena vacía o solo con
    espacios devuelve `""`: de "falta el correo" se encarga la validación.

    No resuelve homoglifos de otros alfabetos (D-013, riesgo aceptado).
    """
    texto = unicodedata.normalize("NFKC", valor).strip()
    texto = unicodedata.normalize("NFKC", texto.casefold())
    for caracter in texto:
        if caracter.isspace():
            raise ValueError("el correo no puede contener espacios")
        if unicodedata.category(caracter) in CATEGORIAS_PROHIBIDAS:
            raise ValueError("el correo contiene caracteres no permitidos")
    return texto
