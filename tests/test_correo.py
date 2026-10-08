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


# --- Política D-020 (opción B, T-08e): fuera de ASCII solo letras y números ------

# Lista de la tarea, escrita aquí aparte (no importada de app.correo) para que
# un cambio en la lista de la aplicación no cambie lo que la prueba espera.
RELLENOS = (
    [0x3164, 0x115F, 0x1160, 0x2800, 0xFFFD, 0xFFFC, 0x00B7]
    + list(range(0x2400, 0x2423))
    + list(range(0x2010, 0x2016))
)


@pytest.mark.parametrize("cp", RELLENOS, ids=lambda cp: f"U+{cp:04X}")
def test_los_rellenos_de_d020_se_rechazan_en_cualquier_posicion(cp):
    c = chr(cp)
    for entrada in (f"ana{c}@example.cl", f"{c}ana@example.cl", f"ana@exam{c}ple.cl", f"ana@example.cl{c}"):
        with pytest.raises(ValueError):
            normalizar_email(entrada)


def test_el_relleno_hangul_de_media_anchura_tambien_se_rechaza_por_nfkc():
    """U+FFA0 pasa por NFKC a U+1160 (relleno de la lista) y ahí se rechaza."""
    assert unicodedata.normalize("NFKC", "\uffa0") == "\u1160"
    with pytest.raises(ValueError):
        normalizar_email("ana\uffa0@example.cl")


def test_los_rellenos_hangul_son_letras_y_solo_la_lista_los_frena():
    """U+3164, U+115F y U+1160 son `Lo`: sin la lista pasarían la regla de categorías."""
    for cp in (0x3164, 0x115F, 0x1160):
        assert unicodedata.category(chr(cp)) == "Lo"
    # Otras letras hangul vecinas siguen siendo letras válidas.
    assert normalizar_email("\uac00na@example.cl") == "\uac00na@example.cl"
    assert normalizar_email("ana\u1161@example.cl") == "ana\u1161@example.cl"


def test_solo_el_relleno_hangul_necesita_la_lista_el_resto_ya_cae_por_categoria():
    """Documenta el solape (D-020): U+3164 pasa por NFKC a U+1160, y de los demás rellenos solo
    U+115F y U+1160 son letras. Los otros no son L ni N: los frena la categoría y quitarlos de la
    lista de la aplicación no cambia el resultado (mutación equivalente, ver PROGRESS)."""
    assert unicodedata.normalize("NFKC", "\u3164") == "\u1160"
    for cp in RELLENOS:
        categoria = unicodedata.category(chr(cp))
        if cp in (0x115F, 0x1160):
            assert categoria == "Lo", hex(cp)
        elif cp != 0x3164:
            assert categoria[0] not in "LN", (hex(cp), categoria)


@pytest.mark.parametrize(
    "entrada",
    [
        "se\u00f1or@example.cl",
        "SE\u00d1OR@example.cl",
        "jos\u00e9@example.cl",
        "m\u00fcller@example.cl",
        "\u00fc\u00f1\u00e1\u00e9\u00ed\u00f3\u00fa@example.cl",
        "\u5c71\u7530@example.jp",  # kanji
        "\u0438\u0432\u0430\u043d@example.ru",  # cirílico
        "\u03b1\u03b2\u03b3@example.gr",  # griego
        "\u0627\u062d\u0645\u062f@example.sa",  # árabe
        "ana\u0662@example.cl",  # dígito árabe-índico (Nd)
        "ana\u2160@example.cl",  # numeral romano (Nl): NFKC lo lleva a «i»
        "ana@\u00e9xample.cl",
    ],
)
def test_letras_y_numeros_no_ascii_siguen_validos(entrada):
    assert normalizar_email(entrada)  # no lanza


@pytest.mark.parametrize(
    "entrada",
    [
        "ana\u20ac@example.cl",  # € (Sc)
        "ana\u00a9@example.cl",  # © (So)
        "ana\u2192@example.cl",  # → (Sm)
        "ana\u00bf@example.cl",  # ¿ (Po)
        "ana\u00ab@example.cl",  # « (Pi)
        "ana\u2018@example.cl",  # ' tipográfico (Pi)
        "ana\u00a2@example.cl",  # ¢ (Sc)
        "ana\U0001f600@example.cl",  # emoji (So)
        "ana\u2022@example.cl",  # viñeta (Po)
        "ana\u2212@example.cl",  # signo menos (Sm)
        "ana\u00b4@example.cl",  # acento agudo (Sk): NFKC lo lleva a espacio + U+0301
    ],
)
def test_simbolos_y_puntuacion_no_ascii_se_rechazan(entrada):
    with pytest.raises(ValueError):
        normalizar_email(entrada)


def test_lo_ascii_acepta_lo_mismo_que_antes_de_d020():
    """T-08e solo restringe lo no ASCII: todo ASCII imprimible sigue aceptado."""
    for cp in range(0x21, 0x7F):
        c = chr(cp)
        assert normalizar_email(f"a{c}b@x.cl") == f"a{c.casefold()}b@x.cl"
    for cp in list(range(0x00, 0x21)) + [0x7F]:
        with pytest.raises(ValueError):
            normalizar_email(f"a{chr(cp)}b@x.cl")


def modelo_acepta(texto):
    """Modelo independiente de la política (D-015 + D-020) sobre el texto ya normalizado.

    No llama a `normalizar_email` ni importa sus constantes: usa rangos y una
    tabla propia. ASCII: todo imprimible 0x21-0x7E. No ASCII: solo letras y
    números (categoría que empieza por L o N) fuera de la lista de rellenos.
    """
    for ch in texto:
        cp = ord(ch)
        if cp < 0x80:
            if not 0x21 <= cp <= 0x7E:
                return False
        else:
            if unicodedata.category(ch)[0] not in ("L", "N"):
                return False
            if cp in (0x3164, 0x115F, 0x1160, 0x2800, 0xFFFD, 0xFFFC, 0x00B7):
                return False
            if 0x2400 <= cp <= 0x2422 or 0x2010 <= cp <= 0x2015:
                return False
    return True


def preparar_para_modelo(valor):
    """Normalización de referencia: NFKC, recorte, casefold, NFKC (pasos de D-013)."""
    t = unicodedata.normalize("NFKC", valor).strip()
    return unicodedata.normalize("NFKC", t.casefold())


def revisar_modelo_en_rango(desde, hasta):
    """Cada punto de código: lo que acepta/rechaza `normalizar_email` coincide con el modelo."""
    for cp in puntos_de_codigo(desde, hasta):
        valor = f"a{chr(cp)}b@x.cl"
        esperado = modelo_acepta(preparar_para_modelo(valor))
        try:
            normalizar_email(valor)
            real = True
        except ValueError:
            real = False
        assert real == esperado, (hex(cp), unicodedata.category(chr(cp)), "esperado", esperado)


def repartir_por_procesos(funcion):
    total = 0x110000
    nucleos = os.cpu_count() or 1
    if nucleos < 2 or "fork" not in multiprocessing.get_all_start_methods():
        funcion(0, total)
        return
    nucleos = min(nucleos, 8)
    cortes = [total * k // nucleos for k in range(nucleos + 1)]
    with ProcessPoolExecutor(nucleos, mp_context=multiprocessing.get_context("fork")) as pool:
        futuros = [pool.submit(funcion, a, b) for a, b in zip(cortes, cortes[1:])]
        for futuro in futuros:
            futuro.result()


def test_exhaustivo_contra_un_modelo_independiente_en_todos_los_puntos_de_codigo():
    """D-020: los 1 112 064 puntos de código (sin sustitutos), esperado vs. real."""
    repartir_por_procesos(revisar_modelo_en_rango)


def test_el_modelo_acepta_y_rechaza_lo_que_debe():
    """Control del propio modelo, para que no acepte todo o rechace todo."""
    aceptados = sum(modelo_acepta(preparar_para_modelo(f"a{chr(cp)}b")) for cp in range(0x80, 0x3000))
    assert 5000 < aceptados < 0x3000 - 0x80
    assert modelo_acepta("se\u00f1or") and not modelo_acepta("a\u3164b") and not modelo_acepta("a b")


@pytest.mark.parametrize("valor", [None, 5, 1.5, b"ana@example.cl", ["ana@example.cl"], ("a",), object()])
def test_entradas_que_no_son_texto_lanzan_value_error(valor):
    with pytest.raises(ValueError):
        normalizar_email(valor)
