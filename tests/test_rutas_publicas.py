"""Lista blanca de rutas públicas (backlog T-04 R-12): toda ruta nueva exige
sesión salvo las declaradas aquí. Si añades una ruta pública, decláralo a propósito."""
import re

import pytest

from app.db import init_db
from tests.test_seguridad import extraer_token

# endpoint -> motivo. Todo lo demás debe mandar a /login sin sesión.
PUBLICAS = {
    "inicio": "página de inicio",
    "auth.registro": "registro de pacientes (US-1)",
    "auth.login": "inicio de sesión (US-2)",
    "static": "archivos estáticos",
}


@pytest.fixture(autouse=True)
def base_inicializada(app):
    with app.app_context():
        init_db()


def ruta_de_ejemplo(regla):
    """Rellena cualquier parámetro de la ruta con un valor cualquiera (no importa si existe)."""
    return re.sub(r"<(?:\w+(?:\([^)]*\))?:)?\w+>", "1", regla.rule)


def endpoints_accesibles_sin_sesion(app):
    """Endpoints que, con un cliente sin sesión y un token CSRF válido, no mandan a /login."""
    client = app.test_client()
    token = extraer_token(client.get("/login").text)
    abiertos = set()
    for regla in app.url_map.iter_rules():
        for metodo in sorted(regla.methods - {"HEAD", "OPTIONS"}):
            datos = {"csrf_token": token} if metodo != "GET" else None
            r = client.open(ruta_de_ejemplo(regla), method=metodo, data=datos)
            if not (r.status_code == 302 and r.headers["Location"] == "/login"):
                abiertos.add(regla.endpoint)
    return abiertos


def test_solo_las_rutas_declaradas_son_publicas(app):
    assert endpoints_accesibles_sin_sesion(app) == set(PUBLICAS)


def test_las_rutas_privadas_conocidas_estan_en_el_mapa(app):
    endpoints = {r.endpoint for r in app.url_map.iter_rules()}
    assert {
        "auth.logout", "paciente.dashboard", "paciente.horas_libres", "paciente.reservar", "paciente.cancelar",
        "profesional.dashboard",
        "profesional.nueva_hora", "profesional.eliminar_hora",
    } <= endpoints


def test_una_ruta_nueva_sin_exigir_sesion_se_detecta(app):
    @app.route("/ruta-olvidada")
    def olvidada():
        return "datos privados"

    assert endpoints_accesibles_sin_sesion(app) - set(PUBLICAS) == {"olvidada"}
