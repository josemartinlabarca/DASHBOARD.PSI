"""Guardas de la fixture de hash rápido (D-019, R-06, R-07)."""
import configparser
import pathlib
import subprocess
import sys

import pytest
from werkzeug import security

from app import auth
from tests.conftest import METODO_RAPIDO, _modulos_de_la_app_con_hash

RAIZ = pathlib.Path(__file__).resolve().parent.parent


def test_el_hash_rapido_esta_activo_en_werkzeug_y_en_auth():
    for funcion in (security.generate_password_hash, auth.generate_password_hash):
        assert funcion("x").startswith(f"{METODO_RAPIDO}$")


def test_el_hash_rapido_cubre_todo_modulo_de_la_app_que_hashea():
    modulos = _modulos_de_la_app_con_hash()
    assert auth in modulos
    for modulo in modulos:
        assert modulo.generate_password_hash("x").startswith(f"{METODO_RAPIDO}$"), modulo.__name__


def test_ningun_archivo_de_app_hashea_por_un_camino_no_cubierto():
    """Todo archivo de app/ que menciona generate_password_hash lo expone como
    atributo del módulo (lo que la fixture parchea); `import werkzeug.security`
    entero también queda cubierto porque se parchea ese módulo."""
    for archivo in (RAIZ / "app").glob("*.py"):
        if "generate_password_hash" in archivo.read_text(encoding="utf-8"):
            modulo = sys.modules[f"app.{archivo.stem}"]
            assert modulo in _modulos_de_la_app_con_hash(), archivo.name


@pytest.mark.hash_real
def test_con_hash_real_no_hay_hash_rapido():
    assert auth.generate_password_hash("x").startswith("scrypt:32768:8:1$")


def test_pytest_ini_usa_strict_markers():
    config = configparser.ConfigParser()
    config.read(RAIZ / "pytest.ini")
    assert "--strict-markers" in config["pytest"]["addopts"]


def test_un_marcador_mal_escrito_hace_fallar_la_coleccion(tmp_path):
    prueba = tmp_path / "test_marcador.py"
    prueba.write_text(
        "import pytest\n\n@pytest.mark.hash_rael\ndef test_x():\n    pass\n"
    )
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-c", str(RAIZ / "pytest.ini"),
         "--rootdir", str(tmp_path), "-p", "no:cacheprovider", str(prueba)],
        capture_output=True, text=True, cwd=tmp_path,
    )
    assert r.returncode != 0
    assert "hash_rael" in r.stdout + r.stderr
