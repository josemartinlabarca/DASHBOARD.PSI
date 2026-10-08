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


# Fragmentos del mensaje de SQLite: indica QUÉ restricción falló (el texto de la
# expresión), para que un rechazo por otro CHECK no pase por bueno (R-04).
CHECK_COHERENCIA = "CHECK constraint failed: (estado = 'libre' AND paciente_id IS NULL"
CHECK_TIPO = "CHECK constraint failed: tipo IN ('confirmacion', 'recordatorio', 'cancelacion')"
CHECK_DURACION = "CHECK constraint failed: duracion_min > 0"
CHECK_RECORDATORIO = "CHECK constraint failed: recordatorio_enviado IN (0, 1)"
CHECK_LEIDA = "CHECK constraint failed: leida IN (0, 1)"
CHECK_INICIO = "CHECK constraint failed: inicio GLOB "
CHECK_ROL = "CHECK constraint failed: rol IN ('paciente', 'profesional')"
CHECK_ESTADO = "CHECK constraint failed: estado IN ('libre', 'reservada')"


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
        CHECK_COHERENCIA,
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
        CHECK_COHERENCIA,
    )
    rechazada(
        lambda: db.execute(
            "UPDATE horas SET estado='libre', paciente_id=NULL WHERE id=?", (hora,)
        ),
        CHECK_COHERENCIA,
    )


# --- B: tipo de notificación ----------------------------------------------------

@pytest.mark.parametrize("tipo", ["confirmacion", "recordatorio", "cancelacion"])
def test_tipo_de_notificacion_valido_aceptado(db, ids, tipo):
    insertar_notificacion(db, usuario_id=ids["pac"], tipo=tipo)


@pytest.mark.parametrize("tipo", ["basura", "", "Confirmacion", "confirmación"])
def test_tipo_de_notificacion_invalido_rechazado(db, ids, tipo):
    rechazada(
        lambda: insertar_notificacion(db, usuario_id=ids["pac"], tipo=tipo),
        CHECK_TIPO,
    )


# --- C: valores de dominio ------------------------------------------------------

def test_duracion_positiva_aceptada(db, ids):
    insertar_hora(db, profesional_id=ids["prof"], duracion_min=1)


@pytest.mark.parametrize("duracion", [0, -50])
def test_duracion_cero_o_negativa_rechazada(db, ids, duracion):
    rechazada(
        lambda: insertar_hora(db, profesional_id=ids["prof"], duracion_min=duracion),
        CHECK_DURACION,
    )


@pytest.mark.parametrize("valor", [0, 1])
def test_recordatorio_enviado_0_o_1_aceptado(db, ids, valor):
    insertar_hora(db, profesional_id=ids["prof"], recordatorio_enviado=valor)


@pytest.mark.parametrize("valor", [7, 2, -1])
def test_recordatorio_enviado_fuera_de_0_1_rechazado(db, ids, valor):
    rechazada(
        lambda: insertar_hora(db, profesional_id=ids["prof"], recordatorio_enviado=valor),
        CHECK_RECORDATORIO,
    )


@pytest.mark.parametrize("valor", [0, 1])
def test_leida_0_o_1_aceptada(db, ids, valor):
    insertar_notificacion(db, usuario_id=ids["pac"], leida=valor)


@pytest.mark.parametrize("valor", [2, -1])
def test_leida_fuera_de_0_1_rechazada(db, ids, valor):
    rechazada(
        lambda: insertar_notificacion(db, usuario_id=ids["pac"], leida=valor),
        CHECK_LEIDA,
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


# --- D-016: ON DELETE SET NULL en notificaciones.hora_id (T-02f) ----------------
# Estas pruebas dependen de que las claves foráneas estén ACTIVAS (get_db() hace
# PRAGMA foreign_keys = ON): con ellas apagadas, ON DELETE SET NULL no se ejecuta.

RESERVAR = (
    "UPDATE horas SET estado='reservada', paciente_id=?, reservada_en=?"
    " WHERE id=? AND estado='libre'"
)
CANCELAR = (
    "UPDATE horas SET estado='libre', paciente_id=NULL, reservada_en=NULL WHERE id=?"
)


def _notificaciones_de(db, hora):
    return db.execute(
        "SELECT id, usuario_id, tipo, mensaje, hora_id FROM notificaciones"
        " ORDER BY id"
    ).fetchall()


def test_las_pruebas_de_fk_corren_con_claves_foraneas_activas(db):
    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_reservar_cancelar_y_eliminar_la_hora_deja_notificaciones_con_hora_id_null(db, ids):
    hora = insertar_hora(db, profesional_id=ids["prof"])
    assert db.execute(RESERVAR, (ids["pac"], RESERVADA_EN, hora)).rowcount == 1
    insertar_notificacion(
        db, usuario_id=ids["pac"], tipo="confirmacion", mensaje="Reservada", hora_id=hora
    )
    insertar_notificacion(
        db, usuario_id=ids["prof"], tipo="confirmacion", mensaje="Te reservaron", hora_id=hora
    )
    assert db.execute(CANCELAR, (hora,)).rowcount == 1
    insertar_notificacion(
        db, usuario_id=ids["pac"], tipo="cancelacion", mensaje="Cancelada", hora_id=hora
    )
    insertar_notificacion(
        db, usuario_id=ids["prof"], tipo="cancelacion", mensaje="Te cancelaron", hora_id=hora
    )

    assert db.execute("DELETE FROM horas WHERE id=?", (hora,)).rowcount == 1

    filas = [tuple(f) for f in _notificaciones_de(db, hora)]
    assert filas == [
        (1, ids["pac"], "confirmacion", "Reservada", None),
        (2, ids["prof"], "confirmacion", "Te reservaron", None),
        (3, ids["pac"], "cancelacion", "Cancelada", None),
        (4, ids["prof"], "cancelacion", "Te cancelaron", None),
    ]
    assert db.execute("SELECT COUNT(*) FROM horas").fetchone()[0] == 0


def test_eliminar_hora_no_toca_notificaciones_de_otras_horas(db, ids):
    h1 = insertar_hora(db, profesional_id=ids["prof"], inicio="2026-10-20T10:00:00")
    h2 = insertar_hora(db, profesional_id=ids["prof"], inicio="2026-10-20T11:00:00")
    insertar_notificacion(db, usuario_id=ids["pac"], hora_id=h1)
    insertar_notificacion(db, usuario_id=ids["pac"], hora_id=h2)
    db.execute("DELETE FROM horas WHERE id=?", (h1,))
    assert [f["hora_id"] for f in _notificaciones_de(db, None)] == [None, h2]


def test_eliminar_hora_sin_notificaciones_funciona(db, ids):
    hora = insertar_hora(db, profesional_id=ids["prof"])
    assert db.execute("DELETE FROM horas WHERE id=?", (hora,)).rowcount == 1
    assert db.execute("SELECT COUNT(*) FROM horas").fetchone()[0] == 0


def test_eliminar_hora_reservada_con_notificaciones_tambien_deja_hora_id_null(db, ids):
    """El esquema lo permite. Que la aplicación prohíba eliminar una hora reservada
    (SPEC, US-5) es una regla de T-05, no de la base de datos."""
    hora = _hora_reservada(db, ids)
    insertar_notificacion(db, usuario_id=ids["pac"], mensaje="Reservada", hora_id=hora)
    assert db.execute("DELETE FROM horas WHERE id=?", (hora,)).rowcount == 1
    fila = _notificaciones_de(db, hora)[0]
    assert (fila["hora_id"], fila["mensaje"], fila["tipo"]) == (None, "Reservada", "confirmacion")


def test_sin_claves_foraneas_la_prueba_no_pasaria_por_casualidad(db, ids):
    """Control: con las FK desactivadas, ON DELETE SET NULL no actúa y hora_id queda
    apuntando a una hora que ya no existe. Por eso las pruebas anteriores exigen FK activas."""
    hora = insertar_hora(db, profesional_id=ids["prof"])
    insertar_notificacion(db, usuario_id=ids["pac"], hora_id=hora)
    db.commit()
    db.execute("PRAGMA foreign_keys = OFF")
    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 0  # realmente quedó apagado
    db.execute("DELETE FROM horas WHERE id=?", (hora,))
    assert _notificaciones_de(db, hora)[0]["hora_id"] == hora  # colgando


def test_el_esquema_declara_on_delete_set_null_solo_en_hora_id(db):
    reglas = {
        (tabla, f["from"]): f["on_delete"]
        for tabla in ("horas", "notificaciones")
        for f in db.execute(f"PRAGMA foreign_key_list({tabla})")
    }
    assert reglas == {
        ("horas", "profesional_id"): "NO ACTION",
        ("horas", "paciente_id"): "NO ACTION",
        ("notificaciones", "usuario_id"): "NO ACTION",
        ("notificaciones", "hora_id"): "SET NULL",
    }


def test_no_se_puede_eliminar_el_profesional_con_horas(db, ids):
    insertar_hora(db, profesional_id=ids["prof"])
    rechazada(
        lambda: db.execute("DELETE FROM usuarios WHERE id=?", (ids["prof"],)),
        "FOREIGN KEY constraint failed",
    )


def test_no_se_puede_eliminar_el_paciente_con_hora_reservada(db, ids):
    _hora_reservada(db, ids)
    rechazada(
        lambda: db.execute("DELETE FROM usuarios WHERE id=?", (ids["pac"],)),
        "FOREIGN KEY constraint failed",
    )


def test_no_se_puede_eliminar_el_usuario_con_notificaciones(db, ids):
    insertar_notificacion(db, usuario_id=ids["pac"])
    rechazada(
        lambda: db.execute("DELETE FROM usuarios WHERE id=?", (ids["pac"],)),
        "FOREIGN KEY constraint failed",
    )


def test_notificacion_con_hora_id_inexistente_sigue_rechazada(db, ids):
    rechazada(
        lambda: insertar_notificacion(db, usuario_id=ids["pac"], hora_id=999),
        "FOREIGN KEY constraint failed",
    )


# --- D-017: formato canónico de horas.inicio (T-02f) ----------------------------

CANONICO = "2026-12-01T10:00:00"

FORMATOS_DE_LA_REVISION = [
    "2026-12-01T10:00",
    "2026-12-01 10:00",
    "2026-12-01T10:00:00-03:00",
    "2026-12-01T10:00:00-04:00",
    "2026-12-01T10:00:00Z",
]
OTROS_FORMATOS_INVALIDOS = [
    "",
    "2026-12-01",
    " 2026-12-01T10:00:00",
    "2026-12-01T10:00:00 ",
    "2026-12-01T10:00:00.000",
    "2026-12-01T10:00:00.5",
    "2026-12-01T1O:00:00",  # letra O en lugar de cero
    "abcd-ef-ghTij:kl:mn",
    "2026-12-01t10:00:00",  # GLOB distingue mayúsculas: la T es literal
    "2026-12-01T10:00:000",  # un carácter de más al final
    "x2026-12-01T10:00:00",  # un carácter de más al principio
    "2026-12-01T10:00:0",  # un carácter de menos
    "26-12-01T10:00:00",
    "2026/12/01T10:00:00",
    "2026-12-01T10:00:00\n",  # salto de línea al final
    "\n2026-12-01T10:00:00",
    "2026-12-01\nT10:00:00",
    "2026-12-01\x00T10:00:00",  # NUL en medio
    "\x002026-12-01T10:00:00",  # NUL al principio
    "٢٠٢٦-١٢-٠١T١٠:٠٠:٠٠",  # dígitos árabe-índicos
    "２０２６-１２-０１T１０:００:００",  # dígitos de ancho completo
    "2026-12-01T10:00:00²",  # superíndice
]


@pytest.mark.parametrize("inicio", FORMATOS_DE_LA_REVISION)
def test_formato_de_la_revision_rechazado(db, ids, inicio):
    rechazada(
        lambda: insertar_hora(db, profesional_id=ids["prof"], inicio=inicio),
        CHECK_INICIO,
    )


@pytest.mark.parametrize("inicio", OTROS_FORMATOS_INVALIDOS)
def test_otro_formato_invalido_rechazado(db, ids, inicio):
    rechazada(
        lambda: insertar_hora(db, profesional_id=ids["prof"], inicio=inicio),
        CHECK_INICIO,
    )
    assert db.execute("SELECT COUNT(*) FROM horas").fetchone()[0] == 0


def test_inicio_que_no_es_texto_rechazado(db, ids):
    """Un número o un BLOB no encajan con el GLOB (se comparan como texto o no coinciden)."""
    for valor in (20261201, 2026.1201, b"2026-12-01T10:00:00"):
        with pytest.raises(sqlite3.IntegrityError):
            insertar_hora(db, profesional_id=ids["prof"], inicio=valor)


def test_formato_canonico_aceptado(db, ids):
    hora = insertar_hora(db, profesional_id=ids["prof"], inicio=CANONICO)
    assert db.execute("SELECT inicio FROM horas WHERE id=?", (hora,)).fetchone()[0] == CANONICO


def test_duplicado_en_formato_canonico_rechazado_por_la_unique(db, ids):
    insertar_hora(db, profesional_id=ids["prof"], inicio=CANONICO)
    rechazada(
        lambda: insertar_hora(db, profesional_id=ids["prof"], inicio=CANONICO),
        "UNIQUE constraint failed: horas.profesional_id, horas.inicio",
    )


def test_las_variantes_ya_no_eluden_la_unique(db, ids):
    """Antes de D-017 las cinco variantes de la revisión entraban junto al canónico."""
    insertar_hora(db, profesional_id=ids["prof"], inicio=CANONICO)
    for variante in FORMATOS_DE_LA_REVISION:
        with pytest.raises(sqlite3.IntegrityError):
            insertar_hora(db, profesional_id=ids["prof"], inicio=variante)
    assert db.execute("SELECT COUNT(*) FROM horas").fetchone()[0] == 1


def test_fecha_con_forma_valida_pero_inexistente_se_acepta_en_la_base(db, ids):
    """Limitación conocida (D-017): el CHECK valida la FORMA, no que la fecha exista.
    Mes 13, día 45 u hora 25 pasan la base de datos; la aplicación (T-05) debe
    validar que la fecha exista y no sea pasada antes de insertar."""
    for inicio in ("2026-13-45T25:61:61", "2026-02-31T00:00:00", "0000-00-00T00:00:00"):
        insertar_hora(db, profesional_id=ids["prof"], inicio=inicio)


def test_update_a_un_formato_invalido_tambien_se_rechaza(db, ids):
    hora = insertar_hora(db, profesional_id=ids["prof"], inicio=CANONICO)
    rechazada(
        lambda: db.execute(
            "UPDATE horas SET inicio='2026-12-01 10:00' WHERE id=?", (hora,)
        ),
        CHECK_INICIO,
    )


# --- D-018: el carácter nulo en horas.inicio (T-02g) ----------------------------

NULOS_RECHAZADOS = {
    "nul_al_final": CANONICO + "\x00",
    "nul_con_texto": CANONICO + "\x00basura",
    "nul_al_inicio": "\x00" + CANONICO,
    "nul_en_medio": "2026-12-01\x00T10:00:00",
    "nul_en_medio_de_la_hora": "2026-12-01T10:00\x00:00",
    "solo_prefijo_y_nul": "2026-12-01T10:00:00\x00",
    "nul_solo": "\x00",
}


@pytest.mark.parametrize("inicio", NULOS_RECHAZADOS.values(), ids=NULOS_RECHAZADOS.keys())
def test_inicio_con_nul_rechazado_por_el_check(db, ids, inicio):
    """D-018: GLOB corta en el NUL; `instr(inicio, char(0)) = 0` lo cierra."""
    rechazada(
        lambda: insertar_hora(db, profesional_id=ids["prof"], inicio=inicio),
        CHECK_INICIO,
    )
    assert db.execute("SELECT COUNT(*) FROM horas").fetchone()[0] == 0


def test_inicio_con_nul_no_elude_la_unique(db, ids):
    insertar_hora(db, profesional_id=ids["prof"], inicio=CANONICO)
    for inicio in (CANONICO + "\x00", CANONICO + "\x00basura"):
        rechazada(
            lambda: insertar_hora(db, profesional_id=ids["prof"], inicio=inicio),
            CHECK_INICIO,
        )
    assert db.execute("SELECT COUNT(*) FROM horas").fetchone()[0] == 1


def test_update_a_un_valor_con_nul_tambien_se_rechaza(db, ids):
    hora = insertar_hora(db, profesional_id=ids["prof"], inicio=CANONICO)
    rechazada(
        lambda: db.execute("UPDATE horas SET inicio=? WHERE id=?", (CANONICO + "\x00x", hora)),
        CHECK_INICIO,
    )
    assert db.execute("SELECT inicio FROM horas WHERE id=?", (hora,)).fetchone()[0] == CANONICO


def test_el_canonico_sigue_aceptado_junto_a_la_regla_del_nul(db, ids):
    hora = insertar_hora(db, profesional_id=ids["prof"], inicio=CANONICO)
    fila = db.execute("SELECT inicio, length(inicio) FROM horas WHERE id=?", (hora,)).fetchone()
    assert tuple(fila) == (CANONICO, 19)


# --- Cada posición del formato (hallazgo 5 de la revisión de T-02f) -------------

SEPARADORES = {4, 7, 10, 13, 16}


def _sustituciones_invalidas():
    for pos, caracter in enumerate(CANONICO):
        malos = ["/", "x", " "] if pos in SEPARADORES else ["x", "O", "*", "?"]
        for malo in malos:
            nombre = {"/": "barra", "x": "x", " ": "espacio", "O": "O", "*": "asterisco", "?": "interrogacion"}[malo]
            tipo = "separador" if pos in SEPARADORES else "digito"
            yield pytest.param(
                CANONICO[:pos] + malo + CANONICO[pos + 1 :],
                id=f"pos{pos:02d}-{tipo}-{caracter!r}-por-{nombre}",
            )


def test_el_canonico_tiene_19_posiciones():
    assert len(CANONICO) == 19


@pytest.mark.parametrize("inicio", list(_sustituciones_invalidas()))
def test_un_caracter_invalido_en_cualquier_posicion_es_rechazado(db, ids, inicio):
    rechazada(
        lambda: insertar_hora(db, profesional_id=ids["prof"], inicio=inicio),
        CHECK_INICIO,
    )
    assert db.execute("SELECT COUNT(*) FROM horas").fetchone()[0] == 0


COMODINES_Y_SEPARADORES = [
    "2026-12-01 10:00:00",  # espacio en lugar de T, con segundos
    "2026-12-01_10:00:00",
    "20*6-12-01T10:00:00",
    "*026-12-01T10:00:00",
    "2026-12-01T10:00:0?",
    "2026-12-01T10:00:??",
    "2026-12-01T10:00:0[0-9]",
    "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]",
    "2026-12-01T[0-9][0-9]:00:00",
    "2026-*",
    "*",
    "????-??-??T??:??:??",
    "20[0-9]6-12-01T10:00:00",
]


@pytest.mark.parametrize("inicio", COMODINES_Y_SEPARADORES)
def test_comodines_de_glob_y_otros_separadores_rechazados(db, ids, inicio):
    rechazada(
        lambda: insertar_hora(db, profesional_id=ids["prof"], inicio=inicio),
        CHECK_INICIO,
    )
    assert db.execute("SELECT COUNT(*) FROM horas").fetchone()[0] == 0


# --- Dígitos de borde en cada posición (ronda 2 de T-02g) --------------------------
# Un GLOB que rechazara un dígito legítimo (p. ej. `[0-8]` en vez de `[0-9]`) no lo
# detectaban las pruebas anteriores. Aquí cada posición de dígito se prueba con 0 y 9.
# La base solo comprueba la FORMA; que la fecha exista (mes 13, hora 25...) lo valida
# la aplicación en T-05.

POSICIONES_DE_DIGITO = [pos for pos in range(len(CANONICO)) if pos not in SEPARADORES]


def _digitos_de_borde():
    for pos in POSICIONES_DE_DIGITO:
        for digito in "90":
            yield pytest.param(
                CANONICO[:pos] + digito + CANONICO[pos + 1 :],
                id=f"pos{pos:02d}-{digito}",
            )


def test_hay_14_posiciones_de_digito():
    assert len(POSICIONES_DE_DIGITO) == 14


@pytest.mark.parametrize("inicio", list(_digitos_de_borde()))
def test_digito_de_borde_en_cada_posicion_se_acepta_en_la_base(db, ids, inicio):
    insertar_hora(db, profesional_id=ids["prof"], inicio=inicio)
    filas = db.execute("SELECT inicio FROM horas").fetchall()
    assert [f[0] for f in filas] == [inicio]


@pytest.mark.parametrize(
    "inicio",
    ["0000-00-00T00:00:00", "9999-99-99T99:99:99"],
    ids=["todo-ceros", "todo-nueves"],
)
def test_extremos_de_forma_valida_se_aceptan_en_la_base(db, ids, inicio):
    insertar_hora(db, profesional_id=ids["prof"], inicio=inicio)
    assert db.execute("SELECT inicio FROM horas").fetchone()[0] == inicio


# --- T-02e: el conjunto EXACTO de valores y el SQL exacto del esquema ----------------
# Las pruebas anteriores comprueban que lo inválido se rechaza, pero no que lo
# permitido sea exactamente lo aprobado: una restricción ampliada (más valores en un
# IN, un lower(), un tope superior) las dejaba en verde. Estas la fijan de dos
# maneras: valores vecinos y SQL de sqlite_master (si el esquema cambia a propósito,
# hay que actualizar el SQL esperado aquí).

def _sql(db, tabla):
    fila = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (tabla,)
    ).fetchone()
    return " ".join(fila["sql"].split())  # normaliza espacios y saltos de línea


SQL_ESPERADO = {
    "usuarios": (
        "CREATE TABLE usuarios ( id INTEGER PRIMARY KEY, nombre TEXT NOT NULL,"
        " email TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL,"
        " rol TEXT NOT NULL CHECK (rol IN ('paciente', 'profesional')),"
        " creado_en TEXT NOT NULL )"
    ),
    "horas": (
        "CREATE TABLE horas ( id INTEGER PRIMARY KEY,"
        " profesional_id INTEGER NOT NULL REFERENCES usuarios (id),"
        " inicio TEXT NOT NULL,"
        " duracion_min INTEGER NOT NULL DEFAULT 50 CHECK (duracion_min > 0),"
        " estado TEXT NOT NULL DEFAULT 'libre' CHECK (estado IN ('libre', 'reservada')),"
        " paciente_id INTEGER REFERENCES usuarios (id), reservada_en TEXT,"
        " recordatorio_enviado INTEGER NOT NULL DEFAULT 0"
        " CHECK (recordatorio_enviado IN (0, 1)),"
        " CHECK ( (estado = 'libre' AND paciente_id IS NULL AND reservada_en IS NULL)"
        " OR (estado = 'reservada' AND paciente_id IS NOT NULL"
        " AND reservada_en IS NOT NULL) ),"
        " CHECK (inicio GLOB"
        " '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]'"
        " AND instr(inicio, char(0)) = 0),"
        " UNIQUE (profesional_id, inicio) )"
    ),
    "notificaciones": (
        "CREATE TABLE notificaciones ( id INTEGER PRIMARY KEY,"
        " usuario_id INTEGER NOT NULL REFERENCES usuarios (id),"
        " tipo TEXT NOT NULL CHECK (tipo IN ('confirmacion', 'recordatorio', 'cancelacion')),"
        " mensaje TEXT NOT NULL,"
        " hora_id INTEGER REFERENCES horas (id) ON DELETE SET NULL,"
        " leida INTEGER NOT NULL DEFAULT 0 CHECK (leida IN (0, 1)),"
        " creada_en TEXT NOT NULL )"
    ),
}


@pytest.mark.parametrize("tabla", list(SQL_ESPERADO))
def test_el_sql_de_cada_tabla_es_exactamente_el_aprobado(db, tabla):
    assert _sql(db, tabla) == SQL_ESPERADO[tabla]


def test_no_hay_otros_objetos_en_la_base(db):
    """Sin triggers, vistas ni índices extra que cambien el comportamiento."""
    filas = db.execute(
        "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
    ).fetchall()
    assert {(f["type"], f["name"]) for f in filas} == {
        ("table", "usuarios"), ("table", "horas"), ("table", "notificaciones"),
    }


FK_ESPERADAS = {
    "horas": [
        ("usuarios", "paciente_id", "id", "NO ACTION", "NO ACTION", "NONE"),
        ("usuarios", "profesional_id", "id", "NO ACTION", "NO ACTION", "NONE"),
    ],
    "notificaciones": [
        ("horas", "hora_id", "id", "NO ACTION", "SET NULL", "NONE"),
        ("usuarios", "usuario_id", "id", "NO ACTION", "NO ACTION", "NONE"),
    ],
    "usuarios": [],
}


@pytest.mark.parametrize("tabla", list(FK_ESPERADAS))
def test_foreign_key_list_completo_incluido_on_update(db, tabla):
    """Compara la fila entera (table, from, to, on_update, on_delete, match)."""
    filas = sorted(
        (f["table"], f["from"], f["to"], f["on_update"], f["on_delete"], f["match"])
        for f in db.execute(f"PRAGMA foreign_key_list({tabla})")
    )
    assert filas == FK_ESPERADAS[tabla]


# Valores vecinos: lo que no está en la lista aprobada se rechaza POR ESE CHECK.

@pytest.mark.parametrize("rol", ["Paciente", "PROFESIONAL", "Profesional", " paciente", "admin", ""])
def test_rol_fuera_de_la_lista_exacta_rechazado_por_su_check(db, rol):
    rechazada(lambda: crear_usuario(db, rol=rol), CHECK_ROL)


@pytest.mark.parametrize("rol", ["paciente", "profesional"])
def test_rol_aprobado_aceptado(db, rol):
    crear_usuario(db, rol=rol)


@pytest.mark.parametrize(
    "estado", ["cancelada", "Libre", "RESERVADA", "otro", ""]
)
def test_estado_fuera_de_la_lista_exacta_rechazado_por_su_check(db, ids, estado):
    rechazada(
        lambda: insertar_hora(db, profesional_id=ids["prof"], estado=estado),
        CHECK_ESTADO,
    )


@pytest.mark.parametrize("tipo", ["otro", "Recordatorio", "cancelación", "confirmacion "])
def test_tipo_fuera_de_la_lista_exacta_rechazado_por_su_check(db, ids, tipo):
    rechazada(
        lambda: insertar_notificacion(db, usuario_id=ids["pac"], tipo=tipo),
        CHECK_TIPO,
    )


@pytest.mark.parametrize("duracion", [1, 50, 60, 480, 1440, 100000, 2**31, 2**62])
def test_duracion_sin_tope_superior(db, ids, duracion):
    """La única regla de duracion_min es ser > 0: no hay máximo en el esquema."""
    insertar_hora(db, profesional_id=ids["prof"], duracion_min=duracion)


def test_duracion_por_defecto_es_50(db, ids):
    hora = insertar_hora(db, profesional_id=ids["prof"])
    assert db.execute("SELECT duracion_min FROM horas WHERE id=?", (hora,)).fetchone()[0] == 50
