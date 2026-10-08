import re
import sqlite3

import pytest
from werkzeug.security import check_password_hash

from app import auth
from app.db import init_db
from tests.test_seguridad import extraer_token

CLAVE = "clave-segura-1"


@pytest.fixture(autouse=True)
def base_inicializada(app):
    with app.app_context():
        init_db()


def crear(app, email="ana@example.cl", password=CLAVE, rol="paciente", nombre="Ana Pérez"):
    with app.app_context():
        auth.crear_usuario(auth.get_db(), nombre, email, password, rol)


def iniciar(client, email="ana@example.cl", password=CLAVE, **extra):
    """Envía el formulario con un token real leído del HTML."""
    token = extraer_token(client.get("/login").text)
    datos = {"email": email, "password": password, "csrf_token": token}
    return client.post("/login", data=datos, **extra)


def sesion(client):
    with client.session_transaction() as s:
        return dict(s)


def sin_token(html):
    return re.sub(r'name="csrf_token" value="[0-9a-f]+"', 'name="csrf_token" value="X"', html)


# ----------------------------------------------------------------- formulario


def test_get_muestra_formulario_con_token(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert 'name="email"' in r.text and 'name="password"' in r.text
    assert len(extraer_token(r.text)) == 64


@pytest.mark.parametrize("ruta", ["/login", "/registro"])
def test_campo_de_correo_no_usa_type_email_bloqueante(client, ruta):
    """R-04: type="email" puede rechazar `señor@...` en algunos navegadores."""
    html = client.get(ruta).text
    campo = re.search(r'<input[^>]*name="email"[^>]*>', html).group(0)
    assert 'type="text"' in campo
    assert 'inputmode="email"' in campo
    assert 'autocomplete="email"' in campo
    assert 'type="email"' not in html


def test_campo_de_contrasena_del_login(client):
    campo = re.search(r'<input[^>]*name="password"[^>]*>', client.get("/login").text).group(0)
    assert 'type="password"' in campo
    assert 'autocomplete="current-password"' in campo


# ----------------------------------------------------------- login correcto


@pytest.mark.parametrize(
    "rol,destino", [("paciente", "/paciente"), ("profesional", "/profesional")]
)
def test_login_correcto_redirige_al_panel_de_su_rol(app, client, rol, destino):
    crear(app, rol=rol)
    r = iniciar(client)
    assert r.status_code == 302
    assert r.headers["Location"] == destino
    assert client.get(destino).status_code == 200


@pytest.mark.parametrize(
    "escrito",
    ["ANA@EXAMPLE.CL", "  ana@example.cl  ", "ａｎａ@example.cl", "Ana@Example.CL"],
)
def test_login_normaliza_el_correo_como_el_registro(app, client, escrito):
    crear(app)
    assert iniciar(client, email=escrito).status_code == 302


def test_login_con_correo_con_enie(app, client):
    crear(app, email="señor@example.cl")
    assert iniciar(client, email="SEÑOR@example.cl").status_code == 302
    assert iniciar(client, email="señor@example.cl").status_code == 302  # n + U+0303


def test_contrasena_de_128_caracteres_funciona_y_129_no(app, client):
    larga = "a" * 128
    crear(app, password=larga)
    assert iniciar(client, password=larga).status_code == 302
    client2 = app.test_client()
    r = iniciar(client2, password=larga + "a")
    assert r.status_code == 200
    assert "usuario_id" not in sesion(client2)


def test_la_contrasena_no_se_recorta(app, client):
    crear(app, password="  con espacios  ")
    assert iniciar(client, password="con espacios").status_code == 200
    assert iniciar(client, password="  con espacios  ").status_code == 302


def test_el_rol_se_lee_de_la_base_en_cada_peticion(app, client):
    crear(app)
    iniciar(client)
    assert client.get("/paciente").status_code == 200
    con = sqlite3.connect(app.config["DATABASE"])
    con.execute("UPDATE usuarios SET rol = 'profesional'")
    con.commit()
    con.close()
    assert client.get("/paciente").status_code == 403
    assert client.get("/profesional").status_code == 200


# ----------------------------------------------------- sesión y cookie


def test_la_sesion_guarda_solo_el_id_y_el_token_csrf(app, client):
    crear(app)
    iniciar(client)
    datos = sesion(client)
    assert set(datos) == {"usuario_id", "csrf_token"}
    assert isinstance(datos["usuario_id"], int)


def test_el_token_csrf_cambia_tras_iniciar_sesion(app, client):
    crear(app)
    antes = extraer_token(client.get("/login").text)
    r = client.post("/login", data={"email": "ana@example.cl", "password": CLAVE, "csrf_token": antes})
    assert r.status_code == 302
    despues = sesion(client)["csrf_token"]
    assert despues != antes and len(despues) == 64
    # el token anterior ya no sirve para un POST
    r = client.post("/logout", data={"csrf_token": antes})
    assert r.status_code == 400


def test_iniciar_sesion_descarta_todo_lo_previo_de_la_sesion(app, client):
    """Fijación de sesión: lo que hubiera en la sesión antes del login no sobrevive."""
    crear(app)
    client.get("/login")
    with client.session_transaction() as s:
        s["sembrado"] = "atacante"
        s["usuario_id"] = 999
    iniciar(client)
    datos = sesion(client)
    assert "sembrado" not in datos
    assert datos["usuario_id"] != 999


def test_login_fallido_no_deja_usuario_en_la_sesion(app, client):
    crear(app)
    iniciar(client, password="incorrecta-1")
    assert "usuario_id" not in sesion(client)


def test_cookie_de_sesion_httponly_samesite_lax(app, client):
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    crear(app)
    r = iniciar(client)
    cookie = [c for c in r.headers.getlist("Set-Cookie") if c.startswith("session=")][0]
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie
    assert "Secure" not in cookie  # requiere HTTPS: se activa en T-14


# ---------------------------------------------------------------- logout


def test_logout_limpia_la_sesion_y_cambia_el_token(app, client):
    crear(app)
    iniciar(client)
    antes = sesion(client)["csrf_token"]
    r = client.post("/logout", data={"csrf_token": antes})
    assert r.status_code == 302 and r.headers["Location"] == "/"
    despues = sesion(client)
    assert set(despues) == {"csrf_token"}
    assert despues["csrf_token"] != antes
    assert client.get("/paciente").status_code == 302  # ya no hay sesión
    assert client.post("/logout", data={"csrf_token": antes}).status_code == 400


def test_logout_exige_post_y_token(app, client):
    crear(app)
    iniciar(client)
    assert client.get("/logout").status_code == 405
    assert client.post("/logout").status_code == 400
    assert client.get("/paciente").status_code == 200  # la sesión sigue viva


def test_logout_sin_sesion_redirige_al_login(client):
    token = extraer_token(client.get("/login").text)
    r = client.post("/logout", data={"csrf_token": token})
    assert r.status_code == 302 and r.headers["Location"] == "/login"


# --------------------------------------------- credenciales inválidas


CASOS_INVALIDOS = {
    "correo inexistente": ("nadie@example.cl", CLAVE),
    "contraseña errónea": ("ana@example.cl", "otra-clave-9"),
    "contraseña vacía": ("ana@example.cl", ""),
    "correo vacío": ("", CLAVE),
    "correo con ancho cero": ("ana​@example.cl", CLAVE),
    "correo con espacio interno": ("a na@example.cl", CLAVE),
    "correo con combinante suelto": ("anã@example.cl", CLAVE),
    "correo con nulo": ("ana\x00@example.cl", CLAVE),
    "correo larguísimo": ("a" * 5000 + "@example.cl", CLAVE),
    "contraseña larguísima": ("ana@example.cl", "x" * 5000),
    "inyección SQL": ("' OR 1=1 --", CLAVE),
    "inyección SQL con la contraseña": ("ana@example.cl", "' OR '1'='1"),
}


@pytest.mark.parametrize("caso", list(CASOS_INVALIDOS))
def test_credenciales_invalidas_dan_el_mismo_mensaje(app, client, caso):
    crear(app)
    email, password = CASOS_INVALIDOS[caso]
    r = iniciar(client, email, password)
    assert r.status_code == 200
    assert auth.MENSAJE_LOGIN_INVALIDO == "Correo o contraseña incorrectos."
    assert auth.MENSAJE_LOGIN_INVALIDO in r.text
    assert "usuario_id" not in sesion(client)


def test_las_respuestas_de_todos_los_fallos_son_identicas(app, client):
    """Mismo código y mismo cuerpo (salvo el correo devuelto al campo y el token)."""
    crear(app)
    crear(app, email="pro@example.cl", rol="profesional")
    cuerpos = set()
    for email, password in [
        ("nadie@example.cl", CLAVE),
        ("ana@example.cl", "otra-clave-9"),
        ("pro@example.cl", "otra-clave-9"),  # correo de un profesional: no revela el rol
        ("ana​@example.cl", CLAVE),
    ]:
        r = iniciar(client, email, password)
        assert r.status_code == 200
        # se quita lo único que cambia: el token y el correo devuelto al campo
        cuerpos.add(sin_token(re.sub(r'(name="email" value=")[^"]*"', r'\1"', r.text)))
    assert len(cuerpos) == 1


def test_el_fallo_no_menciona_rol_ni_existencia(app, client):
    crear(app, email="pro@example.cl", rol="profesional")
    texto = iniciar(client, "pro@example.cl", "otra-clave-9").text.lower()
    for prohibida in ("profesional", "paciente", "no existe", "no está registrado", "inexistente"):
        assert prohibida not in texto


def test_el_correo_devuelto_al_formulario_va_escapado(client):
    r = iniciar(client, '"><script>alert(1)</script>', CLAVE)
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;" in r.text


def test_la_contrasena_nunca_se_devuelve_al_formulario(client):
    r = iniciar(client, "ana@example.cl", "Secreto-que-no-debe-volver")
    assert "Secreto-que-no-debe-volver" not in r.text


def contar_verificaciones(monkeypatch):
    llamadas = []
    real = auth.check_password_hash

    def contado(hash_guardado, password):
        llamadas.append(hash_guardado)
        return real(hash_guardado, password)

    monkeypatch.setattr(auth, "check_password_hash", contado)
    return llamadas


@pytest.mark.parametrize("caso", list(CASOS_INVALIDOS) + ["correcto"])
def test_siempre_se_verifica_exactamente_un_hash(app, client, monkeypatch, caso):
    """Tiempos parejos: existe o no el correo, sea válido o no, se paga un hash."""
    crear(app)
    llamadas = contar_verificaciones(monkeypatch)
    email, password = CASOS_INVALIDOS.get(caso, ("ana@example.cl", CLAVE))
    iniciar(client, email, password)
    assert len(llamadas) == 1


def test_el_hash_falso_se_usa_solo_cuando_no_hay_usuario(app, client, monkeypatch):
    crear(app)
    llamadas = contar_verificaciones(monkeypatch)
    iniciar(client, "ana@example.cl", "otra-clave-9")
    iniciar(client, "nadie@example.cl", CLAVE)
    real, falso = llamadas
    assert real != falso
    assert falso == auth.hash_falso()


def test_el_hash_falso_no_corresponde_a_ninguna_contrasena_conocida():
    assert not check_password_hash(auth.hash_falso(), "")
    assert not check_password_hash(auth.hash_falso(), CLAVE)


@pytest.mark.hash_real
def test_el_hash_falso_tiene_el_costo_real_de_los_hashes_de_usuario():
    assert auth.hash_falso().startswith("scrypt:32768:8:1$")


def test_el_hash_falso_se_crea_al_usarlo_y_una_sola_vez():
    assert auth.hash_falso.cache_info().currsize == 0
    assert auth.hash_falso() == auth.hash_falso()
    assert auth.hash_falso.cache_info().misses == 1


# ----------------------------------------------------- redirecciones


@pytest.mark.parametrize(
    "next_", ["http://evil.example/", "//evil.example/", "/profesional", "https://evil.example"]
)
def test_login_ignora_el_parametro_next(app, client, next_):
    """No hay redirección controlada por el usuario (open redirect)."""
    crear(app)
    token = extraer_token(client.get("/login").text)
    r = client.post(
        "/login",
        query_string={"next": next_},
        data={"email": "ana@example.cl", "password": CLAVE, "csrf_token": token, "next": next_},
    )
    assert r.headers["Location"] == "/paciente"


def test_sin_sesion_redirige_a_login_sin_parametros(client):
    for ruta in ("/paciente", "/profesional"):
        r = client.get(ruta)
        assert r.status_code == 302
        assert r.headers["Location"] == "/login"


# ------------------------------------------ sesiones inválidas o viejas


def test_usuario_borrado_con_sesion_viva_queda_sin_acceso(app, client):
    crear(app)
    iniciar(client)
    con = sqlite3.connect(app.config["DATABASE"])
    con.execute("DELETE FROM usuarios")
    con.commit()
    con.close()
    r = client.get("/paciente")
    assert r.status_code == 302 and r.headers["Location"] == "/login"


@pytest.mark.parametrize("valor", ["1", True, 1.0, None, [1], {"a": 1}, -1, 10**30])
def test_id_de_sesion_con_tipo_o_valor_raro_no_autentica(app, client, valor):
    crear(app)
    client.get("/login")
    with client.session_transaction() as s:
        s["usuario_id"] = valor
    assert client.get("/paciente").status_code == 302
