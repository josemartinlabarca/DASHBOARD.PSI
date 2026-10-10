"""T-06: el paciente ve las horas libres y futuras (US-7; SPEC §4).

T-08e (D-029): solo se listan las horas que se pueden reservar, es decir, las que
empiezan a MÁS de 24 h de «ahora» (las demás se ocultan; no se muestran marcadas).
"""
import re
from datetime import datetime, timedelta

import pytest

from app import auth, paciente, profesional, tiempo
from app.db import get_db, init_db
from tests.test_login import crear, iniciar, permitir_varios_profesionales

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
    with app.app_context():
        hay_uno = get_db().execute("SELECT 1 FROM usuarios WHERE rol = 'profesional'").fetchone()
    if hay_uno:  # el segundo profesional solo existe quitando el índice de D-023
        permitir_varios_profesionales(app)
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
    insertar(app, pro_id, "2026-10-10T10:00:00")
    r = client.get("/paciente/horas")
    assert r.status_code == 403
    assert "10-10-2026" not in r.text


def test_el_paciente_recibe_200_con_no_store(paciente_cli):
    r = paciente_cli.get("/paciente/horas")
    assert r.status_code == 200
    assert "no-store" in r.headers["Cache-Control"]
    assert "Horas disponibles" in r.text


def test_el_panel_del_paciente_enlaza_a_la_lista(paciente_cli):
    r = paciente_cli.get("/paciente")
    assert re.search(r'<a href="/paciente/horas">Reservar hora</a>', r.text)


def test_cada_hora_trae_su_formulario_de_reservar_con_token(app, pro_id, paciente_cli):
    uno = insertar(app, pro_id, "2026-10-10T10:00:00")
    dos = insertar(app, pro_id, "2026-10-10T12:00:00")
    html = paciente_cli.get("/paciente/horas").text
    assert html.count("<form") == 2
    for hora_id in (uno, dos):
        assert re.search(
            rf'<form method="post" action="/horas/{hora_id}/reservar">\s*'
            r'<input type="hidden" name="csrf_token" value="[0-9a-f]{64}">\s*'
            r'<button type="submit">Reservar</button>',
            html,
        )


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
    insertar(app, pro_id, "2026-10-10T10:00:00")
    reservada = insertar(app, pro_id, "2026-10-10T11:00:00")
    insertar(app, pro_id, "2026-10-10T12:00:00")
    reservar_directo(app, reservada)
    assert inicios_mostrados(paciente_cli.get("/paciente/horas").text) == [
        "10-10-2026 10:00",
        "10-10-2026 12:00",
    ]


def test_no_aparecen_las_pasadas_ni_las_de_menos_de_24_horas(app, pro_id, paciente_cli):
    insertar(app, pro_id, "2026-10-07T10:00:00")
    insertar(app, pro_id, "2026-10-08T09:00:00")
    insertar(app, pro_id, "2026-10-08T13:00:00")  # futura, pero faltan 1 h: no se puede reservar
    insertar(app, pro_id, "2026-10-09T10:00:00")  # 22 h
    insertar(app, pro_id, "2026-10-10T13:00:00")
    assert inicios_mostrados(paciente_cli.get("/paciente/horas").text) == ["10-10-2026 13:00"]


def test_el_borde_de_24_horas_se_oculta_justo_en_24_h_y_aparece_un_segundo_despues(
    app, pro_id, paciente_cli
):
    insertar(app, pro_id, "2026-10-08T11:30:00", 50)  # empezó hace 30 min y sigue en curso
    insertar(app, pro_id, "2026-10-08T12:00:00", 50)  # justo ahora
    insertar(app, pro_id, "2026-10-08T12:00:01", 50)
    insertar(app, pro_id, "2026-10-09T11:59:59", 50)  # 23 h 59 min 59 s
    insertar(app, pro_id, "2026-10-09T12:00:00", 50)  # exactamente 24 h: reservar exige MÁS de 24 h
    insertar(app, pro_id, "2026-10-09T12:00:01", 50)  # 24 h y 1 s
    assert inicios_mostrados(paciente_cli.get("/paciente/horas").text) == ["09-10-2026 12:00"]


def test_una_hora_a_23_h_no_tiene_boton_y_otra_a_25_h_si(app, pro_id, paciente_cli):
    """El botón «Reservar» solo se ofrece a las horas que `reservar_hora` aceptaría."""
    cercana = insertar(app, pro_id, "2026-10-09T11:00:00")  # 23 h
    lejana = insertar(app, pro_id, "2026-10-09T13:00:00")  # 25 h
    html = paciente_cli.get("/paciente/horas").text
    assert f"/horas/{lejana}/reservar" in html
    assert f"/horas/{cercana}/reservar" not in html
    assert html.count("<form") == 1 and html.count(">Reservar</button>") == 1


def test_si_todas_estan_a_menos_de_24_h_se_ve_el_mensaje_de_sin_horas(app, pro_id, paciente_cli):
    insertar(app, pro_id, "2026-10-08T15:00:00")
    insertar(app, pro_id, "2026-10-09T10:00:00")
    html = paciente_cli.get("/paciente/horas").text
    assert "Por ahora no hay horas disponibles" in html and "<form" not in html


def test_el_borde_de_24_horas_usa_la_hora_de_chile_y_no_la_de_utc(app, pro_id, paciente_cli):
    """R-01 de T-05b: Chile 12:00 = 15:00 UTC. Contra el reloj de pared UTC el borde sería
    el 9 a las 15:00 y se ocultarían la de las 13:00 y la de las 14:59."""
    insertar(app, pro_id, "2026-10-09T13:00:00")
    insertar(app, pro_id, "2026-10-09T14:59:00")
    insertar(app, pro_id, "2026-10-09T11:00:00")
    assert inicios_mostrados(paciente_cli.get("/paciente/horas").text) == [
        "09-10-2026 13:00",
        "09-10-2026 14:59",
    ]


def test_orden_por_inicio_aunque_se_insertaron_desordenadas(app, pro_id, paciente_cli):
    for inicio in ["2026-12-01T10:00:00", "2026-10-10T18:00:00", "2026-12-05T08:00:00",
                   "2026-10-10T09:00:00", "2026-11-30T23:00:00"]:
        insertar(app, pro_id, inicio)
    assert inicios_mostrados(paciente_cli.get("/paciente/horas").text) == [
        "10-10-2026 09:00", "10-10-2026 18:00", "30-11-2026 23:00",
        "01-12-2026 10:00", "05-12-2026 08:00",
    ]


def test_el_orden_con_el_mismo_inicio_es_estable_por_id(app, paciente_cli):
    a = nuevo_profesional(app, "a@example.cl", "Profesional A")
    b = nuevo_profesional(app, "b@example.cl", "Profesional B")
    insertar(app, b, "2026-10-10T10:00:00")
    insertar(app, a, "2026-10-10T10:00:00")
    html = paciente_cli.get("/paciente/horas").text
    assert html.index("Profesional B") < html.index("Profesional A")


def test_formato_duracion_y_nombre_del_profesional(app, pro_id, paciente_cli):
    insertar(app, pro_id, "2026-11-03T08:05:00", 90)
    html = paciente_cli.get("/paciente/horas").text
    assert "03-11-2026 08:05" in html
    assert "90 min" in html
    assert "Dr. Pro" in html
    assert "2026-11-03" not in html


def test_con_varios_profesionales_cada_hora_trae_su_nombre(app, paciente_cli):
    a = nuevo_profesional(app, "a@example.cl", "Profesional A")
    b = nuevo_profesional(app, "b@example.cl", "Profesional B")
    insertar(app, a, "2026-10-10T10:00:00")
    insertar(app, b, "2026-10-10T11:00:00")
    filas = re.findall(r"<tr>\s*<td>([^<]*)</td>\s*<td>[^<]*</td>\s*<td>([^<]*)</td>",
                       paciente_cli.get("/paciente/horas").text)
    assert filas == [("10-10-2026 10:00", "Profesional A"), ("10-10-2026 11:00", "Profesional B")]


def test_el_nombre_del_profesional_se_escapa(app, paciente_cli):
    pid = nuevo_profesional(app, "x@example.cl", "<script>alert(1)</script>")
    insertar(app, pid, "2026-10-10T10:00:00")
    html = paciente_cli.get("/paciente/horas").text
    assert "<script>alert(1)" not in html and "&lt;script&gt;" in html


def test_no_muestra_correos_ni_datos_de_otros_pacientes(app, pro_id, paciente_cli):
    reservada = insertar(app, pro_id, "2026-10-10T11:00:00")
    insertar(app, pro_id, "2026-10-10T12:00:00")
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
    insertar(app, pro_id, "2026-10-10T10:00:00")
    r = paciente_cli.get("/paciente/horas")
    assert r.status_code == 200
    assert inicios_mostrados(r.text) == ["10-10-2026 10:00"]


# (ahora local, fold, inicio guardado, ¿se ofrece?) con la regla «más de 24 h» en instantes absolutos.
CASOS_BORDE_LISTA = [
    # noche de abril 2027 (el día del cambio dura 25 h): 24 h reales = 23 h del reloj de pared
    (datetime(2027, 4, 3, 12, 0), 0, "2027-04-04T10:59:59", False),
    (datetime(2027, 4, 3, 12, 0), 0, "2027-04-04T11:00:00", False),  # exactamente 24 h reales
    (datetime(2027, 4, 3, 12, 0), 0, "2027-04-04T11:00:01", True),
    (datetime(2027, 4, 3, 12, 0), 0, "2027-04-04T12:00:00", True),
    # ahora = la SEGUNDA vez de las 23:30 (fold=1): ya pasó la hora repetida
    (datetime(2027, 4, 3, 23, 30), 1, "2027-04-04T23:30:00", False),
    (datetime(2027, 4, 3, 23, 30), 1, "2027-04-04T23:30:01", True),
    # ahora = la PRIMERA vez (fold=0): faltan 25 h reales hasta el 4 a las 23:30
    (datetime(2027, 4, 3, 23, 30), 0, "2027-04-04T22:30:00", False),
    (datetime(2027, 4, 3, 23, 30), 0, "2027-04-04T22:30:01", True),
    # noche de septiembre 2027 (el día del cambio dura 23 h): 24 h reales = 25 h del reloj
    (datetime(2027, 9, 4, 12, 0), 0, "2027-09-05T12:59:59", False),  # el reloj de pared diría 24 h 59 min
    (datetime(2027, 9, 4, 12, 0), 0, "2027-09-05T13:00:00", False),  # exactamente 24 h reales
    (datetime(2027, 9, 4, 12, 0), 0, "2027-09-05T13:00:01", True),
    (datetime(2027, 9, 4, 23, 30), 0, "2027-09-06T00:30:00", False),
    (datetime(2027, 9, 4, 23, 30), 0, "2027-09-06T00:30:01", True),
]


@pytest.mark.parametrize("ahora_local, fold, inicio, ofrecida", CASOS_BORDE_LISTA)
def test_el_borde_de_24_horas_usa_instantes_y_no_el_reloj_de_pared(
    app, pro_id, paciente_cli, monkeypatch, zona_sistema, ahora_local, fold, inicio, ofrecida
):
    """Con el sistema en UTC, Tokio y Chile: el resultado es el mismo."""
    fijar_reloj(monkeypatch, ahora_local, fold=fold)
    hora = insertar(app, pro_id, inicio)
    assert (f"/horas/{hora}/reservar" in paciente_cli.get("/paciente/horas").text) is ofrecida


# --------------------------------- T-14b: ventana de 60 días y tope de 100 (D-044) ----

AVISO_D044 = "Mostramos las próximas 100 horas; hay más disponibles más adelante"


def insertar_muchas(app, pro_id, inicios, duracion=10):
    with app.app_context():
        db = get_db()
        db.executemany(
            "INSERT INTO horas (profesional_id, inicio, duracion_min) VALUES (?, ?, ?)",
            [(pro_id, inicio, duracion) for inicio in inicios],
        )
        db.commit()


def cada_20_minutos(desde, cantidad):
    return [(desde + timedelta(minutes=20 * i)).strftime("%Y-%m-%dT%H:%M:%S") for i in range(cantidad)]


def test_las_constantes_de_d044():
    assert paciente.VENTANA_DIAS == 60 and paciente.TOPE_HORAS == 100


def test_el_aviso_es_el_texto_de_d044():
    assert paciente.MENSAJE_RECORTE == AVISO_D044 + "."


def test_solo_se_ofrecen_las_horas_de_los_proximos_60_dias_borde_inclusivo(app, pro_id, paciente_cli):
    # AHORA = 2026-10-08 12:00 (UTC-3); 60 días = 60 x 86 400 s -> 2026-12-07 12:00 (sin cambio de hora)
    for inicio in ("2026-12-07T11:59:59", "2026-12-07T12:00:00", "2026-12-07T12:00:01", "2026-12-08T10:00:00"):
        insertar(app, pro_id, inicio)
    assert inicios_mostrados(paciente_cli.get("/paciente/horas").text) == [
        "07-12-2026 11:59", "07-12-2026 12:00",
    ]


def test_la_ventana_de_60_dias_se_mide_en_instantes_y_no_en_reloj_de_pared(
    app, pro_id, paciente_cli, monkeypatch, zona_sistema
):
    """Desde el 15-02-2027 12:00 (UTC-3) pasan 60 x 24 h reales hasta el 16-04-2027 11:00 de
    pared (el 3-4 el reloj retrocede una hora): con el reloj de pared el corte sería las 12:00."""
    fijar_reloj(monkeypatch, datetime(2027, 2, 15, 12, 0))
    for inicio in ("2027-04-16T10:59:59", "2027-04-16T11:00:00", "2027-04-16T11:00:01", "2027-04-16T12:00:00"):
        insertar(app, pro_id, inicio)
    assert inicios_mostrados(paciente_cli.get("/paciente/horas").text) == [
        "16-04-2027 10:59", "16-04-2027 11:00",
    ]


def test_las_de_24_horas_o_menos_siguen_ocultas_y_no_cuentan_para_el_tope(app, pro_id, paciente_cli):
    insertar_muchas(app, pro_id, cada_20_minutos(datetime(2026, 10, 8, 12, 30), 70))  # todas en las primeras 24 h: ocultas
    insertar(app, pro_id, "2026-10-12T10:00:00")
    html = paciente_cli.get("/paciente/horas").text
    assert inicios_mostrados(html) == ["12-10-2026 10:00"] and AVISO_D044 not in html


def test_con_mas_de_100_se_muestran_las_100_primeras_y_el_aviso(app, pro_id, paciente_cli):
    inicios = cada_20_minutos(datetime(2026, 10, 10, 8, 0), 150)
    insertar_muchas(app, pro_id, inicios)
    html = paciente_cli.get("/paciente/horas").text
    mostrados = inicios_mostrados(html)
    assert len(mostrados) == 100
    assert mostrados[0] == "10-10-2026 08:00" and mostrados[-1] == "11-10-2026 17:00"  # la 100.ª por inicio
    assert AVISO_D044 + "." in html
    assert html.count("<form") == 100  # un botón de reservar por hora, ninguno de más


@pytest.mark.parametrize("cantidad, aviso", [(99, False), (100, False), (101, True)])
def test_el_aviso_aparece_solo_si_de_verdad_se_recorta(app, pro_id, paciente_cli, cantidad, aviso):
    insertar_muchas(app, pro_id, cada_20_minutos(datetime(2026, 10, 10, 8, 0), cantidad))
    html = paciente_cli.get("/paciente/horas").text
    assert len(inicios_mostrados(html)) == min(cantidad, 100)
    assert (AVISO_D044 in html) is aviso


def test_las_horas_fuera_de_la_ventana_no_cuentan_para_el_tope_ni_disparan_el_aviso(app, pro_id, paciente_cli):
    insertar_muchas(app, pro_id, cada_20_minutos(datetime(2026, 10, 10, 8, 0), 100))
    insertar_muchas(app, pro_id, cada_20_minutos(datetime(2027, 3, 1, 8, 0), 300))
    html = paciente_cli.get("/paciente/horas").text
    assert len(inicios_mostrados(html)) == 100 and AVISO_D044 not in html


def test_las_ya_reservadas_no_cuentan_para_el_tope(app, pro_id, paciente_cli):
    ids = []
    for inicio in cada_20_minutos(datetime(2026, 10, 10, 8, 0), 101):
        ids.append(insertar(app, pro_id, inicio))
    reservar_directo(app, ids[0])
    html = paciente_cli.get("/paciente/horas").text
    assert len(inicios_mostrados(html)) == 100 and AVISO_D044 not in html


def test_no_lee_todas_las_horas_libres_ni_el_historial(app, pro_id, paciente_cli, monkeypatch):
    """T-06 R-01: con miles de filas dentro y fuera de la ventana solo se interpretan ~100."""
    insertar_muchas(app, pro_id, cada_20_minutos(datetime(2026, 10, 10, 8, 0), 3000))   # en la ventana
    insertar_muchas(app, pro_id, cada_20_minutos(datetime(2027, 6, 1, 8, 0), 3000))     # más allá
    insertar_muchas(app, pro_id, cada_20_minutos(datetime(2025, 1, 1, 8, 0), 3000))     # historial viejo
    insertar_muchas(app, pro_id, cada_20_minutos(datetime(2026, 9, 1, 8, 0), 1500))     # últimas semanas
    llamadas = []
    real = tiempo.a_segundos_utc
    monkeypatch.setattr(tiempo, "a_segundos_utc", lambda local: llamadas.append(local) or real(local))
    html = paciente_cli.get("/paciente/horas").text
    assert len(inicios_mostrados(html)) == 100 and AVISO_D044 in html
    assert len(llamadas) <= paciente.TOPE_HORAS + 5, len(llamadas)


def test_las_filas_ilegibles_no_ocupan_lugar_en_el_tope(app, pro_id, paciente_cli):
    """Pasan el CHECK del esquema pero no son fechas: se saltan sin gastar los 100 lugares."""
    ilegibles = [f"2026-11-31T{h:02d}:{m:02d}:00" for h in range(0, 24) for m in range(0, 60, 10)]  # 144
    assert len(ilegibles) > paciente.TOPE_HORAS
    insertar_muchas(app, pro_id, ilegibles)
    insertar(app, pro_id, "2026-11-10T10:00:00")
    insertar(app, pro_id, "2026-12-01T10:00:00")
    html = paciente_cli.get("/paciente/horas").text
    assert inicios_mostrados(html) == ["10-11-2026 10:00", "01-12-2026 10:00"]
    assert AVISO_D044 not in html


def test_el_cursor_no_salta_ni_repite_filas_con_el_mismo_inicio(app, paciente_cli, monkeypatch):
    """Tres profesionales con la misma hora y un tope de 2: salen las dos primeras por id."""
    monkeypatch.setattr(paciente, "TOPE_HORAS", 2)
    pros = [nuevo_profesional(app, f"p{i}@example.cl", f"Profesional {i}") for i in range(3)]
    for p in pros:
        insertar(app, p, "2026-10-10T10:00:00")
    insertar(app, pros[0], "2026-10-10T11:00:00")
    html = paciente_cli.get("/paciente/horas").text
    assert re.findall(r"Profesional \d", html) == ["Profesional 0", "Profesional 1"]
    assert paciente.MENSAJE_RECORTE in html  # se recortó: hay 4 y el tope es 2


def test_listar_devuelve_el_indicador_de_recorte(app, pro_id):
    insertar_muchas(app, pro_id, cada_20_minutos(datetime(2026, 10, 10, 8, 0), 101))
    with app.app_context():
        horas, recortada = paciente.listar_horas_libres_futuras(get_db(), tiempo.ahora_chile())
    assert len(horas) == 100 and recortada is True


def test_el_cursor_no_repite_la_ultima_fila_leida_de_un_lote(app, paciente_cli, monkeypatch):
    """Tres horas válidas y un tope de 3: no hay recorte. Un lote que repitiera su última fila
    (cursor `>=`) contaría una cuarta y avisaría de un recorte que no existe."""
    monkeypatch.setattr(paciente, "TOPE_HORAS", 3)
    pros = [nuevo_profesional(app, f"p{i}@example.cl", f"Profesional {i}") for i in range(3)]
    insertar(app, pros[0], "2026-10-09T11:00:00")   # a 23 h: la ve el SQL (margen) y Python la descarta
    for p in pros:
        insertar(app, p, "2026-10-10T10:00:00")
    html = paciente_cli.get("/paciente/horas").text
    assert re.findall(r"Profesional \d", html) == ["Profesional 0", "Profesional 1", "Profesional 2"]
    assert paciente.MENSAJE_RECORTE not in html


def test_el_cursor_no_se_salta_las_filas_empatadas_en_el_inicio_entre_un_lote_y_otro(app, paciente_cli, monkeypatch):
    monkeypatch.setattr(paciente, "TOPE_HORAS", 3)
    pros = [nuevo_profesional(app, f"p{i}@example.cl", f"Profesional {i}") for i in range(4)]
    insertar(app, pros[0], "2026-10-09T11:00:00")   # descartada, ocupa un lugar del primer lote
    for p in pros:
        insertar(app, p, "2026-10-10T10:00:00")
    html = paciente_cli.get("/paciente/horas").text
    assert re.findall(r"Profesional \d", html) == ["Profesional 0", "Profesional 1", "Profesional 2"]
    assert paciente.MENSAJE_RECORTE in html  # la cuarta (tras el corte del lote) sí se vio


def test_las_filas_mas_alla_de_la_ventana_no_se_leen_aunque_haya_pocas_dentro(app, pro_id, paciente_cli, monkeypatch):
    """Con 10 horas dentro de los 60 días y miles después, no se recorre el futuro lejano."""
    insertar_muchas(app, pro_id, cada_20_minutos(datetime(2026, 10, 10, 8, 0), 10))
    insertar_muchas(app, pro_id, cada_20_minutos(datetime(2027, 3, 1, 8, 0), 3000))
    llamadas = []
    real = tiempo.a_segundos_utc
    monkeypatch.setattr(tiempo, "a_segundos_utc", lambda local: llamadas.append(local) or real(local))
    html = paciente_cli.get("/paciente/horas").text
    assert len(inicios_mostrados(html)) == 10 and AVISO_D044 not in html
    assert len(llamadas) <= 15, len(llamadas)
