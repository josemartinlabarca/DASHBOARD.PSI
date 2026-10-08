import multiprocessing
import os
import unicodedata
from concurrent.futures import ProcessPoolExecutor
from functools import partial

import pytest

from app.correo import normalizar_email


@pytest.mark.parametrize(
    "entrada, esperado",
    [
        ("ana@example.cl", "ana@example.cl"),
        ("ANA@Example.CL", "ana@example.cl"),
        ("  ana@example.cl  ", "ana@example.cl"),
        ("\t\nana@example.cl \r\n", "ana@example.cl"),
        ("\u3000ana@example.cl\u3000", "ana@example.cl"),  # espacio ideográfico
        ("\uff41na@example.cl", "ana@example.cl"),  # «ａ» de ancho completo
        ("\uff21na@\uff25xample.cl", "ana@example.cl"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_normaliza_variantes_equivalentes(entrada, esperado):
    assert normalizar_email(entrada) == esperado


def test_sz_y_ss_colisionan_por_casefold():
    """Decisión D-013: `casefold` lleva `ß` a `ss`; ambos correos son el mismo."""
    assert normalizar_email("stra\u00dfe@example.cl") == "strasse@example.cl"
    assert normalizar_email("stra\u00dfe@example.cl") == normalizar_email("STRASSE@example.cl")


def test_es_idempotente():
    for valor in ["\uff21na@Stra\u00dfe.cl", "ANA@EXAMPLE.CL", "\u2460@x.cl"]:
        una_vez = normalizar_email(valor)
        assert normalizar_email(una_vez) == una_vez


# Casos donde las DOS pasadas de NFKC importan (revisión de T-03b): quitar la
# primera cambia el resultado en cientos de puntos de código; quitar la segunda,
# en decenas. Son valores reales calculados con la versión de Python instalada.
@pytest.mark.parametrize(
    "entrada, esperado",
    [
        ("\u03d2@x.cl", "\u03c5@x.cl"),  # ϒ: NFKC -> Υ, casefold -> υ (sin la 1ª NFKC queda Υ)
        ("\u03d3@x.cl", "\u03cd@x.cl"),  # ϓ -> Ύ -> ύ
        ("\u1e9b@x.cl", "\u1e61@x.cl"),  # ẛ -> ṡ
        ("\u01f0@x.cl", "\u01f0@x.cl"),  # ǰ: casefold lo descompone (j + U+030C); la 2ª NFKC lo recompone
        ("\u0390@x.cl", "\u0390@x.cl"),  # ΐ: casefold lo descompone en tres; la 2ª NFKC lo recompone
        ("\u1e96@x.cl", "\u1e96@x.cl"),  # ẖ
    ],
)
def test_las_dos_pasadas_de_nfkc_son_necesarias(entrada, esperado):
    assert normalizar_email(entrada) == esperado
    assert normalizar_email(esperado) == esperado


def puntos_de_codigo(desde=0, hasta=0x110000):
    return (cp for cp in range(desde, hasta) if not 0xD800 <= cp <= 0xDFFF)


def revisar_rango_de_puntos_de_codigo(desde, hasta):
    """Las comprobaciones de siempre sobre los puntos de código [desde, hasta)."""
    nfkc = partial(unicodedata.normalize, "NFKC")
    category = unicodedata.category
    for cp in puntos_de_codigo(desde, hasta):
        c = chr(cp)
        try:
            resultado = normalizar_email(f"a{c}b@x.cl")
        except ValueError:
            continue
        assert nfkc(resultado) == resultado, hex(cp)
        assert normalizar_email(resultado) == resultado, hex(cp)
        for ch in resultado:
            cat = category(ch)
            assert cat[0] != "C" and cat not in ("Mn", "Mc", "Me"), (hex(cp), cat)
            assert not ch.isspace(), hex(cp)


def test_exhaustivo_idempotente_y_estable_en_todos_los_puntos_de_codigo():
    """Recorre 0..0x10FFFF (sin sustitutos): lo aceptado es estable y limpio.

    Para cada punto de código `c`, con `a{c}b@x.cl`: si se acepta, el resultado ya está en NFKC, normalizarlo otra vez no lo
    cambia y ningún carácter pertenece a una categoría prohibida (se juzga por
    categoría, no por una lista: depende de la versión de Unicode instalada).

    T-08b: el recorrido se reparte entre los núcleos del equipo (procesos `fork`) para
    tardar la mitad en dos núcleos; cada proceso hace exactamente las mismas comprobaciones
    y cualquier fallo se propaga con el mismo mensaje. Sin `fork` (Windows) o con un solo
    núcleo se recorre todo en este proceso.
    """
    total = 0x110000
    nucleos = os.cpu_count() or 1
    if nucleos < 2 or "fork" not in multiprocessing.get_all_start_methods():
        revisar_rango_de_puntos_de_codigo(0, total)
        return
    nucleos = min(nucleos, 8)
    cortes = [total * k // nucleos for k in range(nucleos + 1)]
    with ProcessPoolExecutor(nucleos, mp_context=multiprocessing.get_context("fork")) as pool:
        futuros = [pool.submit(revisar_rango_de_puntos_de_codigo, a, b) for a, b in zip(cortes, cortes[1:])]
        for futuro in futuros:
            futuro.result()  # relanza la AssertionError del proceso que falló


@pytest.mark.parametrize(
    "entrada",
    [
        "ana\u200b@example.cl",  # espacio de ancho cero (Cf)
        "\u200bana@example.cl",  # ancho cero en el borde: strip() no lo quita
        "ana@example.cl\u200d",  # unión de ancho cero
        "ana\u00ad@example.cl",  # guion blando (Cf)
        "ana\u202e@example.cl",  # inversión de texto (Cf)
        "ana\ufeff@example.cl",  # BOM (Cf)
        "ana\x00@example.cl",  # nulo (Cc)
        "ana\x07@example.cl",  # campana (Cc)
        "ana@exam\x1fple.cl",  # control (Cc)
        "\x00ana@example.cl",  # control en el borde
        "ana @example.cl",  # espacio interno
        "ana@exam ple.cl",
        "ana\t@example.cl",  # tabulación interna
        "ana\n@example.cl",
        "ana\u00a0@example.cl",  # espacio duro: NFKC lo vuelve espacio
        "ana\u3000@example.cl",  # espacio de ancho completo interno
    ],
)
def test_rechaza_control_invisibles_y_espacios_internos(entrada):
    with pytest.raises(ValueError):
        normalizar_email(entrada)


def test_homoglifo_cirilico_no_se_resuelve():
    """Riesgo aceptado (D-013): NFKC no une la «е» cirílica con la «e» latina."""
    assert normalizar_email("ana@\u0435xample.cl") != normalizar_email("ana@example.cl")


# --- Política D-015 (opción 2): rechazar C* y Mn/Mc/Me tras NFKC ---------------

def test_ene_precompuesta_y_descompuesta_dan_lo_mismo():
    precompuesta = "se\u00f1or@example.cl"
    descompuesta = "sen\u0303or@example.cl"  # n + U+0303
    assert normalizar_email(precompuesta) == precompuesta
    assert normalizar_email(descompuesta) == precompuesta
    assert normalizar_email("SE\u00d1OR@Example.CL") == precompuesta


@pytest.mark.parametrize(
    "entrada",
    [
        "ana\u0301\u0302@example.cl",  # 'á' compuesta + U+0302 que sobra
        "ana@example.\u0301cl",  # combinante tras un punto (nada con qué componer)
        "\u0301ana@example.cl",  # combinante suelto al inicio
        "ana@\u0301example.cl",  # combinante tras la arroba
        "ana\u034f@example.cl",  # U+034F, Mn
        "ana\ufe0f@example.cl",  # selector de variación 16 (Mn)
        "ana\ufe00@example.cl",  # selector de variación 1 (Mn)
        "ana\U000e0100@example.cl",  # selector de variación suplementario (Mn)
        "ana\u0903@example.cl",  # Mc: signo devanagari visarga
        "ana\u20dd@example.cl",  # Me: círculo combinante
        "ana\u0488@example.cl",  # Me: cirílico millares combinante
    ],
)
def test_rechaza_marcas_combinantes_sueltas(entrada):
    with pytest.raises(ValueError):
        normalizar_email(entrada)


@pytest.mark.parametrize(
    "entrada",
    [
        "ana\ue000@example.cl",  # Co: uso privado
        "ana\uf8ff@example.cl",  # Co
        "ana\U000f0000@example.cl",  # Co: plano 15 de uso privado
        "ana\U0010fffd@example.cl",  # Co: plano 16
        "ana\ud800@example.cl",  # Cs: sustituto suelto
        "ana\udfff@example.cl",  # Cs
        "ana\ufffe@example.cl",  # no carácter (Cn)
        "ana\uffff@example.cl",  # no carácter (Cn)
        "ana\U0010ffff@example.cl",  # no carácter (Cn)
        "ana\U000e0001@example.cl",  # etiqueta de idioma (Cf)
        "ana\U000e0041@example.cl",  # etiqueta 'A' (Cf)
        "ana\u2060@example.cl",  # unión de palabras (Cf)
        "ana\u2066@example.cl",  # aislamiento bidi (Cf)
        "ana\u200e@example.cl",  # marca izquierda-derecha (Cf)
        "ana\u200f@example.cl",  # marca derecha-izquierda (Cf)
        "ana\u061c@example.cl",  # marca de letra árabe (Cf)
        "ana\u202a@example.cl",
        "ana\u2069@example.cl",
    ],
)
def test_rechaza_uso_privado_sustitutos_no_asignados_y_marcas_bidi(entrada):
    with pytest.raises(ValueError):
        normalizar_email(entrada)


def test_un_punto_sin_asignar_en_esta_version_se_rechaza_por_su_categoria():
    """Los Cn dependen de la versión de Python (D-015): se juzgan por categoría.

    Se busca un punto que ESTA versión de `unicodedata` declare sin asignar y se
    comprueba que se rechaza; no se fija ningún punto de código concreto, porque
    una versión más nueva de Unicode puede haberlo asignado.
    """
    sin_asignar = [cp for cp in range(0x0378, 0x0400) if unicodedata.category(chr(cp)) == "Cn"]
    assert sin_asignar, "no hay ningún Cn en el rango de prueba de esta versión de Unicode"
    for cp in sin_asignar:
        with pytest.raises(ValueError):
            normalizar_email(f"ana{chr(cp)}@example.cl")


@pytest.mark.parametrize(
    "entrada",
    [
        "ana\u2028@example.cl",  # separador de línea (Zl)
        "ana\u2029@example.cl",  # separador de párrafo (Zp)
        "ana\u1680@example.cl",  # espacio de ogham (Zs, NFKC no lo cambia)
        "ana@exam\u2028ple.cl",
        "ana@exam\u2029ple.cl",
        "ana@exam\u1680ple.cl",
        "ana\u2002@example.cl",  # espacio 'en' (NFKC -> espacio)
        "ana\u205f@example.cl",
    ],
)
def test_rechaza_separadores_unicode_internos(entrada):
    with pytest.raises(ValueError):
        normalizar_email(entrada)


@pytest.mark.parametrize("espacio", ["\u2028", "\u2029", "\u1680", "\u3000", "\u00a0"])
def test_los_separadores_en_los_bordes_se_recortan(espacio):
    assert normalizar_email(f"{espacio}ana@example.cl{espacio}") == "ana@example.cl"


@pytest.mark.parametrize(
    "entrada, esperado",
    [
        ("\u03c2@x.cl", "\u03c3@x.cl"),  # ς (sigma final) -> σ
        ("\u017f@x.cl", "s@x.cl"),  # ſ (s larga) -> s (por NFKC)
        ("\u212a@x.cl", "k@x.cl"),  # K (signo kelvin) -> k
        ("\u0131@x.cl", "\u0131@x.cl"),  # ı (i sin punto) NO se une con 'i'
    ],
)
def test_plegados_especiales_de_casefold_y_nfkc(entrada, esperado):
    assert normalizar_email(entrada) == esperado


def test_i_con_punto_se_rechaza_porque_casefold_agrega_un_combinante():
    """`İ` (U+0130) en minúscula completa es `i` + U+0307 (Mn): ya no se acepta."""
    assert unicodedata.normalize("NFKC", "\u0130".casefold()) == "i\u0307"
    with pytest.raises(ValueError):
        normalizar_email("\u0130@x.cl")
    with pytest.raises(ValueError):
        normalizar_email("ana@\u0130zmir.cl")
    assert normalizar_email("\u0131@x.cl") != normalizar_email("i@x.cl")


def test_ni_el_relleno_hangul_ni_braille_ni_fffd_los_cubre_la_categoria():
    """Documenta el alcance real de D-015 (opción 2): estos NO son C* ni M*.

    Siguen aceptados y se reportó como duda; si se decide rechazarlos habrá
    que cambiar esta prueba junto con la política.
    """
    for ch in ("\u3164", "\u2800", "\ufffd", "\u115f"):
        assert normalizar_email(f"ana{ch}@example.cl").startswith("ana")


@pytest.mark.parametrize("valor", [None, 5, 1.5, b"ana@example.cl", ["ana@example.cl"], ("a",), object()])
def test_entradas_que_no_son_texto_lanzan_value_error(valor):
    with pytest.raises(ValueError):
        normalizar_email(valor)
