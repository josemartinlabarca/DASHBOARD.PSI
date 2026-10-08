"""Guardas de las aceleraciones de conftest.py (T-08b, D-031).

Las pruebas aceleradas (base copiada de una plantilla, caché de plantillas Jinja y de
constructores de URL) deben comportarse igual que sin aceleración y cada prueba debe
seguir viendo una base limpia.
"""
import re
import sqlite3

import pytest

from app import create_app
from app import db as modulo_db
from app.db import get_db, init_db
from tests import conftest as cf
from tests.test_login import crear


def _esquema(ruta):
    con = sqlite3.connect(ruta)
    try:
        return (
            sorted(con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master").fetchall()),
            con.execute("PRAGMA user_version").fetchone(),
        )
    finally:
        con.close()


# --- Aislamiento: cada prueba ve una base limpia, en cualquier orden ------------
# Las tres copias escriben lo mismo. Si una base se compartiera entre pruebas, la
# segunda chocaría con el UNIQUE del correo o vería más de una fila.


@pytest.mark.parametrize("copia", [1, 2, 3])
def test_cada_prueba_empieza_con_la_base_vacia_y_escribe_sin_afectar_a_las_otras(app, copia):
    with app.app_context():
        init_db()
        db = get_db()
        assert db.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM horas").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM notificaciones").fetchone()[0] == 0
    crear(app, email="unico@example.cl")
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 1


def test_dos_apps_en_la_misma_prueba_tienen_archivos_distintos(app, tmp_path):
    otra = create_app({"TESTING": True, "DATABASE": str(tmp_path / "otra.db")})
    assert app.config["DATABASE"] != otra.config["DATABASE"]
    with app.app_context():
        init_db()
    crear(app, email="solo-en-la-primera@example.cl")
    with otra.app_context():
        init_db()
        assert get_db().execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0


def test_la_plantilla_no_recibe_escrituras_de_las_pruebas(app, plantilla_db):
    with app.app_context():
        init_db()
    crear(app, email="no-debe-llegar@example.cl")
    for tabla in ("usuarios", "horas", "notificaciones"):
        assert plantilla_db().execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0] == 0


# --- La base copiada es idéntica a la que crea el init_db de verdad -------------


def test_la_base_de_plantilla_tiene_exactamente_el_esquema_del_init_db_real(tmp_path):
    real = create_app({"TESTING": True, "DATABASE": str(tmp_path / "real.db")})
    with real.app_context():
        cf._init_db_real()
    rapida = create_app({"TESTING": True, "DATABASE": str(tmp_path / "rapida.db")})
    with rapida.app_context():
        assert modulo_db.init_db is not cf._init_db_real  # el atajo está activo
        init_db()
    assert _esquema(tmp_path / "rapida.db") == _esquema(tmp_path / "real.db")
    assert _esquema(tmp_path / "real.db")[0], "el esquema real no puede estar vacío"


def test_la_base_copiada_acepta_y_rechaza_lo_mismo_que_la_real(app):
    with app.app_context():
        init_db()
        db = get_db()
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO usuarios (nombre, email, password_hash, rol, creado_en)"
                " VALUES ('x', 'x@example.cl', 'h', 'otro', '2026-10-08T10:00:00')"
            )


def test_init_db_sobre_una_base_con_tablas_ejecuta_el_real_y_no_borra_datos(app):
    with app.app_context():
        init_db()
    crear(app, email="queda@example.cl")
    with app.app_context():
        init_db()  # ya hay tablas: no se vuelve a copiar la plantilla encima
        assert get_db().execute("SELECT email FROM usuarios").fetchall()[0][0] == "queda@example.cl"


@pytest.mark.base_real
def test_con_base_real_no_hay_atajo():
    assert modulo_db.init_db is cf._init_db_real


# --- Cachés: mismo resultado que sin ellas --------------------------------------


def test_cache_de_constructores_de_url_da_las_mismas_urls_que_sin_cache(app, monkeypatch, tmp_path):
    monkeypatch.setattr(cf.Rule, "_compile_builder", cf._compilar_constructor_real)
    sin_cache = create_app({"TESTING": True, "DATABASE": str(tmp_path / "s.db")})
    reglas = list(app.url_map.iter_rules())
    assert len(reglas) >= 10
    for regla in reglas:
        valores = {argumento: 7 for argumento in regla.arguments}
        con = app.url_map.bind("localhost").build(regla.endpoint, valores)
        sin = sin_cache.url_map.bind("localhost").build(regla.endpoint, valores)
        assert con == sin, regla.endpoint



def test_cache_de_plantillas_renderiza_igual_que_sin_cache(app, client, tmp_path):
    sin_cache = create_app({"TESTING": True, "DATABASE": str(tmp_path / "sc.db")})
    assert type(app.jinja_env.bytecode_cache).__name__ == "_CacheDePlantillasEnMemoria"
    assert sin_cache.jinja_env.bytecode_cache is None
    sin_token = lambda cuerpo: re.sub(rb'name="csrf_token" value="[^"]*"', b"", cuerpo)  # noqa: E731
    for ruta in ("/", "/login", "/registro"):
        con = sin_token(client.get(ruta).get_data())
        sin = sin_token(sin_cache.test_client().get(ruta).get_data())
        assert con == sin and len(con) > 200, ruta


# --- Carpeta temporal en memoria: espacio, permisos y limpieza (T-08c, D-031) ----
# R-01: con un /dev/shm pequeño la suite se rompía a mitad con «database or disk is
# full». R-02: el directorio tenía nombre predecible y quedaba tras un SIGTERM.
import os
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

RAIZ = Path(__file__).resolve().parent.parent
MIB = 2**20
UMBRAL = cf.UMBRAL_TMPFS_BYTES


def _uso(libre):
    return lambda directorio: SimpleNamespace(total=10**12, used=0, free=libre)


def _decidir(libre, entorno=None, acceso=True):
    return cf.decidir_directorio_en_memoria(
        entorno={} if entorno is None else entorno,
        directorio="/dev/shm",
        uso_de_disco=_uso(libre),
        acceso=lambda ruta, modo: acceso,
    )


def test_el_umbral_es_cuatro_veces_el_pico_medido():
    # Pico real medido en T-08c: 23 520 KiB para 1135 pruebas. Bajar la cifra sin volver a medir
    # dejaría la suite expuesta a R-01.
    assert cf.PICO_MEDIDO_BYTES >= 23_520 * 1024
    assert cf.HOLGURA >= 4
    assert cf.UMBRAL_TMPFS_BYTES == cf.HOLGURA * cf.PICO_MEDIDO_BYTES


@pytest.mark.parametrize("libre", [0, 12 * MIB, 64 * MIB, UMBRAL - 1])
def test_con_poco_espacio_libre_no_se_usa_la_memoria_compartida(libre):
    usar, motivo = _decidir(libre)
    assert usar is False
    assert "MiB libres" in motivo and "se piden" in motivo


@pytest.mark.parametrize("libre", [UMBRAL, UMBRAL + 1, 8 * 2**30])
def test_con_espacio_de_sobra_se_usa_la_memoria_compartida(libre):
    assert _decidir(libre)[0] is True


def test_sin_acceso_a_dev_shm_no_se_usa_ni_forzando():
    assert _decidir(8 * 2**30, acceso=False)[0] is False
    assert _decidir(8 * 2**30, {cf.VARIABLE_TMPFS: "1"}, acceso=False)[0] is False


def test_la_variable_de_entorno_permite_forzar_en_los_dos_sentidos():
    assert _decidir(8 * 2**30, {cf.VARIABLE_TMPFS: "0"})[0] is False
    assert _decidir(1 * MIB, {cf.VARIABLE_TMPFS: "1"})[0] is True
    assert _decidir(1 * MIB, {cf.VARIABLE_TMPFS: "auto"})[0] is False
    assert _decidir(1 * MIB, {cf.VARIABLE_TMPFS: ""})[0] is False


def test_si_no_se_puede_medir_el_espacio_se_cae_a_la_carpeta_normal():
    def falla(directorio):
        raise OSError("sin permiso")

    usar, motivo = cf.decidir_directorio_en_memoria(
        entorno={}, uso_de_disco=falla, acceso=lambda ruta, modo: True,
    )
    assert usar is False and "sin permiso" in motivo


def _configurar(monkeypatch, tmp_path, libre, basetemp=None):
    """Ejecuta el `pytest_configure` real con un `disk_usage` simulado y /dev/shm = tmp_path."""
    monkeypatch.delenv(cf.VARIABLE_TMPFS, raising=False)
    monkeypatch.setattr(cf, "DIRECTORIO_TMPFS", str(tmp_path))
    monkeypatch.setattr(cf.shutil, "disk_usage", _uso(libre))
    monkeypatch.setattr(cf, "instalar_limpieza", lambda ruta: None)
    config = SimpleNamespace(option=SimpleNamespace(basetemp=basetemp))
    cf.pytest_configure(config)
    return config


def test_pytest_configure_con_el_tmpfs_casi_lleno_deja_la_carpeta_normal(monkeypatch, tmp_path):
    config = _configurar(monkeypatch, tmp_path, libre=12 * MIB)
    assert config.option.basetemp is None  # pytest usará su carpeta temporal de siempre
    assert list(tmp_path.iterdir()) == []  # y no se creó nada en el "tmpfs"
    assert "la normal de pytest" in cf.pytest_report_header(config)
    assert "MiB libres" in cf.pytest_report_header(config)


def test_pytest_configure_con_espacio_usa_un_directorio_propio_y_lo_informa(monkeypatch, tmp_path):
    config = _configurar(monkeypatch, tmp_path, libre=8 * 2**30)
    raiz = Path(config._tmpfs_raiz)
    assert raiz.parent == tmp_path and raiz.name.startswith(cf.PREFIJO_TMPFS)
    assert Path(config.option.basetemp).parent == raiz
    assert str(config.option.basetemp) in cf.pytest_report_header(config)
    cf.pytest_unconfigure(config)
    assert not raiz.exists()


def test_basetemp_del_usuario_se_respeta(monkeypatch, tmp_path):
    config = _configurar(monkeypatch, tmp_path, libre=8 * 2**30, basetemp="/algun/lugar")
    assert config.option.basetemp == "/algun/lugar"
    assert config._tmpfs_raiz is None and list(tmp_path.iterdir()) == []
    assert "--basetemp" in cf.pytest_report_header(config)


def test_la_raiz_temporal_es_privada_e_impredecible(monkeypatch, tmp_path):
    monkeypatch.setattr(cf, "instalar_limpieza", lambda ruta: None)
    a = Path(cf.crear_raiz_temporal(str(tmp_path)))
    b = Path(cf.crear_raiz_temporal(str(tmp_path)))
    assert a != b and a.parent == tmp_path
    assert a.name.startswith(cf.PREFIJO_TMPFS)
    assert a.name != f"{cf.PREFIJO_TMPFS}{os.getpid()}"  # ya no se deduce del pid
    if os.name == "posix":
        assert a.stat().st_mode & 0o777 == 0o700
        assert b.stat().st_mode & 0o777 == 0o700


def test_la_carpeta_temporal_de_esta_sesion_es_privada(request):
    raiz = request.config._tmpfs_raiz
    if raiz is None:
        pytest.skip("esta corrida no usa la memoria compartida")
    assert os.stat(raiz).st_mode & 0o777 == 0o700
    assert os.stat(request.config.option.basetemp).st_mode & 0o777 == 0o700


GUION = """
import os, signal, sys, time
sys.path.insert(0, {raiz!r})
{preambulo}
from tests import conftest as cf
r = cf.crear_raiz_temporal(sys.argv[1])
open(os.path.join(r, "base.db"), "w").close()
print(r, flush=True)
{final}
"""


def _lanzar(tmp_path, final, preambulo=""):
    guion = GUION.format(raiz=str(RAIZ), preambulo=preambulo, final=final)
    return subprocess.Popen(
        [sys.executable, "-c", guion, str(tmp_path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=RAIZ,
        env={**os.environ, "SECRET_KEY": "abc"},
    )


def test_la_raiz_se_borra_al_salir_con_atexit(tmp_path):
    p = _lanzar(tmp_path, "")
    salida, error = p.communicate(timeout=60)
    assert p.returncode == 0, error
    assert salida.strip().startswith(str(tmp_path))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(not hasattr(signal, "SIGTERM") or os.name != "posix", reason="solo POSIX")
def test_sigterm_borra_la_raiz_y_el_proceso_muere_por_la_senal(tmp_path):
    p = _lanzar(tmp_path, "time.sleep(60)")
    try:
        raiz = p.stdout.readline().strip()
        assert os.path.isdir(raiz)
        p.send_signal(signal.SIGTERM)
        p.wait(timeout=30)
    finally:
        if p.poll() is None:
            p.kill()
        p.communicate()
    assert p.returncode == -signal.SIGTERM  # la señal se reenvió con la acción por defecto
    assert not os.path.exists(raiz)


@pytest.mark.skipif(not hasattr(os, "fork") or not hasattr(signal, "SIGTERM"), reason="solo POSIX")
def test_un_hijo_con_fork_no_borra_la_raiz_del_padre(tmp_path):
    final = (
        "pid = os.fork()\n"
        "if pid == 0:\n"
        "    os.kill(os.getpid(), signal.SIGTERM)\n"
        "    time.sleep(30)\n"
        "    os._exit(0)\n"
        "_, estado = os.waitpid(pid, 0)\n"
        "print('hijo-murio-por-senal', os.WIFSIGNALED(estado), 'raiz-existe', os.path.isdir(r), flush=True)\n"
    )
    p = _lanzar(tmp_path, final)
    salida, error = p.communicate(timeout=60)
    assert p.returncode == 0, error
    assert "hijo-murio-por-senal True raiz-existe True" in salida


def test_sin_sigterm_en_el_sistema_solo_queda_atexit(monkeypatch):
    # Windows: `signal.SIGTERM` no se usa; no debe fallar ni instalar manejadores.
    registrados, manejadores = [], []
    monkeypatch.delattr(cf.signal, "SIGTERM", raising=False)
    monkeypatch.setattr(cf.atexit, "register", lambda *a: registrados.append(a))
    monkeypatch.setattr(cf.signal, "signal", lambda *a: manejadores.append(a))
    cf.instalar_limpieza("/no/existe")
    assert len(registrados) == 1 and manejadores == []


@pytest.mark.skipif(not hasattr(signal, "SIGTERM"), reason="sin SIGTERM")
def test_no_pisa_un_manejador_de_sigterm_ajeno(monkeypatch):
    manejadores = []
    monkeypatch.setattr(cf.atexit, "register", lambda *a: None)
    monkeypatch.setattr(cf.signal, "getsignal", lambda numero: (lambda n, m: None))
    monkeypatch.setattr(cf.signal, "signal", lambda *a: manejadores.append(a))
    cf.instalar_limpieza("/no/existe")
    assert manejadores == []
