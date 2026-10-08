"""T-08: cancelar una reserva (US-9; D-003) y «Mis reservas» en el panel del paciente.

Incluye lo que la revisión de T-07 dejó para esta tarea: reloj leído después del
bloqueo (R-02), rollback en cada salida (R-04) y reservas visibles (R-01).
"""
import multiprocessing
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import auth, create_app, paciente as modulo_paciente, tiempo
from app.db import get_db, init_db
from tests.test_horas_libres import AHORA, fijar_reloj, insertar, nuevo_profesional
from tests.test_login import crear, iniciar
from tests.test_reservar import aviso, fila, nuevo_paciente, todas, uid
from tests.test_seguridad import extraer_token

NO_ENCONTRADA = "No encontramos esa reserva entre las tuyas"
POCA_ANTICIPACION = "Solo puedes cancelar con al menos 24 horas de anticipación"
LIBRE = "Esa hora ya no está disponible"
ANA = "ana@example.cl"
BETO = "beto@example.cl"


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


def reservada(app, pro_id, inicio, email=ANA, duracion=50, recordatorio=0, en="2026-10-07T09:00:00-03:00"):
    """Inserta una hora ya reservada por `email` (por SQL: no depende de la ruta de reservar)."""
    hora = insertar(app, pro_id, inicio, duracion)
    with app.app_context():
        db = get_db()
        db.execute(
            "UPDATE horas SET estado='reservada', paciente_id=?, reservada_en=?, recordatorio_enviado=?"
            " WHERE id=?",
            (uid(app, email), en, recordatorio, hora),
        )
        db.commit()
    return hora


def cancelar(client, hora_id, token=True, panel="/paciente", **extra):
    datos = dict(extra)
    if token:
        datos["csrf_token"] = extraer_token(client.get(panel).text)
    return client.post(f"/horas/{hora_id}/cancelar", data=datos)


def cancelar_y_aviso(client, hora_id, **extra):
    return aviso(client, cancelar(client, hora_id, **extra))


def fila_completa(app, hora_id):
    with app.app_context():
        return tuple(get_db().execute("SELECT * FROM horas WHERE id = ?", (hora_id,)).fetchone())


# ---------------------------------------------------------- cancelar ok ----


def test_cancelar_con_mas_de_24_horas_deja_la_hora_libre(app, pro_id, ana):
    hora = reservada(app, pro_id, "2026-10-12T10:00:00")
    r = cancelar(ana, hora)
    assert r.status_code == 302 and r.headers["Location"] == "/paciente"
    assert fila(app, hora) == ("libre", None, None)
    categoria, texto = aviso(ana, r)
    assert categoria == "exito"
    assert "12-10-2026 10:00" in texto and "Dr. Pro" in texto and "quedó libre" in texto


def test_cancelar_resetea_recordatorio_y_solo_cambia_esas_columnas(app, pro_id, ana):
    """D-030: una hora que vuelve a libre queda como nueva, también `recordatorio_enviado`
    (si no, quien la reserve después nunca recibiría su recordatorio, T-10)."""
    hora = reservada(app, pro_id, "2026-10-12T10:00:00", recordatorio=1)
    antes = fila_completa(app, hora)
    cancelar(ana, hora)
    despues = fila_completa(app, hora)
    # columnas: id, profesional_id, inicio, duracion_min, estado, paciente_id, reservada_en, recordatorio
    assert despues[:4] == antes[:4]
    assert despues[4:] == ("libre", None, None, 0)


def test_solo_cambia_la_fila_cancelada_y_no_se_borra_ninguna(app, pro_id, ana):
    a = reservada(app, pro_id, "2026-10-12T10:00:00")
    b = reservada(app, pro_id, "2026-10-13T10:00:00")
    c = insertar(app, pro_id, "2026-10-14T10:00:00")
    antes = todas(app)
    cancelar(ana, a)
    despues = todas(app)
    assert len(despues) == len(antes) == 3
    assert [f for f in despues if f[0] in (b, c)] == [f for f in antes if f[0] in (b, c)]


def test_la_hora_cancelada_reaparece_en_la_lista_de_todos_y_se_puede_reservar(app, pro_id, ana, beto):
    hora = reservada(app, pro_id, "2026-10-12T10:00:00")
    assert "12-10-2026 10:00" not in beto.get("/paciente/horas").text
    cancelar(ana, hora)
    assert "12-10-2026 10:00" in beto.get("/paciente/horas").text
    assert "12-10-2026 10:00" in ana.get("/paciente/horas").text
    assert beto.post(
        f"/horas/{hora}/reservar", data={"csrf_token": extraer_token(beto.get("/paciente").text)}
    ).status_code == 302
    assert fila(app, hora) == ("reservada", uid(app, BETO), "2026-10-08T12:00:00-03:00")


def test_la_misma_paciente_puede_volver_a_reservarla(app, pro_id, ana):
    hora = reservada(app, pro_id, "2026-10-12T10:00:00")
    cancelar(ana, hora)
    ana.post(f"/horas/{hora}/reservar", data={"csrf_token": extraer_token(ana.get("/paciente").text)})
    assert fila(app, hora)[0] == "reservada"


def test_la_reserva_cancelada_sale_de_mis_reservas(app, pro_id, ana):
    hora = reservada(app, pro_id, "2026-10-12T10:00:00")
    assert len(filas_de_reservas(ana.get("/paciente").text)) == 1
    cancelar(ana, hora)
    assert filas_de_reservas(ana.get("/paciente").text) == []


def test_doble_clic_la_segunda_vez_dice_no_encontrada_y_no_cambia_nada(app, pro_id, ana):
    hora = reservada(app, pro_id, "2026-10-12T10:00:00")
    cancelar(ana, hora)
    estado = fila_completa(app, hora)
    assert cancelar_y_aviso(ana, hora) == ("error", f"{NO_ENCONTRADA}. Puede que ya esté cancelada.")
    assert fila_completa(app, hora) == estado


# ------------------------------------------------ anticipación de 24 h ----

# (ahora local, fold, inicio guardado) y si se puede cancelar. Las tablas se cruzan
# con un cálculo independiente en UTC (`esperado`): no usan código de la aplicación.
CASOS_ANTICIPACION = [
    # día normal (UTC-3): ahora 12:00
    (datetime(2026, 10, 8, 12, 0), 0, "2026-10-09T12:00:00", True),  # 24 h exactas: se permite
    (datetime(2026, 10, 8, 12, 0), 0, "2026-10-09T12:00:01", True),
    (datetime(2026, 10, 8, 12, 0), 0, "2026-10-09T11:59:59", False),  # 23 h 59 min 59 s
    (datetime(2026, 10, 8, 12, 0), 0, "2026-10-09T11:00:00", False),  # 23 h
    (datetime(2026, 10, 8, 12, 0), 0, "2026-10-09T13:00:00", True),  # 25 h
    (datetime(2026, 10, 8, 12, 0), 0, "2026-10-08T12:30:00", False),
    (datetime(2026, 10, 8, 12, 0), 0, "2026-10-10T08:00:00", True),
    # noche de abril 2027: a las 24:00 del sáb 3 el reloj vuelve a las 23:00 (el día dura 25 h)
    (datetime(2027, 4, 3, 12, 0), 0, "2027-04-04T11:00:00", True),  # 24 h reales aunque el reloj marca 23 h
    (datetime(2027, 4, 3, 12, 0), 0, "2027-04-04T10:59:59", False),
    (datetime(2027, 4, 3, 12, 0), 0, "2027-04-04T12:00:00", True),  # 25 h reales
    (datetime(2027, 4, 3, 23, 30), 1, "2027-04-04T23:30:00", True),  # ahora = la SEGUNDA vez de las 23:30
    (datetime(2027, 4, 3, 23, 30), 1, "2027-04-04T23:29:59", False),
    (datetime(2027, 4, 3, 23, 30), 0, "2027-04-04T22:30:00", True),  # ahora = la PRIMERA vez
    (datetime(2027, 4, 3, 23, 30), 0, "2027-04-04T22:29:59", False),
    (datetime(2027, 4, 3, 23, 30), 0, "2027-04-04T23:30:00", True),  # 25 h reales
    # noche de septiembre 2027: a las 24:00 del sáb 4 el reloj salta a 01:00 (el día dura 23 h)
    (datetime(2027, 9, 4, 12, 0), 0, "2027-09-05T13:00:00", True),  # 24 h reales aunque el reloj marca 25 h
    (datetime(2027, 9, 4, 12, 0), 0, "2027-09-05T12:59:59", False),  # el reloj de pared diría 24 h 59 min
    (datetime(2027, 9, 4, 12, 0), 0, "2027-09-05T12:00:00", False),  # 23 h reales
    (datetime(2027, 9, 4, 23, 30), 0, "2027-09-05T23:30:00", False),  # 23 h reales
    (datetime(2027, 9, 4, 23, 30), 0, "2027-09-06T00:30:00", True),  # 24 h reales
]


def esperado(ahora_local, fold, inicio):
    """Referencia independiente: instantes en UTC con zoneinfo y la regla `>= 24 h`."""
    ahora = ahora_local.replace(tzinfo=auth.zona_chile(), fold=fold).astimezone(timezone.utc)
    ini = datetime.strptime(inicio, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=auth.zona_chile()).astimezone(timezone.utc)
    return ini - ahora >= timedelta(hours=24)


@pytest.mark.parametrize("ahora_local, fold, inicio, permitido", CASOS_ANTICIPACION)
def test_la_tabla_de_casos_coincide_con_la_referencia_independiente(ahora_local, fold, inicio, permitido):
    assert esperado(ahora_local, fold, inicio) is permitido


@pytest.mark.parametrize("ahora_local, fold, inicio, permitido", CASOS_ANTICIPACION)
def test_anticipacion_de_24_horas_en_instantes_absolutos(
    app, pro_id, ana, monkeypatch, zona_sistema, ahora_local, fold, inicio, permitido
):
    fijar_reloj(monkeypatch, ahora_local, fold=fold)
    hora = reservada(app, pro_id, inicio)
    categoria, texto = cancelar_y_aviso(ana, hora)
    if permitido:
        assert categoria == "exito"
        assert fila(app, hora) == ("libre", None, None)
    else:
        assert categoria == "error" and POCA_ANTICIPACION in texto
        assert fila(app, hora)[0] == "reservada" and fila(app, hora)[1] == uid(app, ANA)


def test_una_fraccion_de_segundo_menos_de_24_horas_se_rechaza(app, pro_id, ana, monkeypatch):
    """«Al menos 24 horas» se mide con el instante exacto: 23 h 59 min 59,999999 s no basta."""
    fijar_reloj(monkeypatch, datetime(2026, 10, 8, 12, 0, 0, 1))
    hora = reservada(app, pro_id, "2026-10-09T12:00:00")
    assert cancelar_y_aviso(ana, hora)[0] == "error"
    assert fila(app, hora)[0] == "reservada"
    fijar_reloj(monkeypatch, datetime(2026, 10, 8, 12, 0, 0, 0))
    assert cancelar_y_aviso(ana, hora)[0] == "exito"


def test_una_reserva_que_ya_paso_no_se_cancela(app, pro_id, ana):
    hora = reservada(app, pro_id, "2026-10-07T10:00:00")
    categoria, texto = cancelar_y_aviso(ana, hora)
    assert categoria == "error" and POCA_ANTICIPACION in texto
    assert fila(app, hora)[0] == "reservada"


def test_una_hora_entre_la_carga_del_panel_y_el_clic_que_pasa_a_menos_de_24_h_se_rechaza(
    app, pro_id, ana, monkeypatch
):
    hora = reservada(app, pro_id, "2026-10-09T12:30:00")  # 24,5 h: ofrece el botón
    assert f"/horas/{hora}/cancelar" in ana.get("/paciente").text
    fijar_reloj(monkeypatch, datetime(2026, 10, 8, 13, 0))  # 23,5 h
    assert cancelar_y_aviso(ana, hora)[0] == "error"
    assert fila(app, hora)[0] == "reservada"


# ------------------------------------------ propiedad y mensajes únicos ----


def test_otro_paciente_no_puede_cancelar_la_reserva_ajena(app, pro_id, ana, beto):
    hora = reservada(app, pro_id, "2026-10-12T10:00:00")
    antes = fila_completa(app, hora)
    assert cancelar_y_aviso(beto, hora) == ("error", f"{NO_ENCONTRADA}. Puede que ya esté cancelada.")
    assert fila_completa(app, hora) == antes


def test_ajena_inexistente_libre_y_cancelada_dan_el_mismo_mensaje_y_destino(app, pro_id, ana, beto):
    ajena = reservada(app, pro_id, "2026-10-12T10:00:00")
    libre = insertar(app, pro_id, "2026-10-13T10:00:00")
    propia_cancelada = reservada(app, pro_id, "2026-10-14T10:00:00", email=BETO)
    cancelar(beto, propia_cancelada)
    resultados = {
        (cancelar_y_aviso(beto, h), cancelar(beto, h).headers["Location"])
        for h in (ajena, libre, propia_cancelada, 999, 2**63 - 1)
    }
    assert len(resultados) == 1
    (categoria, texto), destino = resultados.pop()
    assert categoria == "error" and destino == "/paciente"
    assert "Ana" not in texto and "ana@" not in texto and "otra persona" not in texto
    assert fila(app, ajena)[1] == uid(app, ANA) and fila(app, libre) == ("libre", None, None)


def test_una_reserva_ajena_que_empieza_en_menos_de_24_h_tampoco_se_distingue(app, pro_id, ana, beto):
    """Si se comprobaran las 24 h antes que la propiedad, Beto vería «anticipación» solo en las
    reservas ajenas que existen y están cerca: eso filtra que la hora está tomada."""
    cercana = reservada(app, pro_id, "2026-10-08T15:00:00")
    pasada = reservada(app, pro_id, "2026-10-07T10:00:00")
    inexistente = 997
    mensajes = {cancelar_y_aviso(beto, h) for h in (cercana, pasada, inexistente)}
    assert mensajes == {("error", f"{NO_ENCONTRADA}. Puede que ya esté cancelada.")}
    assert fila(app, cercana)[1] == uid(app, ANA)


def test_el_formulario_no_puede_cambiar_quien_cancela(app, pro_id, ana, beto):
    hora = reservada(app, pro_id, "2026-10-12T10:00:00")
    cancelar(beto, hora, paciente_id=str(uid(app, ANA)), estado="libre")
    assert fila(app, hora)[1] == uid(app, ANA)


def test_la_fila_con_fecha_ilegible_no_se_cancela_ni_da_500(app, pro_id, ana):
    mala = reservada(app, pro_id, "2026-13-45T99:99:99")
    assert cancelar_y_aviso(ana, mala)[0] == "error"
    assert fila(app, mala)[0] == "reservada"


# --------------------------------------------------- acceso y seguridad ----


def test_sin_sesion_redirige_a_login(app, pro_id, ana):
    hora = reservada(app, pro_id, "2026-10-12T10:00:00")
    client = app.test_client()
    token = extraer_token(client.get("/login").text)
    r = client.post(f"/horas/{hora}/cancelar", data={"csrf_token": token})
    assert r.status_code == 302 and r.headers["Location"] == "/login"
    assert fila(app, hora)[0] == "reservada"


def test_el_profesional_no_puede_cancelar(app, pro_id, ana):
    hora = reservada(app, pro_id, "2026-10-12T10:00:00")
    client = app.test_client()
    iniciar(client, "pro@example.cl")
    assert cancelar(client, hora, panel="/profesional").status_code == 403
    assert fila(app, hora)[1] == uid(app, ANA)


def test_sin_token_csrf_se_rechaza_y_no_se_cancela(app, pro_id, ana):
    hora = reservada(app, pro_id, "2026-10-12T10:00:00")
    assert cancelar(ana, hora, token=False).status_code == 400
    assert cancelar(ana, hora, token=False, csrf_token="x" * 64).status_code == 400
    assert fila(app, hora)[1] == uid(app, ANA)


def test_get_no_cancela(app, pro_id, ana):
    hora = reservada(app, pro_id, "2026-10-12T10:00:00")
    assert ana.get(f"/horas/{hora}/cancelar").status_code == 405
    assert fila(app, hora)[0] == "reservada"


@pytest.mark.parametrize("ruta", ["0", "-1", "abc", str(2**63), str(2**200), "1.5"])
def test_ids_invalidos_o_gigantes_dan_404(app, ana, ruta):
    token = extraer_token(ana.get("/paciente").text)
    assert ana.post(f"/horas/{ruta}/cancelar", data={"csrf_token": token}).status_code == 404


def test_el_id_maximo_de_sqlite_no_revienta(app, ana):
    assert cancelar_y_aviso(ana, 2**63 - 1)[0] == "error"


# ------------------------------------------- forma de la sentencia SQL ----


def hacer(app, funcion, hora, email=ANA, **extra):
    with app.app_context():
        return funcion(get_db(), hora, uid(app, email), **extra)


def test_la_primera_sentencia_es_begin_immediate_y_hay_un_solo_update(app, pro_id, ana):
    hora = reservada(app, pro_id, "2026-10-12T10:00:00")
    sentencias = []
    with app.app_context():
        db = get_db()
        db.set_trace_callback(sentencias.append)
        modulo_paciente.cancelar_reserva(db, hora, uid(app, ANA))
    assert sentencias[0] == "BEGIN IMMEDIATE" and sentencias[-1] == "COMMIT"
    updates = [s for s in sentencias if s.startswith("UPDATE horas SET")]
    assert len(updates) == 1
    update = " ".join(updates[0].split())
    # filtros del UPDATE condicional (D-003); el de estado es redundante con el CHECK, pero se fija
    assert update.endswith("WHERE id = %d AND paciente_id = %d AND estado = 'reservada'" % (hora, uid(app, ANA)))
    assert "recordatorio_enviado = 0" in update


def test_no_se_usa_replace_ni_se_borran_filas_en_paciente(app):
    fuente = Path(modulo_paciente.__file__).read_text().upper()
    assert "REPLACE INTO" not in fuente and "OR REPLACE" not in fuente and "DELETE" not in fuente


class Intruso:
    """Envuelve la conexión: justo antes del UPDATE `que` ejecuta antes `sql` (otra escritura que se coló)."""

    def __init__(self, db, que, sql, params=()):
        self._db, self._que, self._sql, self._params = db, que, sql, params

    def execute(self, sql, params=()):
        if sql.lstrip().startswith(self._que):
            self._db.execute(self._sql, self._params)
        return self._db.execute(sql, params)

    def __getattr__(self, nombre):
        return getattr(self._db, nombre)


def test_si_el_update_no_cambia_ninguna_fila_no_se_confirma_la_cancelacion(app, pro_id, ana, beto):
    """El intruso reasigna la reserva a Beto justo antes del UPDATE: el filtro de paciente deja
    rowcount en 0 y se revisa. Sin el filtro, el UPDATE liberaría la reserva de Beto; sin revisar
    rowcount, se confirmaría una cancelación que no ocurrió (y la escritura del intruso)."""
    hora = reservada(app, pro_id, "2026-10-12T10:00:00")
    antes = fila_completa(app, hora)
    with app.app_context():
        db = get_db()
        intruso = Intruso(
            db, "UPDATE horas SET estado = 'libre'",
            "UPDATE horas SET paciente_id = ? WHERE id = ?", (uid(app, BETO), hora),
        )
        ok, mensaje = modulo_paciente.cancelar_reserva(intruso, hora, uid(app, ANA))
        assert ok is False and NO_ENCONTRADA in mensaje and db.in_transaction is False
    assert fila_completa(app, hora) == antes  # la escritura del intruso también se deshizo


def test_si_la_reserva_se_libera_justo_antes_del_update_no_hay_exito(app, pro_id, ana):
    hora = reservada(app, pro_id, "2026-10-12T10:00:00")
    with app.app_context():
        db = get_db()
        intruso = Intruso(
            db, "UPDATE horas SET estado = 'libre'",
            "UPDATE horas SET estado='libre', paciente_id=NULL, reservada_en=NULL WHERE id = ?", (hora,),
        )
        ok, mensaje = modulo_paciente.cancelar_reserva(intruso, hora, uid(app, ANA))
        assert (ok, NO_ENCONTRADA in mensaje) == (False, True)


def test_entre_comprobar_y_actualizar_nadie_mas_puede_escribir(app, pro_id, ana, monkeypatch):
    """Con la comprobación hecha, otra conexión intenta tomar la hora: BEGIN IMMEDIATE la deja fuera."""
    hora = reservada(app, pro_id, "2026-10-12T10:00:00")
    resultado = {}
    original = tiempo.intervalo_guardado

    def comprobar_y_competir(fila_):
        rival = sqlite3.connect(app.config["DATABASE"], timeout=0.05)
        try:
            rival.execute("UPDATE horas SET paciente_id = 1 WHERE id = ?", (hora,))
            rival.commit()
            resultado["rival"] = "entró"
        except sqlite3.OperationalError as error:
            resultado["rival"] = str(error)
        finally:
            rival.close()
        return original(fila_)

    token = extraer_token(ana.get("/paciente").text)  # antes de armar al rival (el panel también lee fechas)
    monkeypatch.setattr(tiempo, "intervalo_guardado", comprobar_y_competir)
    ana.post(f"/horas/{hora}/cancelar", data={"csrf_token": token})
    assert resultado["rival"] == "database is locked"
    assert fila(app, hora)[0] == "libre"


# ------------------------------------------------------ «Mis reservas» ----


def filas_de_reservas(html):
    """Textos de las filas de la tabla «Mis reservas» (sin la cabecera)."""
    cuerpo = re.search(r"<tbody>(.*?)</tbody>", html, re.S)
    if not cuerpo:
        return []
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", f)).strip() for f in re.findall(r"<tr>(.*?)</tr>", cuerpo.group(1), re.S)]


def test_panel_sin_reservas(app, ana):
    r = ana.get("/paciente")
    assert "Mis reservas" in r.text and "No tienes reservas próximas." in r.text
    assert filas_de_reservas(r.text) == []


def test_mis_reservas_muestra_hora_duracion_y_profesional_ordenadas_por_instante(app, pro_id, ana):
    reservada(app, pro_id, "2026-10-15T10:00:00", duracion=30)  # insertadas en desorden
    reservada(app, pro_id, "2026-10-12T09:00:00", duracion=50)
    reservada(app, pro_id, "2026-10-13T09:00:00", duracion=45)
    filas = filas_de_reservas(ana.get("/paciente").text)
    assert [f.split(" min")[0] for f in filas] == [
        "12-10-2026 09:00 50", "13-10-2026 09:00 45", "15-10-2026 10:00 30",
    ]
    assert all("Dr. Pro" in f for f in filas)


def test_mis_reservas_solo_muestra_las_propias_y_futuras(app, pro_id, ana, beto):
    reservada(app, pro_id, "2026-10-12T09:00:00")
    reservada(app, pro_id, "2026-10-13T09:00:00", email=BETO)  # de otra persona
    insertar(app, pro_id, "2026-10-14T09:00:00")  # libre
    reservada(app, pro_id, "2026-10-07T09:00:00")  # pasada
    reservada(app, pro_id, "2026-10-08T11:00:00")  # ya empezó
    reservada(app, pro_id, "2026-10-08T12:00:00")  # justo ahora
    html = ana.get("/paciente").text
    assert [f[:16] for f in filas_de_reservas(html)] == ["12-10-2026 09:00"]
    assert [f[:16] for f in filas_de_reservas(beto.get("/paciente").text)] == ["13-10-2026 09:00"]


def test_el_boton_cancelar_solo_aparece_con_24_horas_o_mas(app, pro_id, ana):
    lejana = reservada(app, pro_id, "2026-10-12T09:00:00")
    justa = reservada(app, pro_id, "2026-10-09T12:00:00")  # 24 h exactas
    cercana = reservada(app, pro_id, "2026-10-09T11:59:59")
    manana_temprano = reservada(app, pro_id, "2026-10-08T15:00:00")
    html = ana.get("/paciente").text
    for hora in (lejana, justa):
        assert f'action="/horas/{hora}/cancelar"' in html
    for hora in (cercana, manana_temprano):
        assert f"/horas/{hora}/cancelar" not in html
    por_fila = {f[:16]: f for f in filas_de_reservas(html)}
    assert "Ya no se puede cancelar" in por_fila["09-10-2026 11:59"] and "Cancelar" not in por_fila["09-10-2026 11:59"].replace("Ya no se puede cancelar", "")
    assert "Ya no se puede cancelar" in por_fila["08-10-2026 15:00"]
    assert "Ya no se puede cancelar" not in por_fila["12-10-2026 09:00"]
    assert html.count('type="submit">Cancelar</button>') == 2


def test_cada_boton_cancelar_es_un_formulario_post_con_el_token_csrf(app, pro_id, ana):
    reservada(app, pro_id, "2026-10-12T09:00:00")
    reservada(app, pro_id, "2026-10-13T09:00:00")
    html = ana.get("/paciente").text
    formularios = re.findall(r'<form method="post" action="(/horas/\d+/cancelar)">(.*?)</form>', html, re.S)
    assert len(formularios) == 2
    with ana.session_transaction() as s:
        token = s["csrf_token"]
    for _, cuerpo in formularios:
        assert f'name="csrf_token" value="{token}"' in cuerpo


def test_cancelar_desde_el_formulario_de_la_pagina(app, pro_id, ana):
    """Recorrido por la interfaz: se lee el formulario del HTML y se envía tal cual."""
    hora = reservada(app, pro_id, "2026-10-12T09:00:00")
    html = ana.get("/paciente").text
    accion, cuerpo = re.search(r'<form method="post" action="(/horas/\d+/cancelar)">(.*?)</form>', html, re.S).groups()
    token = re.search(r'name="csrf_token" value="([0-9a-f]+)"', cuerpo).group(1)
    r = ana.post(accion, data={"csrf_token": token})
    assert r.status_code == 302 and fila(app, hora) == ("libre", None, None)


def test_el_nombre_del_profesional_se_escapa_en_mis_reservas(app, ana):
    pro = nuevo_profesional(app, "x@example.cl", "Dr <script>alert(1)</script>")
    reservada(app, pro, "2026-10-12T09:00:00")
    html = ana.get("/paciente").text
    assert "<script>alert(1)" not in html and "&lt;script&gt;" in html


def test_filas_raras_no_rompen_el_panel(app, pro_id, ana):
    reservada(app, pro_id, "2026-13-45T99:99:99")
    texto = reservada(app, pro_id, "2026-10-12T08:00:00")
    with app.app_context():
        db = get_db()
        db.execute("UPDATE horas SET duracion_min = 1.5 WHERE id = ?", (texto,))
        db.commit()
    bien = reservada(app, pro_id, "2026-10-13T10:00:00")
    r = ana.get("/paciente")
    assert r.status_code == 200
    assert [f[:16] for f in filas_de_reservas(r.text)] == ["13-10-2026 10:00"]
    assert f"/horas/{bien}/cancelar" in r.text


def test_el_panel_juzga_las_24_horas_con_instantes_en_la_noche_de_abril(app, pro_id, ana, monkeypatch, zona_sistema):
    """Ahora = 3-abr-2027 12:00 (UTC-3). El 4-abr a las 11:00 (UTC-4) son 24 h reales: botón.
    Con el reloj de pared serían 23 h y no se ofrecería."""
    fijar_reloj(monkeypatch, datetime(2027, 4, 3, 12, 0))
    justa = reservada(app, pro_id, "2027-04-04T11:00:00")
    corta = reservada(app, pro_id, "2027-04-04T10:59:59")
    html = ana.get("/paciente").text
    assert f"/horas/{justa}/cancelar" in html and f"/horas/{corta}/cancelar" not in html


def test_el_panel_no_ofrece_cancelar_lo_que_septiembre_ya_deja_corto(app, pro_id, ana, monkeypatch, zona_sistema):
    fijar_reloj(monkeypatch, datetime(2027, 9, 4, 12, 0))
    justa = reservada(app, pro_id, "2027-09-05T13:00:00")
    corta = reservada(app, pro_id, "2027-09-05T12:59:59")
    html = ana.get("/paciente").text
    assert f"/horas/{justa}/cancelar" in html and f"/horas/{corta}/cancelar" not in html


def test_el_panel_del_profesional_y_sin_sesion_no_cambian(app, pro_id):
    client = app.test_client()
    assert client.get("/paciente").status_code == 302
    iniciar(client, "pro@example.cl")
    assert client.get("/paciente").status_code == 403


# ----------------------------- reloj leído después del bloqueo (R-02) ----

FUNCIONES = {
    "reservar": modulo_paciente.reservar_hora,
    "cancelar": modulo_paciente.cancelar_reserva,
}


def preparar(app, pro_id, que):
    """Una hora sobre la que `que` tiene éxito con el reloj fijo."""
    if que == "reservar":
        return insertar(app, pro_id, "2026-10-12T10:00:00")
    return reservada(app, pro_id, "2026-10-12T10:00:00")


@pytest.mark.parametrize("que", ["reservar", "cancelar"])
def test_el_reloj_se_lee_dentro_de_la_transaccion_ya_con_el_bloqueo(app, pro_id, ana, que):
    hora = preparar(app, pro_id, que)
    sentencias, vistas = [], []
    with app.app_context():
        db = get_db()
        db.set_trace_callback(sentencias.append)

        def reloj():
            vistas.append((list(sentencias), db.in_transaction))
            return tiempo.ahora_chile()

        ok, _ = FUNCIONES[que](db, hora, uid(app, ANA), reloj)
    assert ok is True
    assert vistas == [(["BEGIN IMMEDIATE"], True)]


@pytest.mark.parametrize("que", ["reservar", "cancelar"])
def test_el_reloj_por_defecto_es_tiempo_ahora_chile_y_se_busca_al_llamar(app, pro_id, ana, que, monkeypatch):
    hora = preparar(app, pro_id, que)
    llamadas = []
    original = tiempo.ahora_chile
    monkeypatch.setattr(tiempo, "ahora_chile", lambda: llamadas.append(1) or original())
    assert hacer(app, FUNCIONES[que], hora)[0] is True
    assert llamadas == [1]


def retener_el_bloqueo(ruta, listo, soltado):
    """Otra conexión toma el bloqueo de escritura 0,3 s; avisa justo ANTES de soltarlo."""
    con = sqlite3.connect(ruta, timeout=5)
    con.execute("BEGIN IMMEDIATE")
    listo.set()
    threading.Event().wait(0.3)
    soltado.set()
    con.rollback()
    con.close()


def peticion_que_espera_el_bloqueo(app, monkeypatch, cliente, ruta_post, ahora_tras_la_espera):
    """Lanza la petición con el bloqueo tomado por otro. El reloj falso devuelve AHORA mientras el
    otro conserva el bloqueo y `ahora_tras_la_espera` desde que decidió soltarlo."""
    listo, soltado = threading.Event(), threading.Event()
    token = extraer_token(cliente.get("/paciente").text)  # antes de tomar el bloqueo
    monkeypatch.setattr(
        tiempo, "ahora_chile",
        lambda: (ahora_tras_la_espera if soltado.is_set() else AHORA).replace(tzinfo=auth.zona_chile()),
    )
    hilo = threading.Thread(target=retener_el_bloqueo, args=(app.config["DATABASE"], listo, soltado))
    hilo.start()
    assert listo.wait(5)
    respuesta = cliente.post(ruta_post, data={"csrf_token": token})
    hilo.join(5)
    assert soltado.is_set()
    return respuesta


def test_reservar_usa_el_ahora_posterior_a_la_espera_del_bloqueo(app, pro_id, ana, monkeypatch):
    """La hora empieza 24,5 h después de AHORA (T-08e: se puede reservar). La petición espera
    0,3 s el bloqueo; tras la espera «ahora» es AHORA + 1 h: faltan 23,5 h. Con el reloj leído
    antes de esperar se reservaría."""
    hora = insertar(app, pro_id, "2026-10-09T12:30:00")
    peticion_que_espera_el_bloqueo(app, monkeypatch, ana, f"/horas/{hora}/reservar", AHORA + timedelta(hours=1))
    assert fila(app, hora) == ("libre", None, None)


def test_reservada_en_es_el_instante_posterior_a_la_espera_del_bloqueo(app, pro_id, ana, monkeypatch):
    hora = insertar(app, pro_id, "2026-10-12T10:00:00")
    peticion_que_espera_el_bloqueo(app, monkeypatch, ana, f"/horas/{hora}/reservar", AHORA + timedelta(hours=1))
    assert fila(app, hora) == ("reservada", uid(app, ANA), "2026-10-08T13:00:00-03:00")


def test_cancelar_usa_el_ahora_posterior_a_la_espera_del_bloqueo(app, pro_id, ana, monkeypatch):
    """Faltan 24,5 h al empezar a esperar; tras la espera «ahora» es AHORA + 1 h (23,5 h): no se cancela."""
    hora = reservada(app, pro_id, "2026-10-09T12:30:00")
    r = peticion_que_espera_el_bloqueo(app, monkeypatch, ana, f"/horas/{hora}/cancelar", AHORA + timedelta(hours=1))
    assert r.status_code == 302
    assert fila(app, hora)[:2] == ("reservada", uid(app, ANA))


# ----------------------- cada salida deja la transacción cerrada (R-04) ----


def sin_transaccion_ni_bloqueo(app, db):
    """La conexión no tiene transacción abierta y otra conexión puede tomar el bloqueo de escritura."""
    assert db.in_transaction is False
    otra = sqlite3.connect(app.config["DATABASE"], timeout=0.05)
    try:
        otra.execute("BEGIN IMMEDIATE")
        otra.rollback()
    finally:
        otra.close()


def poner_solape(app, pro_id, hora_reservada_ana):
    """Reserva de Ana que se cruza con la hora libre del otro profesional."""
    otro = nuevo_profesional(app, "b@example.cl", "Profesional B")
    reservada(app, pro_id, hora_reservada_ana)
    return insertar(app, otro, hora_reservada_ana)


# (nombre, función, preparación -> hora_id, ok esperado)
def _rechazos(app, pro_id, beto):
    """Un caso por cada `return` de las dos funciones: devuelve {nombre: (que, hora_id, ok)}."""
    casos = {}
    casos["reservar: no existe"] = ("reservar", 999, False)
    casos["reservar: ocupada por otro"] = ("reservar", reservada(app, pro_id, "2026-10-12T10:00:00", email=BETO), False)
    casos["reservar: ya es tuya"] = ("reservar", reservada(app, pro_id, "2026-10-13T10:00:00"), False)
    casos["reservar: fecha ilegible"] = ("reservar", insertar(app, pro_id, "2026-13-45T99:99:99"), False)
    casos["reservar: ya empezó"] = ("reservar", insertar(app, pro_id, "2026-10-08T11:00:00"), False)
    casos["reservar: menos de 24 h"] = ("reservar", insertar(app, pro_id, "2026-10-09T11:00:00"), False)
    casos["reservar: solape"] = ("reservar", poner_solape(app, pro_id, "2026-10-14T10:00:00"), False)
    casos["reservar: éxito"] = ("reservar", insertar(app, pro_id, "2026-10-15T10:00:00"), True)
    casos["cancelar: no existe"] = ("cancelar", 998, False)
    casos["cancelar: ajena"] = ("cancelar", reservada(app, pro_id, "2026-10-16T10:00:00", email=BETO), False)
    casos["cancelar: libre"] = ("cancelar", insertar(app, pro_id, "2026-10-17T10:00:00"), False)
    casos["cancelar: fecha ilegible"] = ("cancelar", reservada(app, pro_id, "2026-13-45T99:98:99"), False)
    casos["cancelar: poca anticipación"] = ("cancelar", reservada(app, pro_id, "2026-10-08T15:00:00"), False)
    casos["cancelar: éxito"] = ("cancelar", reservada(app, pro_id, "2026-10-19T10:00:00"), True)
    return casos


def test_cada_salida_de_reservar_y_cancelar_cierra_la_transaccion(app, pro_id, ana, beto):
    casos = _rechazos(app, pro_id, beto)
    assert len(casos) == 14
    for nombre, (que, hora, ok_esperado) in casos.items():
        with app.app_context():
            db = get_db()
            ok, mensaje = FUNCIONES[que](db, hora, uid(app, ANA))
            assert ok is ok_esperado, (nombre, mensaje)
            try:
                sin_transaccion_ni_bloqueo(app, db)
            except (AssertionError, sqlite3.OperationalError) as error:
                raise AssertionError(f"{nombre}: la transacción quedó abierta ({error!r})")
            db.close()


@pytest.mark.parametrize("que", ["reservar", "cancelar"])
def test_la_condicion_de_carrera_del_update_cierra_la_transaccion(app, pro_id, ana, beto, que):
    """El UPDATE no cambia nada (rowcount 0 por una escritura que se coló): se hace rollback."""
    hora = preparar(app, pro_id, que)
    sql, params, inicio = {
        "reservar": ("UPDATE horas SET estado='reservada', paciente_id=?, reservada_en='x' WHERE id=?",
                     (uid(app, BETO), hora), "UPDATE horas SET estado = 'reservada'"),
        "cancelar": ("UPDATE horas SET paciente_id=? WHERE id=?", (uid(app, BETO), hora), "UPDATE horas SET estado = 'libre'"),
    }[que]
    with app.app_context():
        db = get_db()
        ok, _ = FUNCIONES[que](Intruso(db, inicio, sql, params), hora, uid(app, ANA))
        assert ok is False
        sin_transaccion_ni_bloqueo(app, db)


class Sabotaje:
    """Hace fallar la sentencia que empieza con `que` lanzando `excepcion`."""

    def __init__(self, db, que, excepcion):
        self._db, self._que, self.excepcion = db, que, excepcion

    def execute(self, sql, params=()):
        if sql.lstrip().startswith(self._que):
            raise self.excepcion
        return self._db.execute(sql, params)

    def __getattr__(self, nombre):
        return getattr(self._db, nombre)


EXCEPCIONES = [RuntimeError("fallo inesperado"), sqlite3.IntegrityError("CHECK constraint failed"), KeyboardInterrupt()]
EXCEPCIONES_ID = ["RuntimeError", "IntegrityError", "KeyboardInterrupt"]


@pytest.mark.parametrize("excepcion", EXCEPCIONES, ids=EXCEPCIONES_ID)
@pytest.mark.parametrize("que", ["reservar", "cancelar"])
@pytest.mark.parametrize("donde", ["SELECT", "UPDATE"])
def test_una_excepcion_inesperada_se_relanza_tras_el_rollback(app, pro_id, ana, que, donde, excepcion):
    hora = preparar(app, pro_id, que)
    antes = fila_completa(app, hora)
    with app.app_context():
        db = get_db()
        sabotaje = Sabotaje(db, donde, excepcion)
        with pytest.raises(type(excepcion)) as info:
            FUNCIONES[que](sabotaje, hora, uid(app, ANA))
        assert info.value is excepcion  # la misma excepción, sin envolver ni tragar
        sin_transaccion_ni_bloqueo(app, db)
    assert fila_completa(app, hora) == antes


@pytest.mark.parametrize("excepcion", EXCEPCIONES, ids=EXCEPCIONES_ID)
@pytest.mark.parametrize("que", ["reservar", "cancelar"])
def test_un_reloj_que_falla_tambien_deja_la_transaccion_cerrada(app, pro_id, ana, que, excepcion):
    """El reloj se lee con el bloqueo tomado: si falla, el rollback debe cubrirlo."""
    hora = preparar(app, pro_id, que)

    def reloj():
        raise excepcion

    with app.app_context():
        db = get_db()
        with pytest.raises(type(excepcion)):
            FUNCIONES[que](db, hora, uid(app, ANA), reloj)
        sin_transaccion_ni_bloqueo(app, db)


# ------------------------------------------------------- concurrencia ----


def _intentar(url_db, secret, email, accion, hora_id, barrera, salida):
    """Un 'cliente' completo (su app, su conexión). Guarda (estado HTTP, categoría del aviso)."""
    app = create_app({"TESTING": True, "DATABASE": url_db, "SECRET_KEY": secret})
    app.config["PROPAGATE_EXCEPTIONS"] = False
    client = app.test_client()
    iniciar(client, email)
    token = extraer_token(client.get("/paciente").text)
    barrera.wait(10)
    r = client.post(f"/horas/{hora_id}/{accion}", data={"csrf_token": token})
    categoria = None
    if r.status_code == 302:
        m = re.search(r'<p class="mensaje (\w+)"', client.get(r.headers["Location"]).text)
        categoria = m.group(1) if m else None
    salida.append((r.status_code, categoria))


def _lanzar(app, intentos, como):
    """`intentos`: lista de (email, accion, hora_id). `como`: 'hilos' o 'procesos'."""
    ruta, secreto = app.config["DATABASE"], app.config["SECRET_KEY"]
    if como == "hilos":
        barrera, salida = threading.Barrier(len(intentos)), []
        trabajos = [threading.Thread(target=_intentar, args=(ruta, secreto, e, a, h, barrera, salida)) for e, a, h in intentos]
    else:
        contexto = multiprocessing.get_context("fork")
        barrera, salida = contexto.Barrier(len(intentos)), contexto.Manager().list()
        trabajos = [contexto.Process(target=_intentar, args=(ruta, secreto, e, a, h, barrera, salida)) for e, a, h in intentos]
    for t in trabajos:
        t.start()
    for t in trabajos:
        t.join(60)
    assert len(salida) == len(intentos), "algún intento no terminó"
    return list(salida)


@pytest.mark.parametrize("como", ["hilos", "procesos"])
def test_dos_cancelaciones_simultaneas_de_la_misma_reserva_dan_un_solo_exito(app, pro_id, como):
    crear(app, email=ANA)
    for vuelta in range(5):
        hora = reservada(app, pro_id, f"2026-10-{12 + vuelta}T10:00:00")
        salida = _lanzar(app, [(ANA, "cancelar", hora)] * 2, como)
        assert all(codigo == 302 for codigo, _ in salida), salida
        assert sorted(c for _, c in salida) == ["error", "exito"]
        assert fila(app, hora) == ("libre", None, None)


@pytest.mark.parametrize("como", ["hilos", "procesos"])
def test_cancelar_y_reservar_la_misma_hora_a_la_vez_deja_un_estado_coherente(app, pro_id, como):
    """Ana cancela y Beto reserva la misma hora. O Beto llega después de la cancelación (queda con
    la hora) o llega antes (la hora aún es de Ana: falla) y la hora termina libre. Nunca otra cosa."""
    crear(app, email=ANA)
    crear(app, email=BETO)
    finales = set()
    for vuelta in range(8):
        hora = reservada(app, pro_id, f"2026-10-{12 + vuelta}T10:00:00")
        salida = _lanzar(app, [(ANA, "cancelar", hora), (BETO, "reservar", hora)], como)
        assert all(codigo == 302 for codigo, _ in salida), salida
        estado, paciente, reservada_en = fila(app, hora)
        # la cancelación de Ana siempre es válida (la hora está a días): una de las dos categorías es 'exito'
        resultados = sorted(c for _, c in salida)
        if estado == "libre":
            assert paciente is None and reservada_en is None
            assert resultados == ["error", "exito"]  # Beto llegó antes y falló
            finales.add("libre")
        else:
            assert (estado, paciente) == ("reservada", uid(app, BETO)) and reservada_en
            assert resultados == ["exito", "exito"]
            finales.add("beto")
        with app.app_context():
            assert get_db().execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert finales  # al menos un resultado; ambos son legítimos
