import pytest
from flask import Blueprint

from app import auth
from app.db import init_db
from tests.test_login import CLAVE, crear, iniciar, sesion
from tests.test_seguridad import extraer_token


@pytest.fixture(autouse=True)
def base_inicializada(app):
    with app.app_context():
        init_db()


@pytest.fixture
def paciente(app, client):
    crear(app, email="ana@example.cl", rol="paciente", nombre="Ana Pérez")
    iniciar(client, "ana@example.cl")
    return client


@pytest.fixture
def profesional(app):
    crear(app, email="pro@example.cl", rol="profesional", nombre="Dr. Pro")
    client = app.test_client()
    iniciar(client, "pro@example.cl")
    return client


def test_paciente_ve_su_panel_y_no_el_del_profesional(paciente):
    r = paciente.get("/paciente")
    assert r.status_code == 200 and "Ana Pérez" in r.text
    r = paciente.get("/profesional")
    assert r.status_code == 403
    assert "No tienes permiso" in r.text
    assert "Forbidden" not in r.text  # mensaje en español, no el de Werkzeug


def test_profesional_ve_su_panel_y_no_el_del_paciente(profesional):
    r = profesional.get("/profesional")
    assert r.status_code == 200 and "Dr. Pro" in r.text
    r = profesional.get("/paciente")
    assert r.status_code == 403
    assert "No tienes permiso" in r.text


@pytest.mark.parametrize("ruta", ["/paciente", "/profesional"])
def test_sin_sesion_se_redirige_al_login(client, ruta):
    r = client.get(ruta)
    assert (r.status_code, r.headers["Location"]) == (302, "/login")


def test_el_nombre_del_panel_va_escapado(app, client):
    crear(app, nombre="<script>alert(1)</script>")
    iniciar(client)
    r = client.get("/paciente")
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;" in r.text


def test_el_panel_trae_formulario_de_logout_con_token(paciente):
    html = paciente.get("/paciente").text
    assert 'action="/logout"' in html
    assert len(extraer_token(html)) == 64


def test_flujo_completo_registro_login_panel_logout(client):
    token = extraer_token(client.get("/registro").text)
    r = client.post(
        "/registro",
        data={"nombre": "Luz", "email": "Luz@Example.cl", "password": CLAVE, "csrf_token": token},
    )
    assert r.status_code == 302
    assert iniciar(client, "luz@example.cl").headers["Location"] == "/paciente"
    assert client.get("/paciente").status_code == 200
    assert client.get("/profesional").status_code == 403
    client.post("/logout", data={"csrf_token": sesion(client)["csrf_token"]})
    assert client.get("/paciente").status_code == 302


def test_decorador_en_una_ruta_nueva_exige_rol_y_conserva_el_nombre(app):
    """Un decorador aplicado a otra vista funciona igual (y no pisa su nombre)."""
    bp = Blueprint("prueba", __name__)

    @bp.route("/solo-pro")
    @auth.solo_profesional
    def solo_pro():
        return "ok"

    assert solo_pro.__name__ == "solo_pro"
    app.register_blueprint(bp)
    crear(app)
    cliente = app.test_client()
    assert cliente.get("/solo-pro").status_code == 302
    iniciar(cliente)
    assert cliente.get("/solo-pro").status_code == 403
