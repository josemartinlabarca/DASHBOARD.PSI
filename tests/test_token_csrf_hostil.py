"""T-13b (D-038): guarda determinista contra pruebas de «ausencia de texto» frágiles por el token CSRF.

El token de sesión son 64 caracteres hexadecimales aleatorios y va en el HTML de casi toda
página con formulario. Una aserción como `"abc" not in html` sobre la página completa falla
por azar (~1 de cada 15 páginas). Aquí el token se fuerza (variable `AGENDA_PSI_CSRF_TOKEN`,
ver `conftest.py`; no se toca `app/seguridad.py`) a valores llenos de subcadenas peligrosas y
se vuelven a correr, en un subproceso, los archivos de pruebas que miran páginas completas.
Si alguien reintroduce una aserción vulnerable, fallará siempre, no una vez de cada tantas.
"""
import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app import seguridad
from tests.conftest import VARIABLE_TOKEN, _SecretsConTokenFijo

RAIZ = Path(__file__).resolve().parent.parent
HEX = "0123456789abcdef"

# Cada token es hexadecimal válido y contiene las subcadenas hex que más se usan como «texto
# que no debe aparecer»: abc, abc123, dead, beef, cafe, 00, 0000, 1e2, 99999, 12345, 2026...
TOKENS = {
    "abc-dead-beef-ceros": "abcdeadbeef0000cabc00abcdeadbeef0000cabc00abcdeadbeef0000cabc00a",
    "ceros-y-digitos": "0" * 10 + "abc123" + "1e2" + "99999" + "12345" + "2026" + "0000" + "cafe" + "f" * 21 + "00",
}

# Se reejecutan solo las pruebas que afirman la ausencia de texto en una página (`not in html`,
# `not in r.text`, `not in texto`...), más las que llaman a un ayudante que lo hace. Se
# detectan leyendo el código de `tests/` con `ast`, así una prueba nueva queda cubierta sin
# tocar esta lista, y la guarda cuesta segundos y no otra suite entera.
PAGINA = re.compile(r"not in [\w.\[\]()\"' ,]*?(html|\.text|texto|cuerpo|\.data)\b")


def _funciones(ruta):
    fuente = ruta.read_text(encoding="utf-8")
    return fuente, [n for n in ast.parse(fuente).body if isinstance(n, ast.FunctionDef)]


def pruebas_de_ausencia_en_paginas():
    """Devuelve los ids `archivo::prueba` que miran la ausencia de texto en páginas."""
    ids = []
    for ruta in sorted((RAIZ / "tests").glob("test_*.py")):
        if ruta.name == Path(__file__).name:
            continue
        fuente, funciones = _funciones(ruta)
        cuerpos = {f.name: ast.get_source_segment(fuente, f) or "" for f in funciones}
        con_aserciones = {n for n, c in cuerpos.items() if PAGINA.search(c)}
        cambio = True
        while cambio:  # una prueba que llama a un ayudante con esa aserción también cuenta
            cambio = False
            for nombre, cuerpo in cuerpos.items():
                if nombre not in con_aserciones and any(re.search(rf"\b{h}\(", cuerpo) for h in con_aserciones):
                    con_aserciones.add(nombre)
                    cambio = True
        ids += [f"{ruta}::{n}" for n in cuerpos if n.startswith("test_") and n in con_aserciones]
    return ids


def test_los_tokens_de_la_guarda_son_validos_y_peligrosos():
    for nombre, token in TOKENS.items():
        assert len(token) == 64 and set(token) <= set(HEX), nombre
    assert all("abc" in t or "00" in t for t in TOKENS.values())
    assert "abc" in TOKENS["abc-dead-beef-ceros"] and "0000" in TOKENS["abc-dead-beef-ceros"]


def test_el_token_forzado_llega_a_la_pagina(app, monkeypatch):
    token = TOKENS["abc-dead-beef-ceros"]
    monkeypatch.setattr(seguridad, "secrets", _SecretsConTokenFijo(token))
    html = app.test_client().get("/login").text
    assert f'value="{token}"' in html and "abc" in html  # el riesgo es real en la página


def test_el_token_aleatorio_normal_es_hex_de_64(app):
    html = app.test_client().get("/login").text
    assert re.search(r'name="csrf_token" value="[0-9a-f]{64}"', html)


def test_se_detectan_las_pruebas_de_ausencia_en_paginas():
    ids = pruebas_de_ausencia_en_paginas()
    # Las que motivaron T-13b y un ayudante con la aserción (estilo) deben estar.
    esperadas = ["test_dashboard_profesional.py::test_filas_ilegibles_se_omiten_sin_romper",
                 "test_dashboard_paciente.py::test_filas_ilegibles_se_omiten_sin_romper",
                 "test_estilo.py::test_500_en_espanol_sin_filtrar_la_excepcion"]
    for esperada in esperadas:
        assert any(i.endswith(esperada) for i in ids), esperada
    assert len(ids) >= 40


@pytest.mark.parametrize("nombre", sorted(TOKENS))
def test_las_pruebas_de_ausencia_pasan_con_un_token_hostil(nombre):
    entorno = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS"}
    entorno[VARIABLE_TOKEN] = TOKENS[nombre]
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-c", str(RAIZ / "pytest.ini"),
         "--rootdir", str(RAIZ), *pruebas_de_ausencia_en_paginas()],
        cwd=RAIZ, env=entorno, capture_output=True, text=True, timeout=600,
    )
    cola = (r.stdout + r.stderr)[-3000:]
    assert r.returncode == 0, cola
    assert " passed" in r.stdout and "failed" not in r.stdout and "error" not in r.stdout, cola
