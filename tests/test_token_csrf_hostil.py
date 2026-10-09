"""T-13b (D-038): guarda determinista contra pruebas de «ausencia de texto» frágiles por el token CSRF.

El token de sesión son 64 caracteres hexadecimales aleatorios y va en el HTML de casi toda
página con formulario. Una aserción como `"abc" not in html` sobre la página completa falla
por azar (~1 de cada 15 páginas). Aquí el token se fuerza (variable `AGENDA_PSI_CSRF_TOKEN`,
ver `conftest.py`; no se toca `app/seguridad.py`) a valores llenos de subcadenas peligrosas y
se vuelven a correr, en un subproceso, los archivos de pruebas que miran páginas completas.
Si alguien reintroduce una aserción vulnerable, fallará siempre, no una vez de cada tantas.

T-13c (R-04 de la revisión de T-13): la selección ya no depende de nombres de variable (`html`,
`.text`...): se eligen las pruebas que afirman la ausencia de algo con cualquier forma y que leen
páginas. La guarda completa, sin selección, es correr toda la suite con el token hostil (ver D-040).
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

# Un solo token (64 hexadecimales) con las subcadenas que más se usan como «texto que no debe
# aparecer»: abc, abc123, dead, beef, cafe, 00, 0000, 1e2, 99999, 12345, 2026.
TOKEN_HOSTIL = ("abc123" + "dead" + "beef" + "cafe" + "0000" + "1e2" + "99999" + "12345" + "2026" + "00"
                + "abcdeadbeef" * 3)[:64]

# Se reejecutan las pruebas que afirman la AUSENCIA de algo con cualquier forma (`x not in y`,
# `y.count(x) == 0`, `assertNotIn`, `y.find(x) == -1`...), sin importar cómo se llamen las
# variables ni de dónde venga el texto (`.text`, `get_data(as_text=True)`, variable intermedia,
# ayudante de otro archivo) y que leen páginas (llaman a `get`/`post`/`open`/`test_client`, directa
# o indirectamente). Se detectan leyendo `tests/` con `ast`: una prueba nueva queda cubierta sin
# tocar esta lista, y la guarda cuesta segundos y no otra suite entera.
METODOS_DE_AUSENCIA = {"count", "assertNotIn", "assertNotContains", "find", "rfind", "index"}
METODOS_DE_PAGINA = {"get", "post", "open", "test_client", "put", "delete", "patch", "head"}


def _afirma_ausencia(nodo):
    for n in ast.walk(nodo):
        if isinstance(n, ast.Compare) and any(isinstance(o, ast.NotIn) for o in n.ops):
            return True
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in METODOS_DE_AUSENCIA:
            return True
    return False


def _lee_pagina(nodo):
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in METODOS_DE_PAGINA
               for n in ast.walk(nodo))


def _llamadas(nodo):
    nombres = set()
    for n in ast.walk(nodo):
        if isinstance(n, ast.Call):
            f = n.func
            nombres.add(f.id if isinstance(f, ast.Name) else getattr(f, "attr", ""))
    return nombres


def _funciones(ruta):
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    return [n for n in ast.walk(arbol) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _cierre(todas, propiedad):
    """Nombres de funciones que cumplen `propiedad` ellas mismas o llamando a otra que la cumple."""
    con = {f.name for f in todas if propiedad(f)}
    cambio = True
    while cambio:
        cambio = False
        for f in todas:
            if f.name not in con and _llamadas(f) & con:
                con.add(f.name)
                cambio = True
    return con


def pruebas_de_ausencia(archivos=None):
    """Ids `archivo::prueba` que afirman una ausencia y leen páginas.

    El cierre sobre ayudantes se hace entre TODOS los archivos (una prueba puede importar el
    ayudante de otro), por nombre de función: puede seleccionar de más, nunca de menos.
    """
    rutas = archivos or sorted((RAIZ / "tests").glob("test_*.py"))
    rutas = [r for r in rutas if r.name != Path(__file__).name]
    por_ruta = {r: _funciones(r) for r in rutas}
    todas = [f for fs in por_ruta.values() for f in fs]
    ausencia = _cierre(todas, _afirma_ausencia)
    pagina = _cierre(todas, _lee_pagina)
    return sorted({f"{r}::{f.name}" for r, fs in por_ruta.items() for f in fs
                   if f.name.startswith("test_") and f.name in ausencia and f.name in pagina})


def literales_hexadecimales_de_ausencia(ruta):
    """Literales cortos de solo `0-9a-f` usados como «no debe aparecer» en `ruta`."""
    encontrados = []
    for f in _funciones(ruta):
        for n in ast.walk(f):
            candidatos = []
            if isinstance(n, ast.Compare) and any(isinstance(o, ast.NotIn) for o in n.ops):
                candidatos = [n.left]
            elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("assertNotIn", "count"):
                candidatos = n.args[:1]
            for c in candidatos:
                if isinstance(c, ast.Constant) and isinstance(c.value, str):
                    if 0 < len(c.value) <= 16 and set(c.value.lower()) <= set(HEX):
                        encontrados.append((f.name, c.value))
    return encontrados


def test_el_token_hostil_es_valido_y_peligroso():
    assert len(TOKEN_HOSTIL) == 64 and set(TOKEN_HOSTIL) <= set(HEX), TOKEN_HOSTIL
    for texto in ("abc", "abc123", "dead", "beef", "cafe", "00", "0000", "1e2", "99999", "12345", "2026"):
        assert texto in TOKEN_HOSTIL, texto


def test_el_token_forzado_llega_a_la_pagina(app, monkeypatch):
    monkeypatch.setattr(seguridad, "secrets", _SecretsConTokenFijo(TOKEN_HOSTIL))
    html = app.test_client().get("/login").text
    assert f'value="{TOKEN_HOSTIL}"' in html and "abc" in html  # el riesgo es real en la página


def test_el_token_aleatorio_normal_es_hex_de_64(app):
    html = app.test_client().get("/login").text
    assert re.search(r'name="csrf_token" value="[0-9a-f]{64}"', html)


def test_se_detectan_las_pruebas_de_ausencia_sin_importar_como_se_escriban(tmp_path):
    # Las formas que la guarda de T-13b no veía (R-04): get_data(as_text=True), variable
    # intermedia, count()==0, assertNotIn, find()==-1 y un ayudante.
    (tmp_path / "test_a.py").write_text(
        "def ayudante(r):\n    assert 'abc' not in r\n"
        "def test_uno(c):\n    assert 'abc' not in c.get('/').get_data(as_text=True)\n"
        "def test_dos(c):\n    pagina = c.get('/').text\n    assert 'dead' not in pagina\n"
        "def test_tres(c):\n    assert c.get('/').text.count('beef') == 0\n"
        "def test_cuatro(self):\n    self.assertNotIn('cafe', self.client.get('/').text)\n"
        "def test_cinco(c):\n    assert c.get('/').text.find('00') == -1\n"
        "def test_seis(c):\n    ayudante(c.get('/').text)\n"
        "def test_siete(c):\n    assert 'abc' in c.get('/').text\n"
        "def test_ocho(c):\n    assert 'abc' not in {'x'}\n"
    )
    ids = [i.split("::")[1] for i in pruebas_de_ausencia([tmp_path / "test_a.py"])]
    assert ids == ["test_cinco", "test_cuatro", "test_dos", "test_seis", "test_tres", "test_uno"]


def test_se_detectan_las_pruebas_de_ausencia_en_paginas():
    ids = pruebas_de_ausencia()
    esperadas = ["test_dashboard_profesional.py::test_filas_ilegibles_se_omiten_sin_romper",
                 "test_dashboard_paciente.py::test_filas_ilegibles_se_omiten_sin_romper",
                 "test_estilo.py::test_500_en_espanol_sin_filtrar_la_excepcion"]
    for esperada in esperadas:
        assert any(i.endswith(esperada) for i in ids), esperada
    assert len(ids) >= 60


# Hoy hay un solo literal así y no mira una página sino una lista de sentencias SQL.
HEX_PERMITIDOS = {("test_crear_profesional.py", "db")}


def test_ninguna_prueba_busca_la_ausencia_de_un_texto_hexadecimal_corto():
    """Defensa determinista y sin subproceso: `"abc" not in html` puede fallar por azar (token CSRF)."""
    hallados = set()
    for ruta in sorted((RAIZ / "tests").glob("test_*.py")):
        for _, literal in literales_hexadecimales_de_ausencia(ruta):
            hallados.add((ruta.name, literal))
    nuevos = hallados - HEX_PERMITIDOS
    assert not nuevos, f"texto hexadecimal como «no debe aparecer» (usa un marcador con x, y, z o !): {nuevos}"


def test_la_busqueda_de_literales_hexadecimales_ve_todas_las_formas(tmp_path):
    ruta = tmp_path / "test_b.py"
    ruta.write_text(
        "def test_a(c):\n    assert 'abc' not in c.get('/').get_data(as_text=True)\n"
        "def test_b(c):\n    assert c.x.count('dead') == 0\n"
        "def test_c(self):\n    self.assertNotIn('00', self.x)\n"
        "def test_d(c):\n    assert 'xyz!' not in c.x\n"
        "def test_e(c):\n    assert 'abc' in c.x\n"
    )
    assert sorted(literales_hexadecimales_de_ausencia(ruta)) == [("test_a", "abc"), ("test_b", "dead"), ("test_c", "00")]


def test_las_pruebas_de_ausencia_pasan_con_un_token_hostil():
    entorno = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS"}
    entorno[VARIABLE_TOKEN] = TOKEN_HOSTIL
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-c", str(RAIZ / "pytest.ini"),
         "--rootdir", str(RAIZ), *pruebas_de_ausencia()],
        cwd=RAIZ, env=entorno, capture_output=True, text=True, timeout=600,
    )
    cola = (r.stdout + r.stderr)[-3000:]
    assert r.returncode == 0, cola
    assert " passed" in r.stdout and "failed" not in r.stdout and "error" not in r.stdout, cola
