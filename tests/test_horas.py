"""T-05: el profesional agrega y elimina horas (US-4, US-5; SPEC §4.2, §4.3, §4.4)."""
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app import auth, profesional, tiempo
from app.db import get_db, init_db
from tests.test_login import crear, iniciar
from tests.test_seguridad import extraer_token

AHORA_REAL = tiempo.ahora_chile  # la función de verdad, antes de que la fixture la reemplace

# "Ahora" fijo (hora de Chile, verano: UTC-3) para que las pruebas no dependan del reloj.
AHORA = datetime(2026, 10, 8, 12, 0)


@pytest.fixture(autouse=True)
def base_inicializada(app):
    with app.app_context():
        init_db()


@pytest.fixture(autouse=True)
def reloj_fijo(monkeypatch):
    monkeypatch.setattr(
        tiempo, "ahora_chile", lambda: AHORA.replace(tzinfo=auth.zona_chile())
    )


@pytest.fixture
def pro(app):
    crear(app, email="pro@example.cl", rol="profesional", nombre="Dr. Pro")
    client = app.test_client()
    iniciar(client, "pro@example.cl")
    return client


@pytest.fixture
def pro2(app):
    crear(app, email="pro2@example.cl", rol="profesional", nombre="Dra. Dos")
    client = app.test_client()
    iniciar(client, "pro2@example.cl")
    return client


@pytest.fixture
def paciente(app):
    crear(app, email="ana@example.cl", rol="paciente", nombre="Ana Pérez")
    client = app.test_client()
    iniciar(client, "ana@example.cl")
    return client


def consultar(app, sql, *params):
    with app.app_context():
        return [tuple(f) for f in get_db().execute(sql, params).fetchall()]


def horas(app):
    return consultar(app, "SELECT inicio, duracion_min, estado FROM horas ORDER BY inicio")


def usuario_id(app, email):
    return consultar(app, "SELECT id FROM usuarios WHERE email = ?", email)[0][0]


def agregar(client, fecha, hora, duracion="50", token=True):
    datos = {"fecha": fecha, "hora": hora, "duracion": duracion}
    if token:
        datos["csrf_token"] = extraer_token(client.get("/profesional/horas/nueva").text)
    return client.post("/profesional/horas/nueva", data=datos)


def insertar(app, email, inicio, duracion=50):
    with app.app_context():
        db = get_db()
        cursor = db.execute(
            "INSERT INTO horas (profesional_id, inicio, duracion_min) VALUES (?, ?, ?)",
            (usuario_id(app, email), inicio, duracion),
        )
        db.commit()
        return cursor.lastrowid


def eliminar(client, hora_id, token=True):
    datos = {}
    if token:
        datos["csrf_token"] = extraer_token(client.get("/profesional").text)
    return client.post(f"/profesional/horas/{hora_id}/eliminar", data=datos)


# ---------------------------------------------------------------- agregar ----


def test_formulario_get_tiene_token_y_duracion_por_defecto(pro):
    r = pro.get("/profesional/horas/nueva")
    assert r.status_code == 200
    assert 'name="csrf_token"' in r.text
    assert 'name="duracion" value="50"' in r.text


def test_crear_hora_valida_guarda_formato_canonico(app, pro):
    r = agregar(pro, "2026-12-01", "10:00", "50")
    assert (r.status_code, r.headers["Location"]) == (302, "/profesional")
    assert horas(app) == [("2026-12-01T10:00:00", 50, "libre")]
    r = pro.get("/profesional")
    assert "La hora se agregó correctamente." in r.text
    assert "01-12-2026 10:00" in r.text


def test_la_hora_queda_a_nombre_del_profesional_de_la_sesion(app, pro, pro2):
    agregar(pro, "2026-12-01", "10:00")
    assert consultar(app, "SELECT profesional_id FROM horas") == [
        (usuario_id(app, "pro@example.cl"),)
    ]


def test_duracion_vacia_usa_el_valor_por_defecto(app, pro):
    agregar(pro, "2026-12-01", "10:00", "")
    assert horas(app) == [("2026-12-01T10:00:00", 50, "libre")]


@pytest.mark.parametrize("duracion", ["1", "30", "480"])
def test_duraciones_validas(app, pro, duracion):
    agregar(pro, "2026-12-01", "10:00", duracion)
    assert horas(app)[0][1] == int(duracion)


def test_los_espacios_alrededor_se_ignoran_y_se_guarda_texto_canonico(app, pro):
    agregar(pro, " 2026-12-01 ", " 09:05 ", " 45 ")
    assert horas(app) == [("2026-12-01T09:05:00", 45, "libre")]


def test_el_texto_del_formulario_nunca_se_guarda_tal_cual(app, pro, monkeypatch):
    """`inicio` sale de formatear un datetime, no de los campos del formulario."""
    llamadas = []
    original = profesional.formatear_inicio

    def espia(inicio):
        llamadas.append(inicio)
        return original(inicio)

    monkeypatch.setattr(profesional, "formatear_inicio", espia)
    agregar(pro, "2026-12-01", "10:00")
    assert llamadas == [datetime(2026, 12, 1, 10, 0)]


def test_anio_bisiesto_real_se_acepta(app, pro):
    agregar(pro, "2028-02-29", "10:00")
    assert horas(app) == [("2028-02-29T10:00:00", 50, "libre")]


@pytest.mark.parametrize(
    "fecha",
    [
        "2026-02-30", "2026-02-29", "2027-02-29", "2026-13-01", "2026-12-32",
        "2026-00-10", "2026-12-00", "2026-04-31", "0000-01-01", "2026-1-01",
        "20261201", "2026/12/01", "01-12-2026", "2026-12-01T10:00", "2026-12-01\n12",
        "２０２６-12-01", "٢٠٢٦-12-01", "abc", "", "2026-12-01 10:00", "9999-99-99",
    ],
)
def test_fechas_invalidas_se_rechazan(app, pro, fecha):
    r = agregar(pro, fecha, "10:00")
    assert r.status_code == 200
    assert "Escribe una fecha válida" in r.text
    assert horas(app) == []


@pytest.mark.parametrize(
    "hora",
    ["24:00", "10:60", "99:99", "10:5", "1000", "10", "10:00:00", "１０:００", "ab:cd", "", "-1:00", "10:00\n30"],
)
def test_horas_invalidas_se_rechazan(app, pro, hora):
    r = agregar(pro, "2026-12-01", hora)
    assert r.status_code == 200
    assert "Escribe una hora válida" in r.text
    assert horas(app) == []


@pytest.mark.parametrize(
    "duracion",
    [
        "0", "0000", "-5", "-1", "+5", "5.0", "0.5", ".5", "1e2", "1e30", "abc", "481",
        "9999", "99999", "٥٠", "５０", "0x10", "5 0", "NaN", "inf", "50\x00",
    ],
)
def test_duraciones_invalidas_se_rechazan(app, pro, duracion):
    r = agregar(pro, "2026-12-01", "10:00", duracion)
    assert r.status_code == 200
    assert "La duración debe ser un número entero de minutos" in r.text
    assert horas(app) == []


def test_varios_errores_se_muestran_juntos(app, pro):
    r = agregar(pro, "2026-02-30", "25:00", "0")
    assert "fecha válida" in r.text and "hora válida" in r.text and "duración" in r.text
    assert horas(app) == []


def test_el_formulario_devuelve_lo_escrito_escapado(app, pro):
    r = agregar(pro, '"><script>x</script>', "10:00")
    assert "<script>x</script>" not in r.text
    assert "&lt;script&gt;" in r.text


# ----------------------------------------------------------------- pasado ----


@pytest.mark.parametrize(
    "fecha, hora",
    [
        ("2026-10-07", "23:59"),  # ayer
        ("2026-10-08", "09:00"),  # hoy, antes
        ("2026-10-08", "11:59"),
        ("2026-10-08", "12:00"),  # justo ahora cuenta como pasado
        ("2020-01-01", "10:00"),
        ("2000-02-29", "10:00"),
    ],
)
def test_no_se_crean_horas_en_el_pasado(app, pro, fecha, hora):
    r = agregar(pro, fecha, hora)
    assert r.status_code == 200
    assert "Esa hora ya pasó" in r.text
    assert horas(app) == []


def test_un_minuto_despues_de_ahora_se_acepta(app, pro):
    agregar(pro, "2026-10-08", "12:01")
    assert horas(app) == [("2026-10-08T12:01:00", 50, "libre")]


def test_el_pasado_se_juzga_con_la_hora_de_chile_y_no_la_del_servidor(app, pro, monkeypatch):
    """12:00 en Chile (UTC-3) son las 15:00 UTC: 12:30 chilenas aún es futuro."""
    agregar(pro, "2026-10-08", "12:30")
    assert horas(app) == [("2026-10-08T12:30:00", 50, "libre")]


def test_el_reloj_de_verdad_da_la_hora_de_chile():
    """`ahora_chile` es el instante actual visto en America/Santiago (con su zona),
    no la hora del servidor ni UTC con otra etiqueta."""
    ahora = AHORA_REAL()
    assert ahora.tzinfo is auth.zona_chile()
    assert abs(ahora - datetime.now(timezone.utc)) < timedelta(seconds=5)
    assert ahora.utcoffset() in (timedelta(hours=-3), timedelta(hours=-4))
    assert ahora.utcoffset() == datetime.now(auth.zona_chile()).utcoffset()


# ---------------------------------------------- horario de verano (D-025) ----


def con_reloj(monkeypatch, ano, mes, dia):
    monkeypatch.setattr(
        tiempo, "ahora_chile", lambda: datetime(ano, mes, dia, 8, 0, tzinfo=auth.zona_chile())
    )


@pytest.mark.parametrize("hora", ["00:00", "00:30", "00:59"])
def test_hora_que_no_existe_por_el_cambio_a_verano_se_rechaza(app, pro, monkeypatch, hora):
    con_reloj(monkeypatch, 2027, 9, 1)
    r = agregar(pro, "2027-09-05", hora)
    assert "Esa hora no existe en Chile" in r.text
    assert horas(app) == []


@pytest.mark.parametrize("hora", ["23:00", "23:30", "23:59"])
def test_hora_repetida_por_el_cambio_a_invierno_se_rechaza(app, pro, monkeypatch, hora):
    con_reloj(monkeypatch, 2027, 3, 30)
    r = agregar(pro, "2027-04-03", hora)
    assert "ocurre dos veces" in r.text
    assert horas(app) == []


@pytest.mark.parametrize(
    "fecha, hora",
    [
        ("2027-09-04", "23:59"),  # justo antes del salto
        ("2027-09-05", "01:00"),  # justo después
        ("2027-04-03", "22:59"),  # justo antes de la hora repetida
        ("2027-04-04", "00:00"),  # justo después
        ("2027-04-03", "12:00"),
        ("2027-07-15", "00:30"),  # 00:30 en un día normal sí existe
    ],
)
def test_horas_vecinas_al_cambio_de_horario_se_aceptan(app, pro, monkeypatch, fecha, hora):
    con_reloj(monkeypatch, 2027, 1, 10)
    agregar(pro, fecha, hora)
    assert len(horas(app)) == 1


# ----------------------------------------------------------------- solape ----

BASE = ("2027-03-01", "10:00")  # ocupa 10:00 a 10:50


@pytest.fixture
def con_base(app, pro):
    agregar(pro, *BASE, "50")
    assert len(horas(app)) == 1
    return pro


@pytest.mark.parametrize(
    "hora, duracion, caso",
    [
        ("10:25", "50", "parcial: empieza dentro de la existente"),
        ("09:30", "50", "parcial: termina dentro de la existente"),
        ("10:49", "30", "empieza un minuto antes de que termine"),
        ("09:11", "50", "termina un minuto después de que empieza"),
        ("10:00", "10", "mismo inicio, más corta"),
        ("10:00", "120", "mismo inicio, más larga"),
        ("10:10", "10", "contenida"),
        ("09:00", "180", "contiene a la existente"),
        ("09:59", "52", "contiene a la existente con margen mínimo"),
    ],
)
def test_solapes_se_rechazan(app, con_base, hora, duracion, caso):
    r = agregar(con_base, BASE[0], hora, duracion)
    assert r.status_code == 200, caso
    assert "se solapa con otra que ya publicaste" in r.text, caso
    assert "01-03-2027 10:00 a 10:50" in r.text, caso
    assert horas(app) == [("2027-03-01T10:00:00", 50, "libre")], caso


@pytest.mark.parametrize(
    "hora, duracion",
    [("10:50", "50"), ("09:10", "50"), ("09:00", "60"), ("11:00", "50"), ("08:00", "30")],
)
def test_horas_adyacentes_o_separadas_se_permiten(app, con_base, hora, duracion):
    agregar(con_base, BASE[0], hora, duracion)
    assert len(horas(app)) == 2


def test_otro_dia_a_la_misma_hora_no_es_solape(app, con_base):
    agregar(con_base, "2027-03-02", "10:00")
    assert len(horas(app)) == 2


def test_el_solape_cruza_la_medianoche(app, pro):
    agregar(pro, "2027-03-01", "23:30", "90")  # hasta las 01:00 del día 2
    agregar(pro, "2027-03-02", "00:30", "30")
    assert len(horas(app)) == 1
    agregar(pro, "2027-03-02", "01:00", "30")
    assert len(horas(app)) == 2


def test_solo_cuentan_las_horas_del_mismo_profesional(app, con_base, pro2):
    agregar(pro2, *BASE, "50")  # exactamente la misma hora, otro profesional
    agregar(pro2, BASE[0], "11:00", "50")  # adyacente a la de pro2, sin tocar la de pro
    assert len(horas(app)) == 3
    assert consultar(app, "SELECT COUNT(*) FROM horas WHERE profesional_id = ?",
                     usuario_id(app, "pro2@example.cl")) == [(2,)]


def test_la_hora_de_otro_profesional_no_bloquea_ni_es_bloqueada(app, pro, pro2):
    insertar(app, "pro2@example.cl", "2027-03-01T10:00:00")
    agregar(pro, *BASE, "50")
    assert consultar(app, "SELECT COUNT(*) FROM horas WHERE profesional_id = ?",
                     usuario_id(app, "pro@example.cl")) == [(1,)]
    agregar(pro2, BASE[0], "10:25", "50")  # pro2 sí choca con la suya, no con la de pro
    assert len(horas(app)) == 2


def test_una_hora_reservada_tambien_bloquea(app, con_base):
    crear(app, email="ana@example.cl")
    ana = usuario_id(app, "ana@example.cl")
    with app.app_context():
        db = get_db()
        db.execute(
            "UPDATE horas SET estado='reservada', paciente_id=?, reservada_en='2026-10-08T12:00:00'",
            (ana,),
        )
        db.commit()
    r = agregar(con_base, BASE[0], "10:25")
    assert "se solapa" in r.text
    assert len(horas(app)) == 1


def test_un_rechazo_por_solape_no_deja_la_transaccion_abierta(app, con_base):
    with app.app_context():
        db = get_db()
        mensaje = profesional.crear_hora(
            db, usuario_id(app, "pro@example.cl"), datetime(2027, 3, 1, 10, 25), 50
        )
        assert "se solapa" in mensaje
        assert db.in_transaction is False


def test_la_comprobacion_y_el_insert_van_bajo_un_bloqueo_de_escritura(app, pro, monkeypatch):
    """BEGIN IMMEDIATE: entre comprobar y guardar nadie más puede escribir.

    Mientras la aplicación ya comprobó el solape y aún no inserta, otra conexión
    intenta insertar una hora solapada. Con BEGIN IMMEDIATE queda bloqueada
    (`database is locked`); con una transacción diferida o sin ella, entra y
    quedarían dos horas solapadas.
    """
    resultado = {}
    original = profesional.buscar_solape

    def comprobar_y_competir(db, profesional_id, inicio, duracion):
        encontrado = original(db, profesional_id, inicio, duracion)
        rival = sqlite3.connect(app.config["DATABASE"], timeout=0.05)
        try:
            rival.execute(
                "INSERT INTO horas (profesional_id, inicio, duracion_min) VALUES (?, ?, ?)",
                (profesional_id, "2027-03-01T10:10:00", 50),
            )
            rival.commit()
            resultado["rival"] = "entró"
        except sqlite3.OperationalError as error:
            resultado["rival"] = str(error)
        finally:
            rival.close()
        return encontrado

    monkeypatch.setattr(profesional, "buscar_solape", comprobar_y_competir)
    agregar(pro, *BASE, "50")
    assert resultado["rival"] == "database is locked"
    assert horas(app) == [("2027-03-01T10:00:00", 50, "libre")]


def test_la_transaccion_se_abre_con_begin_immediate_antes_de_cualquier_otra_sentencia(app, pro):
    """Con un BEGIN diferido el bloqueo de escritura llegaría tarde (al INSERT) y
    otra petición podría ganarlo; por eso la primera sentencia debe ser BEGIN IMMEDIATE."""
    sentencias = []
    with app.app_context():
        db = get_db()
        db.set_trace_callback(sentencias.append)
        profesional.crear_hora(db, usuario_id(app, "pro@example.cl"), datetime(2027, 3, 1, 10, 0), 50)
    assert sentencias[0] == "BEGIN IMMEDIATE"
    assert sentencias[1].lstrip().upper().startswith("SELECT")
    assert sentencias[2].lstrip().upper().startswith("INSERT INTO HORAS")
    assert sentencias[3] == "COMMIT"


def test_un_integrity_error_se_traduce_a_mensaje_y_no_a_500(app, pro, monkeypatch):
    monkeypatch.setattr(profesional, "formatear_inicio", lambda inicio: "2026-13-45 99:99")
    r = agregar(pro, "2026-12-01", "10:00")
    assert r.status_code == 200
    assert "No pudimos guardar la hora" in r.text
    assert horas(app) == []


def test_la_base_sigue_rechazando_inicios_identicos_aunque_se_salte_la_aplicacion(app, pro):
    insertar(app, "pro@example.cl", "2027-03-01T10:00:00")
    with pytest.raises(sqlite3.IntegrityError):
        insertar(app, "pro@example.cl", "2027-03-01T10:00:00")


# --------------------------------------------------------------- eliminar ----


def test_eliminar_una_hora_libre(app, pro):
    hora_id = insertar(app, "pro@example.cl", "2027-03-01T10:00:00")
    r = eliminar(pro, hora_id)
    assert (r.status_code, r.headers["Location"]) == (302, "/profesional")
    assert horas(app) == []
    assert "La hora se eliminó correctamente." in pro.get("/profesional").text


def test_no_se_elimina_una_hora_reservada(app, pro):
    hora_id = insertar(app, "pro@example.cl", "2027-03-01T10:00:00")
    crear(app, email="ana@example.cl")
    with app.app_context():
        db = get_db()
        db.execute(
            "UPDATE horas SET estado='reservada', paciente_id=?, reservada_en=? WHERE id=?",
            (usuario_id(app, "ana@example.cl"), "2026-10-08T12:00:00", hora_id),
        )
        db.commit()
    r = eliminar(pro, hora_id)
    assert r.status_code == 302
    assert horas(app) == [("2027-03-01T10:00:00", 50, "reservada")]
    assert "No se puede eliminar una hora reservada" in pro.get("/profesional").text


def test_reservar_cancelar_y_eliminar_conserva_las_notificaciones(app, pro):
    """D-016: con claves foráneas activas la hora cancelada se elimina y las
    notificaciones quedan con `hora_id` NULL y el mensaje intacto."""
    hora_id = insertar(app, "pro@example.cl", "2027-03-01T10:00:00")
    crear(app, email="ana@example.cl")
    ana, doc = usuario_id(app, "ana@example.cl"), usuario_id(app, "pro@example.cl")
    with app.app_context():
        db = get_db()
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        # reserva (simulada con SQL: T-07 aún no existe)
        db.execute(
            "UPDATE horas SET estado='reservada', paciente_id=?, reservada_en=? WHERE id=?",
            (ana, "2026-10-08T12:00:00", hora_id),
        )
        for usuario, tipo, mensaje in [
            (ana, "confirmacion", "Reservaste el 01-03-2027 a las 10:00"),
            (doc, "confirmacion", "Ana reservó el 01-03-2027 a las 10:00"),
        ]:
            db.execute(
                "INSERT INTO notificaciones (usuario_id, tipo, mensaje, hora_id, creada_en)"
                " VALUES (?, ?, ?, ?, '2026-10-08T12:00:00')",
                (usuario, tipo, mensaje, hora_id),
            )
        # cancelación (simulada): la hora vuelve a libre y se limpian los campos
        db.execute(
            "UPDATE horas SET estado='libre', paciente_id=NULL, reservada_en=NULL WHERE id=?",
            (hora_id,),
        )
        for usuario, mensaje in [
            (ana, "Cancelaste la hora del 01-03-2027 a las 10:00"),
            (doc, "Ana canceló la hora del 01-03-2027 a las 10:00"),
        ]:
            db.execute(
                "INSERT INTO notificaciones (usuario_id, tipo, mensaje, hora_id, creada_en)"
                " VALUES (?, 'cancelacion', ?, ?, '2026-10-08T13:00:00')",
                (usuario, mensaje, hora_id),
            )
        db.commit()
    antes = consultar(app, "SELECT id, usuario_id, tipo, mensaje, leida FROM notificaciones ORDER BY id")
    assert len(antes) == 4

    r = eliminar(pro, hora_id)
    assert r.status_code == 302
    assert "La hora se eliminó correctamente." in pro.get("/profesional").text
    assert horas(app) == []
    despues = consultar(app, "SELECT id, usuario_id, tipo, mensaje, leida FROM notificaciones ORDER BY id")
    assert despues == antes
    assert consultar(app, "SELECT hora_id FROM notificaciones") == [(None,)] * 4
    assert consultar(app, "PRAGMA foreign_key_check") == []


def test_no_se_pueden_eliminar_horas_de_otro_profesional(app, pro, pro2):
    ajena = insertar(app, "pro2@example.cl", "2027-03-01T10:00:00")
    r = eliminar(pro, ajena)
    assert r.status_code == 404
    assert horas(app) == [("2027-03-01T10:00:00", 50, "libre")]


def test_eliminar_una_hora_reservada_de_otro_profesional_tampoco_la_revela(app, pro, pro2):
    ajena = insertar(app, "pro2@example.cl", "2027-03-01T10:00:00")
    crear(app, email="ana@example.cl")
    with app.app_context():
        db = get_db()
        db.execute(
            "UPDATE horas SET estado='reservada', paciente_id=?, reservada_en='2026-10-08T12:00:00'",
            (usuario_id(app, "ana@example.cl"),),
        )
        db.commit()
    assert eliminar(pro, ajena).status_code == 404  # igual que si no existiera


@pytest.mark.parametrize("hora_id", ["99999", "0", "-1", "abc", "1.5", str(2**63 - 1), str(2**63), str(2**64), "9" * 40])
def test_ids_inexistentes_o_fuera_de_rango_dan_404_y_no_500(pro, hora_id):
    token = extraer_token(pro.get("/profesional").text)
    r = pro.post(f"/profesional/horas/{hora_id}/eliminar", data={"csrf_token": token})
    assert r.status_code == 404


def test_eliminar_exige_post(app, pro):
    hora_id = insertar(app, "pro@example.cl", "2027-03-01T10:00:00")
    assert pro.get(f"/profesional/horas/{hora_id}/eliminar").status_code == 405
    assert len(horas(app)) == 1


# ------------------------------------------------- CSRF, rol y sin sesión ----


def test_agregar_sin_token_csrf_da_400(app, pro):
    r = agregar(pro, "2026-12-01", "10:00", token=False)
    assert r.status_code == 400
    assert horas(app) == []


def test_agregar_con_token_de_otra_sesion_da_400(app, pro, pro2):
    ajeno = extraer_token(pro2.get("/profesional/horas/nueva").text)
    r = pro.post(
        "/profesional/horas/nueva",
        data={"fecha": "2026-12-01", "hora": "10:00", "duracion": "50", "csrf_token": ajeno},
    )
    assert r.status_code == 400
    assert horas(app) == []


def test_eliminar_sin_token_csrf_da_400(app, pro):
    hora_id = insertar(app, "pro@example.cl", "2027-03-01T10:00:00")
    assert eliminar(pro, hora_id, token=False).status_code == 400
    assert len(horas(app)) == 1


def test_paciente_no_puede_ver_ni_usar_el_formulario(app, paciente):
    assert paciente.get("/profesional/horas/nueva").status_code == 403
    token = extraer_token(paciente.get("/paciente").text)
    r = paciente.post(
        "/profesional/horas/nueva",
        data={"fecha": "2026-12-01", "hora": "10:00", "duracion": "50", "csrf_token": token},
    )
    assert r.status_code == 403
    assert horas(app) == []


def test_paciente_no_puede_eliminar_horas(app, paciente):
    crear(app, email="pro@example.cl", rol="profesional")
    hora_id = insertar(app, "pro@example.cl", "2027-03-01T10:00:00")
    token = extraer_token(paciente.get("/paciente").text)
    r = paciente.post(f"/profesional/horas/{hora_id}/eliminar", data={"csrf_token": token})
    assert r.status_code == 403
    assert len(horas(app)) == 1


def test_sin_sesion_se_redirige_al_login_y_no_se_modifica_nada(app, client):
    crear(app, email="pro@example.cl", rol="profesional")
    hora_id = insertar(app, "pro@example.cl", "2027-03-01T10:00:00")
    token = extraer_token(client.get("/login").text)
    assert client.get("/profesional/horas/nueva").headers["Location"] == "/login"
    r = client.post(
        "/profesional/horas/nueva",
        data={"fecha": "2026-12-01", "hora": "10:00", "duracion": "50", "csrf_token": token},
    )
    assert (r.status_code, r.headers["Location"]) == (302, "/login")
    r = client.post(f"/profesional/horas/{hora_id}/eliminar", data={"csrf_token": token})
    assert (r.status_code, r.headers["Location"]) == (302, "/login")
    assert horas(app) == [("2027-03-01T10:00:00", 50, "libre")]


def test_las_paginas_nuevas_llevan_no_store(pro):
    assert pro.get("/profesional/horas/nueva").headers["Cache-Control"] == "no-store"
    assert pro.get("/profesional").headers["Cache-Control"] == "no-store"


# ------------------------------------------------------------- el listado ----


def test_el_panel_lista_solo_horas_futuras_propias_con_su_estado(app, pro, pro2):
    insertar(app, "pro@example.cl", "2026-10-07T10:00:00")  # pasada: no sale
    insertar(app, "pro@example.cl", "2026-10-08T11:00:00")  # pasada (antes de las 12:00)
    libre = insertar(app, "pro@example.cl", "2027-03-01T10:00:00", 50)
    reservada = insertar(app, "pro@example.cl", "2027-03-02T11:30:00", 45)
    insertar(app, "pro2@example.cl", "2027-04-01T09:00:00")  # de otro profesional
    crear(app, email="ana@example.cl")
    with app.app_context():
        db = get_db()
        db.execute(
            "UPDATE horas SET estado='reservada', paciente_id=?, reservada_en='2026-10-08T12:00:00'"
            " WHERE id=?",
            (usuario_id(app, "ana@example.cl"), reservada),
        )
        db.commit()
    html = pro.get("/profesional").text
    assert "01-03-2027 10:00" in html and "02-03-2027 11:30" in html
    assert "07-10-2026" not in html and "08-10-2026" not in html and "01-04-2027" not in html
    assert "45 min" in html
    assert f"/profesional/horas/{libre}/eliminar" in html
    assert f"/profesional/horas/{reservada}/eliminar" not in html  # sin botón si está reservada
    assert html.count("Reservada") == 1 and "Libre" in html
    assert html.index("01-03-2027") < html.index("02-03-2027")  # ordenadas por fecha


def test_panel_sin_horas(pro):
    assert "Aún no tienes horas publicadas." in pro.get("/profesional").text


# ----------------------------------------------------- vigilancia del código ----

PROHIBIDO = re.compile(r"insert\s+or\s+replace|replace\s+into", re.IGNORECASE)


def test_el_detector_de_replace_reconoce_las_variantes():
    for texto in [
        "INSERT OR REPLACE INTO horas",
        "insert or replace into horas",
        "INSERT  OR\n  REPLACE INTO horas",
        "REPLACE INTO horas (id)",
        "replace\tinto horas",
    ]:
        assert PROHIBIDO.search(texto), texto
    assert not PROHIBIDO.search("SELECT replace(nombre, 'a', 'b') FROM usuarios")


def test_ningun_codigo_de_la_app_usa_replace_sobre_horas():
    """D-016: INSERT OR REPLACE / REPLACE INTO borra y reinserta la fila, lo que
    dispara ON DELETE SET NULL y deja huérfanas las notificaciones sin avisar."""
    codigo = Path(profesional.__file__).parent
    archivos = [*codigo.glob("*.py"), *codigo.glob("templates/*.html")]
    assert len(archivos) > 5
    culpables = [a.name for a in archivos if PROHIBIDO.search(a.read_text(encoding="utf-8"))]
    assert culpables == []


# ------------------------------------------- T-05b: tope de fecha (D-026) ----

LIMITE = "08-10-2028"  # AHORA es 2026-10-08: el tope es hoy + 2 años


@pytest.mark.parametrize("fecha", ["2028-10-09", "2028-12-31", "2029-01-01", "2100-01-01", "2500-01-01", "9999-12-31"])
def test_fecha_posterior_al_tope_se_rechaza_en_el_campo_fecha(app, pro, fecha):
    r = agregar(pro, fecha, "10:00")
    assert r.status_code == 200
    assert f"Elige una fecha hasta el {LIMITE}" in r.text
    assert "máximo 2 años desde hoy" in r.text
    # el mensaje sale bajo «Fecha», no bajo «Hora» (R-05, M12)
    assert r.text.index("demasiado lejos") < r.text.index('id="hora"')
    assert horas(app) == []


@pytest.mark.parametrize("fecha, hora", [("2028-10-08", "00:00"), ("2028-10-08", "12:00"), ("2028-10-08", "23:59"), ("2028-10-07", "10:00")])
def test_el_ultimo_dia_permitido_se_acepta_entero(app, pro, fecha, hora):
    agregar(pro, fecha, hora)
    assert horas(app) == [(f"{fecha}T{hora}:00", 50, "libre")]


def test_el_tope_no_depende_de_la_hora_ni_de_la_duracion(app, pro):
    r = agregar(pro, "2028-10-09", "00:00", "1")
    assert "demasiado lejos" in r.text
    r = agregar(pro, "2028-10-08", "23:59", "480")  # empieza el último día y termina después: vale
    assert r.status_code == 302


def test_fecha_lejana_y_hora_invalida_muestran_ambos_errores(app, pro):
    r = agregar(pro, "9999-12-31", "25:00")
    assert "demasiado lejos" in r.text and "Escribe una hora válida" in r.text


def test_el_tope_se_mueve_con_el_dia_de_hoy(app, pro, monkeypatch):
    con_reloj(monkeypatch, 2026, 12, 31)  # hoy + 2 años = 2028-12-31
    agregar(pro, "2028-12-31", "10:00")
    r = agregar(pro, "2029-01-01", "10:00")
    assert "Elige una fecha hasta el 31-12-2028" in r.text
    assert horas(app) == [("2028-12-31T10:00:00", 50, "libre")]


def test_el_tope_si_hoy_es_29_de_febrero_es_el_28_de_febrero(app, pro, monkeypatch):
    con_reloj(monkeypatch, 2028, 2, 29)  # 2030 no es bisiesto
    agregar(pro, "2030-02-28", "10:00")
    r = agregar(pro, "2030-03-01", "10:00")
    assert "Elige una fecha hasta el 28-02-2030" in r.text
    assert horas(app) == [("2030-02-28T10:00:00", 50, "libre")]


def test_fecha_limite_directa():
    from datetime import date

    assert profesional.fecha_limite(date(2026, 10, 8)) == date(2028, 10, 8)
    assert profesional.fecha_limite(date(2028, 2, 29)) == date(2030, 2, 28)
    assert profesional.fecha_limite(date(2026, 12, 31)) == date(2028, 12, 31)


def test_r01_no_hay_500_con_una_hora_en_el_anio_9999_ya_guardada(app, pro):
    """Escenario del revisor: una fila 9999-12-31 23:59 (insertada por otro camino)
    y luego un intento en esa fecha: ya no hay 500, se rechaza por el tope."""
    insertar(app, "pro@example.cl", "9999-12-31T23:59:00")
    r = agregar(pro, "9999-12-31", "23:58")
    assert r.status_code == 200 and "demasiado lejos" in r.text
    r = agregar(pro, "2027-03-01", "10:00")  # y una hora normal se agrega sin problema
    assert r.status_code == 302


FILAS_RARAS = [
    ("9999-12-31T23:59:00", 50),
    ("9999-12-31T00:00:00", 2**62),
    ("0001-01-01T00:00:00", 50),
    ("0000-00-00T00:00:00", 50),
    ("2026-13-45T99:99:99", 50),
    ("2027-02-30T10:00:00", 50),
    ("2027-03-01T10:00:00", 10**18),
    ("2027-03-01T10:00:00", 1e30),
    ("2027-03-01T10:00:00", "abc"),
    ("2027-03-01T10:00:00", 0.5),
]


@pytest.mark.parametrize("inicio, duracion", FILAS_RARAS)
def test_describir_y_mostrar_nunca_lanzan_con_filas_que_el_esquema_acepta(app, pro, inicio, duracion):
    insertar(app, "pro@example.cl", inicio, duracion)
    with app.app_context():
        db = get_db()
        fila = db.execute("SELECT inicio, duracion_min FROM horas").fetchone()
        assert isinstance(profesional._describir(fila), str)
        assert isinstance(profesional.mostrar_inicio(fila["inicio"]), str)
        # buscar_solape tampoco lanza, y una hora normal nueva se puede evaluar
        profesional.buscar_solape(db, usuario_id(app, "pro@example.cl"), datetime(2027, 3, 1, 10, 25), 50)
    r = agregar(pro, "2027-03-05", "10:00")
    assert r.status_code in (200, 302)


def test_describir_con_fin_calculable_da_inicio_y_fin(app, pro):
    with app.app_context():
        fila = {"inicio": "2027-03-01T10:00:00", "duracion_min": 50}
        assert profesional._describir(fila) == "01-03-2027 10:00 a 10:50"
        # solo el inicio cuando no se puede calcular el fin
        fila = {"inicio": "2026-13-45T99:99:99", "duracion_min": 50}
        assert profesional._describir(fila) == "45-13-2026 99:99"


# ------------------------------- T-05b: solape con instantes absolutos (D-026) ----

CHILE = ZoneInfo("America/Santiago")


def segundos_utc_oraculo(local):
    """Referencia independiente: epoch del reloj de Chile con la librería estándar."""
    return int(local.replace(tzinfo=CHILE, fold=0).timestamp())


def solapa(app, email, nueva, duracion):
    with app.app_context():
        return profesional.buscar_solape(get_db(), usuario_id(app, email), nueva, duracion) is not None


def test_a_segundos_utc_usa_el_desfase_de_chile():
    # verano (UTC-3) e invierno (UTC-4); un mutante "reloj de pared" (UTC) daría 10:00Z
    assert tiempo.a_segundos_utc(datetime(2027, 3, 1, 10, 0)) == int(
        datetime(2027, 3, 1, 13, 0, tzinfo=timezone.utc).timestamp()
    )
    assert tiempo.a_segundos_utc(datetime(2027, 7, 1, 10, 0)) == int(
        datetime(2027, 7, 1, 14, 0, tzinfo=timezone.utc).timestamp()
    )


def test_a_segundos_utc_acepta_horas_inexistentes_o_repetidas_y_fuera_de_rango():
    assert tiempo.a_segundos_utc(datetime(2027, 9, 5, 0, 30)) is not None  # no existe
    assert tiempo.a_segundos_utc(datetime(2027, 4, 3, 23, 30)) is not None  # se repite
    tiempo.a_segundos_utc(datetime(1, 1, 1))  # no lanza (devuelve un valor o None)
    assert tiempo.a_segundos_utc(datetime(9999, 12, 31, 23, 59)) is None


def test_septiembre_50_min_desde_las_2330_pisan_la_1_del_domingo(app, pro):
    """R-03: el sábado 2027-09-04 a las 24:00 el reloj salta a las 01:00. Una hora
    de 50 min desde las 23:30 termina a las 01:20 de reloj (00:20 «de pared»)."""
    agregar_pro = lambda f, h, d="50": agregar(pro, f, h, d)  # noqa: E731
    agregar_pro("2027-09-04", "23:30")
    assert len(horas(app)) == 1
    r = agregar_pro("2027-09-05", "01:00")
    assert "se solapa con otra que ya publicaste" in r.text
    assert "04-09-2027 23:30 a 01:20" in r.text  # el fin se muestra en hora de reloj real
    r = agregar_pro("2027-09-05", "01:19", "10")
    assert "se solapa" in r.text
    assert len(horas(app)) == 1
    agregar_pro("2027-09-05", "01:20")  # pegada: se acepta
    assert len(horas(app)) == 2


def test_septiembre_la_hora_nueva_anterior_tambien_choca_con_la_existente(app, pro):
    insertar(app, "pro@example.cl", "2027-09-05T01:00:00", 50)
    r = agregar(pro, "2027-09-04", "23:30")
    assert "se solapa" in r.text
    assert len(horas(app)) == 1
    agregar(pro, "2027-09-04", "23:10")  # termina a las 01:00 de reloj: pegada
    assert len(horas(app)) == 2


def test_abril_120_min_desde_las_2230_no_pisan_las_00_del_domingo(app, pro):
    """R-03: en abril el reloj se atrasa a las 24:00 -> 23:00. 120 min desde las
    22:30 terminan a las 23:30 de reloj (segunda pasada); no hay solape con las 00:00."""
    agregar(pro, "2027-04-03", "22:30", "120")
    assert len(horas(app)) == 1
    r = agregar(pro, "2027-04-04", "00:00")
    assert r.status_code == 302
    assert len(horas(app)) == 2


def test_abril_la_hora_de_las_00_del_domingo_no_pisa_a_la_de_antes_en_orden_inverso(app, pro):
    insertar(app, "pro@example.cl", "2027-04-04T00:00:00", 50)
    r = agregar(pro, "2027-04-03", "22:30", "120")
    assert r.status_code == 302
    assert len(horas(app)) == 2


def test_abril_120_min_desde_las_2230_si_pisan_una_hora_dentro_de_su_duracion_real(app, pro):
    """[22:30, 23:30) de reloj real: una hora insertada a las 23:30 (fold=0, = 02:30Z)
    queda dentro de [01:30Z, 03:30Z); una a las 00:00 del domingo (04:00Z) no la pisa."""
    insertar(app, "pro@example.cl", "2027-04-03T22:30:00", 120)
    assert solapa(app, "pro@example.cl", datetime(2027, 4, 3, 22, 45), 10) is True
    assert solapa(app, "pro@example.cl", datetime(2027, 4, 3, 23, 30), 10) is True
    assert solapa(app, "pro@example.cl", datetime(2027, 4, 4, 0, 0), 10) is False


def test_septiembre_cierra_el_hueco_de_reloj_y_abril_cierra_el_falso_solape_con_el_oraculo(app, pro):
    """Matriz: para cada inicio y duración de la noche del cambio, el resultado
    coincide con comparar epochs calculados con `timestamp()` de la librería estándar."""
    desajustes = []
    for dia_existente, hora_existente in [(datetime(2027, 9, 4), "23:30"), (datetime(2027, 4, 3), "22:30")]:
        existente = datetime.fromisoformat(f"{dia_existente:%Y-%m-%d}T{hora_existente}:00")
        for duracion_existente in (50, 120):
            with app.app_context():
                db = get_db()
                db.execute("DELETE FROM horas")
                db.execute(
                    "INSERT INTO horas (profesional_id, inicio, duracion_min) VALUES (?, ?, ?)",
                    (usuario_id(app, "pro@example.cl"), existente.isoformat(), duracion_existente),
                )
                db.commit()
            a, b = segundos_utc_oraculo(existente), segundos_utc_oraculo(existente) + duracion_existente * 60
            for desplazamiento in range(-180, 300, 5):
                nueva = existente + timedelta(minutes=desplazamiento)
                if profesional.problema_de_horario(nueva, datetime(2027, 1, 1, tzinfo=CHILE)):
                    continue  # horas inexistentes o repetidas: no se pueden publicar
                for duracion in (10, 50, 120):
                    c = segundos_utc_oraculo(nueva)
                    esperado = a < c + duracion * 60 and c < b
                    if solapa(app, "pro@example.cl", nueva, duracion) != esperado:
                        desajustes.append((existente, duracion_existente, nueva, duracion))
    assert desajustes == []


@pytest.mark.parametrize(
    "existente, dur_e, nueva, dur_n, solapan",
    [
        ("2027-03-01T10:00:00", 50, datetime(2027, 3, 1, 10, 49), 30, True),   # un minuto
        ("2027-03-01T10:00:00", 50, datetime(2027, 3, 1, 10, 50), 30, False),  # pegada después
        ("2027-03-01T10:00:00", 50, datetime(2027, 3, 1, 9, 10), 50, False),   # pegada antes
        ("2027-03-01T10:00:00", 50, datetime(2027, 3, 1, 9, 11), 50, True),
        ("2027-03-01T10:00:00", 50, datetime(2027, 3, 1, 10, 10), 10, True),   # contenida
        ("2027-03-01T10:00:00", 50, datetime(2027, 3, 1, 9, 0), 180, True),    # contiene
        ("2027-03-01T10:00:00", 50, datetime(2027, 3, 1, 10, 0), 50, True),    # idéntica
        ("2027-03-01T23:30:00", 90, datetime(2027, 3, 2, 0, 30), 30, True),    # cruza medianoche
        ("2027-03-01T23:30:00", 90, datetime(2027, 3, 2, 1, 0), 30, False),
        ("2027-03-01T10:00:00", 50, datetime(2027, 3, 2, 10, 0), 50, False),   # otro día
    ],
)
def test_buscar_solape_cubre_los_casos_clasicos(app, pro, existente, dur_e, nueva, dur_n, solapan):
    insertar(app, "pro@example.cl", existente, dur_e)
    assert solapa(app, "pro@example.cl", nueva, dur_n) is solapan


def test_buscar_solape_ignora_a_otro_profesional(app, pro, pro2):
    insertar(app, "pro2@example.cl", "2027-03-01T10:00:00")
    assert solapa(app, "pro@example.cl", datetime(2027, 3, 1, 10, 0), 50) is False
    assert solapa(app, "pro2@example.cl", datetime(2027, 3, 1, 10, 0), 50) is True


def test_buscar_solape_devuelve_la_identica_si_hay_varias(app, pro):
    insertar(app, "pro@example.cl", "2027-03-01T09:30:00", 60)  # también solapa, y va antes
    insertar(app, "pro@example.cl", "2027-03-01T10:00:00", 50)
    with app.app_context():
        fila = profesional.buscar_solape(
            get_db(), usuario_id(app, "pro@example.cl"), datetime(2027, 3, 1, 10, 0), 50
        )
        assert fila["inicio"] == "2027-03-01T10:00:00"
        fila = profesional.buscar_solape(
            get_db(), usuario_id(app, "pro@example.cl"), datetime(2027, 3, 1, 10, 0), 30
        )
        assert fila["inicio"] == "2027-03-01T09:30:00"  # ninguna idéntica: la primera


def test_el_solape_se_calcula_en_python_dentro_del_bloqueo(app, pro):
    """La comprobación sigue siendo una sola lectura entre BEGIN IMMEDIATE e INSERT."""
    sentencias = []
    with app.app_context():
        db = get_db()
        db.set_trace_callback(sentencias.append)
        profesional.crear_hora(db, usuario_id(app, "pro@example.cl"), datetime(2027, 3, 1, 10, 0), 50)
    assert [s.split()[0].upper() for s in sentencias] == ["BEGIN", "SELECT", "INSERT", "COMMIT"]
    assert sentencias[0] == "BEGIN IMMEDIATE"
    assert "strftime" not in sentencias[1]  # ya no se compara en SQL


# ---------------------------------- T-05b: doble envío (R-04) ----------------


def test_doble_envio_del_mismo_formulario_dice_ya_publicada(app, pro):
    agregar(pro, "2027-03-01", "10:00", "50")
    r = agregar(pro, "2027-03-01", "10:00", "50")
    assert r.status_code == 200
    assert "Esa hora ya está publicada." in r.text
    assert "se solapa" not in r.text
    assert horas(app) == [("2027-03-01T10:00:00", 50, "libre")]


def test_mismo_inicio_con_otra_duracion_sigue_siendo_solape(app, pro):
    agregar(pro, "2027-03-01", "10:00", "50")
    r = agregar(pro, "2027-03-01", "10:00", "60")
    assert "se solapa con otra que ya publicaste" in r.text
    assert "ya está publicada" not in r.text


def test_misma_duracion_con_otro_inicio_sigue_siendo_solape(app, pro):
    agregar(pro, "2027-03-01", "10:00", "50")
    r = agregar(pro, "2027-03-01", "10:10", "50")
    assert "se solapa con otra que ya publicaste" in r.text
    assert "ya está publicada" not in r.text


def test_ya_publicada_tambien_si_otra_hora_anterior_solapa_y_va_primero(app, pro):
    insertar(app, "pro@example.cl", "2027-03-01T09:30:00", 60)
    insertar(app, "pro@example.cl", "2027-03-01T10:00:00", 50)
    r = agregar(pro, "2027-03-01", "10:00", "50")
    assert "Esa hora ya está publicada." in r.text


def test_la_identica_de_otro_profesional_no_cuenta_como_ya_publicada(app, pro, pro2):
    insertar(app, "pro2@example.cl", "2027-03-01T10:00:00", 50)
    r = agregar(pro, "2027-03-01", "10:00", "50")
    assert r.status_code == 302


def test_ya_publicada_si_la_identica_esta_reservada(app, con_base):
    crear(app, email="ana@example.cl")
    with app.app_context():
        db = get_db()
        db.execute(
            "UPDATE horas SET estado='reservada', paciente_id=?, reservada_en='2026-10-08T12:00:00'",
            (usuario_id(app, "ana@example.cl"),),
        )
        db.commit()
    r = agregar(con_base, *BASE, "50")
    assert "Esa hora ya está publicada." in r.text


# ------------------------- T-05b: calidad de pruebas (R-05, mutaciones) ----------


def formulario_eliminar(html, hora_id):
    m = re.search(
        rf'<form[^>]*action="/profesional/horas/{hora_id}/eliminar"[^>]*>(.*?)</form>', html, re.S
    )
    assert m, "el panel no tiene el formulario de eliminar"
    return m.group(1)


def test_el_boton_eliminar_lleva_su_propio_token_csrf_y_con_el_funciona(app, pro):
    """R-05 (M18): el token se lee DENTRO del formulario de eliminar, no del primero
    de la página (el de cerrar sesión es el mismo token y ocultaba la falta)."""
    hora_id = insertar(app, "pro@example.cl", "2027-03-01T10:00:00")
    cuerpo = formulario_eliminar(pro.get("/profesional").text, hora_id)
    assert '<input type="hidden" name="csrf_token"' in cuerpo
    token = extraer_token(cuerpo)
    r = pro.post(f"/profesional/horas/{hora_id}/eliminar", data={"csrf_token": token})
    assert (r.status_code, r.headers["Location"]) == (302, "/profesional")
    assert horas(app) == []


def test_todo_formulario_post_del_panel_y_del_formulario_nuevo_trae_token(app, pro):
    insertar(app, "pro@example.cl", "2027-03-01T10:00:00")
    insertar(app, "pro@example.cl", "2027-03-02T10:00:00")
    for url in ("/profesional", "/profesional/horas/nueva"):
        html = pro.get(url).text
        formularios = re.findall(r"<form[^>]*method=\"post\"[^>]*>(.*?)</form>", html, re.S)
        assert formularios
        for cuerpo in formularios:
            assert 'name="csrf_token"' in cuerpo, url
    assert len(re.findall(r"<form", pro.get("/profesional").text)) == 3  # 2 eliminar + cerrar sesión


def test_si_el_formulario_de_eliminar_no_tuviera_token_la_peticion_daria_400(app, pro):
    hora_id = insertar(app, "pro@example.cl", "2027-03-01T10:00:00")
    assert eliminar(pro, hora_id, token=False).status_code == 400
    assert horas(app) == [("2027-03-01T10:00:00", 50, "libre")]


def test_un_error_inesperado_al_guardar_deja_la_base_sin_transaccion_abierta(app, pro, monkeypatch):
    """R-05 (M21): si algo distinto de un IntegrityError falla tras BEGIN IMMEDIATE,
    la transacción se deshace antes de relanzar (no se confía en que la conexión se cierre)."""
    def falla(inicio):
        raise RuntimeError("fallo inesperado")

    monkeypatch.setattr(profesional, "formatear_inicio", falla)
    with app.app_context():
        db = get_db()
        with pytest.raises(RuntimeError):
            profesional.crear_hora(db, usuario_id(app, "pro@example.cl"), datetime(2027, 3, 1, 10, 0), 50)
        assert db.in_transaction is False
    assert horas(app) == []


@pytest.mark.parametrize("campo, valor", [("fecha", "2020-01-01"), ("hora", "25:00"), ("duracion", "0")])
def test_cada_error_aparece_bajo_su_propio_campo(app, pro, campo, valor):
    """R-05 (M12): el mensaje de cada campo sale en el bloque de ese campo."""
    datos = {"fecha": "2027-03-01", "hora": "10:00", "duracion": "50", campo: valor}
    r = agregar(pro, datos["fecha"], datos["hora"], datos["duracion"])
    html = r.text
    orden = ["fecha", "hora", "duracion"]
    inicio_bloque = html.index(f'id="{campo}"')
    siguiente = orden.index(campo) + 1
    fin_bloque = html.index(f'id="{orden[siguiente]}"') if siguiente < 3 else html.index("</form>")
    assert 'role="alert"' in html[inicio_bloque:fin_bloque]
    for otro in orden:
        if otro != campo:
            ini = html.index(f'id="{otro}"')
            fin = html.index('id="', ini + 10) if otro != "duracion" else html.index("</form>")
            assert 'role="alert"' not in html[ini:fin], otro


@pytest.mark.parametrize("texto", ["-5", "+5", "5.0", "0.5", "1e2", "٥٠", "５０", "", " 5", "12345"])
def test_formato_de_duracion_rechaza_lo_que_no_son_1_a_4_digitos_ascii(texto):
    """Primera barrera de `interpretar_duracion`, sola y sin el rango (R-05: los
    mutantes equivalentes de T-05 que cambiaban solo la expresión regular)."""
    assert profesional.FORMATO_DURACION.fullmatch(texto) is None


@pytest.mark.parametrize("texto", ["1", "50", "480", "0480", "9999"])
def test_formato_de_duracion_acepta_1_a_4_digitos_ascii(texto):
    assert profesional.FORMATO_DURACION.fullmatch(texto)


def test_interpretar_duracion_directa():
    assert profesional.interpretar_duracion("") == 50
    assert profesional.interpretar_duracion("480") == 480
    assert profesional.interpretar_duracion("481") is None
    assert profesional.interpretar_duracion("0") is None
    assert profesional.interpretar_duracion("-5") is None
    assert profesional.interpretar_duracion("5.5") is None
