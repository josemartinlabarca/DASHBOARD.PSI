"""T-11: dashboard del paciente (US-10): próxima sesión, historial y notificaciones.

Reloj fijo: jueves 2026-10-08 12:00 en Chile (-03:00). Todo lo que se mira es el HTML real de
`GET /paciente`. Las filas se insertan por SQL cuando importa controlar `hora_id`, `id` o `leida`.
"""
import re
from datetime import datetime

import pytest

from app import notificaciones
from app.db import get_db, init_db
from tests.test_cancelar import cancelar, reservada
from tests.test_horas_libres import fijar_reloj, insertar, nuevo_profesional
from tests.test_login import crear, iniciar
from tests.test_reservar import nuevo_paciente, reservar, uid

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


def notificar(app, email, mensaje, tipo="confirmacion", hora_id=None, leida=0,
              creada_en="2026-10-08T09:00:00-03:00"):
    with app.app_context():
        db = get_db()
        cursor = db.execute(
            "INSERT INTO notificaciones (usuario_id, tipo, mensaje, hora_id, leida, creada_en)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (uid(app, email), tipo, mensaje, hora_id, leida, creada_en),
        )
        db.commit()
        return cursor.lastrowid


def seccion(html, titulo, siguiente):
    m = re.search(rf"<h2[^>]*>\s*{titulo}.*?(?=<h2|</main>)" if siguiente is None else
                  rf"<h2[^>]*>\s*{titulo}.*?(?=<h2)", html, re.S)
    assert m, (titulo, html)
    return m.group(0)


def texto(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def mensajes_listados(html):
    """Textos `<li>` de la sección de notificaciones, en el orden mostrado."""
    return [texto(li) for li in re.findall(r"<li[^>]*>(.*?)</li>", seccion(html, "(?:<span[^>]*>.*?</span>)?\\s*Notificaciones", None), re.S)]


def historial(html):
    """Filas del historial. Falla si la sección no existe; `[]` solo si existe sin tabla (R-04)."""
    bloque = re.search(r"<h2>Historial</h2>(.*?)(?=<h2|</main>)", html, re.S)
    assert bloque, "no existe la sección «Historial»"
    cuerpo = re.search(r"<tbody>(.*?)</tbody>", bloque.group(1), re.S)
    return [texto(f)[:16] for f in re.findall(r"<tr>(.*?)</tr>", cuerpo.group(1), re.S)] if cuerpo else []


def proxima(html):
    return texto(seccion(html, "Próxima sesión", 1))


# ------------------------------------------------------------ por rol ----


def test_anonimo_va_al_login(client):
    r = client.get("/paciente")
    assert r.status_code == 302 and r.headers["Location"].startswith("/login")


def test_el_profesional_no_accede(app, pro_id):
    c = app.test_client()
    iniciar(c, "pro@example.cl")
    r = c.get("/paciente")
    assert r.status_code == 403
    assert "Notificaciones" not in r.text and "Historial" not in r.text


def test_el_paciente_ve_su_panel_sin_cache(app, ana):
    r = ana.get("/paciente")
    assert r.status_code == 200
    assert r.headers["Cache-Control"] == "no-store"  # D-024 intacto
    assert "Hola, Ana Pérez" in r.text and "<script" not in r.text  # sin JavaScript
    assert "No tienes una sesión próxima." in r.text
    assert "Todavía no tienes sesiones pasadas." in r.text
    assert "Aún no tienes notificaciones." in r.text
    assert "No tienes notificaciones sin leer." in r.text


def test_el_html_es_accesible(app, pro_id, ana):
    reservada(app, pro_id, "2026-10-12T10:00:00")
    reservada(app, pro_id, "2026-10-01T10:00:00")
    notificar(app, ANA, "Hola")
    html = ana.get("/paciente").text
    assert html.count("<h1>") == 1 and "<h2" in html
    assert 'aria-label="Campana de notificaciones: 1 sin leer"' in html
    assert html.count("<caption>") == 2
    assert html.count('<th scope="col">') >= 7 and html.count('<th scope="row">') == 2
    assert "<th>" not in html


# ------------------------------------------------------- próxima / historial ----


def test_proxima_es_la_de_menor_inicio_y_no_mezcla_otras_personas(app, pro_id, ana, beto):
    reservada(app, pro_id, "2026-10-15T10:00:00")
    reservada(app, pro_id, "2026-10-13T09:00:00", duracion=45)
    reservada(app, pro_id, "2026-10-10T09:00:00", email=BETO)  # de otra persona
    insertar(app, pro_id, "2026-10-11T09:00:00")  # libre
    html = ana.get("/paciente").text
    p = proxima(html)
    assert "13-10-2026 09:00" in p and "45 min" in p and "Dr. Pro" in p and "(hora de Chile)" in p
    assert "15-10-2026" not in p and "10-10-2026" not in p
    assert "10-10-2026 09:00" in proxima(beto.get("/paciente").text)


def test_historial_pasadas_mas_reciente_primero_y_solo_propias(app, pro_id, ana, beto):
    reservada(app, pro_id, "2026-09-01T10:00:00")
    reservada(app, pro_id, "2026-10-07T10:00:00")
    reservada(app, pro_id, "2026-09-20T10:00:00")
    reservada(app, pro_id, "2026-09-25T10:00:00", email=BETO)
    insertar(app, pro_id, "2026-09-10T10:00:00")  # libre y pasada: no es una sesión
    reservada(app, pro_id, "2026-10-20T10:00:00")  # futura: no va al historial
    assert historial(ana.get("/paciente").text) == [
        "07-10-2026 10:00", "20-09-2026 10:00", "01-09-2026 10:00"]
    assert historial(beto.get("/paciente").text) == ["25-09-2026 10:00"]


def test_una_reserva_cancelada_no_es_sesion_ni_historial(app, pro_id, ana):
    hora = reservada(app, pro_id, "2026-10-14T10:00:00")
    cancelar(ana, hora)
    html = ana.get("/paciente").text
    assert "No tienes una sesión próxima." in html and historial(html) == []


# (inicio, duración, ¿próxima?, ¿en curso?): borde de «terminó» con instantes exactos
@pytest.mark.parametrize("inicio,duracion,es_proxima,en_curso", [
    ("2026-10-08T11:10:00", 50, False, False),  # termina justo ahora: ya es pasada
    ("2026-10-08T11:10:01", 50, True, True),    # le falta 1 s: sigue en curso
    ("2026-10-08T12:00:00", 50, True, True),    # empieza justo ahora: en curso
    ("2026-10-08T12:00:01", 50, True, False),   # empieza en 1 s: aún no
    ("2026-10-08T11:00:00", 50, False, False),  # terminó hace 10 min
])
def test_limite_entre_proxima_en_curso_y_pasada(app, pro_id, ana, inicio, duracion, es_proxima, en_curso):
    reservada(app, pro_id, inicio, duracion=duracion)
    html = ana.get("/paciente").text
    assert ("No tienes una sesión próxima." not in html) is es_proxima
    assert ("Tu sesión está en curso." in html) is en_curso
    assert (historial(html) == []) is es_proxima


def test_la_sesion_en_curso_es_la_proxima_y_la_siguiente_no(app, pro_id, ana):
    reservada(app, pro_id, "2026-10-08T11:30:00")  # termina 12:20
    reservada(app, pro_id, "2026-10-09T10:00:00")
    html = ana.get("/paciente").text
    assert "08-10-2026 11:30" in proxima(html) and "en curso" in proxima(html)
    assert historial(html) == []


def test_en_la_noche_del_cambio_de_horario_se_decide_con_instantes(app, pro_id, ana, monkeypatch):
    """23:30 del 5-sep con 120 min: el reloj salta de 24:00 a 01:00, así que termina a las 02:30
    de pared. A las 02:00 sigue en curso (con aritmética de pared ya habría terminado)."""
    reservada(app, pro_id, "2026-09-05T23:30:00", duracion=120)
    fijar_reloj(monkeypatch, datetime(2026, 9, 6, 2, 0))
    html = ana.get("/paciente").text
    assert "Tu sesión está en curso." in html and historial(html) == []
    fijar_reloj(monkeypatch, datetime(2026, 9, 6, 2, 30))
    html = ana.get("/paciente").text
    assert "No tienes una sesión próxima." in html and historial(html) == ["05-09-2026 23:30"]


def test_filas_ilegibles_se_omiten_sin_romper(app, pro_id, ana):
    """R-03: fecha o duración ilegibles no entran a la próxima, al historial ni a Mis reservas."""
    mala_fecha = reservada(app, pro_id, "2026-10-12T10:00:00")
    mala_duracion = reservada(app, pro_id, "2026-10-13T10:00:00")
    with app.app_context():
        get_db().execute("UPDATE horas SET inicio='2026-13-45T99:99:99' WHERE id=?", (mala_fecha,))
        get_db().execute("UPDATE horas SET duracion_min='no-numero-xyz!' WHERE id=?", (mala_duracion,))
        get_db().commit()
    r = ana.get("/paciente")
    assert r.status_code == 200
    assert historial(r.text) == []
    assert "No tienes una sesión próxima." in r.text
    assert "No tienes reservas próximas." in r.text
    assert "2026-13-45" not in r.text and "no-numero-xyz!" not in r.text
    sana = reservada(app, pro_id, "2026-10-14T10:00:00")  # una fila sana sí aparece
    reservada(app, pro_id, "2026-10-01T10:00:00")
    html = ana.get("/paciente").text
    assert "14-10-2026 10:00" in proxima(html) and f'id="reserva-{sana}"' in html
    assert historial(html) == ["01-10-2026 10:00"]
    assert "2026-13-45" not in html and "no-numero-xyz!" not in html


def test_mis_reservas_y_horas_libres_siguen_en_el_panel(app, pro_id, ana):
    hora = reservada(app, pro_id, "2026-10-12T10:00:00")
    html = ana.get("/paciente").text
    assert f'action="/horas/{hora}/cancelar"' in html and 'href="/paciente/horas"' in html


# -------------------------------------------------------- notificaciones ----


def test_flujo_real_confirmacion_cancelacion_y_recordatorio(app, pro_id, ana):
    lejana = insertar(app, pro_id, "2026-10-14T10:00:00")
    reservada(app, pro_id, "2026-10-09T11:00:00")  # a 23 h: recordatorio pendiente
    assert reservar(ana, lejana).status_code == 302
    cancelar(ana, lejana)
    with app.app_context():
        assert notificaciones.enviar_recordatorios(get_db()) == 1
    lista = mensajes_listados(ana.get("/paciente").text)
    assert len(lista) == 3
    assert lista[0].startswith("Recordatorio") and "09-10-2026 a las 11:00" in lista[0]
    assert lista[1].startswith("Cancelación") and "Cancelaste tu hora" in lista[1]
    assert lista[2].startswith("Confirmación") and "Confirmamos tu hora" in lista[2]
    assert "14-10-2026 a las 10:00" in lista[2]
    # la confirmación fue creada a las 12:00 de Chile
    assert "08-10-2026 12:00" in lista[2]


def test_orden_por_id_descendente_aunque_creada_en_diga_otra_cosa(app, ana):
    notificar(app, ANA, "primera", creada_en="2026-10-08T09:00:00-03:00")
    notificar(app, ANA, "segunda", creada_en="2026-10-08T05:00:00-04:00")  # texto menor, instante igual al de 06:00-03
    notificar(app, ANA, "tercera", creada_en="2025-01-01T00:00:00-03:00")  # texto más antiguo
    lista = mensajes_listados(ana.get("/paciente").text)
    assert [m.split(") ", 1)[1] for m in lista] == ["tercera", "segunda", "primera"]


def test_solo_las_del_usuario_en_sesion(app, pro_id, ana, beto):
    notificar(app, ANA, "para Ana")
    notificar(app, BETO, "para Beto secreto")
    notificar(app, "pro@example.cl", "para el profesional secreto")
    html = ana.get("/paciente").text
    assert "para Ana" in html and "secreto" not in html
    assert "para Ana" not in beto.get("/paciente").text


def test_el_contador_cuenta_solo_no_leidas_propias_y_marca_el_estado(app, pro_id, ana, beto):
    notificar(app, ANA, "nueva uno")
    notificar(app, ANA, "nueva dos")
    notificar(app, ANA, "vieja", leida=1)
    notificar(app, BETO, "de Beto")
    html = ana.get("/paciente").text
    assert 'aria-label="Campana de notificaciones: 2 sin leer"' in html
    assert "Tienes 2 notificaciones sin leer." in html
    lista = mensajes_listados(html)
    assert [m.split(" (")[1].split(",")[0] for m in lista] == ["leída", "nueva", "nueva"]
    assert html.count('class="no-leida"') == 2 and html.count('class="leida"') == 1
    assert "Tienes 1 notificación sin leer." in beto.get("/paciente").text


def test_hora_eliminada_deja_la_notificacion_con_su_mensaje_y_sin_enlace(app, pro_id, ana):
    hora = insertar(app, pro_id, "2026-10-14T10:00:00")
    reservar(ana, hora)
    cancelar(ana, hora)
    with app.app_context():
        get_db().execute("DELETE FROM horas WHERE id = ?", (hora,))
        get_db().commit()
        assert get_db().execute(
            "SELECT COUNT(*) FROM notificaciones WHERE usuario_id=? AND hora_id IS NULL", (uid(app, ANA),)
        ).fetchone()[0] == 2
    html = ana.get("/paciente").text
    lista = mensajes_listados(html)
    assert len(lista) == 2 and "14-10-2026 a las 10:00" in lista[0] + lista[1]
    assert "Ver la reserva" not in html and "#reserva-None" not in html and "reserva-None" not in html


def test_enlace_solo_si_la_reserva_sigue_siendo_de_la_paciente(app, pro_id, ana, beto):
    suya = reservada(app, pro_id, "2026-10-14T10:00:00")
    ajena = reservada(app, pro_id, "2026-10-15T10:00:00", email=BETO)
    libre = insertar(app, pro_id, "2026-10-16T10:00:00")
    notificar(app, ANA, "con enlace", hora_id=suya)
    notificar(app, ANA, "apunta a hora de otra", hora_id=ajena)
    notificar(app, ANA, "apunta a hora libre", hora_id=libre)
    html = ana.get("/paciente").text
    assert html.count("Ver la reserva") == 1
    assert f'href="#reserva-{suya}"' in html and f'id="reserva-{suya}"' in html
    assert f"#reserva-{ajena}" not in html and f"#reserva-{libre}" not in html
    # el mensaje mostrado es el guardado, no algo derivado de la hora a la que apunta
    assert "15-10-2026" not in html


def test_los_textos_hostiles_se_muestran_como_texto(app, pro_id, ana):
    hostil = "<script>alert(1)</script>"
    notificar(app, ANA, f'Hola {hostil} <img src=x onerror=alert(2)>')
    with app.app_context():
        get_db().execute("UPDATE usuarios SET nombre=? WHERE rol='profesional'", (hostil,))
        get_db().commit()
    reservada(app, pro_id, "2026-10-14T10:00:00")
    reservada(app, pro_id, "2026-10-01T10:00:00")
    hora = insertar(app, pro_id, "2026-10-20T10:00:00")
    reservar(ana, hora)  # la confirmación real lleva el nombre hostil del profesional
    html = ana.get("/paciente").text
    assert "<script>" not in html and "<img" not in html
    assert html.count("&lt;script&gt;alert(1)&lt;/script&gt;") >= 4
    assert "&lt;img src=x onerror=alert(2)&gt;" in html


def test_fecha_de_creacion_ilegible_no_rompe_y_se_omite(app, ana):
    notificar(app, ANA, "sin fecha buena", creada_en="ayer")
    notificar(app, ANA, "sin zona", creada_en="2026-10-08T09:00:00")
    notificar(app, ANA, "en utc", creada_en="2026-10-08T15:00:00+00:00")
    r = ana.get("/paciente")
    assert r.status_code == 200
    lista = mensajes_listados(r.text)
    assert lista[0] == "Confirmación (nueva, 08-10-2026 12:00) en utc"
    assert lista[1] == "Confirmación (nueva) sin zona"
    assert lista[2] == "Confirmación (nueva) sin fecha buena"
    assert "ayer" not in r.text


def test_mostrar_instante_convierte_a_chile():
    from app import tiempo
    assert tiempo.mostrar_instante("2026-10-08T15:00:00+00:00") == "08-10-2026 12:00"
    assert tiempo.mostrar_instante("2026-07-01T15:00:00+00:00") == "01-07-2026 11:00"  # invierno: -04:00
    assert tiempo.mostrar_instante("2026-10-08T12:00:00-03:00") == "08-10-2026 12:00"
    assert tiempo.mostrar_instante("2026-10-08T12:00:00") is None
    assert tiempo.mostrar_instante("x") is None and tiempo.mostrar_instante(None) is None


# ------------------------------------------- marcar como leídas (D-035) ----

RUTA_LEIDAS = "/notificaciones/leidas"


def token_de(client, panel="/paciente"):
    client.get(panel)
    with client.session_transaction() as s:
        return s["csrf_token"]


def marcar(client, panel="/paciente", **extra):
    return client.post(RUTA_LEIDAS, data={"csrf_token": token_de(client, panel), **extra})


def estados(app, email):
    with app.app_context():
        return [bool(f[0]) for f in get_db().execute(
            "SELECT leida FROM notificaciones WHERE usuario_id=? ORDER BY id", (uid(app, email),))]


def formularios_de_leidas(html):
    return re.findall(r'<form[^>]*action="/notificaciones/leidas"[^>]*>.*?</form>', html, re.S)


def test_el_boton_solo_aparece_si_hay_no_leidas(app, ana):
    assert formularios_de_leidas(ana.get("/paciente").text) == []
    notificar(app, ANA, "vieja", leida=1)
    html = ana.get("/paciente").text
    assert formularios_de_leidas(html) == [] and "Marcar todas" not in html
    notificar(app, ANA, "nueva")
    html = ana.get("/paciente").text
    formularios = formularios_de_leidas(html)
    assert len(formularios) == 1 and 'method="post"' in formularios[0]
    assert re.search(r'name="csrf_token" value="[0-9a-f]+"', formularios[0])
    assert html.count("Marcar todas como leídas") == 1
    assert "<script" not in html and "<input" in formularios[0]
    assert re.findall(r'<(?:input|select|textarea)[^>]*name="(\w+)"', formularios[0]) == ["csrf_token"]


def test_marcar_todas_baja_el_contador_a_cero_y_no_toca_a_los_demas(app, pro_id, ana, beto):
    notificar(app, ANA, "uno")
    notificar(app, ANA, "dos")
    notificar(app, ANA, "vieja", leida=1)
    notificar(app, BETO, "de Beto")
    notificar(app, "pro@example.cl", "del profesional")
    r = marcar(ana)
    assert r.status_code == 302 and r.headers["Location"] == "/paciente"
    html = ana.get(r.headers["Location"]).text
    assert "Marcaste 2 notificaciones como leídas." in html
    assert 'aria-label="Campana de notificaciones: 0 sin leer"' in html
    assert "No tienes notificaciones sin leer." in html and formularios_de_leidas(html) == []
    assert html.count('class="leida"') == 3 and 'class="no-leida"' not in html
    assert estados(app, ANA) == [True, True, True]
    assert estados(app, BETO) == [False] and estados(app, "pro@example.cl") == [False]
    assert 'aria-label="Campana de notificaciones: 1 sin leer"' in beto.get("/paciente").text


def test_marcar_es_idempotente(app, ana, beto):
    notificar(app, ANA, "uno")
    notificar(app, BETO, "de Beto")
    marcar(ana)
    r = marcar(ana)
    assert r.status_code == 302 and r.headers["Location"] == "/paciente"
    assert "No tenías notificaciones sin leer." in ana.get("/paciente").text
    assert estados(app, ANA) == [True] and estados(app, BETO) == [False]
    notificar(app, ANA, "otra nueva")  # lo nuevo sí queda sin leer
    assert estados(app, ANA) == [True, False]


def test_marcar_una_sola_pasa_el_mensaje_en_singular(app, ana):
    notificar(app, ANA, "uno")
    marcar(ana)
    assert "Marcaste 1 notificación como leída." in ana.get("/paciente").text


def test_sin_token_csrf_no_marca_nada(app, ana):
    notificar(app, ANA, "uno")
    ana.get("/paciente")
    assert ana.post(RUTA_LEIDAS).status_code == 400
    assert ana.post(RUTA_LEIDAS, data={"csrf_token": "0" * 64}).status_code == 400
    assert ana.post(RUTA_LEIDAS, data={"csrf_token": ""}).status_code == 400
    assert estados(app, ANA) == [False]


def test_ignora_los_ids_que_llegan_en_el_formulario(app, ana, beto):
    notificar(app, ANA, "mía")
    ajena = notificar(app, BETO, "de Beto")
    marcar(ana, id=ajena, ids=ajena, notificacion_id=ajena, usuario_id=uid(app, BETO),
           usuario=uid(app, BETO), leida=0)
    assert estados(app, ANA) == [True] and estados(app, BETO) == [False]
    r = ana.post(RUTA_LEIDAS + f"?id={ajena}&usuario_id={uid(app, BETO)}",
                 data={"csrf_token": token_de(ana)})
    assert r.status_code == 302 and estados(app, BETO) == [False]


def test_la_ruta_no_acepta_get(app, ana):
    notificar(app, ANA, "uno")
    assert ana.get(RUTA_LEIDAS).status_code == 405
    assert estados(app, ANA) == [False]


def test_el_profesional_no_puede_usar_la_ruta(app, pro_id, ana):
    notificar(app, "pro@example.cl", "para el profesional")
    notificar(app, ANA, "para Ana")
    c = app.test_client()
    iniciar(c, "pro@example.cl")
    r = marcar(c, panel="/profesional")
    assert r.status_code == 403
    assert estados(app, "pro@example.cl") == [False] and estados(app, ANA) == [False]


def test_el_anonimo_no_puede_usar_la_ruta(app, ana):
    notificar(app, ANA, "para Ana")
    c = app.test_client()
    # con token válido de su propia sesión anónima: lo que frena es el rol, no el CSRF
    r = c.post(RUTA_LEIDAS, data={"csrf_token": token_de(c, "/login")})
    assert r.status_code == 302 and r.headers["Location"].startswith("/login")
    assert c.post(RUTA_LEIDAS).status_code == 400  # y sin token ni llega
    assert estados(app, ANA) == [False]


def test_con_25_se_ven_20_pero_el_contador_cuenta_todas(app, ana, beto):
    for i in range(1, 26):
        notificar(app, ANA, f"aviso {i:02d}")
    notificar(app, BETO, "de Beto")
    html = ana.get("/paciente").text
    lista = mensajes_listados(html)
    assert len(lista) == 20
    assert lista[0].endswith("aviso 25") and lista[-1].endswith("aviso 06")  # las 20 más nuevas, id DESC
    assert "aviso 05" not in html and "de Beto" not in html
    assert 'aria-label="Campana de notificaciones: 25 sin leer"' in html
    assert "Tienes 25 notificaciones sin leer." in html
    assert "Se muestran tus 20 notificaciones más recientes." in html
    marcar(ana)
    html = ana.get("/paciente").text
    assert 'aria-label="Campana de notificaciones: 0 sin leer"' in html
    assert estados(app, ANA) == [True] * 25  # también las 5 que no se veían
    assert estados(app, BETO) == [False]


def test_el_contador_incluye_no_leidas_fuera_de_las_20_visibles(app, ana):
    notificar(app, ANA, "vieja sin leer")  # queda fuera del tope
    for i in range(20):
        notificar(app, ANA, f"leída {i}", leida=1)
    html = ana.get("/paciente").text
    assert len(mensajes_listados(html)) == 20 and "vieja sin leer" not in html
    assert 'aria-label="Campana de notificaciones: 1 sin leer"' in html
    assert len(formularios_de_leidas(html)) == 1  # el botón sigue, aunque ninguna visible sea nueva


@pytest.mark.parametrize("cantidad,aviso", [(19, False), (20, False), (21, True)])
def test_aviso_de_tope_solo_si_hay_mas_que_el_tope(app, ana, cantidad, aviso):
    """R-03 de T-11b: con exactamente 20 no hay más, así que no se avisa."""
    for i in range(cantidad):
        notificar(app, ANA, f"aviso {i:02d}")
    html = ana.get("/paciente").text
    assert len(mensajes_listados(html)) == min(cantidad, 20)
    assert ("Se muestran tus 20 notificaciones más recientes." in html) is aviso
    assert f"Campana de notificaciones: {cantidad} sin leer" in html


def test_el_tope_del_panel_del_paciente_sale_de_la_constante(app, ana, monkeypatch):
    monkeypatch.setattr(notificaciones, "TOPE_PANEL", 3)
    for i in range(4):
        notificar(app, ANA, f"aviso {i}")
    html = ana.get("/paciente").text
    assert len(mensajes_listados(html)) == 3 and "Se muestran tus 3 notificaciones más recientes." in html


def test_marcar_leidas_devuelve_cuantas_cambio_y_solo_las_del_usuario(app, ana, beto):
    notificar(app, ANA, "uno")
    notificar(app, ANA, "dos", leida=1)
    notificar(app, BETO, "de Beto")
    with app.app_context():
        db = get_db()
        assert notificaciones.marcar_leidas(db, uid(app, ANA)) == 1
        assert notificaciones.marcar_leidas(db, uid(app, ANA)) == 0
        assert notificaciones.marcar_leidas(db, 987654) == 0
    assert estados(app, BETO) == [False]


# ------------------------------------------------ orden de secciones (R-06) ----


def test_orden_de_las_secciones_y_enlace_para_reservar(app, pro_id, ana):
    reservada(app, pro_id, "2026-10-14T10:00:00")  # ya hay próxima sesión: el enlace sigue visible
    reservada(app, pro_id, "2026-10-01T10:00:00")
    notificar(app, ANA, "hola")
    html = ana.get("/paciente").text
    posiciones = [html.index(t) for t in (
        "Próxima sesión</h2>", "Reservar hora</a>", "<h2>Mis reservas</h2>",
        "<h2>Historial</h2>", "Notificaciones\n", "Marcar todas como leídas")]
    assert posiciones == sorted(posiciones)
    assert html.count('href="/paciente/horas"') == 1
    assert html.count("<th scope=") >= 7 and html.count("<caption>") == 2


def test_el_enlace_para_reservar_se_ve_sin_sesion_proxima(ana):
    html = ana.get("/paciente").text
    assert '<a href="/paciente/horas">Reservar hora</a>' in html
