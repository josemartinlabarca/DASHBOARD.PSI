"""T-09: notificaciones de confirmación y cancelación (US-11, US-13; SPEC §5; D-016).

Al reservar y al cancelar se insertan dos filas en `notificaciones` (paciente y profesional
DUEÑO de la hora) dentro de la transacción, y después del `commit` se escribe una línea por
aviso en `outbox.log`.
"""
import multiprocessing
import os
import sqlite3
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import pytest

from app import create_app, notificaciones, paciente as modulo_paciente
from app.db import get_db, init_db
from tests.test_horas_libres import fijar_reloj, insertar, nuevo_profesional
from tests.test_login import CLAVE, crear, iniciar, permitir_varios_profesionales
from tests.test_reservar import nuevo_paciente, reservar, uid
from tests.test_cancelar import ANA, BETO, cancelar, reservada
from tests.test_seguridad import extraer_token

PRO = "pro@example.cl"
HORA = "2026-10-12T10:00:00"  # AHORA es 2026-10-08 12:00: faltan más de 24 h


@pytest.fixture(autouse=True)
def base_inicializada(app):
    with app.app_context():
        init_db()


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
def beto(app):
    return nuevo_paciente(app, BETO, "Beto Soto")


def outbox(app):
    return Path(notificaciones.ruta_outbox(app))


def lineas(app):
    ruta = outbox(app)
    if not ruta.exists():
        return []
    return ruta.read_bytes().decode("utf-8").splitlines(keepends=True)


def notifs(app):
    with app.app_context():
        return [
            tuple(f)
            for f in get_db().execute(
                "SELECT id, usuario_id, tipo, mensaje, hora_id, leida, creada_en FROM notificaciones ORDER BY id"
            )
        ]


def por_usuario(app, email):
    u = uid(app, email)
    return [n for n in notifs(app) if n[1] == u]


# --------------------------------------------------------------- reservar ----


def test_reservar_crea_una_notificacion_para_el_paciente_y_otra_para_el_profesional(app, pro_id, ana):
    hora = insertar(app, pro_id, HORA)
    assert reservar(ana, hora).status_code == 302
    rows = notifs(app)
    assert len(rows) == 2
    assert {r[1] for r in rows} == {uid(app, ANA), pro_id}
    for _, _, tipo, _, hora_id, leida, creada_en in rows:
        assert (tipo, hora_id, leida) == ("confirmacion", hora, 0)
        assert creada_en == "2026-10-08T12:00:00-03:00"  # ISO de Chile con zona, como reservada_en


def test_creada_en_usa_el_reloj_leido_dentro_del_bloqueo_y_el_desfase_de_invierno(app, pro_id, ana, monkeypatch):
    fijar_reloj(monkeypatch, datetime(2027, 7, 1, 9, 5, 7))
    hora = insertar(app, pro_id, "2027-07-02T10:00:00")
    reservar(ana, hora)
    assert {r[6] for r in notifs(app)} == {"2027-07-01T09:05:07-04:00"}


def test_el_mensaje_del_paciente_se_basta_solo_y_dice_hasta_cuando_cancelar(app, pro_id, ana):
    reservar(ana, insertar(app, pro_id, HORA, 45))
    mensaje = por_usuario(app, ANA)[0][3]
    assert "Dr. Pro" in mensaje and "12-10-2026 a las 10:00" in mensaje and "45 minutos" in mensaje
    assert "hasta el 11-10-2026 a las 10:00 (hora de Chile)" in mensaje  # inicio - 24 h, hora local


def test_el_mensaje_del_profesional_nombra_al_paciente_y_la_hora(app, pro_id, ana):
    reservar(ana, insertar(app, pro_id, HORA))
    mensaje = por_usuario(app, PRO)[0][3]
    assert "Ana Pérez" in mensaje and "12-10-2026 a las 10:00" in mensaje and "Dr. Pro" not in mensaje


@pytest.mark.parametrize(
    "ahora, inicio, limite",
    [
        # septiembre: el reloj salta a +1 h; 24 h reales antes de las 10:00 son las 09:00 del reloj
        (datetime(2026, 9, 1, 12, 0), "2026-09-06T10:00:00", "05-09-2026 a las 09:00"),
        # abril: el reloj retrocede 1 h; 24 h reales antes de las 10:00 son las 11:00 del reloj
        (datetime(2027, 3, 30, 12, 0), "2027-04-04T10:00:00", "03-04-2027 a las 11:00"),
        (datetime(2026, 10, 8, 12, 0), "2026-10-12T00:30:00", "11-10-2026 a las 00:30"),  # cruza de día
    ],
)
def test_el_limite_para_cancelar_se_mide_en_instantes_y_se_muestra_en_hora_de_chile(
    app, pro_id, ana, monkeypatch, ahora, inicio, limite
):
    fijar_reloj(monkeypatch, ahora)
    reservar(ana, insertar(app, pro_id, inicio))
    assert f"hasta el {limite} (hora de Chile)" in por_usuario(app, ANA)[0][3]


def test_el_mensaje_no_lleva_contrasena_ni_hash(app, pro_id, ana):
    reservar(ana, insertar(app, pro_id, HORA))
    todo = " ".join(r[3] for r in notifs(app)) + "".join(lineas(app))
    assert CLAVE not in todo and "scrypt" not in todo and "password" not in todo.lower()


def test_el_profesional_avisado_es_el_dueno_de_la_hora_y_no_cualquiera_con_ese_rol(app, ana):
    pro1 = nuevo_profesional(app)
    permitir_varios_profesionales(app)
    pro2 = nuevo_profesional(app, "otro@example.cl", "Dra. Otra")
    hora2 = insertar(app, pro2, HORA)
    reservar(ana, hora2)
    assert [r[1] for r in notifs(app)].count(pro1) == 0
    assert sorted(r[1] for r in notifs(app)) == sorted([uid(app, ANA), pro2])
    assert "Ana Pérez" in por_usuario(app, "otro@example.cl")[0][3]
    assert "Dra. Otra" in por_usuario(app, ANA)[0][3]
    assert "Dr. Pro" not in " ".join(r[3] for r in notifs(app))
    assert [l.split("\t")[1] for l in lineas(app)] == [ANA, "otro@example.cl"]


def test_cada_paciente_recibe_su_propio_aviso_y_la_contraparte_correcta(app, pro_id, ana, beto):
    reservar(ana, insertar(app, pro_id, HORA))
    reservar(beto, insertar(app, pro_id, "2026-10-13T10:00:00"))
    assert len(por_usuario(app, ANA)) == 1 and len(por_usuario(app, BETO)) == 1
    assert "13-10-2026" in por_usuario(app, BETO)[0][3] and "12-10-2026" in por_usuario(app, ANA)[0][3]
    mensajes_pro = [r[3] for r in por_usuario(app, PRO)]
    assert "Ana Pérez" in mensajes_pro[0] and "Beto Soto" in mensajes_pro[1]


# ------------------------------------------------------------- cancelar ----


def test_cancelar_crea_dos_notificaciones_de_cancelacion(app, pro_id, ana):
    hora = reservada(app, pro_id, HORA)
    assert cancelar(ana, hora).status_code == 302
    rows = notifs(app)
    assert len(rows) == 2 and {r[1] for r in rows} == {uid(app, ANA), pro_id}
    for _, _, tipo, _, hora_id, leida, creada_en in rows:
        assert (tipo, hora_id, leida, creada_en) == ("cancelacion", hora, 0, "2026-10-08T12:00:00-03:00")
    assert "Dr. Pro" in por_usuario(app, ANA)[0][3] and "12-10-2026 a las 10:00" in por_usuario(app, ANA)[0][3]
    assert "Ana Pérez" in por_usuario(app, PRO)[0][3] and "12-10-2026 a las 10:00" in por_usuario(app, PRO)[0][3]


def test_la_cancelacion_avisa_al_profesional_dueno_de_la_hora(app, ana):
    pro1 = nuevo_profesional(app)
    permitir_varios_profesionales(app)
    pro2 = nuevo_profesional(app, "otro@example.cl", "Dra. Otra")
    cancelar(ana, reservada(app, pro2, HORA))
    assert sorted(r[1] for r in notifs(app)) == sorted([uid(app, ANA), pro2])
    assert pro1 not in [r[1] for r in notifs(app)]


def test_reservar_y_cancelar_varias_veces_la_misma_hora_da_avisos_coherentes(app, pro_id, ana, beto):
    hora = insertar(app, pro_id, HORA)
    for cliente in (ana, beto, ana):
        reservar(cliente, hora)
        cancelar(cliente, hora)
    rows = notifs(app)
    assert [r[2] for r in rows] == ["confirmacion", "confirmacion", "cancelacion", "cancelacion"] * 3
    assert [r[0] for r in rows] == sorted(r[0] for r in rows) and {r[4] for r in rows} == {hora}
    assert [r[2] for r in por_usuario(app, PRO)] == ["confirmacion", "cancelacion"] * 3
    assert [r[2] for r in por_usuario(app, ANA)] == ["confirmacion", "cancelacion"] * 2
    assert [r[2] for r in por_usuario(app, BETO)] == ["confirmacion", "cancelacion"]
    nombres = ["Ana", "Ana", "Beto", "Beto", "Ana", "Ana"]
    assert all(n in r[3] for n, r in zip(nombres, por_usuario(app, PRO)))
    assert len(lineas(app)) == 12


# ------------------------------------------------------ hora eliminada ----


def test_la_hora_eliminada_deja_las_notificaciones_con_hora_id_nulo_y_el_mensaje_intacto(app, pro_id, ana):
    hora = insertar(app, pro_id, HORA)
    reservar(ana, hora)
    cancelar(ana, hora)
    antes = notifs(app)
    with app.app_context():
        db = get_db()
        db.execute("DELETE FROM horas WHERE id = ?", (hora,))
        db.commit()
    despues = notifs(app)
    assert len(despues) == 4 and {r[4] for r in despues} == {None}
    assert [r[:4] + r[5:] for r in despues] == [r[:4] + r[5:] for r in antes]  # solo cambia hora_id
    for r in despues:  # se basta solo: fecha, hora y contraparte
        assert "12-10-2026 a las 10:00" in r[3]
        assert "Ana Pérez" in r[3] or "Dr. Pro" in r[3]


# ------------------------------------------------------------- rechazos ----


def test_los_rechazos_no_crean_notificaciones_ni_lineas(app, pro_id, ana, beto):
    ocupada = reservada(app, pro_id, "2026-10-14T10:00:00", BETO)
    cerca = insertar(app, pro_id, "2026-10-09T10:00:00")  # <24 h para reservar
    ya_mia = reservada(app, pro_id, "2026-10-15T10:00:00", ANA)
    solape = insertar(app, pro_id, "2026-10-15T10:30:00")
    cerca_reservada = reservada(app, pro_id, "2026-10-09T09:00:00", ANA)  # <24 h para cancelar
    libre = insertar(app, pro_id, "2026-10-20T10:00:00")
    for hora in (ocupada, cerca, ya_mia, solape, 99999):
        reservar(ana, hora)
    for hora, cliente in ((cerca_reservada, ana), (ocupada, ana), (libre, ana), (99999, ana), (ya_mia, beto)):
        cancelar(cliente, hora)
    assert notifs(app) == [] and lineas(app) == [] and not outbox(app).exists()


def test_un_rechazo_por_csrf_o_sin_sesion_tampoco_notifica(app, pro_id, ana):
    hora = insertar(app, pro_id, HORA)
    ana.post(f"/horas/{hora}/reservar", data={})
    app.test_client().post(f"/horas/{hora}/reservar", data={})
    assert notifs(app) == [] and not outbox(app).exists()


# ------------------------------------------------- atomicidad (el insert) ----


def trampa(app, donde="", cuando="BEFORE"):
    with app.app_context():
        db = get_db()
        db.execute(
            f"CREATE TRIGGER falla {cuando} INSERT ON notificaciones {donde}"
            " BEGIN SELECT RAISE(ABORT, 'disco lleno simulado'); END"
        )
        db.commit()


@pytest.mark.parametrize("donde", ["", "WHEN NEW.usuario_id = (SELECT id FROM usuarios WHERE rol = 'profesional')"])
def test_si_falla_el_insert_de_la_notificacion_no_queda_reserva(app, pro_id, ana, donde):
    hora = insertar(app, pro_id, HORA)
    trampa(app, donde)
    with app.app_context():
        db = get_db()
        with pytest.raises(sqlite3.DatabaseError):
            modulo_paciente.reservar_hora(db, hora, uid(app, ANA))
        assert db.in_transaction is False
        assert db.execute("SELECT estado, paciente_id, reservada_en FROM horas").fetchone()[:] == ("libre", None, None)
        assert db.execute("SELECT COUNT(*) FROM notificaciones").fetchone()[0] == 0
    assert not outbox(app).exists()


@pytest.mark.parametrize("donde", ["", "WHEN NEW.usuario_id = (SELECT id FROM usuarios WHERE rol = 'profesional')"])
def test_si_falla_el_insert_al_cancelar_la_reserva_sigue_en_pie(app, pro_id, ana, donde):
    hora = reservada(app, pro_id, HORA)
    trampa(app, donde)
    with app.app_context():
        db = get_db()
        with pytest.raises(sqlite3.DatabaseError):
            modulo_paciente.cancelar_reserva(db, hora, uid(app, ANA))
        assert db.in_transaction is False
        fila = db.execute("SELECT estado, paciente_id FROM horas").fetchone()
        assert (fila[0], fila[1]) == ("reservada", uid(app, ANA))
        assert db.execute("SELECT COUNT(*) FROM notificaciones").fetchone()[0] == 0
    assert not outbox(app).exists()


def test_el_orden_es_begin_update_dos_inserts_commit_y_solo_despues_el_log(app, pro_id, ana, monkeypatch):
    hora = insertar(app, pro_id, HORA)
    sentencias = []
    en_el_log = []
    original = notificaciones.escribir_outbox

    def espiar(avisos):
        en_el_log.append((list(sentencias), len(avisos)))
        return original(avisos)

    monkeypatch.setattr(notificaciones, "escribir_outbox", espiar)
    with app.app_context():
        db = get_db()
        db.set_trace_callback(sentencias.append)
        modulo_paciente.reservar_hora(db, hora, uid(app, ANA))
        db.set_trace_callback(None)
    claves = [s.split("(")[0].strip() for s in sentencias]
    assert claves[0] == "BEGIN IMMEDIATE" and claves[-1] == "COMMIT"
    inserts = [i for i, s in enumerate(sentencias) if s.startswith("INSERT INTO notificaciones")]
    assert len(inserts) == 2 and inserts[-1] < len(sentencias) - 1  # ambos antes del COMMIT
    assert sentencias.index(next(s for s in sentencias if s.startswith("UPDATE horas"))) < inserts[0]
    # el log se pidió con el commit ya hecho y con los dos avisos
    assert len(en_el_log) == 1 and en_el_log[0][0][-1] == "COMMIT" and en_el_log[0][1] == 2


def test_cuando_se_escribe_el_log_la_reserva_ya_esta_confirmada_para_otra_conexion(app, pro_id, ana, monkeypatch):
    hora = insertar(app, pro_id, HORA)
    visto = []
    original = notificaciones.escribir_outbox

    def espiar(avisos):
        otra = sqlite3.connect(app.config["DATABASE"])
        visto.append(
            (otra.execute("SELECT estado FROM horas WHERE id = ?", (hora,)).fetchone()[0],
             otra.execute("SELECT COUNT(*) FROM notificaciones").fetchone()[0])
        )
        otra.close()
        return original(avisos)

    monkeypatch.setattr(notificaciones, "escribir_outbox", espiar)
    reservar(ana, hora)
    assert visto == [("reservada", 2)]


def test_el_codigo_no_usa_replace_en_horas_ni_notificaciones():
    fuente = Path(notificaciones.__file__).read_text().upper()
    assert "REPLACE INTO" not in fuente and "OR REPLACE" not in fuente


# ---------------------------------------------------- outbox.log (forma) ----


def test_una_linea_por_notificacion_con_fecha_destinatario_tipo_y_mensaje(app, pro_id, ana):
    reservar(ana, insertar(app, pro_id, HORA))
    ls = lineas(app)
    assert len(ls) == 2 and all(l.endswith("\n") and l.count("\n") == 1 for l in ls)
    campos = [l.rstrip("\n").split("\t") for l in ls]
    assert [c[:3] for c in campos] == [
        ["2026-10-08T12:00:00-03:00", ANA, "confirmacion"],
        ["2026-10-08T12:00:00-03:00", PRO, "confirmacion"],
    ]
    assert [c[3] for c in campos] == [r[3] for r in notifs(app)]  # el mismo texto que la base


def test_al_cancelar_se_agregan_dos_lineas_mas_sin_tocar_las_anteriores(app, pro_id, ana):
    hora = insertar(app, pro_id, HORA)
    reservar(ana, hora)
    antes = lineas(app)
    cancelar(ana, hora)
    despues = lineas(app)
    assert despues[:2] == antes and len(despues) == 4
    assert [l.split("\t")[2] for l in despues] == ["confirmacion"] * 2 + ["cancelacion"] * 2
    assert [l.split("\t")[1] for l in despues[2:]] == [ANA, PRO]


def test_el_archivo_es_utf8_y_conserva_tildes(app, pro_id, ana):
    reservar(ana, insertar(app, pro_id, HORA))
    assert "Ana Pérez" in outbox(app).read_bytes().decode("utf-8")


def test_por_defecto_el_log_queda_junto_a_la_base_y_outbox_path_lo_cambia(tmp_path):
    por_defecto = create_app({"TESTING": True, "DATABASE": str(tmp_path / "x" / "agenda.db")})
    assert notificaciones.ruta_outbox(por_defecto) == str(tmp_path / "x" / "outbox.log")
    elegido = create_app({"TESTING": True, "DATABASE": str(tmp_path / "a.db"), "OUTBOX_PATH": str(tmp_path / "o.log")})
    assert notificaciones.ruta_outbox(elegido) == str(tmp_path / "o.log")


def test_outbox_path_puede_venir_del_entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTBOX_PATH", str(tmp_path / "env.log"))
    assert notificaciones.ruta_outbox(create_app({"TESTING": True, "DATABASE": str(tmp_path / "a.db")})) == str(
        tmp_path / "env.log"
    )


def test_crea_la_carpeta_si_no_existe_y_agrega_sin_borrar(tmp_path, app, pro_id, ana):
    app.config["OUTBOX_PATH"] = str(tmp_path / "no" / "existe" / "outbox.log")
    reservar(ana, insertar(app, pro_id, HORA))
    ruta = tmp_path / "no" / "existe" / "outbox.log"
    assert len(ruta.read_text().splitlines()) == 2
    reservar(ana, insertar(app, pro_id, "2026-10-13T10:00:00"))
    assert len(ruta.read_text().splitlines()) == 4


def test_el_limite_de_cancelacion_del_mensaje_es_el_de_la_regla_de_cancelar():
    assert notificaciones.ANTICIPACION_CANCELAR_S == modulo_paciente.ANTICIPACION_CANCELAR_S


def test_una_variable_outbox_path_del_equipo_no_hace_escribir_fuera_de_la_prueba(app, pro_id, ana):
    # la fixture automática la quita: el log queda junto a la base temporal
    assert "OUTBOX_PATH" not in os.environ and app.config["OUTBOX_PATH"] is None
    reservar(ana, insertar(app, pro_id, HORA))
    assert outbox(app).parent == Path(app.config["DATABASE"]).parent and outbox(app).exists()


def test_outbox_log_esta_en_gitignore():
    ignorados = (Path(notificaciones.__file__).parent.parent / ".gitignore").read_text().split()
    assert "outbox.log" in ignorados


def test_las_pruebas_no_escriben_en_el_proyecto(app):
    assert Path(notificaciones.ruta_outbox(app)).parent == Path(app.config["DATABASE"]).parent
    assert not str(notificaciones.ruta_outbox(app)).startswith(str(Path(notificaciones.__file__).parent.parent))


# --------------------------------------------------- fallos del archivo ----


@pytest.fixture(params=["directorio", "padre_es_archivo", "os_open_falla", "ruta_con_nulo"])
def log_roto(request, app, tmp_path, monkeypatch):
    if request.param == "directorio":
        (tmp_path / "es_carpeta").mkdir()
        app.config["OUTBOX_PATH"] = str(tmp_path / "es_carpeta")
    elif request.param == "padre_es_archivo":
        (tmp_path / "archivo").write_text("x")
        app.config["OUTBOX_PATH"] = str(tmp_path / "archivo" / "outbox.log")
    elif request.param == "ruta_con_nulo":
        app.config["OUTBOX_PATH"] = str(tmp_path / "a\0b.log")
    else:
        def sin_permiso(*a, **k):
            raise PermissionError(13, "Permission denied")
        monkeypatch.setattr(notificaciones.os, "open", sin_permiso)
    return request.param


def test_si_el_log_no_se_puede_escribir_la_reserva_sigue_en_pie_sin_500(app, pro_id, ana, log_roto, caplog):
    hora = insertar(app, pro_id, HORA)
    respuesta = reservar(ana, hora)
    assert respuesta.status_code == 302 and respuesta.headers["Location"] == "/paciente"
    with app.app_context():
        assert get_db().execute("SELECT estado FROM horas WHERE id = ?", (hora,)).fetchone()[0] == "reservada"
    assert len(notifs(app)) == 2
    assert "No se pudo escribir en el outbox" in caplog.text
    assert "Ana Pérez" not in caplog.text  # el contenido de los mensajes no va al log de errores


def test_si_el_log_no_se_puede_escribir_la_cancelacion_sigue_en_pie_sin_500(app, pro_id, ana, log_roto, caplog):
    hora = reservada(app, pro_id, HORA)
    assert cancelar(ana, hora).status_code == 302
    with app.app_context():
        assert get_db().execute("SELECT estado FROM horas WHERE id = ?", (hora,)).fetchone()[0] == "libre"
    assert [r[2] for r in notifs(app)] == ["cancelacion"] * 2
    assert "No se pudo escribir en el outbox" in caplog.text


def test_un_fallo_del_log_no_cambia_el_mensaje_de_exito(app, pro_id, ana, log_roto):
    from tests.test_reservar import aviso

    categoria, texto = aviso(ana, reservar(ana, insertar(app, pro_id, HORA)))
    assert categoria == "exito" and "Reservaste tu hora" in texto


# ---------------------------------------------------------- inyección ----

NOMBRE_INYECTADO = (
    "Ana\n2026-01-01T00:00:00-03:00\tfalso@x.cl\tconfirmacion\tHola\r\x00\x1b[31m\x0b\x0c\x1c\x1d\x1e\x85"
    "   　﻿‮\\n"
)


def test_un_nombre_con_saltos_y_controles_no_puede_inyectar_lineas_en_el_log(app, pro_id, ana):
    hora = insertar(app, pro_id, HORA)
    with app.app_context():  # por SQL: salta las validaciones del registro a propósito
        db = get_db()
        db.execute("UPDATE usuarios SET nombre = ? WHERE id = ?", (NOMBRE_INYECTADO, uid(app, ANA)))
        db.execute("UPDATE usuarios SET nombre = ?, email = ? WHERE id = ?",
                   (NOMBRE_INYECTADO, "pro@x.cl\nfalso@x.cl", pro_id))
        db.commit()
    reservar(ana, hora)
    texto = outbox(app).read_bytes().decode("utf-8")
    assert len(texto.splitlines()) == 2  # splitlines parte en \n \r \x0b \x0c \x1c-\x1e \x85 U+2028/9
    assert texto.count("\n") == 2
    for linea in texto.splitlines():
        assert linea.count("\t") == 3
        assert not any(unicodedata.category(c)[0] == "C" and c != "\t" for c in linea)
        assert not any(c in linea for c in "   　﻿‮")
        assert linea.split("\t")[2] == "confirmacion"
    assert "falso@x.cl" in texto  # el texto sigue ahí, pero inofensivo (dentro del campo)
    assert not any(l.startswith("2026-01-01") for l in texto.splitlines())


def test_el_nombre_inyectado_tambien_se_neutraliza_al_cancelar(app, pro_id, ana):
    hora = reservada(app, pro_id, HORA)
    with app.app_context():
        get_db().execute("UPDATE usuarios SET nombre = ? WHERE id = ?", ("Ana\n9999 falso otra", uid(app, ANA)))
        get_db().commit()
    cancelar(ana, hora)
    assert len(lineas(app)) == 2 and all("\n" not in l[:-1] for l in lineas(app))
    assert len(outbox(app).read_text().splitlines()) == 2


def test_sanear_no_deja_pasar_ningun_caracter_que_parta_la_linea():
    for punto in range(0x10000):
        resultado = notificaciones.sanear("a" + chr(punto) + "b")
        categorias = {unicodedata.category(c) for c in resultado}
        assert not any(c[0] == "C" or c in ("Zl", "Zp") for c in categorias), hex(punto)
        assert len(resultado.splitlines()) == 1, hex(punto)
    for astral in (0x1F600, 0xE0001, 0x10FFFF, 0xF0000):
        assert len(notificaciones.sanear(chr(astral)).splitlines()) == 1


def test_sanear_respeta_el_texto_normal_y_escapa_la_barra():
    assert notificaciones.sanear("Ana Pérez, ñandú 日本 😀") == "Ana Pérez, ñandú 日本 😀"
    assert notificaciones.sanear("a\\nb") == "a\\\\nb"  # la barra se duplica: no imita un escape
    assert notificaciones.sanear("a\nb") == "a\\u000ab"
    assert notificaciones.sanear("a b") == "a\\u2028b"
    assert notificaciones.sanear("\ud800") == "\\ud800"  # sustituto suelto: no rompe la codificación
    assert notificaciones.sanear(None) == "" and notificaciones.sanear(5) == "5"


def test_un_sustituto_suelto_en_el_nombre_no_rompe_la_reserva(app, pro_id, ana):
    with app.app_context():
        # SQLite guarda texto; un sustituto no cabe en UTF-8, así que se prueba con la función directa
        aviso = notificaciones.Aviso("2026-10-08T12:00:00-03:00", "a@x.cl", "confirmacion", "hola \ud800")
        assert notificaciones.escribir_outbox([aviso]) is True
    assert "\\ud800" in outbox(app).read_text()


# --------------------------------------------------------- concurrencia ----


def _trabajar(app, correo, horas, barrera):
    barrera.wait(30)
    with app.app_context():
        db = get_db()
        for hora in horas:
            assert modulo_paciente.reservar_hora(db, hora, uid_directo(db, correo))[0]
            assert modulo_paciente.cancelar_reserva(db, hora, uid_directo(db, correo))[0]
    os._exit(0)


def uid_directo(db, correo):
    return db.execute("SELECT id FROM usuarios WHERE email = ?", (correo,)).fetchone()[0]


@pytest.mark.skipif(sys.platform == "win32", reason="usa fork")
def test_procesos_reales_escribiendo_a_la_vez_no_entrelazan_ni_duplican_lineas(app, pro_id):
    correos = [f"p{i}@example.cl" for i in range(4)]
    for correo in correos:
        crear(app, email=correo, nombre="Paciente " + "N" * 90)  # líneas largas: más fácil entrelazarlas
    por_proceso = 5
    horas = [
        [insertar(app, pro_id, f"2026-11-{10 + i}T{9 + j:02d}:00:00") for j in range(por_proceso)]
        for i in range(len(correos))
    ]
    contexto = multiprocessing.get_context("fork")
    barrera = contexto.Barrier(len(correos))
    procesos = [contexto.Process(target=_trabajar, args=(app, c, h, barrera)) for c, h in zip(correos, horas)]
    for p in procesos:
        p.start()
    for p in procesos:
        p.join(60)
    assert [p.exitcode for p in procesos] == [0] * len(correos)
    ls = lineas(app)
    esperadas = len(correos) * por_proceso * 4  # reservar + cancelar, 2 líneas cada uno
    assert len(ls) == esperadas == len(notifs(app))
    assert len(set(ls)) == len(ls)  # ninguna línea duplicada
    assert sorted(l.rstrip("\n").split("\t")[3] for l in ls) == sorted(r[3] for r in notifs(app))
    for l in ls:
        campos = l.rstrip("\n").split("\t")
        assert len(campos) == 4 and campos[2] in ("confirmacion", "cancelacion")
        assert campos[1] in correos + [PRO] and campos[0] == "2026-10-08T12:00:00-03:00"
    for correo in correos:  # cada paciente: 5 confirmaciones y 5 cancelaciones, y el profesional las suyas
        assert sum(1 for l in ls if l.split("\t")[1] == correo) == por_proceso * 2
    assert sum(1 for l in ls if l.split("\t")[1] == PRO) == len(correos) * por_proceso * 2
