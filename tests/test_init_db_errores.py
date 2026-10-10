"""`init-db` y `create-professional` ante un archivo de base inservible, una carrera y una base
antigua (T-14c, notas (a), (b) y (c) de la revisión de T-14b; D-052).

- Archivo que no es SQLite, base dañada, carpeta, carpeta inexistente, solo lectura, bloqueada:
  mensaje en español, código 1, sin traza y sin crear nada.
- Dos `init-db` a la vez: la decisión se toma DENTRO de `BEGIN IMMEDIATE`.
- Base de una versión más nueva: no se cambia nada (lo que dice el README).
- `notificaciones.hora_id` sin `ON DELETE SET NULL`: aviso con el procedimiento y, en la ruta de
  eliminar, un mensaje en español en lugar del 500.
- `create-professional` comprueba la base ANTES de pedir la contraseña.
"""
import os
import sqlite3
import threading
import time

import pytest

from app import create_app, profesional
from app import db as modulo_db
from tests.test_crear_profesional import ARGS
from tests.test_horas_libres import fijar_reloj
from tests.test_db import ANTIGUOS, base_antigua, tablas_e_indices, user_version, volcado
from tests.test_login import CLAVE, crear, iniciar
from tests.test_reservar import fila
from tests.test_seguridad import extraer_token

ENTRADA = f"{CLAVE}\n{CLAVE}\n"


def _app(ruta, **config):
    return create_app({"TESTING": True, "DATABASE": str(ruta), "DATABASE_TIMEOUT": 0.05, **config})


def _ejecutar(app, *args, entrada=None):
    return app.test_cli_runner().invoke(args=list(args), input=entrada)


def _sin_traza(r):
    assert "Traceback" not in r.output and "sqlite3" not in r.output and "OperationalError" not in r.output
    assert isinstance(r.exception, SystemExit) or r.exception is None, repr(r.exception)


def _dano(ruta):
    """Una base de verdad con la página del esquema pisada: 'database disk image is malformed'."""
    con = sqlite3.connect(ruta)
    con.executescript(modulo_db_schema())
    con.close()
    datos = bytearray(ruta.read_bytes())
    datos[100:300] = b"\xff" * 200
    ruta.write_bytes(bytes(datos))


def modulo_db_schema():
    with open(os.path.join(os.path.dirname(modulo_db.__file__), "schema.sql"), encoding="utf-8") as f:
        return f.read()


# ------------------------------------------------------------ archivos inservibles ----


def _texto(ruta):
    ruta.write_bytes(b"esto no es una base de datos de SQLite" * 50)


def _carpeta(ruta):
    ruta.mkdir()


CASOS_DE_ARCHIVO = [
    pytest.param("basura.db", _texto, "No se pudo leer la base de datos", "¿Es un archivo de SQLite?", id="no-es-sqlite"),
    pytest.param("danada.db", _dano, "está dañada", "Restaura una copia de respaldo", id="danada"),
    pytest.param("carpeta.db", _carpeta, "es una carpeta, no un archivo", "Revisa DATABASE", id="es-carpeta"),
    pytest.param("no/existe/x.db", None, "No existe la carpeta de la base de datos", "Revisa la variable DATABASE", id="carpeta-inexistente"),
]


@pytest.mark.parametrize("nombre,preparar,texto,pista", CASOS_DE_ARCHIVO)
def test_init_db_con_un_archivo_inservible_da_un_mensaje_codigo_1_y_no_toca_nada(tmp_path, nombre, preparar, texto, pista):
    ruta = tmp_path / nombre
    if preparar:
        preparar(ruta)
    antes = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    contenido = ruta.read_bytes() if ruta.is_file() else None
    r = _ejecutar(_app(ruta), "init-db")
    assert r.exit_code == 1, r.output
    assert texto in r.output and pista in r.output
    _sin_traza(r)
    assert sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")) == antes  # nada nuevo
    if contenido is not None:
        assert ruta.read_bytes() == contenido  # ni un byte cambiado


@pytest.mark.parametrize("nombre,preparar,texto,pista", CASOS_DE_ARCHIVO)
def test_create_professional_con_un_archivo_inservible_da_el_mismo_tipo_de_mensaje(tmp_path, nombre, preparar, texto, pista):
    ruta = tmp_path / nombre
    if preparar:
        preparar(ruta)
    r = _ejecutar(_app(ruta), "create-professional", *ARGS, entrada=ENTRADA)
    assert r.exit_code == 1, r.output
    assert texto in r.output
    _sin_traza(r)
    assert "Contraseña" not in r.output  # se comprueba antes de pedirla


def test_init_db_con_la_base_bloqueada_dice_que_esta_ocupada_y_no_cambia_nada(tmp_path):
    ruta = tmp_path / "b.db"
    app = _app(ruta)
    assert _ejecutar(app, "init-db").exit_code == 0
    antes = volcado_de(ruta)
    otra = sqlite3.connect(ruta, isolation_level=None)
    otra.execute("BEGIN IMMEDIATE")
    try:
        r = _ejecutar(app, "init-db")
    finally:
        otra.execute("ROLLBACK")
        otra.close()
    assert r.exit_code == 1 and "La base de datos está ocupada" in r.output and "vuelve a ejecutar" in r.output
    _sin_traza(r)
    assert volcado_de(ruta) == antes
    assert _ejecutar(app, "init-db").exit_code == 0  # liberada: funciona


def volcado_de(ruta):
    with sqlite3.connect(ruta) as con:
        return (
            sorted(con.execute("SELECT type, name, sql FROM sqlite_master").fetchall()),
            con.execute("PRAGMA user_version").fetchone()[0],
        )


def _error_de_sqlite(texto, codigo):
    error = sqlite3.OperationalError(texto)
    error.sqlite_errorcode = codigo
    return error


def test_una_base_de_solo_lectura_da_un_mensaje_claro_en_init_db_y_en_create_professional(tmp_path, monkeypatch):
    """Simulado con el código de SQLite (SQLITE_READONLY): el caso real se ve en la prueba de abajo."""
    ruta = tmp_path / "ro.db"
    app = _app(ruta)
    assert _ejecutar(app, "init-db").exit_code == 0

    def falla(db):
        raise _error_de_sqlite("attempt to write a readonly database", sqlite3.SQLITE_READONLY)

    monkeypatch.setattr(modulo_db, "inicializar", falla)
    r = _ejecutar(app, "init-db")
    assert r.exit_code == 1 and "No se puede escribir en la base de datos" in r.output and "solo lectura" in r.output
    _sin_traza(r)
    monkeypatch.undo()
    monkeypatch.setattr("app.auth.crear_usuario", lambda *a, **k: falla(None))
    r = _ejecutar(app, "create-professional", *ARGS, entrada=ENTRADA)
    assert r.exit_code == 1 and "No se puede escribir en la base de datos" in r.output
    _sin_traza(r)


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="root escribe en archivos de solo lectura")
def test_una_base_de_solo_lectura_real(tmp_path):
    ruta = tmp_path / "ro.db"
    app = _app(ruta)
    assert _ejecutar(app, "init-db").exit_code == 0
    ruta.chmod(0o444)
    try:
        for args in (("init-db",), ("create-professional", *ARGS)):
            r = _ejecutar(app, *args, entrada=ENTRADA)
            assert r.exit_code == 1 and "solo lectura" in r.output, r.output
            _sin_traza(r)
    finally:
        ruta.chmod(0o644)


@pytest.mark.parametrize(
    "texto,codigo,esperado",
    [
        ("attempt to write a readonly database", sqlite3.SQLITE_READONLY, "solo lectura"),
        ("attempt to write a readonly database", sqlite3.SQLITE_READONLY_DIRECTORY, "solo lectura"),
        ("file is not a database", sqlite3.SQLITE_NOTADB, "¿Es un archivo de SQLite?"),
        ("database disk image is malformed", sqlite3.SQLITE_CORRUPT, "está dañada"),
        ("unable to open database file", sqlite3.SQLITE_CANTOPEN, "No se pudo abrir la base de datos"),
        ("database is locked", sqlite3.SQLITE_BUSY, "está ocupada"),
        ("database table is locked", sqlite3.SQLITE_LOCKED, "está ocupada"),
        ("disk I/O error", sqlite3.SQLITE_IOERR, "Error de la base de datos: disk I/O error"),
    ],
)
def test_el_traductor_usa_el_codigo_de_sqlite(texto, codigo, esperado):
    mensaje = modulo_db.mensaje_de_error_sqlite(_error_de_sqlite(texto, codigo), "/x/a.db")
    assert esperado in mensaje


def test_el_traductor_sin_codigo_usa_el_texto_y_deja_pasar_los_errores_de_integridad():
    for texto, esperado in (("attempt to write a readonly database", "solo lectura"), ("file is not a database", "SQLite"),
                            ("database disk image is malformed", "dañada"), ("unable to open database file", "No se pudo abrir")):
        assert esperado in modulo_db.mensaje_de_error_sqlite(sqlite3.OperationalError(texto), "/x/a.db")
    with pytest.raises(sqlite3.IntegrityError):  # un bug del programa no se disfraza
        with modulo_db.errores_de_sqlite_como_mensaje("/x/a.db"):
            raise sqlite3.IntegrityError("NOT NULL constraint failed")


# ------------------------------------------------------- dos init-db a la vez ----


def _transaccion_ajena_que_ya_migro(ruta, sentencias_extra=()):
    """Otra conexión que retiene el bloqueo de escritura con la migración HECHA pero sin confirmar."""
    ajena = sqlite3.connect(ruta, isolation_level=None)
    ajena.execute("BEGIN IMMEDIATE")
    return ajena


def test_dos_init_db_simultaneos_el_segundo_decide_con_lo_que_dejo_el_primero(tmp_path):
    """El segundo `init-db` espera el bloqueo y recién entonces lee el estado: no repite el ALTER."""
    ruta = tmp_path / "carrera.db"
    app = _app(ruta, DATABASE_TIMEOUT=10)
    base_antigua(app, "df7a71f")
    ajena = _transaccion_ajena_que_ya_migro(ruta)
    ajena.execute("ALTER TABLE usuarios ADD COLUMN sesion_version INTEGER NOT NULL DEFAULT 0")
    for sentencia in modulo_db._sentencias(modulo_db_schema()):
        ajena.execute(sentencia)
    ajena.execute(f"PRAGMA user_version = {modulo_db.VERSION_ESQUEMA}")
    resultado = {}

    def segundo():
        try:
            with app.app_context():
                resultado["informe"] = modulo_db.inicializar(modulo_db.get_db())
        except BaseException as error:  # noqa: BLE001 - se informa al hilo principal
            resultado["error"] = error

    hilo = threading.Thread(target=segundo)
    hilo.start()
    time.sleep(0.4)  # el segundo ya está esperando el bloqueo de escritura
    assert hilo.is_alive()
    ajena.execute("COMMIT")
    ajena.close()
    hilo.join(10)
    assert "error" not in resultado, repr(resultado.get("error"))
    informe = resultado["informe"]
    assert informe.acciones == [] and informe.avisos == []  # no había nada más que hacer
    assert [c[1] for c in sqlite3.connect(ruta).execute("PRAGMA table_info(usuarios)")].count("sesion_version") == 1


def test_si_aparece_un_segundo_profesional_mientras_espera_se_detiene_con_el_mensaje_de_siempre(tmp_path):
    ruta = tmp_path / "carrera2.db"
    app = _app(ruta, DATABASE_TIMEOUT=10)
    base_antigua(app, "df7a71f", usuarios=(("Pro Uno", "uno@example.cl", "profesional"),))
    ajena = _transaccion_ajena_que_ya_migro(ruta)
    ajena.execute(
        "INSERT INTO usuarios (nombre, email, password_hash, rol, creado_en) VALUES ('Pro Dos', 'dos@example.cl', 'h', 'profesional', 'x')"
    )
    resultado = {}

    def segundo():
        try:
            with app.app_context():
                modulo_db.inicializar(modulo_db.get_db())
        except BaseException as error:  # noqa: BLE001
            resultado["error"] = error

    hilo = threading.Thread(target=segundo)
    hilo.start()
    time.sleep(0.4)
    ajena.execute("COMMIT")
    ajena.close()
    hilo.join(10)
    error = resultado.get("error")
    assert error is not None and type(error).__name__ == "ClickException", repr(error)
    assert "2 profesionales" in error.message and "No se cambió nada" in error.message
    assert user_version_de(ruta) == 0  # la transacción se revirtió


def user_version_de(ruta):
    return sqlite3.connect(ruta).execute("PRAGMA user_version").fetchone()[0]


def test_sentencias_parte_el_esquema_sin_perder_ni_unir_nada():
    texto = modulo_db_schema()
    sentencias = list(modulo_db._sentencias(texto))
    assert all(sqlite3.complete_statement(s) for s in sentencias)
    memoria = sqlite3.connect(":memory:")
    for s in sentencias:
        memoria.execute(s)
    referencia = sqlite3.connect(":memory:")
    referencia.executescript(texto)
    leer = lambda c: sorted(c.execute("SELECT type, name, sql FROM sqlite_master").fetchall())  # noqa: E731
    assert leer(memoria) == leer(referencia)
    assert list(modulo_db._sentencias("-- solo un comentario\n")) == []
    assert list(modulo_db._sentencias("SELECT 1; -- fin\nSELECT 2")) == ["SELECT 1; -- fin", "SELECT 2"]


# ----------------------------------------------------- base de una versión más nueva ----


def test_una_base_mas_nueva_no_cambia_nada_ni_su_numero_ni_sus_tablas_ni_sus_indices(app):
    runner = app.test_cli_runner()
    assert runner.invoke(args=["init-db"]).exit_code == 0
    with sqlite3.connect(app.config["DATABASE"]) as con:
        con.execute("DROP INDEX intentos_acceso_instante")
        con.execute(f"PRAGMA user_version = {modulo_db.VERSION_ESQUEMA + 5}")
    antes = volcado(app)
    r = runner.invoke(args=["init-db"])
    assert r.exit_code == 0 and "sin cambios" in r.output
    assert "versión más nueva" in r.output and "No se cambió nada" in r.output
    assert "inicializada" not in r.output and "actualizada" not in r.output
    assert volcado(app) == antes  # el índice que faltaba NO se creó
    assert "intentos_acceso_instante" not in tablas_e_indices(app)
    assert user_version(app) == modulo_db.VERSION_ESQUEMA + 5


def test_una_base_mas_nueva_con_una_columna_menos_tampoco_se_migra(app):
    base_antigua(app, "df7a71f")
    with sqlite3.connect(app.config["DATABASE"]) as con:
        con.execute(f"PRAGMA user_version = {modulo_db.VERSION_ESQUEMA + 1}")
    antes = volcado(app)
    assert app.test_cli_runner().invoke(args=["init-db"]).exit_code == 0
    assert volcado(app) == antes


# ------------------------------------------------- FK de avisos sin ON DELETE SET NULL ----

SIN_SET_NULL = ["748f18e", "cd9f209"]
CON_SET_NULL = ["df7a71f", "f06bdb5"]


def test_los_esquemas_guardados_son_los_de_los_commits():
    assert (ANTIGUOS / "cd9f209.sql").read_text(encoding="utf-8").count("ON DELETE SET NULL") == 0
    assert (ANTIGUOS / "748f18e.sql").read_text(encoding="utf-8").count("ON DELETE SET NULL") == 0
    assert (ANTIGUOS / "df7a71f.sql").read_text(encoding="utf-8").count("ON DELETE SET NULL") == 1


@pytest.mark.parametrize("commit", SIN_SET_NULL)
def test_init_db_avisa_con_el_procedimiento_aunque_la_version_ya_este_anotada(app, commit):
    base_antigua(app, commit)
    runner = app.test_cli_runner()
    for vuelta in range(2):  # la segunda vez user_version ya vale 1: el aviso NO desaparece
        r = runner.invoke(args=["init-db"])
        assert r.exit_code == 0, r.output
        assert "Aviso: La tabla notificaciones es de un esquema anterior a D-016" in r.output
        assert "ON DELETE SET NULL" in r.output and "NO podrá eliminar una hora" in r.output
        ruta = app.config["DATABASE"]
        assert f"cp {ruta} {ruta}.respaldo" in r.output and "borra " + ruta in r.output
        assert "README" in r.output and "D-052" in r.output
        assert "no cambió nada" in r.output
        assert "Aviso: La tabla notificaciones se creó con un esquema anterior" not in r.output  # un solo aviso
    assert user_version(app) == modulo_db.VERSION_ESQUEMA


@pytest.mark.parametrize("commit", CON_SET_NULL)
def test_init_db_no_da_ese_aviso_si_la_fk_ya_tiene_set_null(app, commit):
    base_antigua(app, commit)
    r = app.test_cli_runner().invoke(args=["init-db"])
    assert "D-016" not in r.output and "NO podrá eliminar" not in r.output


def test_una_base_nueva_y_una_sin_la_tabla_no_dan_el_aviso_de_la_fk(app):
    r = app.test_cli_runner().invoke(args=["init-db"])
    assert "D-016" not in r.output
    with sqlite3.connect(app.config["DATABASE"]) as con:
        assert modulo_db.fk_de_avisos_sin_set_null(con) is False
        con.execute("DROP TABLE notificaciones")
        assert modulo_db.fk_de_avisos_sin_set_null(con) is False  # sin tabla no hay nada que avisar


def test_fk_de_avisos_distingue_set_null_de_las_demas_acciones():
    def base(accion):
        con = sqlite3.connect(":memory:")
        con.executescript(
            f"CREATE TABLE horas (id INTEGER PRIMARY KEY); CREATE TABLE notificaciones "
            f"(id INTEGER PRIMARY KEY, hora_id INTEGER REFERENCES horas (id){accion});"
        )
        return con

    assert modulo_db.fk_de_avisos_sin_set_null(base("")) is True
    assert modulo_db.fk_de_avisos_sin_set_null(base(" ON DELETE CASCADE")) is True
    assert modulo_db.fk_de_avisos_sin_set_null(base(" ON DELETE RESTRICT")) is True
    assert modulo_db.fk_de_avisos_sin_set_null(base(" ON DELETE SET NULL")) is False
    assert modulo_db.fk_de_avisos_sin_set_null(base(" on delete set null")) is False


def _flujo_reservar_cancelar(app, monkeypatch, commit):
    """Base de `commit` + init-db; Ana reserva y cancela (por HTTP); devuelve (profesional, hora)."""
    fijar_reloj(monkeypatch)
    base_antigua(app, commit, usuarios=())
    assert app.test_cli_runner().invoke(args=["init-db"]).exit_code == 0
    crear(app, email="pro@example.cl", rol="profesional", nombre="Dr. Pro")
    crear(app, email="ana@example.cl", rol="paciente", nombre="Ana")
    with app.app_context():
        db = modulo_db.get_db()
        db.execute("INSERT INTO horas (profesional_id, inicio) VALUES (1, '2026-10-12T10:00:00')")
        db.commit()
    ana = app.test_client()
    iniciar(ana, "ana@example.cl")
    token = extraer_token(ana.get("/paciente/horas").text)
    assert ana.post("/horas/1/reservar", data={"csrf_token": token}).status_code == 302
    token = extraer_token(ana.get("/paciente").text)
    assert ana.post("/horas/1/cancelar", data={"csrf_token": token}).status_code == 302
    pro = app.test_client()
    iniciar(pro, "pro@example.cl")
    return pro, 1


@pytest.mark.parametrize("commit", SIN_SET_NULL)
def test_eliminar_una_hora_con_avisos_en_una_base_antigua_da_un_mensaje_y_no_cambia_nada(app, caplog, monkeypatch, commit):
    pro, hora = _flujo_reservar_cancelar(app, monkeypatch, commit)
    antes = volcado(app)
    token = extraer_token(pro.get("/profesional").text)
    with caplog.at_level("ERROR"):
        r = pro.post(f"/profesional/horas/{hora}/eliminar", data={"csrf_token": token})
    assert r.status_code == 302 and r.headers["Location"] == "/profesional"  # no es un 500
    panel = pro.get("/profesional").text
    assert "No se pudo eliminar esta hora porque ya tuvo avisos" in panel
    assert "procedimiento de «Bases creadas por versiones antiguas» del README" in panel
    assert "Traceback" not in panel and "FOREIGN KEY" not in panel and "sqlite" not in panel.lower()
    assert fila(app, hora) == ("libre", None, None)  # la hora sigue ahí
    assert volcado(app) == antes  # ni una fila cambió
    assert any("sin ON DELETE SET NULL" in m and "README" in m for m in caplog.messages)


@pytest.mark.parametrize("commit", CON_SET_NULL)
def test_en_una_base_con_set_null_el_mismo_flujo_elimina_la_hora(app, monkeypatch, commit):
    pro, hora = _flujo_reservar_cancelar(app, monkeypatch, commit)
    token = extraer_token(pro.get("/profesional").text)
    assert pro.post(f"/profesional/horas/{hora}/eliminar", data={"csrf_token": token}).status_code == 302
    assert "La hora se eliminó correctamente." in pro.get("/profesional").text
    with sqlite3.connect(app.config["DATABASE"]) as con:
        assert con.execute("SELECT COUNT(*) FROM horas").fetchone()[0] == 0
        assert {f[0] for f in con.execute("SELECT hora_id FROM notificaciones")} == {None}


def test_una_integrityerror_que_no_es_la_fk_antigua_sigue_siendo_un_500(app, monkeypatch):
    """Solo se explica la causa comprobada; cualquier otra restricción rota es un bug y no se disfraza."""
    with app.app_context():
        modulo_db.init_db()
    crear(app, email="pro@example.cl", rol="profesional", nombre="Dr. Pro")
    pro = app.test_client()
    iniciar(pro, "pro@example.cl")
    real = profesional.get_db

    class Proxy:
        def __init__(self, db):
            self.db = db

        def execute(self, sql, *a):
            if sql.startswith("DELETE FROM horas"):
                raise sqlite3.IntegrityError("FOREIGN KEY constraint failed")
            return self.db.execute(sql, *a)

        def __getattr__(self, nombre):
            return getattr(self.db, nombre)

    monkeypatch.setattr(profesional, "get_db", lambda: Proxy(real()))
    app.config["PROPAGATE_EXCEPTIONS"] = False
    token = extraer_token(pro.get("/profesional").text)
    r = pro.post("/profesional/horas/1/eliminar", data={"csrf_token": token})
    assert r.status_code == 500 and "No se pudo eliminar esta hora" not in r.text


# ---------------------------------------------------------- aviso al arrancar ----


def test_el_aviso_de_arranque_se_da_solo_con_la_fk_antigua(app, caplog):
    base_antigua(app, "cd9f209", usuarios=())
    with caplog.at_level("WARNING"):
        modulo_db.avisar_si_la_base_es_antigua(app)
    assert any("sin ON DELETE SET NULL" in m and app.config["DATABASE"] in m for m in caplog.messages)
    caplog.clear()
    base_nueva = app.config["DATABASE"] + ".nueva"
    app.config["DATABASE"] = base_nueva
    assert app.test_cli_runner().invoke(args=["init-db"]).exit_code == 0
    with caplog.at_level("WARNING"):
        modulo_db.avisar_si_la_base_es_antigua(app)
    assert caplog.messages == []


def test_el_aviso_de_arranque_nunca_falla_ni_crea_ni_cambia_la_base(tmp_path, caplog):
    app = _app(tmp_path / "no" / "existe.db")
    with caplog.at_level("WARNING"):
        modulo_db.avisar_si_la_base_es_antigua(app)  # carpeta inexistente
        app.config["DATABASE"] = str(tmp_path / "nada.db")
        modulo_db.avisar_si_la_base_es_antigua(app)  # archivo inexistente
        app.config["DATABASE"] = str(tmp_path)
        modulo_db.avisar_si_la_base_es_antigua(app)  # carpeta
        basura = tmp_path / "basura.db"
        _texto(basura)
        app.config["DATABASE"] = str(basura)
        modulo_db.avisar_si_la_base_es_antigua(app)  # no es SQLite
        app.config["DATABASE"] = "\0"
        modulo_db.avisar_si_la_base_es_antigua(app)  # ruta imposible
    assert caplog.messages == []
    assert sorted(p.name for p in tmp_path.iterdir()) == ["basura.db"]


def test_el_aviso_de_arranque_abre_la_base_solo_para_lectura(app, monkeypatch):
    base_antigua(app, "cd9f209", usuarios=())
    abiertas = []
    real = sqlite3.connect
    monkeypatch.setattr(modulo_db.sqlite3, "connect", lambda *a, **k: abiertas.append((a, k)) or real(*a, **k))
    modulo_db.avisar_si_la_base_es_antigua(app)
    (argumentos, opciones), = abiertas
    assert argumentos[0].startswith("file:") and argumentos[0].endswith("?mode=ro") and opciones["uri"] is True


def test_al_crear_la_app_para_servir_se_da_el_aviso_y_en_pruebas_no(tmp_path, caplog):
    ruta = tmp_path / "vieja.db"
    base = _app(ruta)
    base_antigua(base, "748f18e", usuarios=())
    with caplog.at_level("WARNING"):
        create_app({"TESTING": True, "DATABASE": str(ruta)})
        assert not any("ON DELETE SET NULL" in m for m in caplog.messages)  # TESTING: no consulta
        create_app({"DATABASE": str(ruta), "SECRET_KEY": "x" * 32, "SESSION_COOKIE_SECURE": True})
    assert any("sin ON DELETE SET NULL" in m for m in caplog.messages)


# ----------------------------------------------- create-professional: base antes que clave ----


def test_create_professional_comprueba_la_base_antes_de_pedir_la_contrasena(tmp_path):
    r = _ejecutar(_app(tmp_path / "nada.db"), "create-professional", *ARGS, entrada="")
    assert r.exit_code == 1 and "No existe la base de datos" in r.output
    assert "Contraseña" not in r.output and "Repeat" not in r.output
    _sin_traza(r)
    assert list(tmp_path.iterdir()) == []


def test_create_professional_con_la_base_bloqueada_da_el_mensaje_y_no_crea_nada(app):
    assert app.test_cli_runner().invoke(args=["init-db"]).exit_code == 0
    app.config["DATABASE_TIMEOUT"] = 0.05
    otra = sqlite3.connect(app.config["DATABASE"], isolation_level=None)
    otra.execute("BEGIN IMMEDIATE")
    try:
        r = _ejecutar(app, "create-professional", *ARGS, entrada=ENTRADA)
    finally:
        otra.execute("ROLLBACK")
        otra.close()
    assert r.exit_code == 1 and "La base de datos está ocupada" in r.output and "vuelve a ejecutar" in r.output
    assert "Contraseña" not in r.output  # lo supo antes de pedirla
    _sin_traza(r)
    with sqlite3.connect(app.config["DATABASE"]) as con:
        assert con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0
    assert _ejecutar(app, "create-professional", *ARGS, entrada=ENTRADA).exit_code == 0  # liberada
