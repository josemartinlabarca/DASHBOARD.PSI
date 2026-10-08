import pytest

from app import create_app


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
