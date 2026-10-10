"""T-13: hoja de estilos, páginas de error en español, favicon y accesibilidad básica del HTML.

La revisión visual (capturas a 390 y 1280 px) no se puede automatizar aquí: se hizo a mano y
consta en PROGRESS.md. Lo que sí se prueba: que la hoja se sirva y se enlace en todas las
páginas, que ninguna plantilla use `style=` en línea (para no cerrar la puerta a una CSP), que
las páginas de error salgan en español sin datos internos y con `no-store` (D-024), y que los
pares de colores de la hoja cumplan los umbrales de contraste WCAG AA (tema claro y oscuro).
"""
import pathlib
import re

import pytest

from app import create_app, errores, notificaciones, profesional, seguridad
from app.db import init_db
from tests.test_dashboard_paciente import ANA, notificar
from tests.test_horas_libres import fijar_reloj, insertar, nuevo_profesional
from tests.test_login import iniciar
from tests.test_cancelar import reservada
from tests.test_reservar import nuevo_paciente

RAIZ = pathlib.Path(__file__).resolve().parent.parent / "app"
CSS = (RAIZ / "static" / "style.css").read_text(encoding="utf-8")
HOJA = '<link rel="stylesheet" href="/static/style.css">'
ENGLISH = ("Not Found", "Bad Request", "Forbidden", "Method Not Allowed", "Request Entity",
           "Internal Server Error", "The requested URL")


@pytest.fixture(autouse=True)
def base_inicializada(app):
    with app.app_context():
        init_db()


@pytest.fixture(autouse=True)
def reloj_fijo(monkeypatch):
    fijar_reloj(monkeypatch)


# ------------------------------------------------------------ la hoja ----


def test_la_hoja_se_sirve_como_css(client):
    r = client.get("/static/style.css")
    assert r.status_code == 200
    assert r.mimetype == "text/css"
    assert "no-store" not in r.headers.get("Cache-Control", "")  # los estáticos conservan su caché


def test_la_hoja_no_usa_recursos_externos():
    assert "@import" not in CSS and "url(" not in CSS and "http" not in CSS


def test_la_hoja_cuida_foco_movimiento_y_tema():
    assert re.search(r"^:focus-visible\s*\{[^}]*outline: 3px solid", CSS, re.M)
    assert "outline: none" not in CSS and "outline:none" not in CSS
    assert "prefers-reduced-motion: reduce" in CSS
    assert "prefers-color-scheme: dark" in CSS
    assert "min-height: 2.75rem" in CSS  # áreas táctiles de 44 px


def test_los_mensajes_se_distinguen_sin_depender_del_color():
    assert '.mensaje.exito::before { content: "Listo: "' in CSS
    assert 'content: "Error: "' in CSS


# ----------------------------------------------- base enlaza la hoja ----


def test_todas_las_paginas_enlazan_la_hoja_y_el_favicon(app, client):
    pro_id = nuevo_profesional(app)
    ana = nuevo_paciente(app)
    pro = app.test_client()
    iniciar(pro, "pro@example.cl")
    paginas = [(client, "/"), (client, "/login"), (client, "/registro"), (client, "/no-existe"),
               (ana, "/paciente"), (ana, "/paciente/horas"), (ana, "/profesional"),
               (pro, "/profesional"), (pro, "/profesional/horas/nueva")]
    for cliente, ruta in paginas:
        r = cliente.get(ruta)
        assert HOJA in r.text, ruta
        assert '<link rel="icon" type="image/svg+xml" href="/static/favicon.svg">' in r.text, ruta
        assert 'name="color-scheme"' in r.text and 'lang="es-CL"' in r.text, ruta
    assert pro_id


def test_el_favicon_existe_y_no_hay_404(client):
    r = client.get("/static/favicon.svg")
    assert r.status_code == 200 and r.mimetype == "image/svg+xml"
    assert b"<script" not in r.data


def test_ninguna_plantilla_usa_estilos_ni_scripts_en_linea():
    plantillas = list(RAIZ.glob("templates/*.html"))
    assert len(plantillas) >= 11
    for ruta in plantillas:
        html = ruta.read_text(encoding="utf-8")
        assert not re.search(r"\sstyle\s*=", html), ruta.name
        assert not re.search(r"<style|<script|\son[a-z]+\s*=", html), ruta.name


# ------------------------------------------------- páginas de error ----


def verificar_pagina_de_error(r, codigo, titulo):
    assert r.status_code == codigo
    assert r.headers["Cache-Control"] == "no-store" and r.headers["Pragma"] == "no-cache"
    assert r.mimetype == "text/html"
    html = r.text
    assert 'lang="es-CL"' in html and HOJA in html
    assert titulo in html
    assert 'href="/"' in html and "Volver al inicio" in html
    for ingles in ENGLISH:
        assert ingles not in html
    for interno in ("Traceback", "File \"", "SECRETO", "sqlite", "SECRET_KEY", "/home/"):
        assert interno not in html
    return html


def test_404_en_espanol(client):
    verificar_pagina_de_error(client.get("/no-existe"), 404, "Página no encontrada")


def test_404_de_un_estatico_tambien_es_no_store(client):
    r = client.get("/static/no-existe.css")
    verificar_pagina_de_error(r, 404, "Página no encontrada")


def test_403_del_paciente_en_el_panel_ajeno(app):
    nuevo_profesional(app)
    ana = nuevo_paciente(app)
    r = ana.get("/profesional")
    assert r.status_code == 403 and r.headers["Cache-Control"] == "no-store"
    assert "No tienes permiso" in r.text and "Volver al inicio" in r.text and HOJA in r.text


def test_403_generico_en_espanol(app):
    @app.route("/prohibida")
    def prohibida():
        from flask import abort
        abort(403)

    verificar_pagina_de_error(app.test_client().get("/prohibida"), 403, "Acceso denegado")


def test_400_de_csrf_en_espanol_y_sin_datos(client):
    r = client.post("/registro", data={"nombre": "Ana", "password": "secreto-123"})
    html = verificar_pagina_de_error(r, 400, "Solicitud no válida")
    assert seguridad.MENSAJE_CSRF in html
    assert "secreto-123" not in html and "Ana" not in html


def test_un_400_con_descripcion_interna_no_la_muestra(app):
    @app.route("/mala")
    def mala():
        from flask import abort
        abort(400, description="detalle interno SECRETO en inglés")

    html = verificar_pagina_de_error(app.test_client().get("/mala"), 400, "Solicitud no válida")
    assert seguridad.MENSAJE_CSRF not in html


def test_413_sigue_saliendo_con_max_content_length(app, client):
    assert app.config["MAX_CONTENT_LENGTH"] == 16 * 1024
    cuerpo = "x" * (app.config["MAX_CONTENT_LENGTH"] + 1)
    r = client.post("/login", data=cuerpo, content_type="application/x-www-form-urlencoded")
    verificar_pagina_de_error(r, 413, "Envío demasiado grande")


def test_405_en_espanol_conserva_allow(client):
    r = client.get("/logout")
    verificar_pagina_de_error(r, 405, "Acción no permitida")
    assert "POST" in r.headers["Allow"]


def test_500_en_espanol_sin_filtrar_la_excepcion(app):
    app.config["PROPAGATE_EXCEPTIONS"] = False

    @app.route("/rota")
    def rota():
        raise RuntimeError("SECRETO: clave=zz-9-qq en /home/claude/agenda.db")

    r = app.test_client().get("/rota")
    html = verificar_pagina_de_error(r, 500, "Algo salió mal")
    assert "zz-9-qq" not in html and "RuntimeError" not in html


def test_500_sin_secret_key_sale_en_espanol(tmp_path, monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    app = create_app({"DATABASE": str(tmp_path / "t.db")})
    r = app.test_client().get("/login")
    verificar_pagina_de_error(r, 500, "Algo salió mal")


def test_si_la_plantilla_de_error_falla_hay_un_html_minimo(app, monkeypatch):
    app.config["PROPAGATE_EXCEPTIONS"] = False

    def falla(*args, **kwargs):
        raise RuntimeError("plantilla rota")

    monkeypatch.setattr(errores, "render_template", falla)
    r = app.test_client().get("/no-existe")
    assert r.status_code == 404 and "Algo salió mal" in r.text and r.headers["Cache-Control"] == "no-store"


def test_la_pagina_de_error_no_consume_los_mensajes_flash(app):
    ana = nuevo_paciente(app)
    with ana.session_transaction() as s:
        s["_flashes"] = [("exito", "pendiente de mostrar")]
    assert "pendiente de mostrar" not in ana.get("/no-existe").text
    assert "pendiente de mostrar" in ana.get("/paciente").text


# ----------------------------------------- contenido ajustado en T-13 ----


def test_reservar_hora_es_la_accion_principal(app):
    nuevo_profesional(app)
    html = nuevo_paciente(app).get("/paciente").text
    assert '<p class="accion-principal"><a href="/paciente/horas">Reservar hora</a></p>' in html


def test_las_tablas_van_en_un_contenedor_con_scroll_propio(app):
    pro_id = nuevo_profesional(app)
    ana = nuevo_paciente(app)
    reservada(app, pro_id, "2026-10-12T10:00:00")
    insertar(app, pro_id, "2026-10-14T09:00:00")
    for cliente, ruta, tablas in ((ana, "/paciente", 1), (ana, "/paciente/horas", 1)):
        html = cliente.get(ruta).text
        assert html.count('<div class="tabla-scroll"') == html.count("<table") == tablas, ruta
        assert html.count("<caption>") == tablas and "<th>" not in html, ruta
    pro = app.test_client()
    iniciar(pro, "pro@example.cl")
    html = pro.get("/profesional").text
    assert html.count('<div class="tabla-scroll"') == html.count("<table") == 2


def test_la_nota_de_eliminar_sale_una_vez_y_no_en_cada_fila(app):
    pro_id = nuevo_profesional(app)
    nuevo_paciente(app)
    reservada(app, pro_id, "2026-10-12T10:00:00")
    reservada(app, pro_id, "2026-10-13T10:00:00")
    pro = app.test_client()
    iniciar(pro, "pro@example.cl")
    html = pro.get("/profesional").text
    assert html.count("el paciente debe cancelarla primero") == 1
    assert "Para eliminarla" not in html


def test_con_solo_sesiones_pasadas_no_dice_que_nunca_publico_horas(app):
    pro_id = nuevo_profesional(app)
    nuevo_paciente(app)
    reservada(app, pro_id, "2026-10-01T10:00:00")
    pro = app.test_client()
    iniciar(pro, "pro@example.cl")
    html = pro.get("/profesional").text
    assert "Aún no tienes horas publicadas" not in html
    assert "No tienes horas libres publicadas." in html


def test_las_sesiones_pasadas_del_profesional_tienen_tope(app, monkeypatch):
    pro_id = nuevo_profesional(app)
    nuevo_paciente(app)
    for dia in range(1, 8):
        reservada(app, pro_id, f"2026-09-{dia:02d}T10:00:00")
    pro = app.test_client()
    iniciar(pro, "pro@example.cl")
    assert profesional.TOPE_PASADAS == 20
    assert "sesiones pasadas más recientes" not in pro.get("/profesional").text  # 7 < 20
    monkeypatch.setattr(profesional, "TOPE_PASADAS", 3)
    html = pro.get("/profesional").text
    cuerpo = re.search(r"Sesiones pasadas.*?(?=<h2|</main>)", html, re.S).group(0)
    assert cuerpo.count("<tr") == 1 + 3  # encabezado + 3 filas
    assert "Se muestran las 3 sesiones pasadas más recientes." in html
    assert "01-09-2026" not in cuerpo and "07-09-2026" in cuerpo


def test_los_avisos_de_cancelacion_no_enlazan_a_la_reserva(app):
    pro_id = nuevo_profesional(app)
    ana = nuevo_paciente(app)
    hora = reservada(app, pro_id, "2026-10-14T10:00:00")
    # T-15 (b): una confirmación con una cancelación POSTERIOR de la misma hora ya no enlaza; el aviso
    # de cancelación va primero (más antiguo) para que esta prueba siga mirando solo que él no enlaza.
    notificar(app, ANA, "Cancelaste otra.", tipo="cancelacion", hora_id=hora)
    notificar(app, ANA, "Reservaste.", tipo="confirmacion", hora_id=hora)
    assert ana.get("/paciente").text.count("Ver la reserva") == 1


def test_los_campos_con_error_se_marcan_aria_invalid(client):
    from tests.test_login import extraer_token
    token = extraer_token(client.get("/registro").text)
    html = client.post("/registro", data={"csrf_token": token, "nombre": "", "email": "x", "password": "1"}).text
    assert html.count('aria-invalid="true"') == 3 and 'role="alert"' in html
    assert "aria-invalid" not in client.get("/registro").text


# ------------------------------- T-13c: logo, flash y accesibilidad ----

MARCA = re.compile(r'<a class="marca" href="([^"]*)">')


def destino_del_logo(cliente, ruta):
    r = cliente.get(ruta, follow_redirects=True)  # T-15: /login y /registro con sesión redirigen al panel
    return MARCA.search(r.text).group(1)


def test_el_logo_lleva_al_inicio_sin_sesion(app, client):
    for ruta in ("/", "/login", "/registro", "/no-existe"):
        assert destino_del_logo(client, ruta) == "/", ruta


def test_el_logo_lleva_al_panel_del_paciente_con_sesion(app):
    nuevo_profesional(app)
    ana = nuevo_paciente(app)
    for ruta in ("/", "/paciente", "/paciente/horas", "/login", "/registro"):
        assert destino_del_logo(ana, ruta) == "/paciente", ruta


def test_el_logo_lleva_al_panel_del_profesional_con_sesion(app):
    nuevo_profesional(app)
    pro = app.test_client()
    iniciar(pro, "pro@example.cl")
    for ruta in ("/", "/profesional", "/profesional/horas/nueva", "/login"):
        assert destino_del_logo(pro, ruta) == "/profesional", ruta


def test_el_logo_vuelve_al_inicio_tras_cerrar_sesion(app):
    from tests.test_login import extraer_token
    nuevo_profesional(app)
    ana = nuevo_paciente(app)
    assert destino_del_logo(ana, "/paciente") == "/paciente"
    ana.post("/logout", data={"csrf_token": extraer_token(ana.get("/paciente").text)})
    assert destino_del_logo(ana, "/login") == "/"


def test_las_paginas_de_error_no_leen_la_sesion_y_su_logo_va_al_inicio(app):
    nuevo_profesional(app)
    ana = nuevo_paciente(app)
    assert destino_del_logo(ana, "/no-existe") == "/"  # D-008: el error no consulta la sesión
    assert destino_del_logo(ana, "/profesional") == "/paciente"  # 403 del rol: esa página sí lee la sesión


def test_el_flash_de_reserva_no_repite_la_palabra_listo(app):
    from tests.test_reservar import reservar_y_aviso
    pro_id = nuevo_profesional(app)
    ana = nuevo_paciente(app)
    hora = insertar(app, pro_id, "2026-10-20T10:00:00")
    categoria, texto = reservar_y_aviso(ana, hora)
    assert categoria == "exito" and texto.startswith("Reservaste tu hora: ")
    html = ana.get("/paciente").text
    assert "Listo" not in html  # el prefijo «Listo: » lo pone la hoja, una sola vez


def test_ningun_mensaje_de_exito_empieza_con_listo():
    # La hoja antepone «Listo: » a todo flash de éxito (R-02 de T-13): el texto no debe repetirlo.
    for ruta in sorted(RAIZ.glob("*.py")):
        for literal in re.findall(r"""flash\(\s*["']([^"']*)["']""", ruta.read_text(encoding="utf-8")):
            assert not literal.lower().startswith("listo"), (ruta.name, literal)
    from app import paciente
    assert not paciente.MENSAJE_CONFIRMACION.lower().startswith("listo")


PLANTILLAS_CON_BASE = ["inicio", "login", "registro", "horas_libres", "paciente", "profesional", "nueva_hora", "error"]


def test_todas_las_paginas_tienen_el_enlace_saltar_y_el_destino(app, client):
    pro_id = nuevo_profesional(app)
    ana = nuevo_paciente(app)
    pro = app.test_client()
    iniciar(pro, "pro@example.cl")
    paginas = [(client, "/"), (client, "/login"), (client, "/registro"), (client, "/no-existe"),
               (ana, "/paciente"), (ana, "/paciente/horas"), (pro, "/profesional"),
               (pro, "/profesional/horas/nueva")]
    for cliente, ruta in paginas:
        html = cliente.get(ruta).text
        assert '<a class="saltar" href="#contenido">Saltar al contenido</a>' in html, ruta
        assert html.count('id="contenido"') == 1 and '<main id="contenido">' in html, ruta
    assert pro_id
    # el enlace va antes que la cabecera y que cualquier otro enlace (primer Tab)
    base = (RAIZ / "templates" / "base.html").read_text(encoding="utf-8")
    assert base.index('class="saltar"') < base.index('class="cabecera"') < base.index('id="contenido"')


def test_las_tablas_con_scroll_se_pueden_recorrer_con_teclado(app):
    pro_id = nuevo_profesional(app)
    ana = nuevo_paciente(app)
    reservada(app, pro_id, "2026-10-12T10:00:00")
    reservada(app, pro_id, "2026-10-01T10:00:00")
    insertar(app, pro_id, "2026-10-14T09:00:00")
    pro = app.test_client()
    iniciar(pro, "pro@example.cl")
    paginas = [(ana, "/paciente"), (ana, "/paciente/horas"), (pro, "/profesional")]
    for cliente, ruta in paginas:
        html = cliente.get(ruta).text
        regiones = re.findall(r'<div class="tabla-scroll"([^>]*)>', html)
        assert regiones and len(regiones) == html.count("<table"), ruta
        for atributos in regiones:
            assert 'tabindex="0"' in atributos and 'role="region"' in atributos, (ruta, atributos)
            assert re.search(r'aria-label="[^"]+"', atributos), (ruta, atributos)
    # y en el código: ninguna plantilla abre un contenedor de tabla sin tabindex
    for ruta in RAIZ.glob("templates/*.html"):
        for atributos in re.findall(r'<div class="tabla-scroll"([^>]*)>', ruta.read_text(encoding="utf-8")):
            assert 'tabindex="0"' in atributos, ruta.name


def test_las_notificaciones_nuevas_se_distinguen_sin_depender_del_color(app):
    nuevo_profesional(app)
    ana = nuevo_paciente(app)
    notificar(app, ANA, "Aviso sin leer.", tipo="confirmacion")
    html = ana.get("/paciente").text
    assert '<li class="no-leida">' in html and "(nueva" in html
    # el subrayado del título de las nuevas y el borde grueso salen de la hoja
    assert re.search(r"\.notificaciones li\.no-leida strong\s*\{[^}]*text-decoration:\s*underline", CSS)
    assert re.search(r"\.notificaciones li\s*\{[^}]*border-left-width:\s*8px", CSS)
    assert not re.search(r"\.notificaciones li\.leida strong\s*\{[^}]*underline", CSS)


def test_los_campos_de_agregar_hora_con_error_se_marcan_aria_invalid(app):
    from tests.test_login import extraer_token
    nuevo_profesional(app)
    pro = app.test_client()
    iniciar(pro, "pro@example.cl")
    assert "aria-invalid" not in pro.get("/profesional/horas/nueva").text
    token = extraer_token(pro.get("/profesional/horas/nueva").text)
    r = pro.post("/profesional/horas/nueva",
                 data={"csrf_token": token, "fecha": "no-es-fecha", "hora": "", "duracion": "0"})
    assert r.status_code == 200
    campos = re.findall(r'<input[^>]*aria-invalid="true"[^>]*>', r.text)
    assert sorted(re.search(r'name="(\w+)"', c).group(1) for c in campos) == ["duracion", "fecha", "hora"]


def test_la_hoja_apila_las_filas_de_las_tablas_en_pantallas_angostas():
    movil = re.search(r"@media \(max-width: 40em\)\s*\{(.*?)\n\}\n", CSS, re.S).group(1)
    assert re.search(r"table, tbody, tr, th, td\s*\{\s*display: block", movil)
    assert 'content: attr(data-label)' in movil
    assert "clip-path" in movil  # los encabezados se ocultan a la vista, no con display:none


def test_las_celdas_de_datos_de_los_paneles_llevan_su_rotulo(app):
    pro_id = nuevo_profesional(app)
    ana = nuevo_paciente(app)
    reservada(app, pro_id, "2026-10-12T10:00:00")
    insertar(app, pro_id, "2026-10-14T09:00:00")
    pro = app.test_client()
    iniciar(pro, "pro@example.cl")
    for cliente, ruta in ((ana, "/paciente"), (pro, "/profesional")):
        html = cliente.get(ruta).text
        filas = re.findall(r"<tbody>(.*?)</tbody>", html, re.S)
        assert filas, ruta
        for cuerpo in filas:
            for celda in re.findall(r"<td([^>]*)>", cuerpo):
                assert "data-label=" in celda or 'class="accion"' in celda, (ruta, celda)


# --------------------------------------------- contraste (WCAG 2.x AA) ----


def _variables(bloque):
    return dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6})\s*;", bloque))


def _temas():
    claro = re.search(r":root\s*\{(.*?)\}", CSS, re.S).group(1)
    oscuro = re.search(r"prefers-color-scheme: dark\)\s*\{\s*:root\s*\{(.*?)\}", CSS, re.S).group(1)
    base = _variables(claro)
    return {"claro": base, "oscuro": {**base, **_variables(oscuro)}}


def _luminancia(hexa):
    canales = [int(hexa[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lineal = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in canales]
    return 0.2126 * lineal[0] + 0.7152 * lineal[1] + 0.0722 * lineal[2]


def contraste(a, b):
    la, lb = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# (primer plano, fondo, mínimo): 4,5 para texto normal; 3 para bordes de campos y anillo de foco.
PARES = [
    ("texto", "fondo", 4.5), ("texto", "superficie", 4.5), ("suave", "fondo", 4.5),
    ("suave", "superficie", 4.5), ("suave", "nueva-fondo", 4.5), ("texto", "nueva-fondo", 4.5),
    ("enlace", "fondo", 4.5), ("enlace", "superficie", 4.5), ("enlace", "nueva-fondo", 4.5),
    ("sobre-primario", "primario", 4.5), ("sobre-primario", "primario-hover", 4.5),
    ("peligro", "superficie", 4.5), ("peligro", "fondo", 4.5), ("peligro", "nueva-fondo", 4.5),
    ("sobre-peligro", "peligro", 4.5), ("sobre-peligro", "peligro-hover", 4.5),
    ("exito-texto", "exito-fondo", 4.5), ("error-texto", "error-fondo", 4.5),
    ("primario", "superficie", 4.5),
    ("borde-campo", "superficie", 3.0), ("borde-campo", "fondo", 3.0),
    ("foco", "fondo", 3.0), ("foco", "superficie", 3.0),
    ("exito-borde", "exito-fondo", 3.0), ("error-borde", "error-fondo", 3.0),
]


@pytest.mark.parametrize("tema", ["claro", "oscuro"])
def test_contraste_de_la_paleta(tema):
    colores = _temas()[tema]
    fallos = [(a, b, round(contraste(colores[a], colores[b]), 2), minimo)
              for a, b, minimo in PARES if contraste(colores[a], colores[b]) < minimo]
    assert not fallos
