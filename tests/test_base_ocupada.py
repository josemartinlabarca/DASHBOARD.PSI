"""Base ocupada (T-14b, D-050; T-05 R-02, T-11b R-02): con el bloqueo de escritura de SQLite
retenido por otro proceso más tiempo que el de espera (5 s en producción; aquí 0,05 s para que
la prueba sea rápida), reservar, cancelar, agregar, eliminar y marcar leídas responden 503 con
un mensaje en español y `Retry-After`, igual que el límite de intentos, y se pueden reintentar."""
import contextlib
import sqlite3

import pytest

from app import db as modulo_db
from app import errores, limite
from app.db import get_db, init_db
from tests.test_cancelar import reservada
from tests.test_horas_libres import fijar_reloj, insertar, nuevo_profesional
from tests.test_login import crear, iniciar
from tests.test_notificaciones import notifs
from tests.test_reservar import fila, nuevo_paciente
from tests.test_seguridad import extraer_token

OCUPADO = "El sistema está ocupado en este momento. Espera unos segundos e inténtalo de nuevo."


@pytest.fixture(autouse=True)
def base_inicializada(app):
    with app.app_context():
        init_db()
    app.config["DATABASE_TIMEOUT"] = 0.05


@pytest.fixture(autouse=True)
def reloj_fijo(monkeypatch):
    fijar_reloj(monkeypatch)


@pytest.fixture
def pro_id(app):
    return nuevo_profesional(app)


@pytest.fixture
def ana(app):
    return nuevo_paciente(app)


@pytest.fixture
def pro(app, pro_id):
    cliente = app.test_client()
    iniciar(cliente, "pro@example.cl")
    return cliente


@contextlib.contextmanager
def retenida(app, modo="IMMEDIATE"):
    """Otra conexión retiene el bloqueo de escritura (IMMEDIATE) o todo (EXCLUSIVE)."""
    otra = sqlite3.connect(app.config["DATABASE"], isolation_level=None)
    otra.execute(f"BEGIN {modo}")
    try:
        yield
    finally:
        otra.execute("ROLLBACK")
        otra.close()


def ocupada(r, volver=None):
    assert r.status_code == 503, r.status_code
    assert OCUPADO in r.text
    assert r.headers["Retry-After"] == "5"
    assert "Traceback" not in r.text and "sqlite" not in r.text.lower() and "locked" not in r.text
    if volver:
        assert f'href="{volver}"' in r.text
    return r


def test_el_mensaje_es_el_mismo_del_limite_de_intentos_y_la_espera_es_la_de_sqlite():
    assert modulo_db.MENSAJE_BASE_OCUPADA == limite.MENSAJE_BASE_OCUPADA == OCUPADO
    assert modulo_db.TIMEOUT_DEFECTO_S == 5.0 and errores.ESPERA_REINTENTO_S == 5


def test_sin_configuracion_la_conexion_espera_5_segundos(app, monkeypatch):
    tiempos = []
    real = sqlite3.connect
    monkeypatch.setattr(modulo_db.sqlite3, "connect", lambda *a, **k: tiempos.append(k.get("timeout")) or real(*a, **k))
    app.config.pop("DATABASE_TIMEOUT")
    with app.app_context():
        get_db()
    assert tiempos == [5.0]


# ------------------------------------------------------------------ paciente


def test_reservar_con_la_base_ocupada_responde_503_y_se_puede_reintentar(app, pro_id, ana):
    hora = insertar(app, pro_id, "2026-10-12T10:00:00")
    token = extraer_token(ana.get("/paciente/horas").text)
    with retenida(app):
        r = ocupada(ana.post(f"/horas/{hora}/reservar", data={"csrf_token": token}), "/paciente/horas")
    assert "Volver a las horas disponibles" in r.text
    assert fila(app, hora) == ("libre", None, None) and notifs(app) == []
    assert ana.post(f"/horas/{hora}/reservar", data={"csrf_token": token}).status_code == 302
    assert fila(app, hora)[0] == "reservada"


def test_cancelar_con_la_base_ocupada_responde_503_y_se_puede_reintentar(app, pro_id, ana):
    hora = reservada(app, pro_id, "2026-10-12T10:00:00")
    token = extraer_token(ana.get("/paciente").text)
    with retenida(app):
        ocupada(ana.post(f"/horas/{hora}/cancelar", data={"csrf_token": token}), "/paciente")
    assert fila(app, hora)[0] == "reservada" and notifs(app) == []
    assert ana.post(f"/horas/{hora}/cancelar", data={"csrf_token": token}).status_code == 302
    assert fila(app, hora) == ("libre", None, None)


def test_marcar_leidas_del_paciente_con_la_base_ocupada(app, pro_id, ana):
    with app.app_context():
        get_db().execute(
            "INSERT INTO notificaciones (usuario_id, tipo, mensaje, creada_en) VALUES (2, 'confirmacion', 'hola', '2026-10-08T12:00:00-03:00')"
        )
        get_db().commit()
    token = extraer_token(ana.get("/paciente").text)
    with retenida(app):
        ocupada(ana.post("/notificaciones/leidas", data={"csrf_token": token}), "/paciente")
    assert [f[5] for f in notifs(app)] == [0]
    assert ana.post("/notificaciones/leidas", data={"csrf_token": token}).status_code == 302
    assert [f[5] for f in notifs(app)] == [1]


# --------------------------------------------------------------- profesional


def test_marcar_leidas_del_profesional_con_la_base_ocupada(app, pro):
    with app.app_context():
        get_db().execute(
            "INSERT INTO notificaciones (usuario_id, tipo, mensaje, creada_en) VALUES (1, 'confirmacion', 'hola', '2026-10-08T12:00:00-03:00')"
        )
        get_db().commit()
    token = extraer_token(pro.get("/profesional").text)
    with retenida(app):
        ocupada(pro.post("/profesional/notificaciones/leidas", data={"csrf_token": token}), "/profesional")
    assert [f[5] for f in notifs(app)] == [0]
    assert pro.post("/profesional/notificaciones/leidas", data={"csrf_token": token}).status_code == 302


def test_eliminar_con_la_base_ocupada_responde_503_y_se_puede_reintentar(app, pro, pro_id):
    hora = insertar(app, pro_id, "2026-12-01T10:00:00")
    token = extraer_token(pro.get("/profesional").text)
    with retenida(app):
        ocupada(pro.post(f"/profesional/horas/{hora}/eliminar", data={"csrf_token": token}), "/profesional")
    assert fila(app, hora)[0] == "libre"
    assert pro.post(f"/profesional/horas/{hora}/eliminar", data={"csrf_token": token}).status_code == 302
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM horas").fetchone()[0] == 0


def test_agregar_con_la_base_ocupada_devuelve_el_formulario_con_lo_escrito(app, pro):
    token = extraer_token(pro.get("/profesional/horas/nueva").text)
    datos = {"csrf_token": token, "fecha": "2027-03-01", "hora": "10:30", "duracion": "45"}
    with retenida(app):
        r = ocupada(pro.post("/profesional/horas/nueva", data=datos))
    assert 'value="2027-03-01"' in r.text and 'value="10:30"' in r.text and 'value="45"' in r.text
    assert 'role="alert"' in r.text  # el aviso va en el lugar de los errores del formulario
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM horas").fetchone()[0] == 0
    assert pro.post("/profesional/horas/nueva", data=datos).status_code == 302
    with app.app_context():
        assert get_db().execute("SELECT inicio FROM horas").fetchone()[0] == "2027-03-01T10:30:00"


# --------------------------------------------------------------- generales


def test_con_el_bloqueo_total_hasta_una_lectura_da_503(app, ana):
    """Con un escritor confirmando (EXCLUSIVE) hasta los lectores esperan: también es 503."""
    with retenida(app, "EXCLUSIVE"):
        r = ana.get("/paciente")
    ocupada(r)


def test_la_pagina_de_base_ocupada_lleva_las_cabeceras_de_seguridad_y_no_se_almacena(app, ana):
    with retenida(app, "EXCLUSIVE"):
        r = ana.get("/paciente")
    assert "no-store" in r.headers["Cache-Control"] and "default-src 'self'" in r.headers["Content-Security-Policy"]


def test_otro_error_de_sqlite_sigue_siendo_500_y_no_se_disfraza(app, pro_id, ana, monkeypatch):
    from app import paciente

    def falla(*a, **k):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(paciente, "reservar_hora", falla)
    app.config["PROPAGATE_EXCEPTIONS"] = False
    hora = insertar(app, pro_id, "2026-10-12T10:00:00")
    token = extraer_token(ana.get("/paciente/horas").text)
    r = ana.post(f"/horas/{hora}/reservar", data={"csrf_token": token})
    assert r.status_code == 500 and OCUPADO not in r.text


def test_esta_ocupada_distingue_el_bloqueo_de_otros_errores():
    assert modulo_db.esta_ocupada(sqlite3.OperationalError("database is locked"))
    assert modulo_db.esta_ocupada(sqlite3.OperationalError("database table is locked"))
    assert not modulo_db.esta_ocupada(sqlite3.OperationalError("no such table: horas"))
    assert not modulo_db.esta_ocupada(sqlite3.IntegrityError("database is locked"))
    assert not modulo_db.esta_ocupada(ValueError("locked"))


def test_sqlite_locked_real_cuenta_como_ocupada_y_se_ve_por_su_codigo(app):
    """T-14c (e): `SQLITE_LOCKED` (6) es una rama de `esta_ocupada` distinta de `SQLITE_BUSY` (5).

    Se provoca de verdad: dropear una tabla con un cursor abierto sobre ella en la MISMA conexión da
    «database table is locked». La decisión (D-050) es tratarlo como base ocupada (503, reintentar):
    el 503 no filtra el texto de SQLite. Quitar `SQLITE_LOCKED` de la tupla deja esta prueba en rojo
    (el error real lleva `sqlite_errorcode`, así que no entra por la comparación de texto).
    """
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE t (x)")
    con.executemany("INSERT INTO t VALUES (?)", [(1,), (2,)])
    cursor = con.execute("SELECT * FROM t")
    cursor.fetchone()
    with pytest.raises(sqlite3.OperationalError) as dentro:
        con.execute("DROP TABLE t")
    error = dentro.value
    assert error.sqlite_errorcode == sqlite3.SQLITE_LOCKED != sqlite3.SQLITE_BUSY
    assert modulo_db.esta_ocupada(error)
    # También con el código extendido (SQLITE_LOCKED_SHAREDCACHE = 6 | 1 << 8)...
    extendido = sqlite3.OperationalError("database table is locked: t")
    extendido.sqlite_errorcode = sqlite3.SQLITE_LOCKED | (1 << 8)
    assert modulo_db.esta_ocupada(extendido)
    # ...y un código que no es de bloqueo NO cuenta aunque el texto diga «locked» (manda el código).
    otro = sqlite3.OperationalError("database is locked")
    otro.sqlite_errorcode = sqlite3.SQLITE_IOERR
    assert not modulo_db.esta_ocupada(otro)


def test_un_locked_dentro_de_una_peticion_responde_503_sin_filtrar_el_texto(app, pro_id, ana, monkeypatch):
    from app import paciente

    def falla(*a, **k):
        error = sqlite3.OperationalError("database table is locked: horas")
        error.sqlite_errorcode = sqlite3.SQLITE_LOCKED
        raise error

    monkeypatch.setattr(paciente, "reservar_hora", falla)
    hora = insertar(app, pro_id, "2026-10-12T10:00:00")
    token = extraer_token(ana.get("/paciente/horas").text)
    ocupada(ana.post(f"/horas/{hora}/reservar", data={"csrf_token": token}), "/paciente/horas")


def test_el_login_con_la_base_ocupada_sigue_igual_que_antes(app, client):
    crear(app)
    token = extraer_token(client.get("/login").text)
    with retenida(app):
        r = client.post("/login", data={"csrf_token": token, "email": "ana@example.cl", "password": "x"})
    assert r.status_code == 503 and OCUPADO in r.text and r.headers["Retry-After"] == "5"
