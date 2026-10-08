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
