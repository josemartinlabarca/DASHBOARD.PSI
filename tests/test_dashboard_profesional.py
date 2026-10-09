"""T-12: dashboard del profesional (US-6): agenda, horas libres y notificaciones.

Reloj fijo: jueves 2026-10-08 12:00 en Chile (-03:00), el mismo de los paneles del paciente.
Todo lo que se mira es el HTML real de `GET /profesional`. Las filas se insertan por SQL cuando
importa controlar `hora_id`, `id`, `leida` o la fecha.
"""
import re
from datetime import datetime

import pytest

from app import notificaciones
from app.db import get_db, init_db
from tests.test_cancelar import cancelar, reservada
from tests.test_dashboard_paciente import (
    ANA, BETO, estados, formularios_de_leidas, mensajes_listados, notificar, texto,
)
from tests.test_horas_libres import fijar_reloj, insertar, nuevo_profesional
from tests.test_login import iniciar
from tests.test_reservar import nuevo_paciente, reservar, uid

PRO = "pro@example.cl"
RUTA_LEIDAS = "/profesional/notificaciones/leidas"


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
def pro(app, pro_id):
    c = app.test_client()
    iniciar(c, PRO)
    return c


@pytest.fixture
def ana(app):
    return nuevo_paciente(app)


@pytest.fixture
def beto(app):
    return nuevo_paciente(app, BETO, "Beto Soto")


def panel(pro):
    r = pro.get("/profesional")
    assert r.status_code == 200
    return r.text


def seccion(html, titulo):
    """Texto de la sección cuyo `<h2>` empieza con `titulo` (hasta el siguiente `<h2>`)."""
    m = re.search(rf"<h2[^>]*>\s*{titulo}.*?(?=<h2|</main>)", html, re.S)
    assert m, f"no existe la sección «{titulo}»"
    return m.group(0)


def filas(html, titulo):
    """Primera celda de cada fila del `<tbody>` de una sección (`[]` si no hay tabla)."""
    cuerpo = re.search(r"<tbody>(.*?)</tbody>", seccion(html, titulo), re.S)
    return [texto(f) for f in re.findall(r"<tr[^>]*>(.*?)</tr>", cuerpo.group(1), re.S)] if cuerpo else []


def agenda(html):
    return filas(html, "Próximas reservas")


def libres(html):
    return filas(html, "Horas libres")


def pasadas(html):
    return filas(html, "Sesiones pasadas")


# ------------------------------------------------------------ por rol ----


def test_anonimo_va_al_login(client):
    r = client.get("/profesional")
    assert r.status_code == 302 and r.headers["Location"].startswith("/login")


def test_el_paciente_no_accede_ni_ve_nada(app, pro_id, ana):
    reservada(app, pro_id, "2026-10-14T10:00:00")
    notificar(app, PRO, "secreto del profesional")
    r = ana.get("/profesional")
    assert r.status_code == 403
    for rotulo in ("Próximas reservas", "Horas libres", "Notificaciones", "Ana Pérez", "secreto"):
        assert rotulo not in r.text


def test_el_profesional_ve_su_panel_sin_cache_ni_javascript(pro):
    r = pro.get("/profesional")
    assert r.status_code == 200
    assert r.headers["Cache-Control"] == "no-store"  # D-024
    html = r.text
    assert "Hola, Dr. Pro" in html and "<script" not in html
    assert "No tienes sesiones reservadas próximas." in html
    assert "Aún no tienes horas publicadas." in html
    assert "Todavía no tienes sesiones pasadas." in html
    assert "Aún no tienes notificaciones." in html and "No tienes notificaciones sin leer." in html
    assert 'href="/profesional/horas/nueva"' in html  # agregar horas sigue ahí


def test_orden_de_las_secciones(app, pro_id, pro, ana):
    html = panel(pro)
    orden = [html.index(t) for t in (
        "Próximas reservas", "Horas libres", "Sesiones pasadas", "Notificaciones")]
    assert orden == sorted(orden)


def test_el_html_es_accesible(app, pro_id, pro, ana):
    reservada(app, pro_id, "2026-10-12T10:00:00")
    reservada(app, pro_id, "2026-10-01T10:00:00")
    insertar(app, pro_id, "2026-10-20T10:00:00")
    notificar(app, PRO, "Hola")
    html = panel(pro)
    assert html.count("<h1>") == 1 and html.count("<h2") == 4
    assert 'aria-label="Campana de notificaciones: 1 sin leer"' in html
    assert html.count("<caption>") == 3
    assert html.count('<th scope="col">') == 11 and html.count('<th scope="row">') == 3
    assert "<th>" not in html


# ------------------------------------------------------------- agenda ----


def test_agenda_con_paciente_duracion_y_orden(app, pro_id, pro, ana, beto):
    reservada(app, pro_id, "2026-10-15T10:00:00")
    reservada(app, pro_id, "2026-10-13T09:00:00", email=BETO, duracion=45)
    insertar(app, pro_id, "2026-10-14T09:00:00")  # libre: no es una reserva
    html = panel(pro)
    assert agenda(html) == [
        "13-10-2026 09:00 45 min Beto Soto Reservada",
        "15-10-2026 10:00 50 min Ana Pérez Reservada",
    ]
    assert "(hora de Chile)" in seccion(html, "Próximas reservas")


def test_no_se_muestran_correos_ni_datos_de_otros(app, pro_id, pro, ana):
    reservada(app, pro_id, "2026-10-15T10:00:00")
    reservada(app, pro_id, "2026-10-01T10:00:00")
    notificar(app, PRO, "hola")
    html = panel(pro)
    assert ANA not in html and "@" not in html and "password" not in html.lower()


def test_la_agenda_filtra_por_profesional(app, pro_id, pro, ana, beto):
    otro = nuevo_profesional(app, "pro2@example.cl", "Dra. Otra")
    reservada(app, pro_id, "2026-10-14T10:00:00")
    reservada(app, otro, "2026-10-13T10:00:00", email=BETO)  # reserva con la otra profesional
    reservada(app, otro, "2026-10-02T10:00:00", email=BETO)
    insertar(app, otro, "2026-10-30T10:00:00")  # libre de la otra
    html = panel(pro)
    assert len(agenda(html)) == 1 and "Ana Pérez" in agenda(html)[0]
    assert "Beto" not in html and "13-10-2026" not in html and "02-10-2026" not in html
    assert "30-10-2026" not in html


# (inicio, duración, ¿próxima?, ¿en curso?): borde de «terminó» con instantes exactos (D-034)
@pytest.mark.parametrize("inicio,duracion,es_proxima,en_curso", [
    ("2026-10-08T11:10:00", 50, False, False),  # termina justo ahora: ya es pasada
    ("2026-10-08T11:10:01", 50, True, True),    # le falta 1 s: sigue en curso
    ("2026-10-08T12:00:00", 50, True, True),    # empieza justo ahora: en curso
    ("2026-10-08T12:00:01", 50, True, False),   # empieza en 1 s: aún no
    ("2026-10-08T11:00:00", 50, False, False),  # terminó hace 10 min
])
def test_limite_entre_proxima_en_curso_y_pasada(app, pro_id, pro, ana, inicio, duracion, es_proxima, en_curso):
    reservada(app, pro_id, inicio, duracion=duracion)
    html = panel(pro)
    assert (len(agenda(html)) == 1) is es_proxima
    assert (len(pasadas(html)) == 0) is es_proxima
    assert ("<strong>en curso</strong>" in seccion(html, "Próximas reservas")) is en_curso


def test_sesiones_pasadas_mas_reciente_primero_y_solo_terminadas(app, pro_id, pro, ana, beto):
    reservada(app, pro_id, "2026-09-01T10:00:00")
    reservada(app, pro_id, "2026-10-07T10:00:00", email=BETO)
    reservada(app, pro_id, "2026-09-20T10:00:00")
    insertar(app, pro_id, "2026-09-10T10:00:00")  # libre y pasada: no es una sesión
    reservada(app, pro_id, "2026-10-20T10:00:00")  # futura: no va al historial
    assert pasadas(panel(pro)) == [
        "07-10-2026 10:00 50 min Beto Soto", "20-09-2026 10:00 50 min Ana Pérez",
        "01-09-2026 10:00 50 min Ana Pérez"]


def test_una_reserva_cancelada_no_esta_en_la_agenda(app, pro_id, pro, ana):
    hora = reservada(app, pro_id, "2026-10-14T10:00:00")
    cancelar(ana, hora)
    html = panel(pro)
    assert agenda(html) == [] and pasadas(html) == []
    assert len(libres(html)) == 1  # la hora volvió a estar libre


def test_en_la_noche_del_cambio_de_horario_se_decide_con_instantes(app, pro_id, pro, ana, monkeypatch):
    """23:30 del 5-sep con 120 min termina a las 02:30 de pared (el reloj salta de 24:00 a 01:00)."""
    reservada(app, pro_id, "2026-09-05T23:30:00", duracion=120)
    fijar_reloj(monkeypatch, datetime(2026, 9, 6, 2, 0))
    html = panel(pro)
    assert len(agenda(html)) == 1 and pasadas(html) == []
    fijar_reloj(monkeypatch, datetime(2026, 9, 6, 2, 30))
    html = panel(pro)
    assert agenda(html) == [] and len(pasadas(html)) == 1


def test_filas_ilegibles_se_omiten_sin_romper(app, pro_id, pro, ana):
    mala_fecha = reservada(app, pro_id, "2026-10-12T10:00:00")
    mala_duracion = reservada(app, pro_id, "2026-10-13T10:00:00")
    libre_mala = insertar(app, pro_id, "2026-10-25T10:00:00")
    with app.app_context():
        get_db().execute("UPDATE horas SET inicio='2026-13-45T99:99:99' WHERE id = ?", (mala_fecha,))
        get_db().execute("UPDATE horas SET inicio='2026-13-46T99:99:99' WHERE id = ?", (libre_mala,))
        get_db().execute("UPDATE horas SET duracion_min='abc' WHERE id=?", (mala_duracion,))
        get_db().commit()
    html = panel(pro)
    assert agenda(html) == [] and pasadas(html) == [] and libres(html) == []
    assert "2026-13-45" not in html and "abc" not in html
    reservada(app, pro_id, "2026-10-14T10:00:00")
    reservada(app, pro_id, "2026-10-01T10:00:00")
    html = panel(pro)
    assert len(agenda(html)) == 1 and len(pasadas(html)) == 1


# -------------------------------------------------------- horas libres ----


def test_horas_libres_propias_futuras_con_orden_y_boton_eliminar(app, pro_id, pro, ana):
    otro = nuevo_profesional(app, "pro2@example.cl", "Dra. Otra")
    tardia = insertar(app, pro_id, "2026-12-01T10:00:00")
    temprana = insertar(app, pro_id, "2026-11-01T09:00:00", duracion=45)
    insertar(app, pro_id, "2026-10-01T09:00:00")  # pasada
    insertar(app, pro_id, "2026-10-08T11:00:00")  # pasada (antes de las 12:00)
    reservada(app, pro_id, "2026-11-15T10:00:00")  # reservada: está en la agenda, no aquí
    insertar(app, otro, "2026-11-05T10:00:00")  # de otra profesional
    html = panel(pro)
    assert [f[:23] for f in libres(html)] == ["01-11-2026 09:00 45 min", "01-12-2026 10:00 50 min"]
    assert "15-11-2026" not in seccion(html, "Horas libres") and "05-11-2026" not in html
    assert f'action="/profesional/horas/{temprana}/eliminar"' in html
    assert f'action="/profesional/horas/{tardia}/eliminar"' in html
    assert html.count("/eliminar") == 2


def test_hora_libre_hoy_pero_ya_empezada_no_se_muestra(app, pro_id, pro):
    insertar(app, pro_id, "2026-10-08T12:00:00")  # empieza justo ahora: ya no es futura
    insertar(app, pro_id, "2026-10-08T12:00:01")
    assert len(libres(panel(pro))) == 1


# (inicio, ¿reservable?): ahora = 2026-10-08 12:00 -03:00, así que las 24 h exactas son 09-10 12:00
@pytest.mark.parametrize("inicio,reservable", [
    ("2026-10-08T12:00:01", False),
    ("2026-10-09T11:59:59", False),
    ("2026-10-09T12:00:00", False),  # 24 h exactas: estricto, ya no se puede reservar (D-029)
    ("2026-10-09T12:00:01", True),
    ("2026-10-10T12:00:00", True),
])
def test_no_reservable_en_el_borde_exacto_de_24_horas(app, pro_id, pro, ana, inicio, reservable):
    insertar(app, pro_id, inicio)
    fila = libres(panel(pro))[0]
    assert ("no reservable" not in fila) is reservable
    # y coincide con lo que de verdad ve el paciente en su lista de horas libres
    assert (mostrar(inicio) in ana.get("/paciente/horas").text) is reservable


def mostrar(inicio):
    return f"{inicio[8:10]}-{inicio[5:7]}-{inicio[0:4]} {inicio[11:16]}"


def test_no_reservable_con_instantes_absolutos_en_el_cambio_de_horario(app, pro_id, pro, ana, monkeypatch):
    """La noche del 5 al 6 de septiembre el reloj salta de 24:00 a 01:00: la hora del 6-sep 01:00
    (-03:00 = 04:00 UTC del 6) dista 24,5 h reales de las 23:30 del 4-sep (03:30 UTC del 5) y
    23,5 h reales de las 00:30 del 5-sep, aunque en reloj de pared sean 25,5 y 24,5 h."""
    fijar_reloj(monkeypatch, datetime(2026, 9, 4, 23, 30))
    insertar(app, pro_id, "2026-09-06T01:00:00")  # instante: 04:00 UTC; ahora = 03:30 UTC del 5-sep
    assert "no reservable" not in libres(panel(pro))[0]
    fijar_reloj(monkeypatch, datetime(2026, 9, 5, 0, 30))  # 04:30 UTC del 5-sep: en pared serían 24,5 h
    assert "no reservable" in libres(panel(pro))[0]


def test_agregar_y_eliminar_siguen_funcionando_desde_el_panel(app, pro_id, pro):
    from tests.test_seguridad import extraer_token
    hora = insertar(app, pro_id, "2026-12-01T10:00:00")
    html = panel(pro)
    cuerpo = re.search(rf'<form[^>]*action="/profesional/horas/{hora}/eliminar"[^>]*>(.*?)</form>', html, re.S).group(1)
    r = pro.post(f"/profesional/horas/{hora}/eliminar", data={"csrf_token": extraer_token(cuerpo)})
    assert r.status_code == 302 and r.headers["Location"] == "/profesional"
    assert "La hora se eliminó correctamente." in pro.get("/profesional").text
    assert libres(panel(pro)) == []


def test_la_hora_libre_hostil_no_es_posible_pero_el_nombre_del_paciente_se_escapa(app, pro_id, pro, ana):
    hostil = "<script>alert(1)</script>"
    reservada(app, pro_id, "2026-10-14T10:00:00")
    reservada(app, pro_id, "2026-10-01T10:00:00")
    notificar(app, PRO, f"Hola {hostil} <img src=x onerror=alert(2)>")
    with app.app_context():
        get_db().execute("UPDATE usuarios SET nombre=? WHERE email=?", (hostil, ANA))
        get_db().commit()
    html = panel(pro)
    assert "<script>" not in html and "<img" not in html
    assert html.count("&lt;script&gt;alert(1)&lt;/script&gt;") >= 3  # agenda, pasadas y mensaje
    assert "&lt;img src=x onerror=alert(2)&gt;" in html


def test_el_nombre_del_profesional_hostil_se_escapa_en_el_saludo(app, pro_id, pro):
    with app.app_context():
        get_db().execute("UPDATE usuarios SET nombre=? WHERE id=?", ("<b>Dr</b>", pro_id))
        get_db().commit()
    html = panel(pro)
    assert "<b>Dr</b>" not in html and "&lt;b&gt;Dr&lt;/b&gt;" in html


# ------------------------------------------------------ notificaciones ----


def test_flujo_real_confirmacion_y_cancelacion_llegan_al_profesional(app, pro_id, pro, ana):
    hora = insertar(app, pro_id, "2026-10-14T10:00:00")
    assert reservar(ana, hora).status_code == 302
    html = panel(pro)
    assert 'aria-label="Campana de notificaciones: 1 sin leer"' in html
    lista = mensajes_listados(html)
    assert len(lista) == 1 and lista[0].startswith("Confirmación") and "Ana Pérez" in lista[0]
    assert "14-10-2026 a las 10:00" in lista[0] and "08-10-2026 12:00" in lista[0]
    assert "Ver la reserva" in html and f'href="#reserva-{hora}"' in html and f'id="reserva-{hora}"' in html
    cancelar(ana, hora)
    lista = mensajes_listados(panel(pro))
    assert len(lista) == 2 and lista[0].startswith("Cancelación") and lista[1].startswith("Confirmación")
    # la paciente no ve las del profesional ni al revés
    assert len(mensajes_listados(ana.get("/paciente").text)) == 2


def test_aislamiento_entre_paciente_y_profesional(app, pro_id, pro, ana, beto):
    notificar(app, PRO, "para el profesional")
    notificar(app, ANA, "para Ana secreta")
    notificar(app, BETO, "para Beto secreto")
    html = panel(pro)
    assert "para el profesional" in html and "secret" not in html
    assert 'aria-label="Campana de notificaciones: 1 sin leer"' in html
    assert "para el profesional" not in ana.get("/paciente").text
    assert "para el profesional" not in beto.get("/paciente").text
    assert 'aria-label="Campana de notificaciones: 1 sin leer"' in ana.get("/paciente").text


def test_orden_por_id_descendente_aunque_creada_en_diga_otra_cosa(app, pro_id, pro):
    notificar(app, PRO, "primera", creada_en="2026-10-08T09:00:00-03:00")
    notificar(app, PRO, "segunda", creada_en="2026-10-08T05:00:00-04:00")
    notificar(app, PRO, "tercera", creada_en="2025-01-01T00:00:00-03:00")
    lista = mensajes_listados(panel(pro))
    assert [m.split(") ", 1)[1] for m in lista] == ["tercera", "segunda", "primera"]


def test_el_contador_cuenta_solo_no_leidas_propias(app, pro_id, pro, ana):
    notificar(app, PRO, "nueva uno")
    notificar(app, PRO, "nueva dos")
    notificar(app, PRO, "vieja", leida=1)
    notificar(app, ANA, "de Ana")
    html = panel(pro)
    assert 'aria-label="Campana de notificaciones: 2 sin leer"' in html
    assert "Tienes 2 notificaciones sin leer." in html
    assert html.count('class="no-leida"') == 2 and html.count('class="leida"') == 1


def test_hora_id_null_muestra_el_mensaje_sin_enlace(app, pro_id, pro, ana):
    hora = insertar(app, pro_id, "2026-10-14T10:00:00")
    reservar(ana, hora)
    cancelar(ana, hora)
    with app.app_context():
        get_db().execute("DELETE FROM horas WHERE id = ?", (hora,))
        get_db().commit()
        assert get_db().execute(
            "SELECT COUNT(*) FROM notificaciones WHERE usuario_id=? AND hora_id IS NULL", (uid(app, PRO),)
        ).fetchone()[0] == 2
    html = panel(pro)
    lista = mensajes_listados(html)
    assert len(lista) == 2 and all("14-10-2026 a las 10:00" in m for m in lista)
    assert "Ver la reserva" not in html and "reserva-None" not in html


def test_notificacion_directa_con_hora_id_null(app, pro_id, pro):
    notificar(app, PRO, "sin hora", hora_id=None)
    html = panel(pro)
    assert mensajes_listados(html)[0].endswith("sin hora") and "Ver la reserva" not in html


def test_enlace_solo_a_una_reserva_de_la_agenda_del_profesional(app, pro_id, pro, ana, beto):
    otro = nuevo_profesional(app, "pro2@example.cl", "Dra. Otra")
    suya = reservada(app, pro_id, "2026-10-14T10:00:00")
    ajena = reservada(app, otro, "2026-10-15T10:00:00", email=BETO)  # hora de otra profesional
    libre = insertar(app, pro_id, "2026-10-16T10:00:00")
    pasada = reservada(app, pro_id, "2026-10-01T10:00:00")
    notificar(app, PRO, "con enlace", hora_id=suya)
    notificar(app, PRO, "apunta a hora ajena", hora_id=ajena)
    notificar(app, PRO, "apunta a hora libre", hora_id=libre)
    notificar(app, PRO, "apunta a sesión pasada", hora_id=pasada)
    html = panel(pro)
    assert html.count("Ver la reserva") == 1
    assert f'href="#reserva-{suya}"' in html and f'id="reserva-{suya}"' in html
    for no in (ajena, libre, pasada):
        assert f'href="#reserva-{no}"' not in html
    assert "15-10-2026" not in html  # el mensaje mostrado es el guardado


def test_la_ruta_de_leidas_y_el_boton(app, pro_id, pro):
    assert formularios_de_leidas(panel(pro)) == []
    notificar(app, PRO, "vieja", leida=1)
    assert "Marcar todas" not in panel(pro)
    notificar(app, PRO, "nueva")
    html = panel(pro)
    forms = re.findall(rf'<form[^>]*action="{RUTA_LEIDAS}"[^>]*>.*?</form>', html, re.S)
    assert len(forms) == 1 and 'method="post"' in forms[0]
    assert re.search(r'name="csrf_token" value="[0-9a-f]+"', forms[0])
    assert re.findall(r'<(?:input|select|textarea)[^>]*name="(\w+)"', forms[0]) == ["csrf_token"]
    assert html.count("Marcar todas como leídas") == 1


# ------------------------------------------------ tope y aviso (R-03) ----


@pytest.mark.parametrize("cantidad,aviso", [(19, False), (20, False), (21, True), (25, True)])
def test_aviso_de_tope_solo_si_hay_mas_que_el_tope(app, pro_id, pro, ana, cantidad, aviso):
    for i in range(cantidad):
        notificar(app, PRO, f"aviso {i:02d}")
    html = panel(pro)
    assert len(mensajes_listados(html)) == min(cantidad, notificaciones.TOPE_PANEL)
    assert ("Se muestran tus 20 notificaciones más recientes." in html) is aviso
    assert f'Campana de notificaciones: {cantidad} sin leer' in html  # el contador no se recorta


def test_el_tope_sale_de_la_constante(app, pro_id, pro, monkeypatch):
    monkeypatch.setattr(notificaciones, "TOPE_PANEL", 3)
    for i in range(4):
        notificar(app, PRO, f"aviso {i}")
    html = panel(pro)
    assert len(mensajes_listados(html)) == 3
    assert "Se muestran tus 3 notificaciones más recientes." in html
    notificar(app, PRO, "otro")
    monkeypatch.setattr(notificaciones, "TOPE_PANEL", 5)
    assert "Se muestran tus" not in panel(pro)  # 5 notificaciones con tope 5: no hay más


def test_listar_de_usuario_devuelve_si_hay_mas(app, pro_id):
    for i in range(21):
        notificar(app, PRO, f"aviso {i}")
    with app.app_context():
        lista, sin_leer, hay_mas = notificaciones.listar_de_usuario(get_db(), pro_id)
    assert len(lista) == 20 and sin_leer == 21 and hay_mas is True
    assert lista[0]["mensaje"] == "aviso 20" and lista[-1]["mensaje"] == "aviso 1"


def test_el_contador_incluye_no_leidas_fuera_de_las_20_visibles(app, pro_id, pro):
    notificar(app, PRO, "vieja sin leer")
    for i in range(20):
        notificar(app, PRO, f"leída {i}", leida=1)
    html = panel(pro)
    assert len(mensajes_listados(html)) == 20 and "vieja sin leer" not in html
    assert 'Campana de notificaciones: 1 sin leer' in html and len(formularios_de_leidas(html)) == 0
    assert len(re.findall(rf'action="{RUTA_LEIDAS}"', html)) == 1


# ----------------------------------------------- marcar como leídas ----


def token_de(client, ruta="/profesional"):
    client.get(ruta)
    with client.session_transaction() as s:
        return s["csrf_token"]


def marcar(client, ruta="/profesional", **extra):
    return client.post(RUTA_LEIDAS, data={"csrf_token": token_de(client, ruta), **extra})


def test_marcar_todas_baja_el_contador_y_solo_toca_al_profesional(app, pro_id, pro, ana, beto):
    notificar(app, PRO, "uno")
    notificar(app, PRO, "dos")
    notificar(app, PRO, "vieja", leida=1)
    notificar(app, ANA, "de Ana")
    notificar(app, BETO, "de Beto")
    r = marcar(pro)
    assert r.status_code == 302 and r.headers["Location"] == "/profesional"
    html = pro.get(r.headers["Location"]).text
    assert "Marcaste 2 notificaciones como leídas." in html
    assert 'Campana de notificaciones: 0 sin leer' in html and "Marcar todas" not in html
    assert estados(app, PRO) == [True, True, True]
    assert estados(app, ANA) == [False] and estados(app, BETO) == [False]


def test_marcar_es_idempotente_y_el_singular(app, pro_id, pro):
    notificar(app, PRO, "uno")
    marcar(pro)
    assert "Marcaste 1 notificación como leída." in pro.get("/profesional").text
    r = marcar(pro)
    assert r.status_code == 302
    assert "No tenías notificaciones sin leer." in pro.get("/profesional").text
    notificar(app, PRO, "otra")
    assert estados(app, PRO) == [True, False]


def test_sin_token_csrf_no_marca_nada(app, pro_id, pro):
    notificar(app, PRO, "uno")
    pro.get("/profesional")
    assert pro.post(RUTA_LEIDAS).status_code == 400
    assert pro.post(RUTA_LEIDAS, data={"csrf_token": "0" * 64}).status_code == 400
    assert estados(app, PRO) == [False]


def test_ignora_los_ids_del_formulario(app, pro_id, pro, ana):
    ajena = notificar(app, ANA, "de Ana")
    notificar(app, PRO, "mía")
    marcar(pro, id=ajena, ids=ajena, usuario_id=uid(app, ANA), leida=0)
    r = pro.post(RUTA_LEIDAS + f"?id={ajena}&usuario_id={uid(app, ANA)}", data={"csrf_token": token_de(pro)})
    assert r.status_code == 302
    assert estados(app, PRO) == [True] and estados(app, ANA) == [False]


def test_la_ruta_no_acepta_get(app, pro_id, pro):
    notificar(app, PRO, "uno")
    assert pro.get(RUTA_LEIDAS).status_code == 405
    assert estados(app, PRO) == [False]


def test_el_paciente_no_puede_usar_la_ruta_del_profesional(app, pro_id, ana):
    notificar(app, PRO, "del profesional")
    notificar(app, ANA, "de Ana")
    r = marcar(ana, ruta="/paciente")
    assert r.status_code == 403
    assert estados(app, PRO) == [False] and estados(app, ANA) == [False]


def test_el_profesional_no_puede_usar_la_ruta_del_paciente(app, pro_id, pro, ana):
    notificar(app, ANA, "de Ana")
    r = pro.post("/notificaciones/leidas", data={"csrf_token": token_de(pro)})
    assert r.status_code == 403 and estados(app, ANA) == [False]


def test_el_anonimo_no_puede_usar_la_ruta(app, pro_id):
    notificar(app, PRO, "del profesional")
    c = app.test_client()
    r = c.post(RUTA_LEIDAS, data={"csrf_token": token_de(c, "/login")})
    assert r.status_code == 302 and r.headers["Location"].startswith("/login")
    assert c.post(RUTA_LEIDAS).status_code == 400
    assert estados(app, PRO) == [False]


def test_los_dos_paneles_comparten_la_funcion_del_mensaje(app, pro_id, pro, ana, monkeypatch):
    monkeypatch.setattr(notificaciones, "mensaje_marcadas", lambda n: f"MENSAJE COMPARTIDO {n}")
    notificar(app, PRO, "uno")
    notificar(app, ANA, "uno")
    marcar(pro)
    assert "MENSAJE COMPARTIDO 1" in pro.get("/profesional").text
    ana.post("/notificaciones/leidas", data={"csrf_token": token_de(ana, "/paciente")})
    assert "MENSAJE COMPARTIDO 1" in ana.get("/paciente").text


def test_mensaje_marcadas():
    assert notificaciones.mensaje_marcadas(0) == "No tenías notificaciones sin leer."
    assert notificaciones.mensaje_marcadas(1) == "Marcaste 1 notificación como leída."
    assert notificaciones.mensaje_marcadas(7) == "Marcaste 7 notificaciones como leídas."
