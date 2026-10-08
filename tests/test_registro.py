import re
import sqlite3
from datetime import datetime

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

from app import auth
from app.db import init_db
from tests.test_seguridad import extraer_token

VALIDO = {"nombre": "Ana Pérez", "email": "ana@example.cl", "password": "clave-segura-1"}


@pytest.fixture(autouse=True)
def base_inicializada(app):
    with app.app_context():
        init_db()


def usuarios(app):
    con = sqlite3.connect(app.config["DATABASE"])
    con.row_factory = sqlite3.Row
    try:
        return con.execute("SELECT * FROM usuarios ORDER BY id").fetchall()
    finally:
        con.close()


def registrar(client, datos=None, token=True, **extra):
    """Envía el formulario con un token real leído del HTML (no se desactiva CSRF)."""
    datos = dict(VALIDO if datos is None else datos, **extra)
    if token is True:
        token = extraer_token(client.get("/registro").text)
    if token:
        datos["csrf_token"] = token
    return client.post("/registro", data=datos)


def test_get_muestra_formulario_con_token(client):
    r = client.get("/registro")
    assert r.status_code == 200
    for campo in ('name="nombre"', 'name="email"', 'name="password"'):
        assert campo in r.text
    assert "confirm" not in r.text.lower()
    assert len(extraer_token(r.text)) == 64


def test_registro_valido_guarda_usuario(app, client):
    r = registrar(client)
    assert r.status_code == 302
    assert r.headers["Location"] == "/"
    (u,) = usuarios(app)
    assert u["nombre"] == "Ana Pérez"
    assert u["email"] == "ana@example.cl"
    assert u["rol"] == "paciente"


def test_registro_exitoso_muestra_mensaje_en_inicio(client):
    r = registrar(client)
    r = client.get(r.headers["Location"])
    assert "Tu cuenta fue creada correctamente." in r.text


def test_password_guardada_con_hash(app, client):
    registrar(client)
    (u,) = usuarios(app)
    assert u["password_hash"] != VALIDO["password"]
    assert VALIDO["password"] not in u["password_hash"]
    assert check_password_hash(u["password_hash"], VALIDO["password"])
    assert not check_password_hash(u["password_hash"], "otra-clave-123")


def test_creado_en_iso_con_zona_de_chile(app, client):
    registrar(client)
    (u,) = usuarios(app)
    creado = datetime.fromisoformat(u["creado_en"])
    assert creado.utcoffset() is not None
    assert re.search(r"[+-]0[34]:00$", u["creado_en"])  # Chile: -03:00 o -04:00


def test_rol_siempre_paciente_aunque_se_envie_otro(app, client):
    registrar(client, rol="profesional")
    registrar(client, email="b@example.cl", rol="profesional")
    filas = usuarios(app)
    assert len(filas) == 2
    assert {u["rol"] for u in filas} == {"paciente"}


def test_nombre_y_correo_se_normalizan(app, client):
    registrar(client, nombre="  Ana  ", email="  ANA@Example.CL ")
    (u,) = usuarios(app)
    assert u["nombre"] == "Ana"
    assert u["email"] == "ana@example.cl"


@pytest.mark.parametrize("variante", ["ana@example.cl", "ANA@EXAMPLE.CL", "  Ana@Example.cl  "])
def test_correo_duplicado_rechazado_sin_500(app, client, variante):
    assert registrar(client).status_code == 302
    r = registrar(client, email=variante, nombre="Otra")
    assert r.status_code == 200
    assert "No pudimos registrarte con ese correo" in r.text
    assert len(usuarios(app)) == 1


def test_correo_duplicado_lo_detecta_la_restriccion_unique(app, client, monkeypatch):
    """Sin consulta previa: el INSERT se ejecuta y solo UNIQUE da el aviso.

    Se registran las sentencias SQL del segundo intento: no debe haber ningún
    SELECT (una consulta previa tendría carrera) y sí el INSERT rechazado.
    """
    registrar(client)
    sentencias = []
    get_db_real = auth.get_db

    def get_db_con_traza():
        con = get_db_real()
        con.set_trace_callback(sentencias.append)
        return con

    monkeypatch.setattr(auth, "get_db", get_db_con_traza)
    r = registrar(client, nombre="Intrusa", password="otra-clave-123")
    assert r.status_code == 200
    assert "No pudimos registrarte con ese correo" in r.text
    assert "Traceback" not in r.text
    assert sentencias, "la traza no registró ninguna sentencia"
    assert not [s for s in sentencias if s.lstrip().upper().startswith("SELECT")]
    assert [s for s in sentencias if s.lstrip().upper().startswith("INSERT INTO USUARIOS")]
    (u,) = usuarios(app)
    assert u["nombre"] == "Ana Pérez"


@pytest.mark.parametrize(
    "cambio, texto",
    [
        ({"nombre": ""}, "Escribe tu nombre."),
        ({"nombre": "   "}, "Escribe tu nombre."),
        ({"nombre": "x" * 101}, "no puede superar"),
        ({"email": ""}, "Escribe tu correo."),
        ({"email": "sin-arroba"}, "correo válido"),
        ({"email": "a@b"}, "correo válido"),
        ({"email": "a b@c.cl"}, "correo válido"),
        ({"email": "a@" + "b" * 250 + ".cl"}, "correo válido"),
        ({"password": ""}, "al menos 8"),
        ({"password": "corta12"}, "al menos 8"),
        ({"password": "x" * 129}, "no puede superar"),
    ],
)
def test_datos_invalidos_rechazados_con_mensaje(app, client, cambio, texto):
    r = registrar(client, **cambio)
    assert r.status_code == 200
    assert texto in r.text
    assert usuarios(app) == []


def test_campos_ausentes_rechazados(app, client):
    token = extraer_token(client.get("/registro").text)
    r = client.post("/registro", data={"csrf_token": token})
    assert r.status_code == 200
    assert "Escribe tu nombre." in r.text
    assert usuarios(app) == []


def test_error_conserva_nombre_y_correo_pero_nunca_la_contrasena(client):
    r = registrar(client, password="corta")
    assert 'value="Ana Pérez"' in r.text
    assert 'value="ana@example.cl"' in r.text
    assert "corta" not in r.text.replace("al menos 8", "")
    assert 'name="password"' in r.text
    assert re.search(r'name="password"[^>]*value=', r.text) is None


def test_password_de_8_caracteres_es_valida_y_no_se_recorta(app, client):
    registrar(client, password="  abcd  ")
    (u,) = usuarios(app)
    assert check_password_hash(u["password_hash"], "  abcd  ")


def test_post_sin_token_da_400_y_no_crea_usuario(app, client):
    r = registrar(client, token=False)
    assert r.status_code == 400
    assert usuarios(app) == []


def test_post_con_token_invalido_da_400_y_no_crea_usuario(app, client):
    client.get("/registro")
    r = registrar(client, token="0" * 64)
    assert r.status_code == 400
    assert usuarios(app) == []


def test_nombre_con_html_se_guarda_tal_cual_y_se_escapa(app, client):
    xss = "<script>alert(1)</script>"
    r = registrar(client, nombre=xss, email="malo")  # error: se vuelve a mostrar
    assert xss not in r.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in r.text
    registrar(client, nombre=xss)
    (u,) = usuarios(app)
    assert u["nombre"] == xss


def test_comillas_y_sql_en_campos_no_rompen_nada(app, client):
    sql = "'; DROP TABLE usuarios; --"
    r = registrar(client, nombre=sql, email="o'brien@example.cl")
    assert r.status_code == 302
    r = registrar(client, nombre="x", email=sql + "@e.cl")
    assert r.status_code in (200, 302)
    filas = usuarios(app)  # la tabla sigue existiendo
    assert filas[0]["nombre"] == sql
    assert filas[0]["email"] == "o'brien@example.cl"


def test_inicio_enlaza_al_registro(client):
    assert 'href="/registro"' in client.get("/").text


def test_correo_con_comillas_y_html_se_escapa_en_el_atributo_value(client):
    peligroso = "a\"b'c\"><script>alert(1)</script>"
    r = registrar(client, email=peligroso)  # formato inválido: se vuelve a mostrar
    assert r.status_code == 200
    assert "<script>alert(1)</script>" not in r.text
    assert '"><script>' not in r.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in r.text
    assert 'value="a&#34;b&#39;c&#34;&gt;' in r.text


def test_hash_usa_scrypt_con_al_menos_los_parametros_por_defecto(app, client):
    """Los mínimos se leen de lo que la versión instalada de werkzeug genera."""
    registrar(client)
    (u,) = usuarios(app)

    def parametros(hash_):
        metodo, n, r, p = hash_.split("$")[0].split(":")
        return metodo, int(n), int(r), int(p)

    referencia = parametros(generate_password_hash("x"))
    assert referencia[0] == "scrypt", "werkzeug ya no usa scrypt por defecto: revisar D-010"
    metodo, n, r, p = parametros(u["password_hash"])
    assert metodo == "scrypt"
    assert n >= referencia[1] and r >= referencia[2] and p >= referencia[3]


def test_correo_en_ancho_completo_se_guarda_normalizado(app, client):
    registrar(client, email="\uff21na@Example.cl")
    (u,) = usuarios(app)
    assert u["email"] == "ana@example.cl"


def test_variante_unicode_del_correo_cuenta_como_duplicado(app, client):
    assert registrar(client).status_code == 302
    r = registrar(client, email="\uff41na@EXAMPLE.cl", nombre="Otra")
    assert r.status_code == 200
    assert "No pudimos registrarte con ese correo" in r.text
    assert len(usuarios(app)) == 1


def test_sz_y_ss_son_el_mismo_correo(app, client):
    assert registrar(client, email="stra\u00dfe@example.cl").status_code == 302
    r = registrar(client, email="strasse@example.cl")
    assert "No pudimos registrarte con ese correo" in r.text
    assert [u["email"] for u in usuarios(app)] == ["strasse@example.cl"]


@pytest.mark.parametrize("email", ["ana\u200b@example.cl", "ana\x00@example.cl", "an a@example.cl"])
def test_correo_con_invisibles_control_o_espacios_se_rechaza(app, client, email):
    r = registrar(client, email=email)
    assert r.status_code == 200
    assert "correo válido" in r.text
    assert usuarios(app) == []


def test_peticion_mayor_a_16_kb_da_413_y_no_crea_usuario(app, client):
    assert app.config["MAX_CONTENT_LENGTH"] == 16 * 1024
    # Con token válido y sin él: el 413 ocurre al leer el cuerpo (request.form),
    # que ya hace el before_request del CSRF, antes que la vista.
    token = extraer_token(client.get("/registro").text)
    grande = dict(VALIDO, nombre="x" * (16 * 1024 + 1), csrf_token=token)
    assert client.post("/registro", data=grande).status_code == 413
    assert client.post("/registro", data={"nombre": "x" * 20000}).status_code == 413
    assert usuarios(app) == []


def test_peticion_justo_bajo_el_limite_sigue_funcionando(app, client):
    assert registrar(client).status_code == 302
    assert len(usuarios(app)) == 1
