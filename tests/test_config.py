import logging
import os
import subprocess
import sys

import click
import pytest

from app import MENSAJE_SIN_SECRET_KEY, create_app


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("FLASK_DEBUG", raising=False)


def _config(tmp_path, **extra):
    return {"DATABASE": str(tmp_path / "test.db"), **extra}


def _peticion_fuera_de_debug(app):
    """Hace una petición real; la app no debe atenderla con 200."""
    return app.test_client().get("/")


def test_sin_secret_key_fuera_de_debug_no_atiende_peticiones(tmp_path, caplog):
    app = create_app(_config(tmp_path))
    respuesta = _peticion_fuera_de_debug(app)
    assert respuesta.status_code == 500
    assert "SECRET_KEY" in caplog.text


def test_secret_key_vacia_fuera_de_debug_no_atiende_peticiones(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "")
    assert _peticion_fuera_de_debug(create_app(_config(tmp_path))).status_code == 500


@pytest.mark.parametrize("valor", ["   ", "\t\n ", " "])
def test_secret_key_de_solo_espacios_cuenta_como_ausente(tmp_path, monkeypatch, valor):
    monkeypatch.setenv("SECRET_KEY", valor)
    assert _peticion_fuera_de_debug(create_app(_config(tmp_path))).status_code == 500


def test_secret_key_de_solo_espacios_por_test_config_falla(tmp_path):
    app = create_app(_config(tmp_path, SECRET_KEY="   "))
    assert _peticion_fuera_de_debug(app).status_code == 500


@pytest.mark.parametrize("valor", ["0", "false", "False", "no"])
def test_flask_debug_desactivado_sin_secret_key_falla(tmp_path, monkeypatch, valor):
    monkeypatch.setenv("FLASK_DEBUG", valor)
    app = create_app(_config(tmp_path))
    assert not app.debug
    assert _peticion_fuera_de_debug(app).status_code == 500


def test_init_db_por_cli_funciona_sin_secret_key_ni_debug(tmp_path):
    app = create_app(_config(tmp_path))  # sin TESTING, sin clave, sin debug
    assert not app.testing and not app.debug
    resultado = app.test_cli_runner().invoke(args=["init-db"])
    assert resultado.exit_code == 0, resultado.output
    assert (tmp_path / "test.db").exists()


def test_secret_key_por_test_config_se_respeta(tmp_path):
    app = create_app(_config(tmp_path, SECRET_KEY="clave-por-config"))
    assert app.config["SECRET_KEY"] == "clave-por-config"
    assert _peticion_fuera_de_debug(app).status_code == 200


def test_secret_key_valida_no_se_modifica(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "  con espacios  ")
    app = create_app(_config(tmp_path))
    assert app.config["SECRET_KEY"] == "  con espacios  "
    assert _peticion_fuera_de_debug(app).status_code == 200


def test_testing_funciona_sin_secret_key(tmp_path):
    app = create_app(_config(tmp_path, TESTING=True))
    assert app.config["SECRET_KEY"]


def test_con_secret_key_funciona_sin_testing_ni_debug(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "clave-de-prueba")
    app = create_app(_config(tmp_path))
    assert app.config["SECRET_KEY"] == "clave-de-prueba"
    assert not app.debug and not app.testing


def test_flask_debug_funciona_sin_secret_key(tmp_path, monkeypatch):
    monkeypatch.setenv("FLASK_DEBUG", "1")
    app = create_app(_config(tmp_path))
    assert app.debug
    assert app.config["SECRET_KEY"]


# --- T-02d #3: la exigencia de SECRET_KEY cubre todo tipo de ruta ---------------


@pytest.mark.parametrize(
    "ruta",
    ["/", "/registro", "/login", "/paciente", "/profesional", "/static/x.css", "/no-existe"],
)
@pytest.mark.parametrize("metodo", ["get", "post"])
def test_sin_secret_key_toda_ruta_da_500(tmp_path, ruta, metodo):
    """Blueprints, estáticos y rutas inexistentes, por GET y por POST."""
    app = create_app(_config(tmp_path))
    assert getattr(app.test_client(), metodo)(ruta).status_code == 500


def test_con_secret_key_las_mismas_rutas_responden_normal(tmp_path):
    app = create_app(_config(tmp_path, SECRET_KEY="una-clave"))
    cliente = app.test_client()
    assert cliente.get("/no-existe").status_code == 404
    assert cliente.get("/static/x.css").status_code == 404
    assert cliente.get("/login").status_code == 200
    assert cliente.get("/paciente").status_code == 302


# --- T-02d #2: aviso al arrancar sin SECRET_KEY ----------------------------------


def _avisos_de_clave(caplog):
    return [r for r in caplog.records if MENSAJE_SIN_SECRET_KEY in r.getMessage()]


def test_aviso_al_cargar_la_app_sin_secret_key_como_servidor(tmp_path, caplog):
    """Sin contexto de click (gunicorn, etc.): se carga para servir, así que avisa."""
    with caplog.at_level(logging.WARNING):
        create_app(_config(tmp_path))
    (registro,) = _avisos_de_clave(caplog)
    assert registro.levelno == logging.WARNING


def test_aviso_con_flask_run_y_una_sola_vez(tmp_path, caplog):
    with click.Context(click.Command("run")), caplog.at_level(logging.WARNING):
        create_app(_config(tmp_path))
    assert len(_avisos_de_clave(caplog)) == 1


@pytest.mark.parametrize("comando", ["init-db", "create-professional", "flask", "routes"])
def test_sin_aviso_en_los_demas_comandos(tmp_path, caplog, comando):
    with click.Context(click.Command(comando)), caplog.at_level(logging.WARNING):
        create_app(_config(tmp_path))
    assert _avisos_de_clave(caplog) == []


@pytest.mark.parametrize("extra", [{"SECRET_KEY": "clave"}, {"TESTING": True}, {"DEBUG": True}])
def test_sin_aviso_si_hay_clave_testing_o_debug(tmp_path, caplog, extra):
    with click.Context(click.Command("run")), caplog.at_level(logging.WARNING):
        create_app(_config(tmp_path, **extra))
    assert _avisos_de_clave(caplog) == []


def _entorno_sin_clave(tmp_path):
    entorno = {k: v for k, v in os.environ.items() if k not in ("SECRET_KEY", "FLASK_DEBUG")}
    entorno["DATABASE"] = str(tmp_path / "cli.db")
    return entorno


def test_init_db_real_no_hace_ruido_sin_secret_key(tmp_path):
    r = subprocess.run(
        [sys.executable, "-m", "flask", "--app", "app", "init-db"],
        env=_entorno_sin_clave(tmp_path), capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert r.stderr == "" and "SECRET_KEY" not in r.stdout


def test_flask_run_real_avisa_al_arrancar_sin_secret_key(tmp_path):
    proceso = subprocess.Popen(
        [sys.executable, "-m", "flask", "--app", "app", "run", "--port", "0"],
        env=_entorno_sin_clave(tmp_path), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        # `--port 0` no sirve en todos los sistemas; basta con que arranque o falle
        # tras haber cargado la app, que es cuando se emite el aviso.
        try:
            _, error = proceso.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            proceso.terminate()
            _, error = proceso.communicate(timeout=10)
    finally:
        if proceso.poll() is None:
            proceso.kill()
    assert "Falta la variable de entorno SECRET_KEY" in error
