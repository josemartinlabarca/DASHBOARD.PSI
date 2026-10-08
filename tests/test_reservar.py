"""T-07: reservar una hora (US-8; SPEC §4 reglas 1 y 5; D-003)."""
import multiprocessing
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

import pytest

from app import auth, create_app, paciente as modulo_paciente, tiempo
from app.db import get_db, init_db
from tests.test_horas_libres import AHORA, fijar_reloj, inicios_mostrados, insertar, nuevo_profesional
from tests.test_login import CLAVE, crear, iniciar
from tests.test_seguridad import extraer_token

LIBRE = "Esa hora ya no está disponible"


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


def nuevo_paciente(app, email="ana@example.cl", nombre="Ana Pérez"):
    crear(app, email=email, rol="paciente", nombre=nombre)
    client = app.test_client()
    iniciar(client, email)
    return client


@pytest.fixture
def ana(app):
    return nuevo_paciente(app)


@pytest.fixture
def beto(app):
    return nuevo_paciente(app, "beto@example.cl", "Beto Soto")


def uid(app, email):
    with app.app_context():
        return get_db().execute("SELECT id FROM usuarios WHERE email = ?", (email,)).fetchone()[0]


def fila(app, hora_id):
    with app.app_context():
        return tuple(
            get_db()
            .execute("SELECT estado, paciente_id, reservada_en FROM horas WHERE id = ?", (hora_id,))
            .fetchone()
        )


def todas(app):
    with app.app_context():
        return [tuple(f) for f in get_db().execute("SELECT * FROM horas ORDER BY id").fetchall()]


def reservar(client, hora_id, token=True, panel="/paciente", **extra):
    datos = dict(extra)
    if token:
        datos["csrf_token"] = extraer_token(client.get(panel).text)
    return client.post(f"/horas/{hora_id}/reservar", data=datos)


def aviso(client, respuesta):
    """Texto del mensaje que se muestra al seguir la redirección."""
    assert respuesta.status_code == 302
    html = client.get(respuesta.headers["Location"]).text
    m = re.search(r'<p class="mensaje (\w+)" role="status">(.*?)</p>', html, re.S)
    assert m, html
    return m.group(1), m.group(2)


def reservar_y_aviso(client, hora_id, **extra):
    return aviso(client, reservar(client, hora_id, **extra))


# ---------------------------------------------------------- reserva ok ----


def test_reserva_exitosa(app, pro_id, ana):
    hora = insertar(app, pro_id, "2026-10-09T10:00:00")
    r = reservar(ana, hora)
    assert r.status_code == 302 and r.headers["Location"] == "/paciente"
    assert fila(app, hora) == ("reservada", uid(app, "ana@example.cl"), "2026-10-08T12:00:00-03:00")
    categoria, texto = aviso(ana, r)
    assert categoria == "exito"
    assert "09-10-2026 10:00" in texto and "Dr. Pro" in texto


def test_reservada_en_es_iso_de_chile_con_zona_como_creado_en(app, pro_id, ana, monkeypatch):
    """Formato `YYYY-MM-DDTHH:MM:SS±HH:MM`, el mismo de `usuarios.creado_en`; en invierno -04:00."""
    fijar_reloj(monkeypatch, datetime(2027, 7, 1, 9, 5, 7))
    hora = insertar(app, pro_id, "2027-07-02T10:00:00")
    reservar(ana, hora)
    assert fila(app, hora)[2] == "2027-07-01T09:05:07-04:00"
    with app.app_context():
        creado = get_db().execute("SELECT creado_en FROM usuarios LIMIT 1").fetchone()[0]
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d-0[34]:00", creado)


def test_reservada_en_trae_segundos_sin_fraccion(app, pro_id, ana, monkeypatch):
    fijar_reloj(monkeypatch, datetime(2026, 10, 8, 12, 0, 0, 987654))
    hora = insertar(app, pro_id, "2026-10-09T10:00:00")
    reservar(ana, hora)
    assert fila(app, hora)[2] == "2026-10-08T12:00:00-03:00"


def test_la_hora_reservada_deja_de_aparecer_en_la_lista(app, pro_id, ana):
    a = insertar(app, pro_id, "2026-10-09T10:00:00")
    insertar(app, pro_id, "2026-10-09T12:00:00")
    ana.get(reservar(ana, a).headers["Location"])  # consume el aviso de confirmación
    assert inicios_mostrados(ana.get("/paciente/horas").text) == ["09-10-2026 12:00"]


def test_solo_cambia_la_fila_reservada(app, pro_id, ana):
    a = insertar(app, pro_id, "2026-10-09T10:00:00")
    b = insertar(app, pro_id, "2026-10-09T12:00:00")
    antes = todas(app)
    reservar(ana, a)
    despues = todas(app)
    assert [f for f in despues if f[0] == b] == [f for f in antes if f[0] == b]
    assert len(despues) == len(antes)


def test_el_paciente_de_la_sesion_se_ignora_lo_que_diga_el_formulario(app, pro_id, ana, beto):
    hora = insertar(app, pro_id, "2026-10-09T10:00:00")
    reservar(ana, hora, paciente_id=str(uid(app, "beto@example.cl")), reservada_en="2000-01-01")
    assert fila(app, hora) == ("reservada", uid(app, "ana@example.cl"), "2026-10-08T12:00:00-03:00")


# ------------------------------------------------- acceso y seguridad ----


def test_sin_sesion_redirige_a_login(app, pro_id):
    hora = insertar(app, pro_id, "2026-10-09T10:00:00")
    client = app.test_client()
    token = extraer_token(client.get("/login").text)
    r = client.post(f"/horas/{hora}/reservar", data={"csrf_token": token})
    assert r.status_code == 302 and r.headers["Location"] == "/login"
    assert fila(app, hora)[0] == "libre"


def test_el_profesional_no_puede_reservar(app, pro_id):
    hora = insertar(app, pro_id, "2026-10-09T10:00:00")
    client = app.test_client()
    iniciar(client, "pro@example.cl")
    r = reservar(client, hora, panel="/profesional")
    assert r.status_code == 403
    assert fila(app, hora) == ("libre", None, None)


def test_sin_token_csrf_se_rechaza_y_no_se_reserva(app, pro_id, ana):
    hora = insertar(app, pro_id, "2026-10-09T10:00:00")
    assert reservar(ana, hora, token=False).status_code == 400
    assert reservar(ana, hora, token=False, csrf_token="x" * 64).status_code == 400
    assert fila(app, hora) == ("libre", None, None)


def test_get_no_reserva(app, pro_id, ana):
    hora = insertar(app, pro_id, "2026-10-09T10:00:00")
    assert ana.get(f"/horas/{hora}/reservar").status_code == 405
    assert fila(app, hora)[0] == "libre"


@pytest.mark.parametrize("ruta", ["0", "-1", "abc", str(2**63), str(2**200), "1.5"])
def test_ids_invalidos_o_gigantes_dan_404(app, pro_id, ana, ruta):
    token = extraer_token(ana.get("/paciente").text)
    r = ana.post(f"/horas/{ruta}/reservar", data={"csrf_token": token})
    assert r.status_code == 404


def test_el_id_maximo_de_sqlite_no_revienta(app, ana):
    r = reservar(ana, 2**63 - 1)
    assert aviso(ana, r) == ("error", f"{LIBRE}. Elige otra de la lista.")


# ------------------------------------------------ regla 1: doble reserva ----


def test_la_segunda_reserva_de_la_misma_hora_falla(app, pro_id, ana, beto):
    hora = insertar(app, pro_id, "2026-10-09T10:00:00")
    reservar(ana, hora)
    r = reservar(beto, hora)
    assert r.status_code == 302 and r.headers["Location"] == "/paciente/horas"
    categoria, texto = aviso(beto, r)
    assert categoria == "error" and LIBRE in texto
    assert fila(app, hora) == ("reservada", uid(app, "ana@example.cl"), "2026-10-08T12:00:00-03:00")


def test_el_mensaje_no_revela_quien_tiene_la_hora_ni_si_existe(app, pro_id, ana, beto):
    """Hora de otra persona, hora eliminada y hora que nunca existió dan el mismo texto."""
    ocupada = insertar(app, pro_id, "2026-10-09T10:00:00")
    eliminada = insertar(app, pro_id, "2026-10-09T12:00:00")
    reservar(ana, ocupada)
    with app.app_context():
        db = get_db()
        db.execute("DELETE FROM horas WHERE id = ?", (eliminada,))
        db.commit()
    mensajes = {reservar_y_aviso(beto, h) for h in (ocupada, eliminada, 999)}
    assert len(mensajes) == 1
    _, texto = mensajes.pop()
    assert "Ana" not in texto and "ana@" not in texto and "otra persona" not in texto


def test_doble_clic_del_mismo_paciente_dice_ya_reservaste(app, pro_id, ana):
    hora = insertar(app, pro_id, "2026-10-09T10:00:00")
    reservar(ana, hora)
    estado = fila(app, hora)
    assert reservar_y_aviso(ana, hora) == ("error", "Ya reservaste esta hora.")
    assert fila(app, hora) == estado


def test_hora_eliminada_por_el_profesional_da_mensaje_y_no_500(app, pro_id, ana):
    hora = insertar(app, pro_id, "2026-10-09T10:00:00")
    html = ana.get("/paciente/horas").text  # el paciente ya la tenía en pantalla
    assert "09-10-2026 10:00" in html
    pro = app.test_client()
    iniciar(pro, "pro@example.cl")
    token = extraer_token(pro.get("/profesional").text)
    assert pro.post(f"/profesional/horas/{hora}/eliminar", data={"csrf_token": token}).status_code == 302
    r = reservar(ana, hora)
    assert r.status_code == 302
    assert aviso(ana, r)[0] == "error"
    assert todas(app) == []


def test_el_update_condicional_decide_y_se_revisa_rowcount(app, pro_id, ana, beto):
    """Si el UPDATE no cambia ninguna fila (otra escritura se coló) no se confirma la reserva."""
    hora = insertar(app, pro_id, "2026-10-09T10:00:00")
    otro = uid(app, "beto@example.cl")

    class Intruso:
        def __init__(self, db):
            self._db = db

        def execute(self, sql, params=()):
            if sql.lstrip().startswith("UPDATE horas SET estado = 'reservada'"):
                self._db.execute(
                    "UPDATE horas SET estado = 'reservada', paciente_id = ?, reservada_en = 'x'"
                    " WHERE id = ?",
                    (otro, hora),
                )
            return self._db.execute(sql, params)

        def __getattr__(self, nombre):
            return getattr(self._db, nombre)

    with app.app_context():
        db = get_db()
        ok, mensaje = modulo_paciente.reservar_hora(
            Intruso(db), hora, uid(app, "ana@example.cl"), tiempo.ahora_chile()
        )
        assert (ok, LIBRE in mensaje) == (False, True)
        assert db.in_transaction is False
    assert fila(app, hora) == ("libre", None, None)  # la escritura del intruso se deshizo


def test_la_reserva_se_hace_con_update_condicional_sin_replace():
    codigo = Path(modulo_paciente.__file__).read_text()
    assert "AND estado = 'libre'" in codigo
    for archivo in Path(modulo_paciente.__file__).parent.glob("*.py"):
        fuente = archivo.read_text().upper()
        assert "REPLACE INTO" not in fuente and "OR REPLACE" not in fuente


def test_la_primera_sentencia_es_begin_immediate(app, pro_id, ana):
    hora = insertar(app, pro_id, "2026-10-09T10:00:00")
    sentencias = []
    with app.app_context():
        db = get_db()
        db.set_trace_callback(sentencias.append)
        modulo_paciente.reservar_hora(db, hora, uid(app, "ana@example.cl"), tiempo.ahora_chile())
    assert sentencias[0] == "BEGIN IMMEDIATE"
    assert sentencias[-1] == "COMMIT"
    assert sum(s.startswith("UPDATE horas SET") for s in sentencias) == 1


def test_entre_comprobar_y_actualizar_nadie_mas_puede_escribir(app, pro_id, ana, monkeypatch):
    """Con la comprobación ya hecha, otra conexión intenta reservar la misma hora: BEGIN
    IMMEDIATE la deja fuera (`database is locked`). Sin bloqueo temprano, entraría."""
    hora = insertar(app, pro_id, "2026-10-09T10:00:00")
    resultado = {}
    original = tiempo.intervalo_guardado

    def comprobar_y_competir(fila_):
        rival = sqlite3.connect(app.config["DATABASE"], timeout=0.05)
        try:
            rival.execute(
                "UPDATE horas SET estado='reservada', paciente_id=1, reservada_en='x' WHERE id=?",
                (hora,),
            )
            rival.commit()
            resultado["rival"] = "entró"
        except sqlite3.OperationalError as error:
            resultado["rival"] = str(error)
        finally:
            rival.close()
        return original(fila_)

    monkeypatch.setattr(tiempo, "intervalo_guardado", comprobar_y_competir)
    reservar(ana, hora)
    assert resultado["rival"] == "database is locked"
    assert fila(app, hora)[1] == uid(app, "ana@example.cl")


# ------------------------------------------------------ hora futura ----


def test_no_se_reserva_una_hora_que_ya_empezo_o_paso(app, pro_id, ana):
    pasadas = [
        insertar(app, pro_id, "2026-10-07T10:00:00"),
        insertar(app, pro_id, "2026-10-08T11:30:00"),  # en curso
        insertar(app, pro_id, "2026-10-08T11:59:59"),
        insertar(app, pro_id, "2026-10-08T12:00:00"),  # justo ahora
    ]
    for hora in pasadas:
        categoria, texto = reservar_y_aviso(ana, hora)
        assert categoria == "error" and "ya empezó o ya pasó" in texto
        assert fila(app, hora) == ("libre", None, None)


def test_un_segundo_despues_de_ahora_si_se_reserva(app, pro_id, ana):
    hora = insertar(app, pro_id, "2026-10-08T12:00:01")
    reservar(ana, hora)
    assert fila(app, hora)[0] == "reservada"


def test_la_hora_se_juzga_en_chile_y_no_en_utc(app, pro_id, ana):
    """Chile 12:00 = 15:00 UTC: la de las 13:00 chilenas es futura aunque en UTC ya pasó."""
    hora = insertar(app, pro_id, "2026-10-08T13:00:00")
    reservar(ana, hora)
    assert fila(app, hora)[0] == "reservada"


def test_la_hora_que_empieza_entre_la_carga_de_la_lista_y_el_clic_se_rechaza(
    app, pro_id, ana, monkeypatch
):
    hora = insertar(app, pro_id, "2026-10-08T12:30:00")
    assert "08-10-2026 12:30" in ana.get("/paciente/horas").text
    fijar_reloj(monkeypatch, datetime(2026, 10, 8, 12, 31))
    assert reservar_y_aviso(ana, hora)[0] == "error"
    assert fila(app, hora)[0] == "libre"


def test_futuro_o_pasado_se_decide_con_instantes_y_no_con_el_reloj_de_pared(
    app, pro_id, ana, monkeypatch
):
    """Noche de abril 2027: ahora son las 23:10 de la SEGUNDA vez (UTC-4 = 03:10Z). La hora
    guardada 23:40 se lee con fold=0 (UTC-3 = 02:40Z): ya pasó, aunque 23:40 > 23:10 en el reloj."""
    fijar_reloj(monkeypatch, datetime(2027, 4, 3, 23, 10), fold=1)
    hora = insertar(app, pro_id, "2027-04-03T23:40:00")
    assert reservar_y_aviso(ana, hora)[0] == "error"
    assert fila(app, hora)[0] == "libre"


# ------------------------------------------------- regla 5: solapes ----


def dos_profesionales(app):
    return nuevo_profesional(app, "a@example.cl", "Profesional A"), nuevo_profesional(
        app, "b@example.cl", "Profesional B"
    )


def con_reserva_existente(app, ana, inicio="2026-10-09T10:00:00", duracion=50):
    a, b = dos_profesionales(app)
    primera = insertar(app, a, inicio, duracion)
    reservar(ana, primera)
    assert fila(app, primera)[0] == "reservada"
    return a, b


@pytest.mark.parametrize(
    "inicio, duracion",
    [
        ("2026-10-09T10:00:00", 50),  # mismo inicio y duración
        ("2026-10-09T10:00:00", 10),  # mismo inicio, otra duración
        ("2026-10-09T10:30:00", 50),  # empieza dentro
        ("2026-10-09T10:49:59", 50),  # empieza un segundo antes del fin
        ("2026-10-09T09:30:00", 50),  # termina dentro
        ("2026-10-09T09:59:00", 2),  # termina un minuto después del inicio
        ("2026-10-09T09:00:00", 180),  # la contiene
        ("2026-10-09T10:10:00", 10),  # está contenida
    ],
)
def test_solapes_del_mismo_paciente_se_rechazan(app, ana, inicio, duracion):
    _, b = con_reserva_existente(app, ana)
    intento = insertar(app, b, inicio, duracion)  # otro profesional: igualdad de inicio no basta
    categoria, texto = reservar_y_aviso(ana, intento)
    assert categoria == "error" and "se cruza con otra hora que ya reservaste" in texto
    assert "09-10-2026 10:00" in texto
    assert fila(app, intento) == ("libre", None, None)


@pytest.mark.parametrize(
    "inicio, duracion",
    [
        ("2026-10-09T10:50:00", 50),  # empieza justo cuando termina la otra
        ("2026-10-09T09:10:00", 50),  # termina justo cuando empieza la otra
        ("2026-10-09T11:00:00", 50),
        ("2026-10-10T10:00:00", 50),  # otro día, misma hora
    ],
)
def test_horas_adyacentes_o_separadas_se_reservan(app, ana, inicio, duracion):
    _, b = con_reserva_existente(app, ana)
    intento = insertar(app, b, inicio, duracion)
    reservar(ana, intento)
    assert fila(app, intento)[0] == "reservada"


def test_mismo_inicio_con_el_mismo_profesional_no_existe_pero_con_dos_si_se_rechaza(app, ana):
    a, b = dos_profesionales(app)
    una = insertar(app, a, "2026-10-09T10:00:00")
    otra = insertar(app, b, "2026-10-09T10:00:00")
    reservar(ana, una)
    assert reservar_y_aviso(ana, otra)[0] == "error"


def test_las_reservas_de_otros_pacientes_no_bloquean(app, ana, beto):
    a, b = dos_profesionales(app)
    con_ana = insertar(app, a, "2026-10-09T10:00:00")
    para_beto = insertar(app, b, "2026-10-09T10:20:00")
    reservar(ana, con_ana)
    reservar(beto, para_beto)  # solapada con la de Ana, pero son personas distintas
    assert fila(app, para_beto) == ("reservada", uid(app, "beto@example.cl"), "2026-10-08T12:00:00-03:00")


def test_una_reserva_liberada_ya_no_bloquea(app, ana):
    a, b = dos_profesionales(app)
    primera = insertar(app, a, "2026-10-09T10:00:00")
    segunda = insertar(app, b, "2026-10-09T10:20:00")
    reservar(ana, primera)
    with app.app_context():
        db = get_db()
        db.execute(
            "UPDATE horas SET estado='libre', paciente_id=NULL, reservada_en=NULL WHERE id=?",
            (primera,),
        )
        db.commit()
    reservar(ana, segunda)
    assert fila(app, segunda)[0] == "reservada"


def test_un_rechazo_no_deja_la_transaccion_abierta(app, ana):
    _, b = con_reserva_existente(app, ana)
    intento = insertar(app, b, "2026-10-09T10:10:00")
    with app.app_context():
        db = get_db()
        ok, _ = modulo_paciente.reservar_hora(
            db, intento, uid(app, "ana@example.cl"), tiempo.ahora_chile()
        )
        assert ok is False and db.in_transaction is False


def test_filas_raras_del_paciente_no_rompen_la_comprobacion(app, ana):
    """El CHECK deja pasar fechas imposibles y duraciones de otro tipo; no son 500."""
    a, b = dos_profesionales(app)
    mala = insertar(app, a, "2026-13-45T99:99:99")
    texto = insertar(app, a, "2026-10-09T08:00:00")
    with app.app_context():
        db = get_db()
        pid = uid(app, "ana@example.cl")
        db.execute(
            "UPDATE horas SET estado='reservada', paciente_id=?, reservada_en='x' WHERE id IN (?, ?)",
            (pid, mala, texto),
        )
        db.execute("UPDATE horas SET duracion_min = 1.5 WHERE id = ?", (texto,))
        db.commit()
    bien = insertar(app, b, "2026-10-09T10:00:00")
    reservar(ana, bien)
    assert fila(app, bien)[0] == "reservada"
    assert reservar_y_aviso(ana, mala)[0] == "error"  # fecha imposible: no disponible, no 500


def test_solape_entre_septiembre_con_instantes_absolutos(app, ana, monkeypatch):
    """4-sep-2027 23:30 + 90 min reales = 02:00 del reloj (el reloj salta 24:00 -> 01:00):
    la de 01:45 se cruza. Con reloj de pared (fin 01:00) no se vería el cruce; la de 02:00
    (justo cuando termina) sí se reserva."""
    fijar_reloj(monkeypatch, datetime(2027, 9, 1, 9, 0))
    a, b = dos_profesionales(app)
    reservar(ana, insertar(app, a, "2027-09-04T23:30:00", 90))
    cruza = insertar(app, b, "2027-09-05T01:45:00", 20)
    pegada = insertar(app, b, "2027-09-05T02:00:00", 20)
    assert reservar_y_aviso(ana, cruza)[0] == "error"
    reservar(ana, pegada)
    assert fila(app, pegada)[0] == "reservada"


def test_solape_entre_abril_con_instantes_absolutos(app, ana, monkeypatch):
    """3-abr-2027 22:30 + 120 min reales termina a las 23:30 del reloj (UTC-4). Con reloj de
    pared terminaría a las 00:30 y la de las 00:10 se vería cruzada; en realidad es posterior."""
    fijar_reloj(monkeypatch, datetime(2027, 4, 1, 9, 0))
    a, b = dos_profesionales(app)
    reservar(ana, insertar(app, a, "2027-04-03T22:30:00", 120))
    despues = insertar(app, b, "2027-04-04T00:10:00", 20)
    reservar(ana, despues)
    assert fila(app, despues)[0] == "reservada"


# -------------------------------------------------------- concurrencia ----


def _intentar(url_db, secret, email, hora_id, barrera, salida):
    """Un 'cliente' completo en su propia app y conexión; todos disparan a la vez."""
    app = create_app({"TESTING": True, "DATABASE": url_db, "SECRET_KEY": secret})
    app.config["PROPAGATE_EXCEPTIONS"] = False
    client = app.test_client()
    iniciar(client, email)
    token = extraer_token(client.get("/paciente").text)
    barrera.wait(10)
    r = client.post(f"/horas/{hora_id}/reservar", data={"csrf_token": token})
    salida.append((r.status_code, r.headers.get("Location")))


def _lanzar(app, intentos, como):
    """`intentos`: lista de (email, hora_id). `como`: 'hilos' o 'procesos'."""
    ruta = app.config["DATABASE"]
    secreto = app.config["SECRET_KEY"]
    if como == "hilos":
        barrera, salida, trabajos = threading.Barrier(len(intentos)), [], []
        crear_trabajo = lambda args: threading.Thread(target=_intentar, args=args)  # noqa: E731
    else:
        contexto = multiprocessing.get_context("fork")
        gestor = contexto.Manager()
        barrera, salida = contexto.Barrier(len(intentos)), gestor.list()
        crear_trabajo = lambda args: contexto.Process(target=_intentar, args=args)  # noqa: E731
    trabajos = [crear_trabajo((ruta, secreto, e, h, barrera, salida)) for e, h in intentos]
    for t in trabajos:
        t.start()
    for t in trabajos:
        t.join(60)
    assert len(salida) == len(intentos), "algún intento no terminó"
    return list(salida)


@pytest.mark.parametrize("como", ["hilos", "procesos"])
def test_dos_pacientes_a_la_vez_por_la_misma_hora_dan_un_solo_exito(app, pro_id, como):
    for correo in ("p1@example.cl", "p2@example.cl", "p3@example.cl", "p4@example.cl"):
        crear(app, email=correo)
    for vuelta in range(5):
        hora = insertar(app, pro_id, f"2026-10-{10 + vuelta}T10:00:00")
        salida = _lanzar(
            app, [(c, hora) for c in ("p1@example.cl", "p2@example.cl", "p3@example.cl", "p4@example.cl")], como
        )
        assert all(codigo == 302 for codigo, _ in salida), salida  # ninguno da 500
        assert fila(app, hora)[0] == "reservada"
        # exactamente uno terminó en el panel (éxito); los demás volvieron a la lista
        assert sorted(destino for _, destino in salida) == ["/paciente"] + ["/paciente/horas"] * 3


@pytest.mark.parametrize("como", ["hilos", "procesos"])
def test_el_mismo_paciente_con_dos_horas_solapadas_a_la_vez_se_queda_con_una(app, como):
    a, b = dos_profesionales(app)
    crear(app, email="ana@example.cl")
    for vuelta in range(5):
        dia = 10 + vuelta
        h1 = insertar(app, a, f"2026-10-{dia}T10:00:00")
        h2 = insertar(app, b, f"2026-10-{dia}T10:20:00")
        salida = _lanzar(app, [("ana@example.cl", h1), ("ana@example.cl", h2)], como)
        assert all(codigo == 302 for codigo, _ in salida), salida
        estados = sorted([fila(app, h1)[0], fila(app, h2)[0]])
        assert estados == ["libre", "reservada"]
        assert sorted(destino for _, destino in salida) == ["/paciente", "/paciente/horas"]
