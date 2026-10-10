"""Límite de intentos de login y registro (T-14a, D-041, D-045)."""
import logging
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app import auth, correo, create_app, limite, seguridad, tiempo
from app import db as modulo_db
from app.db import get_db, init_db
from tests.test_login import CLAVE, crear, sesion
from tests.test_seguridad import extraer_token

IP = "203.0.113.7"
OTRA_IP = "198.51.100.20"
MALA = "otra-clave-9"
RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def base_inicializada(app):
    with app.app_context():
        init_db()


class Reloj:
    """Reemplazo de `tiempo.ahora_chile` que las pruebas hacen avanzar a mano."""

    def __init__(self):
        self.ahora = datetime(2026, 10, 9, 12, 0, 0, tzinfo=ZoneInfo("America/Santiago"))

    def __call__(self):
        return self.ahora

    def avanzar(self, segundos):
        self.ahora += timedelta(seconds=segundos)


@pytest.fixture
def reloj(monkeypatch):
    reloj = Reloj()
    monkeypatch.setattr(tiempo, "ahora_chile", reloj)
    return reloj


def intentar(client, email="ana@example.cl", password=MALA, ip=IP, **extra):
    """POST /login con un token real, como si viniera de la dirección `ip`."""
    token = extraer_token(client.get("/login", follow_redirects=True).text)
    return client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": token},
        environ_overrides={"REMOTE_ADDR": ip},
        **extra,
    )


def registrar(client, n, ip=IP, **campos):
    token = extraer_token(client.get("/registro").text)
    datos = {
        "nombre": "Paciente",
        "email": f"nuevo{n}@example.cl",
        "password": CLAVE,
        "csrf_token": token,
    }
    datos.update(campos)
    return client.post("/registro", data=datos, environ_overrides={"REMOTE_ADDR": ip})


def filas(app, where="1=1", params=()):
    with app.app_context():
        return [
            tuple(f)
            for f in get_db().execute(
                f"SELECT accion, ambito, clave, instante FROM intentos_acceso WHERE {where}"
                " ORDER BY id",
                params,
            )
        ]


def cuerpo_sin_variables(respuesta):
    """El cuerpo sin lo único que cambia entre respuestas: el token y el correo devuelto."""
    texto = re.sub(r'name="csrf_token" value="[0-9a-f]+"', 'name="csrf_token" value="X"', respuesta.text)
    return re.sub(r'(name="email" value=")[^"]*"', r'\1"', texto)


def contar_verificaciones(monkeypatch):
    llamadas = []
    real = auth.check_password_hash

    def contado(hash_guardado, password):
        llamadas.append(hash_guardado)
        return real(hash_guardado, password)

    monkeypatch.setattr(auth, "check_password_hash", contado)
    return llamadas


# ------------------------------------------------------------------ login: bloqueo


def test_cinco_fallos_del_mismo_par_bloquean_el_sexto(app, client, reloj):
    crear(app)
    for _ in range(5):
        assert intentar(client).status_code == 200
    r = intentar(client)
    assert r.status_code == 429
    assert "Demasiados intentos" in r.text and "15 minutos" in r.text
    assert r.headers["Retry-After"] == "900"
    assert "usuario_id" not in sesion(client)


def test_bloqueado_ni_la_contrasena_correcta_entra(app, client, reloj):
    crear(app)
    for _ in range(5):
        intentar(client)
    r = intentar(client, password=CLAVE)
    assert r.status_code == 429
    assert "usuario_id" not in sesion(client)


def test_el_bloqueo_es_identico_para_un_correo_real_y_uno_inventado(app, client, reloj):
    """D-010: no se distingue si la cuenta existe, ni en el cuerpo ni en las cabeceras."""
    crear(app)
    respuestas = []
    for correo in ("ana@example.cl", "nadie@example.cl"):
        for _ in range(5):
            intentar(client, correo)
        respuestas.append(intentar(client, correo))
    real, falso = respuestas
    assert real.status_code == falso.status_code == 429
    assert cuerpo_sin_variables(real) == cuerpo_sin_variables(falso)
    cabeceras = lambda r: {k: v for k, v in r.headers.items() if k.lower() not in ("date", "set-cookie", "content-length")}
    assert cabeceras(real) == cabeceras(falso)
    aviso = re.search(r'<p class="error" role="alert">(.*?)</p>', real.text).group(1).lower()
    for prohibida in ("no existe", "no está registrado", "cuenta", "paciente", "profesional"):
        assert prohibida not in aviso


def test_un_intento_bloqueado_no_paga_scrypt_ni_mira_la_cuenta(app, client, reloj, monkeypatch):
    """Igual para real e inventado: ningún hash, así que el tiempo no delata la cuenta."""
    crear(app)
    for correo in ("ana@example.cl", "nadie@example.cl"):
        for _ in range(5):
            intentar(client, correo)
    llamadas = contar_verificaciones(monkeypatch)
    for correo in ("ana@example.cl", "nadie@example.cl"):
        assert intentar(client, correo).status_code == 429
    assert llamadas == []


def test_un_intento_no_bloqueado_verifica_exactamente_un_hash_real_o_inventado(app, client, reloj, monkeypatch):
    crear(app)
    llamadas = contar_verificaciones(monkeypatch)
    intentar(client, "ana@example.cl")
    intentar(client, "nadie@example.cl")
    assert len(llamadas) == 2


def test_cuatro_fallos_y_un_acierto_entra_y_limpia_el_par(app, client, reloj):
    crear(app)
    for _ in range(4):
        intentar(client)
    assert intentar(client, password=CLAVE).status_code == 302
    assert filas(app, "ambito = 'par'") == []
    # el par quedó limpio: otros cinco fallos hacen falta para bloquearlo de nuevo
    for _ in range(5):
        assert intentar(client).status_code == 200
    assert intentar(client).status_code == 429


def test_los_logins_correctos_no_cuentan_como_fallos(app, client, reloj):
    crear(app)
    for _ in range(12):
        assert intentar(client, password=CLAVE).status_code == 302
    assert filas(app) == []  # cada acierto devolvió su anotación
    assert intentar(client).status_code == 200  # y el primer fallo sigue siendo el primero


def test_un_acierto_no_limpia_los_fallos_de_la_direccion(app, client, reloj):
    """Con una cuenta propia no se "borran" los fallos acumulados contra las de otros."""
    crear(app)
    crear(app, email="pro@example.cl", password=CLAVE)
    for _ in range(3):
        intentar(client, "nadie@example.cl")
    assert intentar(client, "ana@example.cl", CLAVE).status_code == 302
    assert len(filas(app, "ambito = 'ip'")) == 3


def test_otra_direccion_no_queda_bloqueada_por_los_fallos_ajenos(app, client, reloj):
    """Mitigación del bloqueo a un tercero: el par incluye la dirección del que falla."""
    crear(app)
    for _ in range(5):
        intentar(client, ip=IP)  # un tercero falla con el correo de Ana
    assert intentar(client, ip=IP).status_code == 429
    assert intentar(client, password=CLAVE, ip=OTRA_IP).status_code == 302


def test_el_ambito_ip_bloquea_el_barrido_de_correos_distintos(app, client, reloj):
    crear(app)
    for n in range(20):
        assert intentar(client, f"victima{n}@example.cl").status_code == 200
    r = intentar(client, "victima99@example.cl")
    assert r.status_code == 429
    assert intentar(client, "ana@example.cl", CLAVE).status_code == 429  # documentado en D-045
    assert intentar(client, "ana@example.cl", CLAVE, ip=OTRA_IP).status_code == 302


def test_el_ambito_correo_bloquea_el_ataque_repartido_en_muchas_direcciones(app, client, reloj):
    crear(app)
    for n in range(30):  # 6 direcciones x 5 fallos: ninguna supera su propio límite del par (5)
        intentar(client, ip=f"198.51.100.{n // 5 + 1}")
    r = intentar(client, password=CLAVE, ip="192.0.2.99")  # una dirección nueva, con la clave buena
    assert r.status_code == 429  # riesgo documentado en D-045


def test_29_fallos_repartidos_no_alcanzan_el_ambito_correo(app, client, reloj):
    crear(app)
    for n in range(29):
        intentar(client, ip=f"198.51.100.{n // 5 + 1}")
    assert intentar(client, password=CLAVE, ip="192.0.2.99").status_code == 302


def test_los_umbrales_son_los_documentados():
    assert limite.VENTANA_S == 15 * 60
    assert limite.LIMITES == {
        "login": {"ip": 20, "par": 5, "correo": 30},
        "registro": {"ip": 10},
    }


# ----------------------------------------------------------- ventana y limpieza


def test_el_bloqueo_se_levanta_al_salir_el_intento_mas_antiguo(app, client, reloj):
    crear(app)
    intentar(client)  # t = 0
    reloj.avanzar(600)
    for _ in range(4):  # t = 600
        intentar(client)
    r = intentar(client)
    assert r.status_code == 429 and r.headers["Retry-After"] == "300"
    assert "5 minutos" in r.text
    reloj.avanzar(299)
    assert intentar(client).status_code == 429
    reloj.avanzar(1)  # t = 900: el primer intento ya salió de la ventana
    assert intentar(client).status_code == 200
    assert intentar(client).status_code == 429  # volvieron a ser 5 dentro de la ventana


def test_pasada_la_ventana_se_puede_volver_a_intentar_y_las_filas_viejas_se_borran(app, client, reloj):
    crear(app)
    for _ in range(5):
        intentar(client)
    assert intentar(client).status_code == 429
    reloj.avanzar(900)
    assert intentar(client, password=CLAVE).status_code == 302
    assert filas(app) == []  # las vencidas se borraron y el acierto devolvió la suya


def test_un_minuto_restante_se_dice_en_singular(app, client, reloj):
    crear(app)
    for _ in range(5):
        intentar(client)
    reloj.avanzar(900 - 30)
    assert "espera 1 minuto antes" in intentar(client).text


def test_los_intentos_bloqueados_no_se_anotan_ni_prolongan_el_bloqueo(app, client, reloj):
    crear(app)
    for _ in range(5):
        intentar(client)
    anotados = len(filas(app))
    for _ in range(10):
        assert intentar(client).status_code == 429
    assert len(filas(app)) == anotados
    reloj.avanzar(900)
    assert intentar(client).status_code == 200


def test_las_filas_vencidas_de_otras_claves_se_limpian_al_anotar(app, client, reloj):
    with app.app_context():
        db = get_db()
        ahora = int(reloj().timestamp())
        db.execute(
            "INSERT INTO intentos_acceso (accion, ambito, clave, instante) VALUES ('login', 'ip', '192.0.2.1', ?)",
            (ahora - 901,),
        )
        db.commit()
    intentar(client)
    assert filas(app, "clave = '192.0.2.1'") == []


# ---------------------------------------------------------------- la clave


def test_el_correo_se_normaliza_para_la_clave(app, client, reloj):
    crear(app)
    variantes = ["ANA@example.cl", " ana@EXAMPLE.cl ", "ａna@example.cl", "Ana@Example.cl", "ana@example.cl"]
    for correo in variantes:
        assert intentar(client, correo).status_code == 200
    assert intentar(client, "ana@example.cl").status_code == 429
    assert {f[2] for f in filas(app, "ambito = 'correo'")} == {"ana@example.cl"}


def test_una_basura_inutilizable_solo_cuenta_para_la_direccion(app, client, reloj):
    # Vacío y más largo que EMAIL_MAX no dan clave de correo (D-056): solo cuenta la IP.
    for malo in ["", "   ", "x" * 300 + "@example.cl"]:
        intentar(client, malo)
    assert {f[1] for f in filas(app)} == {"ip"}


@pytest.mark.parametrize("basura", [None, 5, b"ana@example.cl", ["ana@example.cl"], "", "x" * 255])
def test_clave_de_correo_vacia_para_lo_inutilizable(basura):
    assert auth._correo_para_limite(basura) == ""
    # el sustituto suelto ya sale vacío de la normalización de login
    assert auth._correo_para_limite(correo.normalizar_email_login("a\ud800b@example.cl")) == ""


def test_clave_de_correo_acepta_hasta_email_max():
    exacto = "x" * auth.EMAIL_MAX
    assert auth._correo_para_limite(exacto) == exacto
    assert auth._correo_para_limite(exacto + "x") == ""


def crear_legacy(app, email):
    """Cuenta guardada por SQL con un carácter que hoy el registro rechaza (D-048 C2)."""
    with app.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO usuarios (nombre, email, password_hash, rol, creado_en)"
            " VALUES ('Mía', ?, ?, 'paciente', '2020-01-01T00:00:00-03:00')",
            (email, auth.generate_password_hash(CLAVE)),
        )
        db.commit()


LEGACY = "m·ia@example.cl"  # U+00B7: el registro lo rechaza, el login lo acepta


def test_cuenta_legacy_se_bloquea_por_par_a_los_5_fallos(app, client, reloj):
    crear_legacy(app, LEGACY)
    assert [intentar(client, LEGACY).status_code for _ in range(5)] == [200] * 5
    r = intentar(client, LEGACY)
    assert r.status_code == 429
    assert {f[2].split("|")[0] for f in filas(app, "ambito = 'par'")} == {IP}
    assert intentar(client, LEGACY, ip=OTRA_IP).status_code == 200  # otra IP aún puede intentar


def test_cuenta_legacy_se_corta_por_correo_con_ips_distintas(app, client, reloj):
    crear_legacy(app, LEGACY)
    codigos = [intentar(client, LEGACY, ip=f"198.51.{n // 250}.{n % 250 + 1}").status_code for n in range(31)]
    assert codigos[:30] == [200] * 30
    assert codigos[30] == 429
    assert {f[2] for f in filas(app, "ambito = 'correo'")} == {LEGACY}


def test_variantes_del_mismo_correo_suman_a_la_misma_clave(app, client, reloj):
    variantes = ["ana@example.cl", "ANA@EXAMPLE.CL", "ａｎａ＠ｅｘａｍｐｌｅ.ｃｌ", " Ana@Example.cl "]
    for v in variantes:
        intentar(client, v)
    assert {f[2] for f in filas(app, "ambito = 'correo'")} == {"ana@example.cl"}
    assert len(filas(app, "ambito = 'par'")) == 4
    assert intentar(client, "ANA@example.cl").status_code == 200  # 5.º fallo
    assert intentar(client, "ａｎａ＠ｅｘａｍｐｌｅ.ｃｌ").status_code == 429


def test_variantes_de_una_cuenta_legacy_suman_a_la_misma_clave(app, client, reloj):
    crear_legacy(app, LEGACY)
    for v in [LEGACY, "M·IA@EXAMPLE.CL", "ｍ·ｉａ＠ｅｘａｍｐｌｅ.ｃｌ", " m·ia@example.cl "]:
        intentar(client, v)
    assert {f[2] for f in filas(app, "ambito = 'correo'")} == {LEGACY}
    assert intentar(client, "M·ia@example.cl").status_code == 200  # 5.º fallo
    assert intentar(client, LEGACY).status_code == 429


def test_correo_sobredimensionado_no_crea_filas_por_correo(app, client, reloj):
    for largo in (auth.EMAIL_MAX + 1, 5000):
        intentar(client, "y" * largo)
    assert {f[1] for f in filas(app)} == {"ip"}


def test_el_login_normaliza_el_correo_una_sola_vez(app, client, reloj, monkeypatch):
    llamadas = []
    original = auth.normalizar_email_login
    monkeypatch.setattr(auth, "normalizar_email_login", lambda v: llamadas.append(v) or original(v))
    intentar(client, "Ana@Example.cl")
    assert len(llamadas) == 1


def test_ipv6_se_agrupa_por_su_prefijo_64(app, client, reloj):
    crear(app)
    for n in range(1, 6):
        intentar(client, ip=f"2001:db8:1:2::{n:x}")
    assert intentar(client, ip="2001:db8:1:2:9::7").status_code == 429  # otro /128 del mismo /64
    assert intentar(client, password=CLAVE, ip="2001:db8:1:3::1").status_code == 302


@pytest.mark.parametrize(
    "direccion, esperada",
    [
        ("203.0.113.7", "203.0.113.7"),
        ("2001:db8:1:2::5", "2001:db8:1:2::/64"),
        ("2001:db8:1:2:aaaa:bbbb:cccc:dddd", "2001:db8:1:2::/64"),
        ("::ffff:203.0.113.7", "203.0.113.7"),
        ("::1", "::/64"),
        (None, "desconocida"),
        ("", "desconocida"),
        ("no-es-una-ip", "desconocida"),
    ],
)
def test_clave_ip(direccion, esperada):
    assert limite.clave_ip(direccion) == esperada


def test_una_cabecera_x_forwarded_for_no_permite_evadir_el_limite(app, client, reloj):
    crear(app)
    for n in range(5):
        intentar(client, headers={"X-Forwarded-For": f"10.0.0.{n}"})
    r = intentar(client, headers={"X-Forwarded-For": "10.0.0.99"})
    assert r.status_code == 429
    assert {f[2].split("|")[0] for f in filas(app, "ambito = 'par'")} == {IP}


def _app_con_proxies(tmp_path, cantidad):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "p.db"), "TRUSTED_PROXY_COUNT": cantidad})

    @app.route("/_ip")
    def ver_ip():
        from flask import request

        return request.remote_addr

    return app


@pytest.mark.parametrize(
    "cantidad, cabecera, esperada",
    [
        (0, "9.9.9.9", "127.0.0.1"),
        (1, "9.9.9.9, 198.51.100.4", "198.51.100.4"),  # lo que antepone el cliente no cuenta
        (1, "198.51.100.4", "198.51.100.4"),
        (2, "9.9.9.9, 198.51.100.4, 10.0.0.1", "198.51.100.4"),
        (1, None, "127.0.0.1"),  # sin cabecera: la dirección de la conexión
    ],
)
def test_proxies_de_confianza(tmp_path, cantidad, cabecera, esperada):
    cliente = _app_con_proxies(tmp_path, cantidad).test_client()
    cabeceras = {"X-Forwarded-For": cabecera} if cabecera else {}
    assert cliente.get("/_ip", headers=cabeceras).text == esperada


def test_con_un_proxy_de_confianza_el_limite_usa_la_direccion_real(tmp_path):
    app = _app_con_proxies(tmp_path, 1)
    cliente = app.test_client()
    with app.app_context():
        init_db()
    crear(app)
    for _ in range(5):
        intentar(cliente, headers={"X-Forwarded-For": "7.7.7.7, 198.51.100.4"})
    assert intentar(cliente, headers={"X-Forwarded-For": "8.8.8.8, 198.51.100.4"}).status_code == 429
    assert intentar(cliente, password=CLAVE, headers={"X-Forwarded-For": "8.8.8.8, 198.51.100.5"}).status_code == 302


@pytest.mark.parametrize(
    "cabecera, valor",
    [
        ("X-Forwarded-Proto", "https"),
        ("X-Forwarded-Host", "malo.example"),
        ("X-Forwarded-Port", "8443"),
        ("X-Forwarded-Prefix", "/malo"),
    ],
)
@pytest.mark.parametrize("cantidad", [1, 2])
def test_proxyfix_solo_confia_en_la_direccion_no_en_esquema_host_puerto_ni_prefijo(
    tmp_path, cantidad, cabecera, valor
):
    """R-07 (D-047): con proxies de confianza solo cuenta X-Forwarded-For. Confiar además en
    Proto/Host/Port/Prefix dejaría que un cliente cambie `request.scheme`, `host` o las URL absolutas."""
    app = _app_con_proxies(tmp_path, cantidad)

    @app.route("/_origen")
    def ver_origen():
        from flask import request

        return "|".join([request.scheme, request.host, request.script_root, request.url_root])

    cliente = app.test_client()
    base = cliente.get("/_origen", headers={"X-Forwarded-For": "198.51.100.4"}).text
    esperado = "http|localhost||http://localhost/"
    assert base == esperado
    forjada = cliente.get("/_origen", headers={"X-Forwarded-For": "198.51.100.4", cabecera: valor}).text
    assert forjada == esperado


@pytest.mark.parametrize(
    "segundos, minutos",
    [(1, 1), (59, 1), (60, 1), (61, 2), (119, 2), (120, 2), (121, 3), (299, 5), (300, 5), (899, 15), (900, 15), (901, 16)],
)
def test_el_mensaje_de_espera_redondea_hacia_arriba(segundos, minutos):
    """Un mensaje que diga 14 minutos con 899 s dejaría al usuario intentar demasiado pronto."""
    texto = limite.mensaje_bloqueo(segundos)
    unidad = "minuto" if minutos == 1 else "minutos"
    assert f"espera {minutos} {unidad} antes" in texto


def test_el_mensaje_de_espera_llega_redondeado_a_la_pagina(app, client, reloj):
    crear(app)
    for _ in range(5):
        intentar(client)
    reloj.avanzar(1)  # quedan 899 s
    r = intentar(client)
    assert r.status_code == 429 and r.headers["Retry-After"] == "899"
    assert "espera 15 minutos" in r.text


# ------------------------------------- R-02: proxy sin TRUSTED_PROXY_COUNT


@pytest.fixture
def aviso_de_proxy_nuevo(monkeypatch):
    """Cada prueba parte de «aún no se avisó» (el aviso es una vez por proceso)."""
    monkeypatch.setitem(seguridad._aviso_de_proxy, "dado", False)


def _avisos_de_proxy(caplog):
    return [r for r in caplog.records if r.getMessage().startswith("Llegó una petición con X-Forwarded-For")]


@pytest.mark.parametrize("cabecera", ["X-Forwarded-For", "X-Real-IP", "x-forwarded-for"])
def test_r02_cabeceras_de_proxy_sin_configurar_avisan_una_sola_vez(
    app, client, caplog, aviso_de_proxy_nuevo, cabecera
):
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            client.get("/login", headers={cabecera: "9.9.9.9"}, environ_overrides={"REMOTE_ADDR": "10.0.0.1"})
    (aviso,) = _avisos_de_proxy(caplog)
    texto = aviso.getMessage()
    assert "TRUSTED_PROXY_COUNT" in texto and "10.0.0.1" in texto
    assert "20 intentos fallidos" in texto and "15 minutos" in texto


def test_r02_sin_cabeceras_de_proxy_no_avisa(app, client, caplog, aviso_de_proxy_nuevo):
    with caplog.at_level(logging.WARNING):
        client.get("/login")
        client.get("/")
    assert _avisos_de_proxy(caplog) == []
    assert seguridad._aviso_de_proxy["dado"] is False


def test_r02_con_trusted_proxy_count_no_avisa(tmp_path, caplog, aviso_de_proxy_nuevo):
    cliente = _app_con_proxies(tmp_path, 1).test_client()
    with caplog.at_level(logging.WARNING):
        cliente.get("/login", headers={"X-Forwarded-For": "198.51.100.4", "X-Real-IP": "198.51.100.4"})
    assert _avisos_de_proxy(caplog) == []


def test_r02_el_aviso_no_cambia_la_respuesta_ni_la_direccion(app, client, caplog, aviso_de_proxy_nuevo):
    """Solo informa: sigue ignorando la cabecera (el límite cuenta la dirección de la conexión)."""
    crear(app)
    with caplog.at_level(logging.WARNING):
        for n in range(5):
            assert intentar(client, headers={"X-Forwarded-For": f"10.0.0.{n}"}).status_code == 200
        assert intentar(client, headers={"X-Forwarded-For": "10.0.0.99"}).status_code == 429
    assert len(_avisos_de_proxy(caplog)) == 1


def test_r02_la_consecuencia_esta_explicita_en_el_readme():
    readme = (RAIZ / "README.md").read_text(encoding="utf-8")
    assert "TRUSTED_PROXY_COUNT" in readme
    assert "20 intentos fallidos" in readme and "bloquean" in readme and "todos" in readme


@pytest.mark.parametrize("valor", ["abc", "-1", "11", "1.5", "uno"])
def test_trusted_proxy_count_invalido_se_rechaza(tmp_path, monkeypatch, valor):
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", valor)
    with pytest.raises(RuntimeError, match="TRUSTED_PROXY_COUNT"):
        create_app({"TESTING": True, "DATABASE": str(tmp_path / "x.db")})


@pytest.mark.parametrize("valor, esperado", [("", 0), ("  ", 0), ("0", 0), ("1", 1), (" 2 ", 2)])
def test_trusted_proxy_count_validos(tmp_path, monkeypatch, valor, esperado):
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", valor)
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "x.db")})
    assert app.config["TRUSTED_PROXY_COUNT"] == esperado


# ----------------------------------------------------------------- registro


def test_el_registro_se_bloquea_tras_diez_por_direccion(app, client, reloj):
    for n in range(10):
        assert registrar(client, n).status_code == 302
    r = registrar(client, 99)
    assert r.status_code == 429
    assert "Demasiados intentos" in r.text and "15 minutos" in r.text
    assert r.headers["Retry-After"] == "900"
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 10
    assert registrar(client, 100, ip=OTRA_IP).status_code == 302


def test_el_registro_cuenta_tambien_los_duplicados_y_no_los_rechazos_de_validacion(app, client, reloj):
    crear(app)
    for _ in range(5):
        assert registrar(client, 0, email="ana@example.cl").status_code == 200  # duplicado: cuenta
    for _ in range(20):
        assert registrar(client, 0, password="corta").status_code == 200  # validación: no cuenta
    assert len(filas(app, "accion = 'registro'")) == 5
    for n in range(5):
        registrar(client, n)
    assert registrar(client, 50).status_code == 429


def test_el_registro_se_libera_al_pasar_la_ventana(app, client, reloj):
    for n in range(10):
        registrar(client, n)
    assert registrar(client, 50).status_code == 429
    reloj.avanzar(900)
    assert registrar(client, 51).status_code == 302


def test_registro_y_login_tienen_contadores_independientes(app, client, reloj):
    crear(app)
    for n in range(10):
        registrar(client, n)
    assert registrar(client, 60).status_code == 429  # el registro ya está lleno...
    assert intentar(client, password=CLAVE).status_code == 302  # ...y el login no lo nota
    for _ in range(5):
        intentar(client)
    assert len(filas(app, "accion = 'registro'")) == 10
    assert len(filas(app, "accion = 'login' AND ambito = 'par'")) == 5


def test_los_fallos_de_login_no_bloquean_el_registro(app, client, reloj):
    for _ in range(20):
        intentar(client, "nadie@example.cl")
    assert intentar(client, "nadie@example.cl").status_code == 429
    assert registrar(client, 1).status_code == 302


def test_el_bloqueo_del_registro_no_depende_del_correo_que_se_escribe(app, client, reloj):
    crear(app)
    for n in range(10):
        registrar(client, n)
    real = registrar(client, 0, email="ana@example.cl")
    nuevo = registrar(client, 1, email="otro@example.cl")
    assert real.status_code == nuevo.status_code == 429
    assert real.text.replace("ana@example.cl", "X") == nuevo.text.replace("otro@example.cl", "X")


def test_el_registro_bloqueado_conserva_lo_escrito_menos_la_contrasena(app, client, reloj):
    for n in range(10):
        registrar(client, n)
    r = registrar(client, 1, nombre="María", email="maria@example.cl", password="Secreto-que-no-vuelve")
    assert r.status_code == 429
    assert 'value="María"' in r.text and 'value="maria@example.cl"' in r.text
    assert "Secreto-que-no-vuelve" not in r.text


# ------------------------------------------------- base ocupada (sin 500)


@pytest.fixture
def base_retenida(app, monkeypatch):
    """Otra conexión retiene el bloqueo de escritura y la espera de la app es de 50 ms."""
    retenedor = sqlite3.connect(app.config["DATABASE"], isolation_level=None)
    retenedor.execute("BEGIN IMMEDIATE")
    real = sqlite3.connect
    monkeypatch.setattr(modulo_db.sqlite3, "connect", lambda *a, **k: real(*a, **{**k, "timeout": 0.05}))
    yield
    retenedor.close()


@pytest.fixture
def lector_retenido(app, monkeypatch):
    """Otra conexión mantiene una lectura abierta: la anotación entra, pero no puede confirmarse."""
    lector = sqlite3.connect(app.config["DATABASE"], isolation_level=None)
    lector.execute("BEGIN")
    lector.execute("SELECT COUNT(*) FROM usuarios").fetchall()
    real = sqlite3.connect
    monkeypatch.setattr(modulo_db.sqlite3, "connect", lambda *a, **k: real(*a, **{**k, "timeout": 0.05}))
    yield
    lector.close()


def test_login_con_la_base_ocupada_responde_503_en_espanol(app, client, base_retenida, monkeypatch):
    llamadas = contar_verificaciones(monkeypatch)
    r = intentar(client)
    assert r.status_code == 503
    assert limite.MENSAJE_BASE_OCUPADA in r.text and "Retry-After" in r.headers
    assert llamadas == []  # sin poder anotar el intento, no se prueba ninguna contraseña


def test_si_la_base_se_ocupa_al_confirmar_tambien_es_503_y_no_deja_filas(app, client, lector_retenido):
    r = intentar(client)
    assert r.status_code == 503 and limite.MENSAJE_BASE_OCUPADA in r.text
    assert filas(app) == []  # la anotación se deshizo: no quedó medio hecha


def test_registro_con_la_base_ocupada_responde_503_y_no_crea_la_cuenta(app, client, base_retenida):
    r = registrar(client, 1)
    assert r.status_code == 503
    assert limite.MENSAJE_BASE_OCUPADA in r.text


def test_la_base_ocupada_al_absolver_no_impide_un_login_correcto(app, client, reloj, monkeypatch):
    crear(app)

    llamadas = []

    def empezar(db):
        llamadas.append(1)
        if len(llamadas) == 2:  # el segundo BEGIN IMMEDIATE (absolver) falla
            raise limite.BaseOcupada()
        db.execute("BEGIN IMMEDIATE")

    monkeypatch.setattr(limite, "_empezar", empezar)
    assert intentar(client, password=CLAVE).status_code == 302
    assert len(llamadas) == 2


def test_un_error_al_empezar_que_no_es_de_ocupacion_no_se_disfraza(app, reloj):
    """Una transacción ya abierta en la conexión es un fallo del programa, no una base ocupada."""
    with app.test_request_context("/login"):
        db = get_db()
        db.execute(
            "INSERT INTO intentos_acceso (accion, ambito, clave, instante) VALUES ('login', 'ip', 'x', 1)"
        )  # deja una transacción abierta
        with pytest.raises(sqlite3.OperationalError, match="within a transaction"):
            limite.reservar("login", "ana@example.cl")
        db.rollback()


def test_un_error_de_sqlite_que_no_es_de_ocupacion_no_se_disfraza(app, client):
    """Una tabla ausente (base anterior a T-14a) es un fallo real, no "base ocupada"."""
    with app.app_context():
        get_db().execute("DROP TABLE intentos_acceso")
        get_db().commit()
    app.config["PROPAGATE_EXCEPTIONS"] = False
    assert intentar(client).status_code == 500


# ------------------------------------------------------------ varios procesos

CODIGO_PROCESO = """
import sys, time
from app import create_app, limite
app = create_app({"TESTING": True, "DATABASE": sys.argv[1]})
salida = float(sys.argv[3])  # instante común fijado por la prueba: todos arrancan a la vez
with app.test_request_context("/login", environ_overrides={"REMOTE_ADDR": "203.0.113.9"}):
    while time.time() < salida:
        pass
    admitidos = 0
    for _ in range(int(sys.argv[2])):
        try:
            limite.reservar("login", "ana@example.cl")
            admitidos += 1
        except limite.Bloqueado:
            pass
        except limite.BaseOcupada:
            pass
print(admitidos)
"""


def test_con_varios_procesos_a_la_vez_pasan_exactamente_los_permitidos(app, tmp_path):
    """El conteo y la anotación van juntos en BEGIN IMMEDIATE: ningún proceso se cuela."""
    archivo = tmp_path / "multi.db"
    app_multi = create_app({"TESTING": True, "DATABASE": str(archivo)})
    with app_multi.app_context():
        init_db()
    salida_comun = time.time() + 1.0  # si un equipo lento tarda más en importar, solo se sincroniza menos
    procesos = [
        subprocess.Popen(
            [sys.executable, "-c", CODIGO_PROCESO, str(archivo), "10", str(salida_comun)],
            cwd=RAIZ, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        for _ in range(6)
    ]
    admitidos = []
    for proceso in procesos:
        salida, error = proceso.communicate(timeout=60)
        assert proceso.returncode == 0, error
        admitidos.append(int(salida))
    assert sum(admitidos) == 5  # el límite del par; el de la dirección (20) y del correo (30) son mayores
    with sqlite3.connect(archivo) as conexion:
        assert conexion.execute("SELECT COUNT(*) FROM intentos_acceso WHERE ambito = 'par'").fetchone()[0] == 5


# --------------------------------------------- T-08d R-04: login y logout a la vez


def test_un_logout_durante_la_verificacion_no_deja_la_sesion_nueva_ya_revocada(app, client, monkeypatch):
    """El hash tarda; si otro navegador cierra sesión en ese rato, la sesión nueva nace vigente."""
    crear(app)
    real = auth.check_password_hash
    ruta = app.config["DATABASE"]

    def con_logout_en_medio(hash_guardado, password):
        resultado = real(hash_guardado, password)
        with sqlite3.connect(ruta) as otra:  # "otro navegador" cierra sesión ahora
            otra.execute("UPDATE usuarios SET sesion_version = sesion_version + 1")
        return resultado

    monkeypatch.setattr(auth, "check_password_hash", con_logout_en_medio)
    r = intentar(client, password=CLAVE)
    assert r.status_code == 302
    monkeypatch.setattr(auth, "check_password_hash", real)
    assert client.get("/paciente").status_code == 200  # no lo manda de vuelta a /login


def test_un_usuario_borrado_durante_la_verificacion_no_inicia_sesion(app, client, monkeypatch):
    crear(app)
    real = auth.check_password_hash
    ruta = app.config["DATABASE"]

    def borrando(hash_guardado, password):
        resultado = real(hash_guardado, password)
        with sqlite3.connect(ruta) as otra:
            otra.execute("DELETE FROM usuarios")
        return resultado

    monkeypatch.setattr(auth, "check_password_hash", borrando)
    r = intentar(client, password=CLAVE)
    assert r.status_code == 200 and auth.MENSAJE_LOGIN_INVALIDO in r.text
    assert "usuario_id" not in sesion(client)


# ----------------------------------------- T-14b: reloj atrasado y limpieza acotada (D-050)


def test_si_el_reloj_retrocede_la_espera_no_pasa_de_la_ventana(app, client, reloj):
    """T-14a R-05: con el reloj 24 h atrás la espera crecía con el salto (1455 minutos)."""
    crear(app)
    for _ in range(5):
        intentar(client)
    reloj.avanzar(-24 * 3600)
    r = intentar(client)
    assert r.status_code == 429
    assert r.headers["Retry-After"] == str(limite.VENTANA_S)
    assert "15 minutos" in r.text and "1455 minutos" not in r.text


def test_tras_un_retroceso_el_bloqueo_se_libera_15_minutos_despues_de_notarlo(app, client, reloj):
    crear(app)
    for _ in range(5):
        intentar(client)
    reloj.avanzar(-24 * 3600)
    assert intentar(client).status_code == 429  # el retroceso se nota en este intento
    reloj.avanzar(limite.VENTANA_S - 1)
    assert intentar(client).status_code == 429
    reloj.avanzar(1)
    assert intentar(client, password=CLAVE).status_code == 302


def test_un_retroceso_pequeno_no_regala_intentos(app, client, reloj):
    """Las marcas «futuras» se reubican en `ahora`, no se borran: siguen contando."""
    crear(app)
    for _ in range(5):
        intentar(client)
    reloj.avanzar(-1)
    assert intentar(client).status_code == 429
    assert len(filas(app, "ambito = 'par'")) == 5


def test_las_marcas_futuras_se_reubican_en_ahora(app, client, reloj):
    crear(app)
    for _ in range(3):
        intentar(client)
    reloj.avanzar(-3600)
    intentar(client)
    ahora = int(reloj.ahora.timestamp())
    assert {f[3] for f in filas(app)} == {ahora}


def _insertar_vencidas(app, cantidad, instante):
    with app.app_context():
        db = get_db()
        db.executemany(
            "INSERT INTO intentos_acceso (accion, ambito, clave, instante) VALUES ('login', 'ip', ?, ?)",
            [(f"10.0.{i // 250}.{i % 250}", instante) for i in range(cantidad)],
        )
        db.commit()


def test_la_limpieza_de_vencidas_es_acotada_por_intento(app, client, reloj):
    """T-14a R-06: el borrado de vencidas no recorre ni borra toda la tabla en un solo intento."""
    crear(app)
    _insertar_vencidas(app, 1500, int(reloj.ahora.timestamp()) - limite.VENTANA_S - 10)
    intentar(client)
    vencidas = filas(app, "instante < ?", (int(reloj.ahora.timestamp()) - limite.VENTANA_S,))
    assert len(vencidas) == 1500 - limite.LOTE_LIMPIEZA
    intentar(client)
    assert len(filas(app, "instante < ?", (int(reloj.ahora.timestamp()) - limite.VENTANA_S,))) == (
        1500 - 2 * limite.LOTE_LIMPIEZA
    )


def test_las_vencidas_que_quedan_sin_borrar_no_cuentan(app, client, reloj):
    crear(app)
    with app.app_context():
        db = get_db()
        db.executemany(
            "INSERT INTO intentos_acceso (accion, ambito, clave, instante) VALUES (?, ?, ?, ?)",
            [("login", "par", f"{IP}|ana@example.cl", int(reloj.ahora.timestamp()) - 5000)] * 2000,
        )
        db.commit()
    for _ in range(5):
        assert intentar(client).status_code == 200  # 2000 vencidas del mismo par: ninguna cuenta
    assert intentar(client).status_code == 429


def test_el_lote_de_limpieza_es_chico_frente_a_una_tabla_enorme():
    assert 100 <= limite.LOTE_LIMPIEZA <= 5000
