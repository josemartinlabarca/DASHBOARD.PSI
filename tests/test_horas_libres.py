"""T-06: el paciente ve las horas libres y futuras (US-7; SPEC §4)."""
import re
from datetime import datetime

import pytest

from app import auth, paciente, profesional, tiempo
from app.db import get_db, init_db
from tests.test_login import crear, iniciar

# "Ahora" fijo: 12:00 en Chile (UTC-3 en octubre) = 15:00 UTC. Una hora de las
# 13:00 de hoy es futura en Chile pero ya pasó si se compara con la hora UTC.
AHORA = datetime(2026, 10, 8, 12, 0)


def fijar_reloj(monkeypatch, ahora=AHORA, **extra):
    monkeypatch.setattr(
        tiempo, "ahora_chile", lambda: ahora.replace(tzinfo=auth.zona_chile(), **extra)
    )


@pytest.fixture(autouse=True)
def base_inicializada(app):
    with app.app_context():
        init_db()


@pytest.fixture(autouse=True)
def reloj_fijo(monkeypatch):
    fijar_reloj(monkeypatch)


@pytest.fixture
def paciente_cli(app):
    crear(app, email="ana@example.cl", rol="paciente", nombre="Ana Pérez")
    client = app.test_client()
    iniciar(client, "ana@example.cl")
    return client


def nuevo_profesional(app, email="pro@example.cl", nombre="Dr. Pro"):
    crear(app, email=email, rol="profesional", nombre=nombre)
    with app.app_context():
        return get_db().execute("SELECT id FROM usuarios WHERE email = ?", (email,)).fetchone()[0]


def insertar(app, pro_id, inicio, duracion=50):
    with app.app_context():
        db = get_db()
        cursor = db.execute(
            "INSERT INTO horas (profesional_id, inicio, duracion_min) VALUES (?, ?, ?)",
            (pro_id, inicio, duracion),
        )
        db.commit()
        return cursor.lastrowid


def reservar_directo(app, hora_id, paciente_email="otra@example.cl"):
    crear(app, email=paciente_email, rol="paciente", nombre="Otra Paciente")
    with app.app_context():
        db = get_db()
        pid = db.execute("SELECT id FROM usuarios WHERE email = ?", (paciente_email,)).fetchone()[0]
        db.execute(
            "UPDATE horas SET estado = 'reservada', paciente_id = ?, reservada_en = ? WHERE id = ?",
            (pid, "2026-10-08T11:00:00", hora_id),
        )
        db.commit()


def inicios_mostrados(html):
    return re.findall(r"\d\d-\d\d-\d{4} \d\d:\d\d", html)


@pytest.fixture
def pro_id(app):
    return nuevo_profesional(app)


# ------------------------------------------------------------- acceso ----


def test_sin_sesion_redirige_a_login(client):
    r = client.get("/paciente/horas")
    assert r.status_code == 302 and r.headers["Location"] == "/login"


def test_el_profesional_recibe_403(app, pro_id):
    client = app.test_client()
    iniciar(client, "pro@example.cl")
    insertar(app, pro_id, "2026-10-09T10:00:00")
    r = client.get("/paciente/horas")
    assert r.status_code == 403
    assert "09-10-2026" not in r.text


def test_el_paciente_recibe_200_con_no_store(paciente_cli):
    r = paciente_cli.get("/paciente/horas")
    assert r.status_code == 200
    assert "no-store" in r.headers["Cache-Control"]
    assert "Horas disponibles" in r.text


def test_el_panel_del_paciente_enlaza_a_la_lista(paciente_cli):
    r = paciente_cli.get("/paciente")
    assert re.search(r'<a href="/paciente/horas">Ver horas disponibles</a>', r.text)


def test_no_hay_boton_de_reservar_todavia(app, pro_id, paciente_cli):
    insertar(app, pro_id, "2026-10-09T10:00:00")
    r = paciente_cli.get("/paciente/horas")
    assert "<form" not in r.text and "<button" not in r.text
    assert "reservar" not in r.text.lower()


def test_solo_acepta_get(paciente_cli):
    assert paciente_cli.post("/paciente/horas").status_code in (400, 405)


def test_el_reloj_es_un_unico_punto_parcheable():
    """Ningún módulo de rutas guarda su propia copia del reloj: se parchea `tiempo`."""
    assert not hasattr(profesional, "ahora_chile")
    assert not hasattr(paciente, "ahora_chile")


# ----------------------------------------------------------- contenido ----


def test_con_cero_horas_muestra_un_mensaje_amable(paciente_cli):
    r = paciente_cli.get("/paciente/horas")
    assert "Por ahora no hay horas disponibles" in r.text
    assert "<table" not in r.text


def test_solo_aparecen_horas_libres(app, pro_id, paciente_cli):
    insertar(app, pro_id, "2026-10-09T10:00:00")
    reservada = insertar(app, pro_id, "2026-10-09T11:00:00")
    insertar(app, pro_id, "2026-10-09T12:00:00")
    reservar_directo(app, reservada)
    assert inicios_mostrados(paciente_cli.get("/paciente/horas").text) == [
        "09-10-2026 10:00",
        "09-10-2026 12:00",
    ]


def test_no_aparecen_las_pasadas(app, pro_id, paciente_cli):
    insertar(app, pro_id, "2026-10-07T10:00:00")
    insertar(app, pro_id, "2026-10-08T09:00:00")
    insertar(app, pro_id, "2026-10-08T13:00:00")
    assert inicios_mostrados(paciente_cli.get("/paciente/horas").text) == ["08-10-2026 13:00"]


def test_no_aparece_la_que_ya_empezo_ni_la_que_empieza_justo_ahora(app, pro_id, paciente_cli):
    insertar(app, pro_id, "2026-10-08T11:30:00", 50)  # empezó hace 30 min y sigue en curso
    insertar(app, pro_id, "2026-10-08T11:59:59", 50)
    insertar(app, pro_id, "2026-10-08T12:00:00", 50)  # justo ahora: ya empezó
    insertar(app, pro_id, "2026-10-08T12:00:01", 50)
    assert inicios_mostrados(paciente_cli.get("/paciente/horas").text) == ["08-10-2026 12:00"]


def test_una_hora_de_hoy_aun_futura_aparece_aunque_en_utc_ya_paso(app, pro_id, paciente_cli):
    """R-01 de T-05b: Chile 12:00 = 15:00 UTC. La de las 13:00 chilenas debe verse."""
    insertar(app, pro_id, "2026-10-08T13:00:00")
    insertar(app, pro_id, "2026-10-08T14:59:00")
    insertar(app, pro_id, "2026-10-08T11:00:00")
    assert inicios_mostrados(paciente_cli.get("/paciente/horas").text) == [
        "08-10-2026 13:00",
        "08-10-2026 14:59",
    ]


def test_orden_por_inicio_aunque_se_insertaron_desordenadas(app, pro_id, paciente_cli):
    for inicio in ["2026-12-01T10:00:00", "2026-10-09T18:00:00", "2027-01-05T08:00:00",
                   "2026-10-09T09:00:00", "2026-11-30T23:00:00"]:
        insertar(app, pro_id, inicio)
    assert inicios_mostrados(paciente_cli.get("/paciente/horas").text) == [
        "09-10-2026 09:00", "09-10-2026 18:00", "30-11-2026 23:00",
        "01-12-2026 10:00", "05-01-2027 08:00",
    ]


def test_el_orden_con_el_mismo_inicio_es_estable_por_id(app, paciente_cli):
    a = nuevo_profesional(app, "a@example.cl", "Profesional A")
    b = nuevo_profesional(app, "b@example.cl", "Profesional B")
    insertar(app, b, "2026-10-09T10:00:00")
    insertar(app, a, "2026-10-09T10:00:00")
    html = paciente_cli.get("/paciente/horas").text
    assert html.index("Profesional B") < html.index("Profesional A")


def test_formato_duracion_y_nombre_del_profesional(app, pro_id, paciente_cli):
    insertar(app, pro_id, "2027-03-01T08:05:00", 90)
    html = paciente_cli.get("/paciente/horas").text
    assert "01-03-2027 08:05" in html
    assert "90 min" in html
    assert "Dr. Pro" in html
    assert "2027-03-01" not in html


def test_con_varios_profesionales_cada_hora_trae_su_nombre(app, paciente_cli):
    a = nuevo_profesional(app, "a@example.cl", "Profesional A")
    b = nuevo_profesional(app, "b@example.cl", "Profesional B")
    insertar(app, a, "2026-10-09T10:00:00")
    insertar(app, b, "2026-10-09T11:00:00")
    filas = re.findall(r"<tr>\s*<td>([^<]*)</td>\s*<td>[^<]*</td>\s*<td>([^<]*)</td>",
                       paciente_cli.get("/paciente/horas").text)
    assert filas == [("09-10-2026 10:00", "Profesional A"), ("09-10-2026 11:00", "Profesional B")]


def test_el_nombre_del_profesional_se_escapa(app, paciente_cli):
    pid = nuevo_profesional(app, "x@example.cl", "<script>alert(1)</script>")
    insertar(app, pid, "2026-10-09T10:00:00")
    html = paciente_cli.get("/paciente/horas").text
    assert "<script>alert(1)" not in html and "&lt;script&gt;" in html


def test_no_muestra_correos_ni_datos_de_otros_pacientes(app, pro_id, paciente_cli):
    reservada = insertar(app, pro_id, "2026-10-09T11:00:00")
    insertar(app, pro_id, "2026-10-09T12:00:00")
    reservar_directo(app, reservada, "secreta@example.cl")
    html = paciente_cli.get("/paciente/horas").text
    for prohibido in ["@", "pro@example", "secreta", "Otra Paciente", "ana@example"]:
        assert prohibido not in html


def test_una_sola_consulta_a_horas_sin_n_mas_1(app, pro_id, paciente_cli, monkeypatch):
    for dia in range(10, 30):
        insertar(app, pro_id, f"2026-10-{dia}T10:00:00")
    sentencias = []

    def get_db_espiado():
        db = get_db()
        db.set_trace_callback(sentencias.append)
        return db

    monkeypatch.setattr(paciente, "get_db", get_db_espiado)
    assert paciente_cli.get("/paciente/horas").status_code == 200
    de_horas = [s for s in sentencias if "FROM horas" in s]
    assert len(de_horas) == 1 and "JOIN usuarios" in de_horas[0]
    assert not [s for s in sentencias if "FROM usuarios" in s and "JOIN" not in s]


def test_filas_raras_no_dan_500_y_no_se_muestran(app, pro_id, paciente_cli):
    insertar(app, pro_id, "2026-13-45T99:99:99")
    insertar(app, pro_id, "9999-12-31T23:59:59")
    insertar(app, pro_id, "0001-01-01T00:00:00")
    insertar(app, pro_id, "2026-10-09T10:00:00")
    r = paciente_cli.get("/paciente/horas")
    assert r.status_code == 200
    assert inicios_mostrados(r.text) == ["09-10-2026 10:00"]


def test_el_filtro_usa_el_instante_y_no_el_reloj_de_pared(app, pro_id, paciente_cli, monkeypatch):
    """Noche de abril: las 23:xx ocurren dos veces. Es la segunda pasada (fold=1,
    UTC-4, 03:30 UTC); una fila 23:45 de la primera pasada (UTC-3, 02:45 UTC)
    ya pasó aunque el reloj de pared diga 23:45 > 23:30."""
    fijar_reloj(monkeypatch, datetime(2027, 4, 3, 23, 30), fold=1)
    insertar(app, pro_id, "2027-04-03T23:45:00")
    insertar(app, pro_id, "2027-04-04T09:00:00")
    assert inicios_mostrados(paciente_cli.get("/paciente/horas").text) == ["04-04-2027 09:00"]
