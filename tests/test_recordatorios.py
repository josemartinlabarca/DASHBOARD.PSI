"""T-10: recordatorios 24 h antes (US-12; SPEC §5; D-033).

`flask --app app send-reminders`: a cada reserva que empieza dentro de las próximas 24 h
(inclusive) y aún no empezó se le avisa UNA vez al paciente, con instantes absolutos.
"""
import multiprocessing
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app import auth, notificaciones
from app.db import get_db, init_db
from tests.test_cancelar import ANA, BETO, cancelar, reservada
from tests.test_horas_libres import AHORA, fijar_reloj, insertar, nuevo_profesional
from tests.test_login import crear
from tests.test_notificaciones import lineas, notifs, outbox, por_usuario, trampa
from tests.test_reservar import nuevo_paciente, reservar, uid

PRO = "pro@example.cl"
# AHORA = 2026-10-08 12:00 (Chile, UTC-3).
EXACTA_24H = "2026-10-09T12:00:00"
PASADA_24H = "2026-10-09T12:00:01"
INICIO_YA = "2026-10-08T12:00:00"
INICIO_EN_1S = "2026-10-08T12:00:01"


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


def enviar(app):
    with app.app_context():
        return notificaciones.enviar_recordatorios(get_db())


def recordatorios(app):
    return [n for n in notifs(app) if n[2] == "recordatorio"]


def enviado(app, hora_id):
    with app.app_context():
        return get_db().execute(
            "SELECT recordatorio_enviado FROM horas WHERE id = ?", (hora_id,)
        ).fetchone()[0]


# ------------------------------------------------------- qué se recuerda ----


@pytest.mark.parametrize(
    "inicio, cantidad",
    [
        ("2026-10-08T12:30:00", 1),  # dentro de 30 min
        (INICIO_EN_1S, 1),  # a 1 s de empezar
        (INICIO_YA, 0),  # empieza justo ahora: ya empezó
        ("2026-10-08T11:59:59", 0),  # empezó hace 1 s
        ("2026-10-08T09:00:00", 0),  # en curso / pasada
        ("2026-10-01T09:00:00", 0),
        ("2026-10-09T11:59:59", 1),  # 23 h 59 min 59 s
        (EXACTA_24H, 1),  # 24 h exactas: aún se puede cancelar, se recuerda
        (PASADA_24H, 0),  # 24 h + 1 s: todavía no toca
        ("2026-10-12T10:00:00", 0),
    ],
)
def test_el_borde_de_las_24_horas_y_el_de_inicio(app, pro_id, ana, zona_sistema, inicio, cantidad):
    hora = reservada(app, pro_id, inicio)
    assert enviar(app) == cantidad
    assert len(recordatorios(app)) == cantidad and enviado(app, hora) == cantidad
    assert len(lineas(app)) == cantidad


def test_la_fraccion_de_segundo_cuenta_en_el_borde(app, pro_id, ana, monkeypatch):
    hora = reservada(app, pro_id, EXACTA_24H)
    fijar_reloj(monkeypatch, AHORA - timedelta(microseconds=1))  # faltan 24 h + 1 microsegundo
    assert enviar(app) == 0 and enviado(app, hora) == 0
    fijar_reloj(monkeypatch, AHORA, microsecond=1)  # faltan 24 h - 1 microsegundo
    assert enviar(app) == 1 and enviado(app, hora) == 1


def test_el_borde_se_mide_en_instantes_al_empezar_el_horario_de_verano(app, pro_id, ana, monkeypatch, zona_sistema):
    # En Chile el reloj se adelanta la noche del 5 al 6 de septiembre de 2026 (de 24:00 a 01:00,
    # UTC-4 -> UTC-3). Desde el sábado a las 12:00 hasta el domingo a las 13:00 hay 25 h de
    # pared pero solo 24 h reales: se recuerda. Un segundo más y todavía no.
    fijar_reloj(monkeypatch, datetime(2026, 9, 5, 12, 0))
    justo = reservada(app, pro_id, "2026-09-06T13:00:00")
    tarde = reservada(app, pro_id, "2026-09-06T13:00:01")
    assert enviar(app) == 1
    assert (enviado(app, justo), enviado(app, tarde)) == (1, 0)


def test_el_borde_se_mide_en_instantes_al_terminar_el_horario_de_verano(app, pro_id, ana, monkeypatch, zona_sistema):
    # El reloj se atrasa la noche del 4 al 5 de abril de 2026 (de 24:00 a 23:00, UTC-3 -> UTC-4):
    # entre el sábado 4 a las 12:00 y el domingo 5 a las 11:00 hay 23 h de pared pero 24 h reales.
    fijar_reloj(monkeypatch, datetime(2026, 4, 4, 12, 0))
    justo = reservada(app, pro_id, "2026-04-05T11:00:00")
    antes = reservada(app, pro_id, "2026-04-05T10:59:59")
    despues = reservada(app, pro_id, "2026-04-05T11:00:01")
    assert enviar(app) == 2
    assert (enviado(app, justo), enviado(app, antes), enviado(app, despues)) == (1, 1, 0)


def test_las_horas_libres_no_se_recuerdan(app, pro_id, ana):
    insertar(app, pro_id, "2026-10-08T18:00:00")
    assert enviar(app) == 0
    assert notifs(app) == [] and not outbox(app).exists()


def test_una_hora_cancelada_no_se_recuerda(app, pro_id, ana):
    hora = insertar(app, pro_id, "2026-10-12T10:00:00")
    reservar(ana, hora)
    cancelar(ana, hora)
    with app.app_context():
        assert get_db().execute("SELECT estado FROM horas").fetchone()[0] == "libre"
    assert enviar(app) == 0
    assert recordatorios(app) == []


def test_una_hora_cancelada_a_menos_de_24_h_por_sql_tampoco_se_recuerda(app, pro_id, ana):
    hora = reservada(app, pro_id, "2026-10-09T09:00:00")
    with app.app_context():
        db = get_db()
        db.execute(
            "UPDATE horas SET estado='libre', paciente_id=NULL, reservada_en=NULL WHERE id=?", (hora,)
        )
        db.commit()
    assert enviar(app) == 0 and enviado(app, hora) == 0


def test_la_hora_eliminada_que_tuvo_notificaciones_no_se_recuerda_ni_rompe(app, pro_id, ana):
    hora = insertar(app, pro_id, "2026-10-12T10:00:00")
    reservar(ana, hora)
    cancelar(ana, hora)
    antes = notifs(app)
    with app.app_context():
        db = get_db()
        db.execute("DELETE FROM horas WHERE id = ?", (hora,))
        db.commit()
    assert enviar(app) == 0
    assert notifs(app) == [(*r[:4], None, *r[5:]) for r in antes]  # solo perdieron el enlace
    assert len(lineas(app)) == 4  # las de confirmar y cancelar; ninguna de recordatorio


def test_la_reserva_eliminada_a_la_fuerza_con_notificaciones_no_se_recuerda(app, pro_id, ana):
    hora = reservada(app, pro_id, "2026-10-08T18:00:00")
    with app.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO notificaciones (usuario_id, tipo, mensaje, hora_id, creada_en)"
            " VALUES (?, 'confirmacion', 'vieja', ?, '2026-10-01T09:00:00-03:00')",
            (uid(app, ANA), hora),
        )
        db.execute("DELETE FROM horas WHERE id = ?", (hora,))
        db.commit()
    assert enviar(app) == 0 and recordatorios(app) == []


def test_el_recordatorio_no_depende_de_las_notificaciones_ni_de_hora_id(app, pro_id, ana):
    hora = reservada(app, pro_id, "2026-10-08T18:00:00")
    with app.app_context():  # una confirmación con hora_id NULL no impide ni sustituye al recordatorio
        db = get_db()
        db.execute(
            "INSERT INTO notificaciones (usuario_id, tipo, mensaje, hora_id, creada_en)"
            " VALUES (?, 'confirmacion', 'vieja', NULL, '2026-10-01T09:00:00-03:00')",
            (uid(app, ANA),),
        )
        db.commit()
    assert enviar(app) == 1 and enviado(app, hora) == 1
    assert len(recordatorios(app)) == 1


def test_una_fila_ilegible_se_omite_sin_marcarla_y_las_buenas_se_envian(app, pro_id, ana):
    mala = reservada(app, pro_id, "2026-10-08T99:99:99")
    sin_duracion = reservada(app, pro_id, "2026-10-08T17:00:00")
    with app.app_context():
        db = get_db()
        db.execute("UPDATE horas SET duracion_min = 'x' WHERE id = ?", (sin_duracion,))
        db.commit()
    buena = reservada(app, pro_id, "2026-10-08T19:00:00")
    assert enviar(app) == 1
    assert (enviado(app, mala), enviado(app, sin_duracion), enviado(app, buena)) == (0, 0, 1)


def test_orden_por_instante_y_no_por_id(app, pro_id, ana):
    tarde = reservada(app, pro_id, "2026-10-09T10:00:00")
    pronto = reservada(app, pro_id, "2026-10-08T15:00:00")
    assert enviar(app) == 2 and tarde < pronto
    assert [n[4] for n in recordatorios(app)] == [pronto, tarde]


# --------------------------------------------------------- no se repite ----


def test_ejecutar_dos_veces_envia_una_sola_vez(app, pro_id, ana):
    hora = reservada(app, pro_id, "2026-10-08T18:00:00")
    assert enviar(app) == 1
    despues_de_la_primera = (notifs(app), lineas(app))
    assert enviar(app) == 0 and enviar(app) == 0
    assert (notifs(app), lineas(app)) == despues_de_la_primera
    assert enviado(app, hora) == 1 and len(recordatorios(app)) == 1


def test_el_comando_dos_veces_seguidas_no_duplica(app, pro_id, ana):
    reservada(app, pro_id, "2026-10-08T18:00:00")
    ejecutor = app.test_cli_runner()
    primero = ejecutor.invoke(args=["send-reminders"])
    segundo = ejecutor.invoke(args=["send-reminders"])
    assert (primero.exit_code, segundo.exit_code) == (0, 0)
    assert primero.output == "Recordatorios enviados: 1.\n"
    assert segundo.output == "Recordatorios enviados: 0.\n"
    assert len(recordatorios(app)) == 1 and len(lineas(app)) == 1


def test_el_comando_no_imprime_datos_personales(app, pro_id, ana):
    reservada(app, pro_id, "2026-10-08T18:00:00")
    resultado = app.test_cli_runner().invoke(args=["send-reminders"])
    assert resultado.exit_code == 0 and len(resultado.output.splitlines()) == 1
    for dato in ("Ana", "Pérez", ANA, "Dr. Pro", PRO, "18:00", "2026"):
        assert dato not in resultado.output


def test_el_comando_esta_registrado_en_la_aplicacion(app):
    assert "send-reminders" in app.cli.commands
    assert app.test_cli_runner().invoke(args=["send-reminders"]).output == "Recordatorios enviados: 0.\n"


def test_cancelar_y_volver_a_reservar_permite_un_recordatorio_nuevo(app, pro_id, ana, beto, monkeypatch):
    hora = insertar(app, pro_id, "2026-10-12T10:00:00")
    reservar(ana, hora)
    fijar_reloj(monkeypatch, datetime(2026, 10, 11, 9, 0))  # faltan 25 h: aún no toca
    assert enviar(app) == 0
    fijar_reloj(monkeypatch, datetime(2026, 10, 11, 11, 0))  # faltan 23 h
    assert enviar(app) == 1 and enviado(app, hora) == 1
    fijar_reloj(monkeypatch, datetime(2026, 10, 9, 9, 0))  # (reloj atrás) para poder cancelar
    cancelar(ana, hora)
    assert enviado(app, hora) == 0
    reservar(beto, hora)
    fijar_reloj(monkeypatch, datetime(2026, 10, 11, 11, 0))
    assert enviar(app) == 1  # al nuevo paciente
    assert [n[1] for n in recordatorios(app)] == [uid(app, ANA), uid(app, BETO)]


def test_una_reserva_hecha_entre_24_h_y_24_h_mas_el_periodo_se_envia_en_la_siguiente_ejecucion(
    app, pro_id, ana, monkeypatch
):
    hora = insertar(app, pro_id, "2026-10-09T13:00:00")  # a 25 h
    reservar(ana, hora)
    assert enviar(app) == 0 and enviado(app, hora) == 0  # pendiente, no perdida
    fijar_reloj(monkeypatch, AHORA + timedelta(hours=1))  # pasó el período del cron: faltan 24 h
    assert enviar(app) == 1
    fijar_reloj(monkeypatch, AHORA + timedelta(hours=2))
    assert enviar(app) == 0


def test_una_reserva_a_menos_de_24_h_insertada_por_sql_se_recuerda_de_inmediato(app, pro_id, ana):
    reservada(app, pro_id, "2026-10-08T20:00:00")  # la aplicación ya no lo permite: se inserta por SQL
    assert enviar(app) == 1


# --------------------------------------------- quién gana: cancelar o avisar ----


def test_si_el_recordatorio_gana_la_cancelacion_igual_funciona_y_reabre_la_hora(app, pro_id, ana):
    hora = reservada(app, pro_id, EXACTA_24H)  # a las 24 h exactas ambas cosas son válidas
    assert enviar(app) == 1
    assert cancelar(ana, hora).status_code == 302
    with app.app_context():
        fila = get_db().execute("SELECT estado, paciente_id, recordatorio_enviado FROM horas").fetchone()
    assert tuple(fila) == ("libre", None, 0)
    assert enviar(app) == 0  # libre: nada que recordar


def test_si_la_cancelacion_gana_no_hay_recordatorio(app, pro_id, ana):
    hora = reservada(app, pro_id, EXACTA_24H)
    cancelar(ana, hora)
    assert enviar(app) == 0 and recordatorios(app) == []


# ------------------------------------------------------ a quién se avisa ----


def test_el_recordatorio_es_solo_para_el_paciente_de_la_hora(app, pro_id, ana, beto):
    reservada(app, pro_id, "2026-10-08T18:00:00", BETO)
    reservada(app, pro_id, "2026-10-09T08:00:00", ANA)
    assert enviar(app) == 2
    assert por_usuario(app, PRO) == []  # SPEC US-12: el profesional no recibe recordatorio
    assert [n[2] for n in por_usuario(app, ANA)] == ["recordatorio"]
    assert [n[2] for n in por_usuario(app, BETO)] == ["recordatorio"]
    assert [l.split("\t")[1] for l in lineas(app)] == [BETO, ANA]  # por instante, cada uno a su paciente


def test_el_mensaje_se_basta_solo(app, pro_id, ana):
    reservada(app, pro_id, "2026-10-08T18:00:00", duracion=45)
    enviar(app)
    (n,) = recordatorios(app)
    assert n[3] == "Recordatorio: tienes una hora con Dr. Pro el 08-10-2026 a las 18:00 (hora de Chile), de 45 minutos."
    assert n[6] == "2026-10-08T12:00:00-03:00" and n[5] == 0
    assert lineas(app)[0].rstrip("\n").split("\t") == [n[6], ANA, "recordatorio", n[3]]


def test_la_hora_es_la_de_chile_aunque_el_sistema_este_en_otra_zona(app, pro_id, ana, zona_sistema):
    reservada(app, pro_id, "2026-10-08T23:30:00")
    enviar(app)
    assert "08-10-2026 a las 23:30 (hora de Chile)" in recordatorios(app)[0][3]


def test_el_nombre_con_saltos_no_parte_la_linea_del_recordatorio(app, pro_id, ana):
    with app.app_context():
        db = get_db()
        db.execute("UPDATE usuarios SET nombre = ? WHERE email = ?", ("Ana\nfalso\tx", ANA))
        db.commit()
    reservada(app, pro_id, "2026-10-08T18:00:00")
    enviar(app)
    ls = lineas(app)
    assert len(ls) == 1 and len(ls[0].rstrip("\n").split("\t")) == 4


# ------------------------------------------- tipos sin mensaje (R-01 de T-09) ----


HORA_FALSA = {
    "profesional": "Dr. Pro", "paciente": "Ana", "inicio": "2026-10-12T10:00:00", "duracion_min": 50,
}


def tipos_del_esquema(app):
    with app.app_context():
        sql = get_db().execute("SELECT sql FROM sqlite_master WHERE name = 'notificaciones'").fetchone()[0]
    return set(re.search(r"tipo IN \(([^)]*)\)", sql).group(1).replace("'", "").replace(" ", "").split(","))


def test_todos_los_tipos_del_esquema_tienen_mensaje_propio_y_distinto(app):
    assert tipos_del_esquema(app) == set(notificaciones.TIPOS)
    textos = set()
    for tipo in notificaciones.TIPOS:
        para_paciente, _ = notificaciones._mensajes(tipo, HORA_FALSA)
        assert para_paciente and "12-10-2026 a las 10:00" in para_paciente
        textos.add(para_paciente)
    assert len(textos) == len(notificaciones.TIPOS)  # ninguno cae en el texto de otro


@pytest.mark.parametrize("tipo", ["otro", "", "RECORDATORIO", None, "recordatorio "])
def test_un_tipo_sin_mensaje_se_rechaza_y_no_inserta_nada(app, pro_id, ana, tipo):
    hora = reservada(app, pro_id, "2026-10-12T10:00:00")
    datos = dict(HORA_FALSA, profesional_id=pro_id, profesional_email=PRO, paciente_email=ANA)
    with app.app_context():
        db = get_db()
        with pytest.raises(ValueError):
            notificaciones.registrar(db, tipo, hora, datos, uid(app, ANA), "2026-10-08T12:00:00-03:00")
        assert db.execute("SELECT COUNT(*) FROM notificaciones").fetchone()[0] == 0


def test_confirmacion_y_cancelacion_siguen_avisando_a_las_dos_partes(app, pro_id, ana):
    hora = insertar(app, pro_id, "2026-10-12T10:00:00")
    reservar(ana, hora)
    cancelar(ana, hora)
    assert [n[2] for n in notifs(app)] == ["confirmacion"] * 2 + ["cancelacion"] * 2
    assert len(por_usuario(app, PRO)) == 2 and len(por_usuario(app, ANA)) == 2


# ------------------------------------------------------------ atomicidad ----


def test_si_falla_el_aviso_no_queda_marcado_ni_hay_linea(app, pro_id, ana):
    hora = reservada(app, pro_id, "2026-10-08T18:00:00")
    trampa(app)
    with app.app_context():
        db = get_db()
        with pytest.raises(sqlite3.DatabaseError):
            notificaciones.enviar_recordatorios(db)
        assert db.in_transaction is False
    assert enviado(app, hora) == 0 and notifs(app) == [] and not outbox(app).exists()
    with app.app_context():  # arreglada la causa, la siguiente ejecución sí lo envía
        db = get_db()
        db.execute("DROP TRIGGER falla")
        db.commit()
    assert enviar(app) == 1


def test_si_falla_un_aviso_a_mitad_no_queda_ninguno_marcado(app, pro_id, ana, beto):
    a = reservada(app, pro_id, "2026-10-08T18:00:00", ANA)
    b = reservada(app, pro_id, "2026-10-08T19:00:00", BETO)
    trampa(app, f"WHEN NEW.usuario_id = {uid(app, BETO)}")
    with app.app_context():
        with pytest.raises(sqlite3.DatabaseError):
            notificaciones.enviar_recordatorios(get_db())
    assert (enviado(app, a), enviado(app, b)) == (0, 0) and notifs(app) == []


def test_orden_begin_select_update_insert_commit_y_solo_despues_el_log(app, pro_id, ana, monkeypatch):
    reservada(app, pro_id, "2026-10-08T18:00:00")
    sentencias = []
    en_el_log = []
    original = notificaciones.escribir_outbox

    def espiar(avisos):
        otra = sqlite3.connect(app.config["DATABASE"])
        marcado = otra.execute("SELECT recordatorio_enviado FROM horas").fetchone()[0]
        vistas = otra.execute("SELECT COUNT(*) FROM notificaciones").fetchone()[0]
        otra.close()
        en_el_log.append((list(sentencias), len(avisos), marcado, vistas))
        return original(avisos)

    monkeypatch.setattr(notificaciones, "escribir_outbox", espiar)
    with app.app_context():
        db = get_db()
        db.set_trace_callback(sentencias.append)
        notificaciones.enviar_recordatorios(db)
        db.set_trace_callback(None)
    assert sentencias[0] == "BEGIN IMMEDIATE" and sentencias[-1] == "COMMIT"
    assert sentencias[1].startswith("SELECT")  # se lee DESPUÉS de tomar el bloqueo
    actualizacion = next(i for i, s in enumerate(sentencias) if s.startswith("UPDATE horas"))
    insercion = next(i for i, s in enumerate(sentencias) if s.startswith("INSERT INTO notificaciones"))
    assert actualizacion < insercion < len(sentencias) - 1
    assert len(en_el_log) == 1
    sentencias_al_log, cantidad, marcado, vistas = en_el_log[0]
    assert sentencias_al_log[-1] == "COMMIT" and (cantidad, marcado, vistas) == (1, 1, 1)


def test_el_reloj_se_lee_despues_de_tomar_el_bloqueo(app, pro_id, ana):
    reservada(app, pro_id, "2026-10-08T18:00:00")
    sentencias = []

    def reloj():
        sentencias.append("RELOJ")
        return AHORA.replace(tzinfo=auth.zona_chile())

    with app.app_context():
        db = get_db()
        db.set_trace_callback(sentencias.append)
        notificaciones.enviar_recordatorios(db, reloj=reloj)
        db.set_trace_callback(None)
    primer_select = next(i for i, s in enumerate(sentencias) if s.startswith("SELECT"))
    assert sentencias.index("BEGIN IMMEDIATE") < sentencias.index("RELOJ") < primer_select


def test_un_fallo_del_log_no_deshace_el_recordatorio_ni_da_error(app, pro_id, ana):
    hora = reservada(app, pro_id, "2026-10-08T18:00:00")
    app.config["OUTBOX_PATH"] = str(Path(app.config["DATABASE"]).parent)  # es una carpeta: no se puede escribir
    resultado = app.test_cli_runner().invoke(args=["send-reminders"])
    assert resultado.exit_code == 0 and resultado.output == "Recordatorios enviados: 1.\n"
    assert enviado(app, hora) == 1 and len(recordatorios(app)) == 1


def test_el_codigo_del_recordatorio_no_usa_replace():
    fuente = Path(notificaciones.__file__).read_text().upper()
    assert "REPLACE INTO" not in fuente and "OR REPLACE" not in fuente


# --------------------------------------------------------- concurrencia ----


def _correr(app, barrera):
    barrera.wait(30)
    with app.app_context():
        notificaciones.enviar_recordatorios(get_db())
    os._exit(0)


@pytest.mark.skipif(sys.platform == "win32", reason="usa fork")
def test_tres_procesos_a_la_vez_no_duplican_ningun_aviso(app, pro_id):
    for i in range(6):
        crear(app, email=f"p{i}@example.cl", nombre=f"Paciente {i}")
        reservada(app, pro_id, f"2026-10-08T{13 + i}:00:00", f"p{i}@example.cl")
    contexto = multiprocessing.get_context("fork")
    for _ in range(3):  # varias rondas: una carrera no es determinista
        with app.app_context():
            db = get_db()
            db.execute("UPDATE horas SET recordatorio_enviado = 0")
            db.execute("DELETE FROM notificaciones")
            db.commit()
        outbox(app).unlink(missing_ok=True)
        barrera = contexto.Barrier(3)
        procesos = [contexto.Process(target=_correr, args=(app, barrera)) for _ in range(3)]
        for p in procesos:
            p.start()
        for p in procesos:
            p.join(60)
        assert [p.exitcode for p in procesos] == [0, 0, 0]
        assert len(recordatorios(app)) == 6 and len(lineas(app)) == 6
        assert len({n[1] for n in recordatorios(app)}) == 6 and len(set(lineas(app))) == 6
