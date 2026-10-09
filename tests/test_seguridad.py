import re

import pytest

from app import create_app
from app.seguridad import generar_token


def extraer_token(html):
    m = re.search(r'name="csrf_token" value="([0-9a-f]+)"', html)
    assert m, "el formulario no trae token CSRF"
    return m.group(1)


def test_generar_token_es_estable_dentro_de_la_sesion(app):
    with app.test_request_context("/"):
        assert generar_token() == generar_token()
        assert len(generar_token()) == 64


@pytest.mark.token_aleatorio
def test_tokens_distintos_entre_sesiones(app):
    t1 = extraer_token(app.test_client().get("/registro").text)
    t2 = extraer_token(app.test_client().get("/registro").text)
    assert t1 != t2


def test_post_a_cualquier_ruta_exige_token(app):
    """La verificación es global: también una ruta futura sin código CSRF propio."""

    @app.route("/ruta-futura", methods=["POST"])
    def ruta_futura():
        return "ok"

    client = app.test_client()
    assert client.post("/ruta-futura").status_code == 400
    token = extraer_token(client.get("/registro").text)
    assert client.post("/ruta-futura", data={"csrf_token": token}).status_code == 200
    assert (
        client.post("/ruta-futura", headers={"X-CSRFToken": token}).status_code == 200
    )


@pytest.mark.parametrize("metodo", ["put", "patch", "delete"])
def test_put_patch_delete_exigen_token(app, metodo):
    """CSRF vale para todo método que modifica estado, no solo POST."""

    @app.route("/recurso-futuro", methods=["PUT", "PATCH", "DELETE"])
    def recurso_futuro():
        return "ok"

    client = app.test_client()
    token = extraer_token(client.get("/registro").text)
    enviar = getattr(client, metodo)
    assert enviar("/recurso-futuro").status_code == 400
    assert enviar("/recurso-futuro", headers={"X-CSRFToken": "0" * 64}).status_code == 400
    assert enviar("/recurso-futuro", headers={"X-CSRFToken": token}).status_code == 200
    assert enviar("/recurso-futuro", data={"csrf_token": token}).status_code == 200


def test_get_no_exige_token(client):
    assert client.get("/").status_code == 200


@pytest.mark.token_aleatorio
def test_token_vacio_o_de_otra_sesion_rechazado(app):
    otro = extraer_token(app.test_client().get("/registro").text)
    client = app.test_client()
    client.get("/registro")
    assert client.post("/registro", data={"csrf_token": ""}).status_code == 400
    assert client.post("/registro", data={"csrf_token": otro}).status_code == 400


def test_mensaje_de_error_csrf_es_claro(client):
    r = client.post("/registro", data={})
    assert r.status_code == 400
    assert "token de seguridad" in r.text


def test_exigencia_de_secret_key_corre_antes_que_csrf(tmp_path, monkeypatch, caplog):
    """D-008 primero: sin clave el error es el de SECRET_KEY, no un 400 de CSRF."""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    app = create_app({"DATABASE": str(tmp_path / "t.db")})
    r = app.test_client().post("/registro", data={})
    assert r.status_code == 500
    assert "SECRET_KEY" in caplog.text


def test_post_a_ruta_inexistente_da_400_no_404(client):
    """El CSRF corre antes del enrutamiento (D-009)."""
    assert client.post("/no-existe").status_code == 400
    assert client.get("/no-existe").status_code == 404
