import sqlite3

import pytest

from app.db import get_db, init_db

AHORA = "2026-10-07T10:00:00"


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


def test_init_db_crea_las_tres_tablas(db):
    filas = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    assert {f["name"] for f in filas} == {"usuarios", "horas", "notificaciones"}


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
