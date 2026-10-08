"""Restricciones del esquema (T-02c, D-007): se prueban directamente contra SQLite,
sin pasar por la aplicación, para que fallen si se quita la restricción de schema.sql."""
import sqlite3

import pytest

from app.db import get_db, init_db

AHORA = "2026-10-07T10:00:00"
RESERVADA_EN = "2026-10-07T09:00:00"


@pytest.fixture
def db(app):
    with app.app_context():
        init_db()
        yield get_db()


def crear_usuario(db, email="a@example.cl", rol="paciente"):
    return db.execute(
        "INSERT INTO usuarios (nombre, email, password_hash, rol, creado_en)"
        " VALUES (?, ?, ?, ?, ?)",
        ("Ana", email, "hash", rol, AHORA),
    ).lastrowid


@pytest.fixture
def ids(db):
    return {
        "prof": crear_usuario(db, "prof@example.cl", "profesional"),
        "pac": crear_usuario(db, "pac@example.cl", "paciente"),
    }


def insertar_hora(db, **campos):
    """Inserta una hora; los campos dados reemplazan a los de una hora libre válida."""
    valores = {"profesional_id": 1, "inicio": "2026-10-20T10:00:00"}
    valores.update(campos)
    columnas = ", ".join(valores)
    marcas = ", ".join("?" for _ in valores)
    return db.execute(
        f"INSERT INTO horas ({columnas}) VALUES ({marcas})", tuple(valores.values())
    ).lastrowid


def insertar_notificacion(db, **campos):
    valores = {
        "usuario_id": 1,
        "tipo": "confirmacion",
        "mensaje": "hola",
        "creada_en": AHORA,
    }
    valores.update(campos)
    columnas = ", ".join(valores)
    marcas = ", ".join("?" for _ in valores)
    return db.execute(
        f"INSERT INTO notificaciones ({columnas}) VALUES ({marcas})",
        tuple(valores.values()),
    ).lastrowid


def rechazada(accion, fragmento):
    """Exige un IntegrityError de la base cuyo mensaje contenga `fragmento`."""
    with pytest.raises(sqlite3.IntegrityError) as info:
        accion()
    assert fragmento in str(info.value)


# --- A: coherencia de la reserva -------------------------------------------------

def test_hora_libre_sin_paciente_ni_reservada_en_aceptada(db, ids):
    insertar_hora(db, profesional_id=ids["prof"])


def test_hora_reservada_con_paciente_y_reservada_en_aceptada(db, ids):
    insertar_hora(
        db,
        profesional_id=ids["prof"],
        estado="reservada",
        paciente_id=ids["pac"],
        reservada_en=RESERVADA_EN,
    )


@pytest.mark.parametrize(
    "campos",
    [
        {"estado": "reservada", "reservada_en": RESERVADA_EN},  # reservada sin paciente
        {"estado": "reservada", "paciente_id": "pac"},  # reservada sin reservada_en
        {"estado": "reservada"},  # reservada sin nada
        {"estado": "libre", "paciente_id": "pac"},  # libre con paciente
        {"estado": "libre", "reservada_en": RESERVADA_EN},  # libre con reservada_en
        {"estado": "libre", "paciente_id": "pac", "reservada_en": RESERVADA_EN},
    ],
    ids=[
        "reservada-sin-paciente",
        "reservada-sin-reservada_en",
        "reservada-sin-nada",
        "libre-con-paciente",
        "libre-con-reservada_en",
        "libre-con-ambos",
    ],
)
def test_hora_incoherente_rechazada(db, ids, campos):
    campos = {k: (ids[v] if v == "pac" else v) for k, v in campos.items()}
    rechazada(
        lambda: insertar_hora(db, profesional_id=ids["prof"], **campos),
        "CHECK constraint failed",
    )


def test_reservar_con_el_update_atomico_funciona(db, ids):
    hora = insertar_hora(db, profesional_id=ids["prof"])
    cur = db.execute(
        "UPDATE horas SET estado='reservada', paciente_id=?, reservada_en=?"
        " WHERE id=? AND estado='libre'",
        (ids["pac"], RESERVADA_EN, hora),
    )
    assert cur.rowcount == 1


def test_cancelar_limpiando_paciente_y_reservada_en_funciona(db, ids):
    hora = insertar_hora(
        db,
        profesional_id=ids["prof"],
        estado="reservada",
        paciente_id=ids["pac"],
        reservada_en=RESERVADA_EN,
    )
    cur = db.execute(
        "UPDATE horas SET estado='libre', paciente_id=NULL, reservada_en=NULL"
        " WHERE id=?",
        (hora,),
    )
    assert cur.rowcount == 1
    fila = db.execute("SELECT * FROM horas WHERE id=?", (hora,)).fetchone()
    assert (fila["estado"], fila["paciente_id"], fila["reservada_en"]) == (
        "libre",
        None,
        None,
    )


def test_cancelar_sin_limpiar_paciente_es_rechazado(db, ids):
    hora = insertar_hora(
        db,
        profesional_id=ids["prof"],
        estado="reservada",
        paciente_id=ids["pac"],
        reservada_en=RESERVADA_EN,
    )
    rechazada(
        lambda: db.execute("UPDATE horas SET estado='libre' WHERE id=?", (hora,)),
        "CHECK constraint failed",
    )
    rechazada(
        lambda: db.execute(
            "UPDATE horas SET estado='libre', paciente_id=NULL WHERE id=?", (hora,)
        ),
        "CHECK constraint failed",
    )


# --- B: tipo de notificación ----------------------------------------------------

@pytest.mark.parametrize("tipo", ["confirmacion", "recordatorio", "cancelacion"])
def test_tipo_de_notificacion_valido_aceptado(db, ids, tipo):
    insertar_notificacion(db, usuario_id=ids["pac"], tipo=tipo)


@pytest.mark.parametrize("tipo", ["basura", "", "Confirmacion", "confirmación"])
def test_tipo_de_notificacion_invalido_rechazado(db, ids, tipo):
    rechazada(
        lambda: insertar_notificacion(db, usuario_id=ids["pac"], tipo=tipo),
        "CHECK constraint failed",
    )


# --- C: valores de dominio ------------------------------------------------------

def test_duracion_positiva_aceptada(db, ids):
    insertar_hora(db, profesional_id=ids["prof"], duracion_min=1)


@pytest.mark.parametrize("duracion", [0, -50])
def test_duracion_cero_o_negativa_rechazada(db, ids, duracion):
    rechazada(
        lambda: insertar_hora(db, profesional_id=ids["prof"], duracion_min=duracion),
        "CHECK constraint failed",
    )


@pytest.mark.parametrize("valor", [0, 1])
def test_recordatorio_enviado_0_o_1_aceptado(db, ids, valor):
    insertar_hora(db, profesional_id=ids["prof"], recordatorio_enviado=valor)


@pytest.mark.parametrize("valor", [7, 2, -1])
def test_recordatorio_enviado_fuera_de_0_1_rechazado(db, ids, valor):
    rechazada(
        lambda: insertar_hora(db, profesional_id=ids["prof"], recordatorio_enviado=valor),
        "CHECK constraint failed",
    )


@pytest.mark.parametrize("valor", [0, 1])
def test_leida_0_o_1_aceptada(db, ids, valor):
    insertar_notificacion(db, usuario_id=ids["pac"], leida=valor)


@pytest.mark.parametrize("valor", [2, -1])
def test_leida_fuera_de_0_1_rechazada(db, ids, valor):
    rechazada(
        lambda: insertar_notificacion(db, usuario_id=ids["pac"], leida=valor),
        "CHECK constraint failed",
    )


# --- D: UNIQUE (profesional_id, inicio) -----------------------------------------

def test_mismo_inicio_y_mismo_profesional_rechazado(db, ids):
    insertar_hora(db, profesional_id=ids["prof"], inicio="2026-10-20T10:00:00")
    rechazada(
        lambda: insertar_hora(db, profesional_id=ids["prof"], inicio="2026-10-20T10:00:00"),
        "UNIQUE constraint failed: horas.profesional_id, horas.inicio",
    )


def test_mismo_inicio_con_otro_profesional_aceptado(db, ids):
    otro = crear_usuario(db, "otro@example.cl", "profesional")
    insertar_hora(db, profesional_id=ids["prof"], inicio="2026-10-20T10:00:00")
    insertar_hora(db, profesional_id=otro, inicio="2026-10-20T10:00:00")


def test_mismo_profesional_con_otro_inicio_aceptado(db, ids):
    insertar_hora(db, profesional_id=ids["prof"], inicio="2026-10-20T10:00:00")
    insertar_hora(db, profesional_id=ids["prof"], inicio="2026-10-20T11:00:00")


def test_el_solape_parcial_no_lo_controla_el_esquema(db, ids):
    """Regla §4.3 sigue en la aplicación (T-05): el esquema solo impide inicios idénticos."""
    insertar_hora(db, profesional_id=ids["prof"], inicio="2026-10-20T10:00:00")
    insertar_hora(db, profesional_id=ids["prof"], inicio="2026-10-20T10:30:00")


# --- E: email sin distinguir mayúsculas -----------------------------------------

def test_email_con_otras_mayusculas_rechazado_por_la_base(db):
    crear_usuario(db, "ana@example.cl")
    # Directo contra SQLite: no pasa por normalizar_email() ni por la aplicación.
    rechazada(
        lambda: crear_usuario(db, "ANA@Example.CL"),
        "UNIQUE constraint failed: usuarios.email",
    )


def test_email_distinto_aceptado(db):
    crear_usuario(db, "ana@example.cl")
    crear_usuario(db, "ana2@example.cl")
    assert db.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 2


def test_busqueda_por_email_ignora_mayusculas_ascii(db):
    uid = crear_usuario(db, "ana@example.cl")
    fila = db.execute("SELECT id FROM usuarios WHERE email = ?", ("ANA@EXAMPLE.CL",))
    assert fila.fetchone()["id"] == uid


def test_nocase_solo_cubre_ascii(db):
    """Limitación documentada en D-007/E: no sustituye a normalizar_email()."""
    crear_usuario(db, "é@example.cl")
    crear_usuario(db, "É@example.cl")


# --- NOT NULL: cada columna que lo declara --------------------------------------

def _usuario(db, **campos):
    valores = {
        "nombre": "Ana",
        "email": "nn@example.cl",
        "password_hash": "h",
        "rol": "paciente",
        "creado_en": AHORA,
    }
    valores.update(campos)
    columnas = ", ".join(valores)
    marcas = ", ".join("?" for _ in valores)
    db.execute(
        f"INSERT INTO usuarios ({columnas}) VALUES ({marcas})", tuple(valores.values())
    )


COLUMNAS_NOT_NULL = {
    "usuarios": ["nombre", "email", "password_hash", "rol", "creado_en"],
    "horas": [
        "profesional_id",
        "inicio",
        "duracion_min",
        "estado",
        "recordatorio_enviado",
    ],
    "notificaciones": ["usuario_id", "tipo", "mensaje", "leida", "creada_en"],
}
CASOS_NOT_NULL = [(t, c) for t, cols in COLUMNAS_NOT_NULL.items() for c in cols]


@pytest.mark.parametrize("tabla,columna", CASOS_NOT_NULL)
def test_not_null_rechaza_null(db, ids, tabla, columna):
    """Una fila válida se acepta; la misma con NULL en `columna` la rechaza la base."""
    if tabla == "usuarios":
        _usuario(db)  # control: sin NULL es válida
        db.execute("DELETE FROM usuarios WHERE email = 'nn@example.cl'")
        accion = lambda: _usuario(db, **{columna: None})
    elif tabla == "horas":
        insertar_hora(db, profesional_id=ids["prof"], inicio="2026-10-21T10:00:00")
        accion = lambda: insertar_hora(
            db, **{"profesional_id": ids["prof"], columna: None}
        )
    else:
        insertar_notificacion(db, usuario_id=ids["pac"])
        accion = lambda: insertar_notificacion(
            db, **{"usuario_id": ids["pac"], columna: None}
        )
    rechazada(accion, f"NOT NULL constraint failed: {tabla}.{columna}")


@pytest.mark.parametrize("tabla,columna", CASOS_NOT_NULL)
def test_table_info_declara_not_null(db, tabla, columna):
    info = {f["name"]: f for f in db.execute(f"PRAGMA table_info({tabla})")}
    assert info[columna]["notnull"] == 1


def test_columnas_opcionales_aceptan_null(db, ids):
    """paciente_id, reservada_en y hora_id son NULL a propósito."""
    insertar_hora(db, profesional_id=ids["prof"])
    insertar_notificacion(db, usuario_id=ids["pac"], hora_id=None)


# --- Claves foráneas ------------------------------------------------------------

def _hora_reservada(db, ids, **campos):
    valores = {
        "profesional_id": ids["prof"],
        "estado": "reservada",
        "paciente_id": ids["pac"],
        "reservada_en": RESERVADA_EN,
    }
    valores.update(campos)
    return insertar_hora(db, **valores)


def test_fk_horas_profesional_id(db, ids):
    rechazada(
        lambda: insertar_hora(db, profesional_id=999), "FOREIGN KEY constraint failed"
    )


def test_fk_horas_paciente_id(db, ids):
    # La hora es coherente con el CHECK (reservada con paciente y fecha): solo falla la FK.
    rechazada(
        lambda: _hora_reservada(db, ids, paciente_id=999),
        "FOREIGN KEY constraint failed",
    )


def test_fk_notificaciones_usuario_id(db, ids):
    rechazada(
        lambda: insertar_notificacion(db, usuario_id=999),
        "FOREIGN KEY constraint failed",
    )


def test_fk_notificaciones_hora_id(db, ids):
    rechazada(
        lambda: insertar_notificacion(db, usuario_id=ids["pac"], hora_id=999),
        "FOREIGN KEY constraint failed",
    )


def test_referencias_existentes_aceptadas(db, ids):
    hora = _hora_reservada(db, ids)
    insertar_notificacion(db, usuario_id=ids["pac"], hora_id=hora)


@pytest.mark.parametrize(
    "tabla,columna,destino",
    [
        ("horas", "profesional_id", "usuarios"),
        ("horas", "paciente_id", "usuarios"),
        ("notificaciones", "usuario_id", "usuarios"),
        ("notificaciones", "hora_id", "horas"),
    ],
)
def test_foreign_key_list_declara_cada_fk(db, tabla, columna, destino):
    fks = {(f["from"], f["table"], f["to"]) for f in db.execute(
        f"PRAGMA foreign_key_list({tabla})"
    )}
    assert (columna, destino, "id") in fks
