import subprocess
import sys
from pathlib import Path

import pytest

from app import auth

RAIZ = Path(__file__).resolve().parent.parent

# Simula un sistema sin datos de zona horaria: TZPATH vacío y sin paquete tzdata.
PREAMBULO = """
import sys, zoneinfo
sys.modules["tzdata"] = None
zoneinfo.reset_tzpath(to=[{vacio!r}])
"""


def ejecutar(codigo, tmp_path):
    vacio = tmp_path / "sin_zonas"
    vacio.mkdir(exist_ok=True)
    entorno = {"PYTHONTZPATH": str(vacio), "PATH": "", "SECRET_KEY": "abc"}
    return subprocess.run(
        [sys.executable, "-c", PREAMBULO.format(vacio=str(vacio)) + codigo],
        cwd=RAIZ, env=entorno, capture_output=True, text=True, timeout=60,
    )


def test_el_entorno_simulado_realmente_no_tiene_la_zona(tmp_path):
    r = ejecutar(
        "from zoneinfo import ZoneInfo\n"
        "try:\n    ZoneInfo('America/Santiago')\nexcept Exception as e:\n    print(type(e).__name__)",
        tmp_path,
    )
    assert r.stdout.strip() == "ZoneInfoNotFoundError", r.stderr


def test_importar_app_y_crear_la_app_no_necesitan_zona_horaria(tmp_path):
    r = ejecutar(
        "import app\n"
        f"a = app.create_app({{'DATABASE': {str(tmp_path / 'x.db')!r}}})\n"
        "print('ok')",
        tmp_path,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "ok"


def test_init_db_no_necesita_zona_horaria(tmp_path):
    r = ejecutar(
        "import app\n"
        f"a = app.create_app({{'DATABASE': {str(tmp_path / 'x.db')!r}}})\n"
        "r = a.test_cli_runner().invoke(args=['init-db'])\n"
        "print(r.exit_code, r.output.strip())",
        tmp_path,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "0 Base de datos inicializada."


def test_sin_zona_horaria_el_error_es_claro(monkeypatch):
    def sin_zona(nombre):
        raise auth.ZoneInfoNotFoundError(nombre)

    auth.zona_chile.cache_clear()
    monkeypatch.setattr(auth, "ZoneInfo", sin_zona)
    try:
        with pytest.raises(RuntimeError, match="tzdata"):
            auth.zona_chile()
    finally:
        auth.zona_chile.cache_clear()


def test_zona_chile_se_crea_una_sola_vez():
    auth.zona_chile.cache_clear()
    assert auth.zona_chile() is auth.zona_chile()
    assert str(auth.zona_chile()) == "America/Santiago"
