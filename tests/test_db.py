import sqlite3

import pytest

from app import db as modulo_db
from app.db import get_db, init_db

AHORA = "2026-10-07T10:00:00"

# Prueban `init_db` mismo: corren siempre con el real, sin la base de plantilla (D-031).
pytestmark = pytest.mark.base_real


@pytest.fixture
def db(app):
    with app.app_context():
        init_db()
        yield get_db()


def crear_usuario(db, email="a@example.cl", rol="paciente"):
    cur = db.execute(
        "INSERT INTO usuarios (nombre, email, password_hash, rol, creado_en)"
        " VALUES (?, ?, ?, ?, ?)",
        ("Ana", email, "hash", rol, AHORA),
    )
    return cur.lastrowid


def test_init_db_crea_las_cuatro_tablas(db):
    filas = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    assert {f["name"] for f in filas} == {
        "usuarios", "horas", "notificaciones", "intentos_acceso",
    }


def test_rol_invalido_rechazado(db):
    with pytest.raises(sqlite3.IntegrityError):
        crear_usuario(db, rol="admin")


def test_estado_invalido_rechazado(db):
    prof = crear_usuario(db, rol="profesional")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO horas (profesional_id, inicio, estado) VALUES (?, ?, ?)",
            (prof, AHORA, "cancelada"),
        )


def test_email_duplicado_rechazado(db):
    crear_usuario(db, email="x@example.cl")
    with pytest.raises(sqlite3.IntegrityError):
        crear_usuario(db, email="x@example.cl")


def test_claves_foraneas_se_hacen_cumplir(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO horas (profesional_id, inicio) VALUES (?, ?)", (999, AHORA)
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO notificaciones (usuario_id, tipo, mensaje, creada_en)"
            " VALUES (?, ?, ?, ?)",
            (999, "confirmacion", "hola", AHORA),
        )


def test_valores_por_defecto(db):
    prof = crear_usuario(db, rol="profesional")
    db.execute("INSERT INTO horas (profesional_id, inicio) VALUES (?, ?)", (prof, AHORA))
    db.execute(
        "INSERT INTO notificaciones (usuario_id, tipo, mensaje, creada_en)"
        " VALUES (?, ?, ?, ?)",
        (prof, "confirmacion", "hola", AHORA),
    )
    hora = db.execute("SELECT * FROM horas").fetchone()
    assert hora["duracion_min"] == 50
    assert hora["estado"] == "libre"
    assert hora["recordatorio_enviado"] == 0
    assert hora["paciente_id"] is None
    assert hora["reservada_en"] is None
    assert db.execute("SELECT leida FROM notificaciones").fetchone()["leida"] == 0


# (nombre, tipo, notnull, valor por defecto, pk) tal como lo entrega PRAGMA table_info.
COLUMNAS_ESPERADAS = {
    "usuarios": [
        ("id", "INTEGER", 0, None, 1),
        ("nombre", "TEXT", 1, None, 0),
        ("email", "TEXT", 1, None, 0),
        ("password_hash", "TEXT", 1, None, 0),
        ("rol", "TEXT", 1, None, 0),
        ("creado_en", "TEXT", 1, None, 0),
        ("sesion_version", "INTEGER", 1, "0", 0),
    ],
    "horas": [
        ("id", "INTEGER", 0, None, 1),
        ("profesional_id", "INTEGER", 1, None, 0),
        ("inicio", "TEXT", 1, None, 0),
        ("duracion_min", "INTEGER", 1, "50", 0),
        ("estado", "TEXT", 1, "'libre'", 0),
        ("paciente_id", "INTEGER", 0, None, 0),
        ("reservada_en", "TEXT", 0, None, 0),
        ("recordatorio_enviado", "INTEGER", 1, "0", 0),
    ],
    "notificaciones": [
        ("id", "INTEGER", 0, None, 1),
        ("usuario_id", "INTEGER", 1, None, 0),
        ("tipo", "TEXT", 1, None, 0),
        ("mensaje", "TEXT", 1, None, 0),
        ("hora_id", "INTEGER", 0, None, 0),
        ("leida", "INTEGER", 1, "0", 0),
        ("creada_en", "TEXT", 1, None, 0),
    ],
    "intentos_acceso": [
        ("id", "INTEGER", 0, None, 1),
        ("accion", "TEXT", 1, None, 0),
        ("ambito", "TEXT", 1, None, 0),
        ("clave", "TEXT", 1, None, 0),
        ("instante", "INTEGER", 1, None, 0),
    ],
}


def test_comando_init_db(app):
    resultado = app.test_cli_runner().invoke(args=["init-db"])
    assert resultado.exit_code == 0
    with sqlite3.connect(app.config["DATABASE"]) as conn:
        tablas = {
            f[0]
            for f in conn.execute(
                "SELECT name FROM sqlite_master"
                " WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert tablas == set(COLUMNAS_ESPERADAS)
        for tabla, esperadas in COLUMNAS_ESPERADAS.items():
            # table_info: (cid, name, type, notnull, dflt_value, pk)
            reales = [
                (c[1], c[2], c[3], c[4], c[5])
                for c in conn.execute(f"PRAGMA table_info({tabla})")
            ]
            assert reales == esperadas, tabla


def test_init_db_no_borra_datos_existentes(app):
    runner = app.test_cli_runner()
    runner.invoke(args=["init-db"])
    with app.app_context():
        db = get_db()
        crear_usuario(db)
        db.commit()
    assert runner.invoke(args=["init-db"]).exit_code == 0
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 1


# --- T-08d: índice y columna nuevos (D-022, D-023) y D-006 ---------------------------

def test_init_db_crea_el_indice_un_solo_profesional(db):
    filas = db.execute(
        "SELECT name, tbl_name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    assert sorted((f["name"], f["tbl_name"]) for f in filas) == [
        ("intentos_acceso_clave", "intentos_acceso"),
        ("intentos_acceso_instante", "intentos_acceso"),
        ("un_solo_profesional", "usuarios"),
    ]


def test_init_db_dos_veces_no_falla_por_el_indice(app):
    runner = app.test_cli_runner()
    assert runner.invoke(args=["init-db"]).exit_code == 0
    assert runner.invoke(args=["init-db"]).exit_code == 0


# --- T-14b (D-050): `init-db` sobre bases de esquemas anteriores y `PRAGMA user_version` ------------
# Los .sql son `git show <commit>:app/schema.sql` tal cual: 748f18e (T-02, sin restricciones),
# df7a71f (antes de T-08d: sin `sesion_version` ni `un_solo_profesional`) y f06bdb5 (antes de
# T-14a: sin `intentos_acceso`).

from pathlib import Path  # noqa: E402

ANTIGUOS = Path(__file__).parent / "esquemas_antiguos"


def base_antigua(app, commit, usuarios=(("Dr. Pro", "pro@example.cl", "profesional"), ("Ana", "ana@example.cl", "paciente"))):
    conexion = sqlite3.connect(app.config["DATABASE"])
    conexion.executescript((ANTIGUOS / f"{commit}.sql").read_text(encoding="utf-8"))
    for nombre, email, rol in usuarios:
        conexion.execute(
            "INSERT INTO usuarios (nombre, email, password_hash, rol, creado_en) VALUES (?, ?, 'h', ?, ?)",
            (nombre, email, rol, AHORA),
        )
    conexion.commit()
    conexion.close()


def volcado(app):
    """Todo lo que hay en la base: esquema y filas, para comparar antes y después."""
    with sqlite3.connect(app.config["DATABASE"]) as conn:
        return (
            sorted(conn.execute("SELECT type, name, sql FROM sqlite_master").fetchall()),
            conn.execute("PRAGMA user_version").fetchone()[0],
            {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
             for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()},
        )


def user_version(app):
    with sqlite3.connect(app.config["DATABASE"]) as conn:
        return conn.execute("PRAGMA user_version").fetchone()[0]


def tablas_e_indices(app):
    with sqlite3.connect(app.config["DATABASE"]) as conn:
        return {f[0] for f in conn.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}


def test_una_base_nueva_queda_con_la_version_del_esquema(app):
    r = app.test_cli_runner().invoke(args=["init-db"])
    assert r.exit_code == 0 and "Base de datos inicializada." in r.output
    assert user_version(app) == modulo_db.VERSION_ESQUEMA >= 1


def test_el_esquema_actual_no_tiene_avisos_ni_acciones(app):
    runner = app.test_cli_runner()
    runner.invoke(args=["init-db"])
    r = runner.invoke(args=["init-db"])
    assert r.exit_code == 0 and r.output.strip() == "Base de datos inicializada."


@pytest.mark.parametrize("commit", ["f06bdb5", "df7a71f", "748f18e"])
def test_init_db_completa_una_base_anterior_sin_borrar_ni_alterar_los_datos(app, commit):
    base_antigua(app, commit)
    with sqlite3.connect(app.config["DATABASE"]) as conn:
        antes = conn.execute("SELECT id, nombre, email, password_hash, rol, creado_en FROM usuarios ORDER BY id").fetchall()
        assert user_version(app) == 0
    r = app.test_cli_runner().invoke(args=["init-db"])
    assert r.exit_code == 0, r.output
    assert "Base de datos actualizada" in r.output
    with sqlite3.connect(app.config["DATABASE"]) as conn:
        assert conn.execute("SELECT id, nombre, email, password_hash, rol, creado_en FROM usuarios ORDER BY id").fetchall() == antes
        assert [c[1] for c in conn.execute("PRAGMA table_info(usuarios)")][-1] == "sesion_version"
        assert {x[0] for x in conn.execute("SELECT sesion_version FROM usuarios")} == {0}
    assert {"intentos_acceso", "intentos_acceso_clave", "intentos_acceso_instante", "un_solo_profesional"} <= tablas_e_indices(app)
    assert user_version(app) == modulo_db.VERSION_ESQUEMA


def test_init_db_dice_que_agrego_y_la_segunda_vez_no_cambia_nada(app):
    base_antigua(app, "df7a71f")
    runner = app.test_cli_runner()
    primera = runner.invoke(args=["init-db"])
    assert "se agregó la columna usuarios.sesion_version" in primera.output
    assert "se creó la tabla intentos_acceso" in primera.output
    assert "se creó el índice un_solo_profesional" in primera.output
    despues = volcado(app)
    segunda = runner.invoke(args=["init-db"])
    assert segunda.output.strip() == "Base de datos inicializada."
    assert volcado(app) == despues


def test_init_db_nunca_toca_las_filas_de_las_demas_tablas(app):
    base_antigua(app, "f06bdb5")
    conexion = sqlite3.connect(app.config["DATABASE"])
    conexion.execute("INSERT INTO horas (profesional_id, inicio) VALUES (1, '2027-03-01T10:00:00')")
    conexion.execute(
        "UPDATE horas SET estado='reservada', paciente_id=2, reservada_en='2026-10-08T12:00:00-03:00' WHERE id=1"
    )
    conexion.execute(
        "INSERT INTO notificaciones (usuario_id, tipo, mensaje, hora_id, creada_en)"
        " VALUES (2, 'confirmacion', 'hola', 1, '2026-10-08T12:00:00-03:00')"
    )
    conexion.commit()
    conexion.close()
    filas = lambda: {  # noqa: E731
        t: sqlite3.connect(app.config["DATABASE"]).execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
        for t in ("horas", "notificaciones")
    }
    antes = filas()
    assert app.test_cli_runner().invoke(args=["init-db"]).exit_code == 0
    assert filas() == antes


def test_con_dos_profesionales_init_db_se_detiene_con_un_mensaje_y_sin_cambiar_nada(app):
    base_antigua(app, "df7a71f", usuarios=(
        ("Pro Uno", "uno@example.cl", "profesional"), ("Pro Dos", "dos@example.cl", "profesional"),
    ))
    antes = volcado(app)
    r = app.test_cli_runner().invoke(args=["init-db"])
    assert r.exit_code == 1
    assert "2 profesionales" in r.output and "un_solo_profesional" in r.output and "No se cambió nada" in r.output
    assert "Traceback" not in r.output and not isinstance(r.exception, sqlite3.Error)
    assert volcado(app) == antes
    assert user_version(app) == 0


def test_una_tabla_de_un_esquema_anterior_se_avisa_y_no_se_toca(app):
    base_antigua(app, "748f18e")
    antes_horas = sqlite3.connect(app.config["DATABASE"]).execute(
        "SELECT sql FROM sqlite_master WHERE name = 'horas'"
    ).fetchone()
    r = app.test_cli_runner().invoke(args=["init-db"])
    assert r.exit_code == 0
    for tabla in ("usuarios", "horas"):
        assert f"Aviso: La tabla {tabla} se creó con un esquema anterior" in r.output
    # `notificaciones` de este esquema no tiene ON DELETE SET NULL: la cubre el aviso específico
    # (T-14c, ver tests/test_init_db_errores.py), no el genérico.
    assert "Aviso: La tabla notificaciones es de un esquema anterior a D-016" in r.output
    assert "intentos_acceso se creó" not in r.output  # la que se creó ahora está al día
    assert "no reconstruye tablas existentes (D-006)" in r.output
    despues = sqlite3.connect(app.config["DATABASE"]).execute("SELECT sql FROM sqlite_master WHERE name = 'horas'").fetchone()
    assert despues == antes_horas  # la tabla no se reconstruyó


def test_una_base_del_esquema_de_t08d_en_adelante_no_da_avisos_de_tablas(app):
    base_antigua(app, "f06bdb5")
    r = app.test_cli_runner().invoke(args=["init-db"])
    assert "Aviso" not in r.output


def test_si_el_script_falla_a_medias_no_queda_nada_a_medias(app, monkeypatch):
    """Todo va en una transacción: un error en la mitad deja la base como estaba."""
    base_antigua(app, "df7a71f")
    antes = volcado(app)
    real = modulo_db._texto_del_esquema
    monkeypatch.setattr(modulo_db, "_texto_del_esquema", lambda: real() + "\nCREATE TABLE horas (x);")
    r = app.test_cli_runner().invoke(args=["init-db"])
    assert r.exit_code != 0
    assert volcado(app) == antes


def test_una_base_con_una_version_mas_nueva_se_avisa_y_no_se_baja(app):
    app.test_cli_runner().invoke(args=["init-db"])
    with sqlite3.connect(app.config["DATABASE"]) as conn:
        conn.execute(f"PRAGMA user_version = {modulo_db.VERSION_ESQUEMA + 5}")
    r = app.test_cli_runner().invoke(args=["init-db"])
    assert r.exit_code == 0 and "versión más nueva" in r.output
    assert user_version(app) == modulo_db.VERSION_ESQUEMA + 5


# --- login y registro con una base anterior: mensaje claro, no 500 con traza (T-14a R-09) ----------

from tests.test_seguridad import extraer_token  # noqa: E402


def _post(client, ruta, **datos):
    token = extraer_token(client.get(ruta).text)
    return client.post(ruta, data={"csrf_token": token, **datos})


@pytest.mark.parametrize("commit", ["f06bdb5", "df7a71f", "748f18e"])
def test_login_y_registro_con_una_base_anterior_responden_con_un_mensaje_claro(app, client, caplog, commit):
    base_antigua(app, commit)
    for ruta, datos in (
        ("/login", {"email": "ana@example.cl", "password": "clave-larga-1"}),
        ("/registro", {"nombre": "Beto", "email": "beto@example.cl", "password": "clave-larga-1"}),
    ):
        with caplog.at_level("ERROR"):
            r = _post(client, ruta, **datos)
        assert r.status_code == 503, (ruta, r.status_code)
        assert "versión anterior" in r.text and "flask --app app init-db" in r.text
        assert "Traceback" not in r.text and "sqlite3" not in r.text and "no such" not in r.text
    assert any("init-db" in m and "PRAGMA user_version = 0" in m for m in caplog.messages)


def test_la_base_anterior_no_se_modifica_al_responder(app, client):
    base_antigua(app, "df7a71f")
    antes = volcado(app)
    _post(client, "/login", email="ana@example.cl", password="clave-larga-1")
    assert volcado(app) == antes


def test_con_una_base_anterior_una_sesion_ya_abierta_tampoco_da_500(app, client):
    base_antigua(app, "748f18e")
    with client.session_transaction() as s:
        s["usuario_id"], s["sesion_version"] = 2, 0
    r = client.get("/paciente")
    assert r.status_code == 503 and "versión anterior" in r.text


def test_tras_init_db_login_y_registro_funcionan_con_los_datos_de_antes(app, client):
    from werkzeug.security import generate_password_hash

    base_antigua(app, "df7a71f")
    with sqlite3.connect(app.config["DATABASE"]) as conn:
        conn.execute("UPDATE usuarios SET password_hash = ? WHERE email = 'ana@example.cl'", (generate_password_hash("clave-larga-1"),))
    assert _post(client, "/login", email="ana@example.cl", password="clave-larga-1").status_code == 503
    assert app.test_cli_runner().invoke(args=["init-db"]).exit_code == 0
    r = _post(client, "/login", email="ana@example.cl", password="clave-larga-1")
    assert r.status_code == 302 and r.headers["Location"] == "/paciente"
    assert _post(client, "/registro", nombre="Beto", email="beto@example.cl", password="clave-larga-1").status_code == 302


def test_un_no_such_column_con_la_base_al_dia_sigue_siendo_un_error_del_programa(app, client):
    """No se disfraza un bug de «base anterior»: con `user_version` actual es un 500."""
    app.test_cli_runner().invoke(args=["init-db"])
    with app.app_context():
        assert modulo_db.es_esquema_antiguo(sqlite3.OperationalError("no such column: x")) is False
        assert modulo_db.es_esquema_antiguo(sqlite3.OperationalError("disk I/O error")) is False
        assert modulo_db.es_esquema_antiguo(ValueError("no such table: x")) is False


def test_es_esquema_antiguo_nunca_lanza_aunque_la_base_no_se_pueda_leer(app, monkeypatch):
    with app.app_context():
        monkeypatch.setattr(modulo_db, "version_esquema", lambda db: (_ for _ in ()).throw(sqlite3.OperationalError("disk I/O error")))
        assert modulo_db.es_esquema_antiguo(sqlite3.OperationalError("no such table: x")) is False
