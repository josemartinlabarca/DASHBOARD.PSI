"""R-01 de la revisión de T-08: sin `time.tzset` (Windows) la suite no debe romperse.

Se simula la ausencia en un subproceso con un `sitecustomize` que hace
`del time.tzset` antes de importar nada, y se corre allí el `conftest.py` real
con dos pruebas mínimas. Nada de esto toca la zona ni el módulo `time` de la
sesión que ejecuta estas pruebas.
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent

PRUEBAS_MINIMAS = '''
import os, time

def test_sencilla(client):
    assert client.get("/login").status_code == 200

def test_con_zona(zona_sistema):
    assert os.environ["TZ"] == zona_sistema
'''


PLUGIN_FINAL = '''
import os, time

def pytest_sessionfinish(session):
    print("TZFINAL=%s|%s" % (os.environ.get("TZ"), time.tzname[0]))
'''


def _correr(tmp_path, sin_tzset, tz=None):
    carpeta = tmp_path / "proyecto"
    carpeta.mkdir()
    shutil.copy(RAIZ / "tests" / "conftest.py", carpeta / "conftest.py")
    (carpeta / "test_minimas.py").write_text(PRUEBAS_MINIMAS)
    (carpeta / "plugin_final.py").write_text(PLUGIN_FINAL)
    rutas = [str(carpeta), str(RAIZ)]
    if sin_tzset:
        sitio = tmp_path / "sitio"
        sitio.mkdir()
        (sitio / "sitecustomize.py").write_text("import time\ndel time.tzset\n")
        rutas.insert(0, str(sitio))
    entorno = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "TZ")}
    if tz is not None:
        entorno["TZ"] = tz
    entorno["PYTHONPATH"] = os.pathsep.join(rutas)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider", "-p", "plugin_final",
         "--rootdir", str(carpeta), "-c", str(RAIZ / "pytest.ini"), str(carpeta)],
        cwd=carpeta, env=entorno, capture_output=True, text=True, timeout=120,
    )


@pytest.fixture
def sin_tzset(tmp_path):
    return _correr(tmp_path, sin_tzset=True)


def test_la_simulacion_realmente_quita_tzset(tmp_path):
    sitio = tmp_path / "sitio"
    sitio.mkdir()
    (sitio / "sitecustomize.py").write_text("import time\ndel time.tzset\n")
    entorno = dict(os.environ, PYTHONPATH=str(sitio))
    r = subprocess.run(
        [sys.executable, "-c", "import time; print(hasattr(time, 'tzset'))"],
        env=entorno, capture_output=True, text=True,
    )
    assert r.stdout.strip() == "False"


def test_sin_tzset_una_prueba_sencilla_corre_sin_errores(sin_tzset):
    salida = sin_tzset.stdout + sin_tzset.stderr
    assert "AttributeError" not in salida, salida
    assert " error" not in salida, salida
    assert "1 passed" in salida, salida
    assert sin_tzset.returncode == 0, salida


def test_sin_tzset_las_pruebas_con_zona_sistema_se_saltan_y_no_fallan(sin_tzset):
    salida = sin_tzset.stdout + sin_tzset.stderr
    assert "failed" not in salida, salida
    # la prueba con zona_sistema x 3 zonas = 3 saltadas, con un motivo claro
    assert "3 skipped" in salida, salida
    assert "time.tzset" in salida, salida
    assert sin_tzset.returncode == 0, salida


def test_con_tzset_las_mismas_pruebas_si_se_ejecutan_en_las_tres_zonas(tmp_path):
    # Control: la simulación es lo que produce el salto, no el subproceso en sí.
    if not hasattr(time, "tzset"):
        pytest.skip("sin time.tzset")
    r = _correr(tmp_path, sin_tzset=False)
    salida = r.stdout + r.stderr
    assert "skipped" not in salida, salida
    assert "4 passed" in salida, salida


def test_con_tzset_la_zona_del_equipo_se_restaura_al_terminar(tmp_path):
    # La última zona que fija `zona_sistema` en las pruebas mínimas es Santiago; el
    # equipo simulado está en Tokio, así que solo una restauración real lo deja en Tokio.
    if not hasattr(time, "tzset"):
        pytest.skip("sin time.tzset")
    r = _correr(tmp_path, sin_tzset=False, tz="Asia/Tokyo")
    assert "TZFINAL=Asia/Tokyo|JST" in r.stdout, r.stdout


def test_con_tzset_si_TZ_no_estaba_definida_no_queda_definida(tmp_path):
    if not hasattr(time, "tzset"):
        pytest.skip("sin time.tzset")
    r = _correr(tmp_path, sin_tzset=False)
    assert "TZFINAL=None|" in r.stdout, r.stdout


def test_sin_tzset_la_zona_del_equipo_no_se_toca(tmp_path):
    r = _correr(tmp_path, sin_tzset=True, tz="Asia/Tokyo")
    assert "TZFINAL=Asia/Tokyo|JST" in r.stdout, r.stdout
