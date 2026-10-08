"""Guardas de las aceleraciones de conftest.py (T-08b, D-031).

Las pruebas aceleradas (base copiada de una plantilla, caché de plantillas Jinja y de
constructores de URL) deben comportarse igual que sin aceleración y cada prueba debe
seguir viendo una base limpia.
"""
import re
import sqlite3

import pytest

from app import create_app
from app import db as modulo_db
from app.db import get_db, init_db
from tests import conftest as cf
from tests.test_login import crear


def _esquema(ruta):
    con = sqlite3.connect(ruta)
    try:
        return (
            sorted(con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master").fetchall()),
            con.execute("PRAGMA user_version").fetchone(),
        )
    finally:
        con.close()


# --- Aislamiento: cada prueba ve una base limpia, en cualquier orden ------------
# Las tres copias escriben lo mismo. Si una base se compartiera entre pruebas, la
# segunda chocaría con el UNIQUE del correo o vería más de una fila.


@pytest.mark.parametrize("copia", [1, 2, 3])
def test_cada_prueba_empieza_con_la_base_vacia_y_escribe_sin_afectar_a_las_otras(app, copia):
    with app.app_context():
        init_db()
        db = get_db()
        assert db.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM horas").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM notificaciones").fetchone()[0] == 0
    crear(app, email="unico@example.cl")
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 1


def test_dos_apps_en_la_misma_prueba_tienen_archivos_distintos(app, tmp_path):
    otra = create_app({"TESTING": True, "DATABASE": str(tmp_path / "otra.db")})
    assert app.config["DATABASE"] != otra.config["DATABASE"]
    with app.app_context():
        init_db()
    crear(app, email="solo-en-la-primera@example.cl")
    with otra.app_context():
        init_db()
        assert get_db().execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0


def test_la_plantilla_no_recibe_escrituras_de_las_pruebas(app, plantilla_db):
    with app.app_context():
        init_db()
    crear(app, email="no-debe-llegar@example.cl")
    for tabla in ("usuarios", "horas", "notificaciones"):
        assert plantilla_db().execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0] == 0


# --- La base copiada es idéntica a la que crea el init_db de verdad -------------


def test_la_base_de_plantilla_tiene_exactamente_el_esquema_del_init_db_real(tmp_path):
    real = create_app({"TESTING": True, "DATABASE": str(tmp_path / "real.db")})
    with real.app_context():
        cf._init_db_real()
    rapida = create_app({"TESTING": True, "DATABASE": str(tmp_path / "rapida.db")})
    with rapida.app_context():
        assert modulo_db.init_db is not cf._init_db_real  # el atajo está activo
        init_db()
    assert _esquema(tmp_path / "rapida.db") == _esquema(tmp_path / "real.db")
    assert _esquema(tmp_path / "real.db")[0], "el esquema real no puede estar vacío"


def test_la_base_copiada_acepta_y_rechaza_lo_mismo_que_la_real(app):
    with app.app_context():
        init_db()
        db = get_db()
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO usuarios (nombre, email, password_hash, rol, creado_en)"
                " VALUES ('x', 'x@example.cl', 'h', 'otro', '2026-10-08T10:00:00')"
            )


def test_init_db_sobre_una_base_con_tablas_ejecuta_el_real_y_no_borra_datos(app):
    with app.app_context():
        init_db()
    crear(app, email="queda@example.cl")
    with app.app_context():
        init_db()  # ya hay tablas: no se vuelve a copiar la plantilla encima
        assert get_db().execute("SELECT email FROM usuarios").fetchall()[0][0] == "queda@example.cl"


@pytest.mark.base_real
def test_con_base_real_no_hay_atajo():
    assert modulo_db.init_db is cf._init_db_real


# --- Cachés: mismo resultado que sin ellas --------------------------------------


def test_cache_de_constructores_de_url_da_las_mismas_urls_que_sin_cache(app, monkeypatch, tmp_path):
    monkeypatch.setattr(cf.Rule, "_compile_builder", cf._compilar_constructor_real)
    sin_cache = create_app({"TESTING": True, "DATABASE": str(tmp_path / "s.db")})
    reglas = list(app.url_map.iter_rules())
    assert len(reglas) >= 10
    for regla in reglas:
        valores = {argumento: 7 for argumento in regla.arguments}
        con = app.url_map.bind("localhost").build(regla.endpoint, valores)
        sin = sin_cache.url_map.bind("localhost").build(regla.endpoint, valores)
        assert con == sin, regla.endpoint



def test_cache_de_plantillas_renderiza_igual_que_sin_cache(app, client, tmp_path):
    sin_cache = create_app({"TESTING": True, "DATABASE": str(tmp_path / "sc.db")})
    assert type(app.jinja_env.bytecode_cache).__name__ == "_CacheDePlantillasEnMemoria"
    assert sin_cache.jinja_env.bytecode_cache is None
    sin_token = lambda cuerpo: re.sub(rb'name="csrf_token" value="[^"]*"', b"", cuerpo)  # noqa: E731
    for ruta in ("/", "/login", "/registro"):
        con = sin_token(client.get(ruta).get_data())
        sin = sin_token(sin_cache.test_client().get(ruta).get_data())
        assert con == sin and len(con) > 200, ruta
