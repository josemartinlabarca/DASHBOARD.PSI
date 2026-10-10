import logging
import os
import subprocess
import sys
import threading
import time

import click
import pytest

from app import (
    MENSAJE_DEBUG_EN_SERVIDOR,
    MENSAJE_DEBUG_SIN_CLAVE,
    MENSAJE_SIN_SECRET_KEY,
    SECRET_KEY_DESARROLLO,
    create_app,
)


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


def _comando(nombre):
    return click.Context(click.Command(nombre), info_name=nombre)


@pytest.mark.parametrize("comando", ["run", "init-db", "create-professional", "send-reminders"])
def test_flask_debug_funciona_sin_secret_key_bajo_comandos_de_flask(tmp_path, monkeypatch, comando):
    """`flask run --debug` en local (D-043) y los comandos de mantenimiento (D-008) siguen igual."""
    monkeypatch.setenv("FLASK_DEBUG", "1")
    with _comando(comando):
        app = create_app(_config(tmp_path))
    assert app.debug
    assert app.config["SECRET_KEY"] == SECRET_KEY_DESARROLLO


@pytest.mark.parametrize("valor", ["1", "true", "yes", "on", "off", "OFF", "x"])
@pytest.mark.parametrize("clave", [None, "", "   "])
def test_r01_servidor_wsgi_con_debug_y_sin_secret_key_se_niega_a_servir(tmp_path, monkeypatch, valor, clave):
    """R-01: sin contexto de click (gunicorn, uWSGI) la clave pública de desarrollo no se usa.

    `off` cuenta como debug fuera de `flask run`; antes la app servía con la clave pública y
    una cookie forjada daba acceso al profesional.
    """
    monkeypatch.setenv("FLASK_DEBUG", valor)
    if clave is not None:
        monkeypatch.setenv("SECRET_KEY", clave)
    with pytest.raises(RuntimeError) as error:
        create_app(_config(tmp_path))
    mensaje = str(error.value)
    assert mensaje == MENSAJE_DEBUG_SIN_CLAVE
    assert "SECRET_KEY" in mensaje and "FLASK_DEBUG" in mensaje and "off" in mensaje


def test_r01_tambien_con_debug_pedido_por_configuracion(tmp_path):
    with pytest.raises(RuntimeError, match="Me niego a servir"):
        create_app(_config(tmp_path, DEBUG=True))


@pytest.mark.parametrize("valor", ["0", "false", "no"])
def test_r01_con_debug_apagado_sigue_la_regla_de_siempre(tmp_path, monkeypatch, valor):
    """Sin debug la app se crea (D-008) y falla cerrada en cada petición."""
    monkeypatch.setenv("FLASK_DEBUG", valor)
    app = create_app(_config(tmp_path))
    assert not app.debug and app.config["SECRET_KEY"] is None


def test_r01_con_clave_propia_y_debug_fuera_de_flask_run_solo_avisa_y_sin_mentir(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("FLASK_DEBUG", "off")
    monkeypatch.setenv("SECRET_KEY", "una-clave-propia-larga")
    with caplog.at_level(logging.WARNING):
        app = create_app(_config(tmp_path))
    assert app.debug and app.config["SECRET_KEY"] == "una-clave-propia-larga"
    avisos = [r.getMessage() for r in caplog.records if r.getMessage() == MENSAJE_DEBUG_EN_SERVIDOR]
    assert len(avisos) == 1
    # Con clave propia la clave NO es pública: el aviso no debe decirlo.
    assert "públic" not in avisos[0] and "falsific" not in avisos[0]


def test_r01_la_cookie_forjada_con_la_clave_publica_ya_no_entra(tmp_path, monkeypatch):
    """Reproducción de R-01 como prueba: con la clave pública no hay app que sirva."""
    monkeypatch.setenv("FLASK_DEBUG", "off")
    with pytest.raises(RuntimeError):
        create_app(_config(tmp_path))
    # Y bajo `flask run` en local sí se crea, pero con otra clave la cookie forjada no vale.
    with _comando("run"):
        app = create_app(_config(tmp_path, SECRET_KEY="clave-real-larga"))
    from flask.sessions import SecureCookieSessionInterface

    forjada = SecureCookieSessionInterface().get_signing_serializer(
        create_app(_config(tmp_path, TESTING=True))  # clave pública de desarrollo
    ).dumps({"usuario_id": 1, "sesion_version": 0})
    cliente = app.test_client()
    cliente.set_cookie("session", forjada)
    assert cliente.get("/profesional").status_code in (302, 403)


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
        # El aviso sale al cargar la app, antes de servir. En vez de esperar 3 s fijos
        # a que el proceso termine, se lee su stderr hasta ver el aviso (máx. 15 s) y
        # entonces se lo detiene (T-08b).
        leido = []
        hilo = threading.Thread(
            target=lambda: [leido.append(linea) for linea in proceso.stderr], daemon=True
        )
        hilo.start()
        limite = time.monotonic() + 15
        while time.monotonic() < limite and proceso.poll() is None:
            if "Falta la variable de entorno SECRET_KEY" in "".join(leido):
                break
            time.sleep(0.02)
        if proceso.poll() is None:
            proceso.terminate()
        proceso.wait(timeout=10)
        hilo.join(timeout=5)
        error = "".join(leido)
    finally:
        if proceso.poll() is None:
            proceso.kill()
    assert "Falta la variable de entorno SECRET_KEY" in error
