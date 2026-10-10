"""Cabeceras de seguridad en toda respuesta (T-14a, D-046): CSP, nosniff, anti-frame, Referrer-Policy."""
import re
from pathlib import Path

import pytest

from app import seguridad
from app.db import init_db
from tests.test_limite import intentar
from tests.test_login import CLAVE, crear, iniciar
from tests.test_seguridad import extraer_token

RAIZ = Path(__file__).resolve().parent.parent
ESPERADAS = {
    "Content-Security-Policy": seguridad.POLITICA_CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


@pytest.fixture(autouse=True)
def base_inicializada(app):
    with app.app_context():
        init_db()


def comprobar(respuesta):
    for nombre, valor in ESPERADAS.items():
        assert respuesta.headers.get(nombre) == valor, (nombre, respuesta.status_code)


def test_los_valores_exactos():
    assert ESPERADAS["Content-Security-Policy"] == (
        "default-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'"
    )


def directivas(csp):
    return {d.split()[0]: d.split()[1:] for d in csp.split(";") if d.strip()}


def test_la_csp_es_estricta():
    d = directivas(seguridad.POLITICA_CSP)
    assert d["default-src"] == ["'self'"]
    assert d["frame-ancestors"] == ["'none'"]
    assert d["base-uri"] == ["'none'"] and d["object-src"] == ["'none'"] and d["form-action"] == ["'self'"]
    todo = seguridad.POLITICA_CSP
    for prohibido in ("unsafe-inline", "unsafe-eval", "*", "data:", "http:", "https:", "blob:"):
        assert prohibido not in todo
    assert "script-src" not in d and "style-src" not in d  # heredan de default-src 'self'


@pytest.mark.parametrize(
    "ruta", ["/", "/login", "/registro", "/static/style.css", "/static/favicon.svg"]
)
def test_paginas_y_estaticos_200(client, ruta):
    r = client.get(ruta)
    assert r.status_code == 200
    comprobar(r)


def test_head_y_options_tambien(client):
    for metodo in ("head", "options"):
        comprobar(getattr(client, metodo)("/login"))
        comprobar(getattr(client, metodo)("/static/style.css"))


def test_un_estatico_304_condicional_tambien(client):
    primera = client.get("/static/style.css")
    etag = primera.headers["ETag"]
    r = client.get("/static/style.css", headers={"If-None-Match": etag})
    assert r.status_code == 304
    comprobar(r)


@pytest.mark.parametrize("ruta", ["/no-existe", "/static/no-existe.css", "/static/", "/horas/1/x"])
def test_404(client, ruta):
    r = client.get(ruta)
    assert r.status_code == 404
    comprobar(r)


def test_400_de_csrf(client):
    r = client.post("/registro", data={})
    assert r.status_code == 400
    comprobar(r)


def test_405(client):
    r = client.get("/logout")
    assert r.status_code == 405
    comprobar(r)


def test_413(client):
    r = client.post("/registro", data={"nombre": "x" * 40000})
    assert r.status_code == 413
    comprobar(r)


def test_403_de_rol(app, client):
    crear(app)
    iniciar(client)
    r = client.get("/profesional")
    assert r.status_code == 403
    comprobar(r)


def test_redirecciones(client):
    r = client.get("/paciente")
    assert r.status_code == 302
    comprobar(r)


def test_login_correcto_y_paneles(app, client):
    crear(app)
    r = iniciar(client)
    assert r.status_code == 302
    comprobar(r)
    for ruta in ("/paciente", "/paciente/horas"):
        r = client.get(ruta)
        assert r.status_code == 200
        comprobar(r)


def test_panel_del_profesional_y_formulario(app, client):
    crear(app, email="pro@example.cl", rol="profesional")
    iniciar(client, "pro@example.cl")
    for ruta in ("/profesional", "/profesional/horas/nueva"):
        r = client.get(ruta)
        assert r.status_code == 200
        comprobar(r)


def test_429_de_bloqueo(app, client):
    crear(app)
    for _ in range(5):
        intentar(client)
    r = intentar(client)
    assert r.status_code == 429
    comprobar(r)


def test_500_sin_pagina_propia(app, client):
    app.config["PROPAGATE_EXCEPTIONS"] = False

    @app.route("/rota")
    def rota():
        raise RuntimeError("fallo interno")

    r = client.get("/rota")
    assert r.status_code == 500
    comprobar(r)


def test_500_por_falta_de_secret_key(tmp_path, monkeypatch):
    from app import create_app

    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    r = create_app({"DATABASE": str(tmp_path / "s.db")}).test_client().get("/")
    assert r.status_code == 500
    comprobar(r)


def test_una_ruta_nueva_las_recibe_sin_hacer_nada(app, client):
    @app.route("/ruta-futura")
    def ruta_futura():
        return "ok"

    r = client.get("/ruta-futura")
    comprobar(r)


def test_una_vista_no_puede_relajar_las_cabeceras(app, client):
    @app.route("/relajada")
    def relajada():
        return "ok", 200, {
            "Content-Security-Policy": "default-src *",
            "X-Frame-Options": "ALLOWALL",
            "Referrer-Policy": "unsafe-url",
        }

    comprobar(client.get("/relajada"))


def test_no_store_sigue_en_lo_dinamico_y_no_en_los_estaticos_200(client):
    """D-024 intacto: las cabeceras nuevas no tocan Cache-Control."""
    assert client.get("/login").headers["Cache-Control"] == "no-store"
    assert client.get("/no-existe").headers["Cache-Control"] == "no-store"
    estatico = client.get("/static/style.css")
    assert "no-store" not in estatico.headers.get("Cache-Control", "")
    assert client.get("/static/no-existe.css").headers["Cache-Control"] == "no-store"


# ---- Lo que la CSP supone de las plantillas y la hoja: se vigila de forma estática.

PLANTILLAS = sorted((RAIZ / "app" / "templates").glob("*.html"))


@pytest.mark.parametrize("plantilla", PLANTILLAS, ids=lambda p: p.name)
def test_las_plantillas_no_usan_nada_que_la_csp_bloquee(plantilla):
    texto = plantilla.read_text(encoding="utf-8")
    assert not re.search(r"<script|<style|<iframe|<object|<embed|<base\b", texto, re.I)
    assert not re.search(r"\sstyle\s*=", texto, re.I)  # atributos style en línea
    assert not re.search(r"\son[a-z]+\s*=", texto, re.I)  # onclick, onsubmit...
    assert not re.search(r"javascript:|data:|https?://", texto, re.I)


def test_la_hoja_no_importa_ni_carga_nada_externo():
    texto = (RAIZ / "app" / "static" / "style.css").read_text(encoding="utf-8")
    assert not re.search(r"@import|@font-face|url\(", texto, re.I)
    assert not re.search(r"https?://", texto)


def test_el_favicon_es_un_archivo_propio_y_no_un_data_uri():
    base = (RAIZ / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    assert "url_for('static', filename='favicon.svg')" in base
    svg = (RAIZ / "app" / "static" / "favicon.svg").read_text(encoding="utf-8")
    assert "<script" not in svg and "href=" not in svg.replace("xmlns=", "")


def test_el_token_csrf_ya_no_se_acepta_por_cabecera(app, client):
    """D-046: sin JavaScript ni clientes que lo envíen, el único canal es el campo del formulario."""
    token = extraer_token(client.get("/registro").text)
    datos = {"nombre": "Ana", "email": "ana@example.cl", "password": CLAVE}
    assert client.post("/registro", data=datos, headers={"X-CSRFToken": token}).status_code == 400
    assert client.post("/registro", data={**datos, "csrf_token": token}).status_code == 302
    assert not hasattr(seguridad, "CABECERA")
