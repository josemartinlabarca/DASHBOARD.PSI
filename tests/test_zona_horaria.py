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


@pytest.fixture
def cache_de_zona_limpia():
    """La caché de `zona_chile()` queda vacía antes y después de la prueba."""
    auth.zona_chile.cache_clear()
    yield
    auth.zona_chile.cache_clear()


def test_zona_chile_se_crea_una_sola_vez(cache_de_zona_limpia):
    assert auth.zona_chile() is auth.zona_chile()
    assert str(auth.zona_chile()) == "America/Santiago"


def test_las_pruebas_anteriores_no_dejan_la_cache_poblada():
    """Corre después de la anterior (mismo archivo, orden de definición)."""
    assert auth.zona_chile.cache_info().currsize == 0


def test_sin_zona_horaria_el_registro_da_500_y_no_crea_usuarios(app, client, monkeypatch, cache_de_zona_limpia):
    from app.db import init_db
    from tests.test_registro import VALIDO
    from tests.test_seguridad import extraer_token
    import sqlite3

    def sin_zona(nombre):
        raise auth.ZoneInfoNotFoundError(nombre)

    with app.app_context():
        init_db()
    app.config["PROPAGATE_EXCEPTIONS"] = False  # que el 500 llegue como respuesta
    monkeypatch.setattr(auth, "ZoneInfo", sin_zona)
    token = extraer_token(client.get("/registro").text)
    r = client.post("/registro", data=dict(VALIDO, csrf_token=token))
    assert r.status_code == 500
    con = sqlite3.connect(app.config["DATABASE"])
    try:
        assert con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0
    finally:
        con.close()


def test_con_tzdata_instalado_y_sin_zonas_en_el_sistema_funciona(tmp_path):
    """Rama de Alpine/distroless: sin /usr/share/zoneinfo, el paquete tzdata basta."""
    vacio = tmp_path / "sin_zonas"
    vacio.mkdir()
    codigo = (
        "import zoneinfo\n"
        f"zoneinfo.reset_tzpath(to=[{str(vacio)!r}])\n"
        "from app import auth\n"
        "print(auth.zona_chile())\n"
    )
    entorno = {"PYTHONTZPATH": str(vacio), "PATH": "", "SECRET_KEY": "abc"}
    r = subprocess.run(
        [sys.executable, "-c", codigo], cwd=RAIZ, env=entorno,
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stderr + "\n(¿falta `pip install -r requirements.txt`, que instala tzdata?)"
    assert r.stdout.strip() == "America/Santiago"


def test_requirements_pide_tzdata_en_todas_las_plataformas():
    lineas = [
        linea.split("#")[0].strip()
        for linea in (RAIZ / "requirements.txt").read_text(encoding="utf-8").splitlines()
    ]
    tzdata = [linea for linea in lineas if linea.lower().startswith("tzdata")]
    assert tzdata, "falta tzdata en requirements.txt (D-012)"
    assert ";" not in tzdata[0], "tzdata no debe llevar marcador de plataforma (D-012)"
