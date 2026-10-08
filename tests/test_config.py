import pytest

from app import create_app


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("FLASK_DEBUG", raising=False)


def _config(tmp_path, **extra):
    return {"DATABASE": str(tmp_path / "test.db"), **extra}


def test_sin_secret_key_fuera_de_debug_falla(tmp_path):
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(_config(tmp_path))


def test_secret_key_vacia_fuera_de_debug_falla(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(_config(tmp_path))


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
