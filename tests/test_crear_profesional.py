import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest
from werkzeug.security import check_password_hash

from app import auth
from app.db import init_db
from tests.test_login import CLAVE, crear, iniciar

ARGS = ["--email", "Pro@Example.CL", "--nombre", "  Dra. Pro  "]


@pytest.fixture(autouse=True)
def base_inicializada(app):
    with app.app_context():
        init_db()


@pytest.fixture
def runner(app):
    return app.test_cli_runner()


def filas(app):
    con = sqlite3.connect(app.config["DATABASE"])
    con.row_factory = sqlite3.Row
    try:
        return con.execute("SELECT * FROM usuarios ORDER BY id").fetchall()
    finally:
        con.close()


def crear_pro(runner, args=ARGS, password=CLAVE, confirmacion=None):
    entrada = f"{password}\n{password if confirmacion is None else confirmacion}\n"
    return runner.invoke(auth.create_professional_command, args, input=entrada)


def test_crea_el_profesional_con_correo_normalizado_y_hash(app, runner):
    r = crear_pro(runner)
    assert r.exit_code == 0, r.output
    (u,) = filas(app)
    assert u["rol"] == "profesional"
    assert u["email"] == "pro@example.cl"
    assert u["nombre"] == "Dra. Pro"
    assert u["password_hash"] != CLAVE and CLAVE not in u["password_hash"]
    assert check_password_hash(u["password_hash"], CLAVE)
    assert u["creado_en"].endswith(("-03:00", "-04:00"))


@pytest.mark.hash_real
def test_con_hash_real_el_profesional_se_guarda_con_scrypt_de_costo_completo(app, runner):
    assert crear_pro(runner).exit_code == 0
    assert filas(app)[0]["password_hash"].startswith("scrypt:32768:8:1$")


def test_no_imprime_la_contrasena(runner):
    r = crear_pro(runner, password="Contraseña-Secreta-77")
    assert r.exit_code == 0
    assert "Contraseña-Secreta-77" not in r.output
    assert "Profesional creado: pro@example.cl" in r.output


def test_la_contrasena_no_se_acepta_como_opcion(app, runner):
    """Así no queda en argv (lista de procesos) ni en el historial del shell."""
    r = runner.invoke(auth.create_professional_command, ARGS + ["--password", CLAVE])
    assert r.exit_code == 2
    assert filas(app) == []


def test_pide_la_contrasena_sin_eco_y_con_confirmacion(app, runner, monkeypatch):
    avisos = []
    import click

    real = click.prompt

    def espia(*args, **kwargs):
        avisos.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(click, "prompt", espia)
    assert crear_pro(runner).exit_code == 0
    assert avisos[0]["hide_input"] is True
    assert avisos[0]["confirmation_prompt"] is True


def test_confirmacion_distinta_no_crea_nada(app, runner):
    r = crear_pro(runner, confirmacion="otra-distinta-1")
    assert r.exit_code != 0
    assert filas(app) == []


def test_el_profesional_creado_puede_iniciar_sesion(app, runner, client):
    crear_pro(runner)
    r = iniciar(client, "PRO@example.cl")
    assert r.headers["Location"] == "/profesional"
    assert client.get("/profesional").status_code == 200


@pytest.mark.parametrize("email", ["pro@example.cl", "PRO@EXAMPLE.CL", "ｐｒｏ@example.cl"])
def test_correo_duplicado_avisa_y_no_crea(app, runner, email):
    crear(app, email="pro@example.cl")
    r = crear_pro(runner, ["--email", email, "--nombre", "Otra"])
    assert r.exit_code == 1
    assert "Ya existe un usuario con ese correo." in r.output
    assert len(filas(app)) == 1


def test_otra_integrityerror_no_se_disfraza_de_duplicado(runner, monkeypatch):
    def falla(*args, **kwargs):
        raise sqlite3.IntegrityError("NOT NULL constraint failed: usuarios.nombre")

    monkeypatch.setattr(auth, "crear_usuario", falla)
    r = crear_pro(runner)
    assert isinstance(r.exception, sqlite3.IntegrityError)
    assert "Ya existe" not in r.output


@pytest.mark.parametrize(
    "args,password,texto",
    [
        (["--email", "pro​@example.cl", "--nombre", "X"], CLAVE, "correo válido"),
        (["--email", "sin-arroba", "--nombre", "X"], CLAVE, "correo válido"),
        (["--email", "pro@example.cl", "--nombre", "   "], CLAVE, "nombre"),
        (["--email", "pro@example.cl", "--nombre", "Eve\nroja"], CLAVE, "saltos de línea"),
        (["--email", "pro@example.cl", "--nombre", "Eve\x1b[31m"], CLAVE, "control"),
        (["--email", "pro@example.cl", "--nombre", "Eve\u202e"], CLAVE, "invisibles"),
        (["--email", "pro@example.cl", "--nombre", "X"], "corta", "al menos 8"),
        (["--email", "pro@example.cl", "--nombre", "X"], "a" * 129, "128"),
    ],
)
def test_datos_invalidos_no_crean_nada(app, runner, args, password, texto):
    r = crear_pro(runner, args, password)
    assert r.exit_code == 1
    assert texto in r.output
    assert filas(app) == []


def test_faltan_opciones(app, runner):
    assert runner.invoke(auth.create_professional_command, []).exit_code == 2
    assert filas(app) == []


def test_el_comando_esta_registrado_y_funciona_sin_secret_key(tmp_path):
    """Por CLI real (proceso aparte), sin SECRET_KEY ni FLASK_DEBUG, con la
    contraseña por la entrada estándar (no por argv)."""
    entorno = {k: v for k, v in os.environ.items() if k not in ("SECRET_KEY", "FLASK_DEBUG")}
    entorno["DATABASE"] = str(tmp_path / "cli.db")
    base = [sys.executable, "-m", "flask", "--app", "app"]
    ok = subprocess.run(base + ["init-db"], env=entorno, capture_output=True, text=True)
    assert ok.returncode == 0 and ok.stderr == ""  # sin ruido ni aviso de SECRET_KEY
    r = subprocess.run(
        base + ["create-professional", "--email", "pro@example.cl", "--nombre", "Pro"],
        env=entorno, input="clave-segura-1\nclave-segura-1\n", capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "clave-segura-1" not in r.stdout + r.stderr
    assert "SECRET_KEY" not in r.stderr
    con = sqlite3.connect(tmp_path / "cli.db")
    assert con.execute("SELECT rol FROM usuarios").fetchall() == [("profesional",)]
    con.close()


def test_nombre_legitimo_con_tilde_enie_y_apostrofe_se_acepta(app, runner):
    r = crear_pro(runner, ["--email", "pro@example.cl", "--nombre", "Dra. María Ñanco-O'Higgins"])
    assert r.exit_code == 0, r.output
    assert filas(app)[0]["nombre"] == "Dra. María Ñanco-O'Higgins"


# ------------------------------------------------ D-023: un solo profesional

OTROS_ARGS = ["--email", "otra@example.cl", "--nombre", "Otra Profesional"]
MENSAJE_EXISTE = "Ya existe un profesional; en esta versión solo puede haber uno."


def test_la_segunda_ejecucion_se_niega_con_mensaje_en_espanol(app, runner):
    assert crear_pro(runner).exit_code == 0
    r = crear_pro(runner, OTROS_ARGS)
    assert r.exit_code == 1
    assert MENSAJE_EXISTE in r.output
    assert [u["email"] for u in filas(app)] == ["pro@example.cl"]


def test_repetir_el_mismo_correo_tambien_dice_que_ya_hay_profesional(app, runner):
    crear_pro(runner)
    r = crear_pro(runner)
    assert r.exit_code == 1 and MENSAJE_EXISTE in r.output
    assert len(filas(app)) == 1


def test_los_pacientes_existentes_no_impiden_crear_al_profesional(app, runner):
    crear(app, email="p1@example.cl")
    crear(app, email="p2@example.cl")
    assert crear_pro(runner).exit_code == 0
    assert [u["rol"] for u in filas(app)] == ["paciente", "paciente", "profesional"]


def test_el_rechazo_no_deja_una_transaccion_abierta(app, runner):
    """BEGIN IMMEDIATE toma el bloqueo de escritura: tras negarse hay que soltarlo."""
    crear_pro(runner)
    crear_pro(runner, OTROS_ARGS)
    con = sqlite3.connect(app.config["DATABASE"], timeout=0.2)
    try:
        con.execute("BEGIN IMMEDIATE")  # falla con 'database is locked' si quedó abierta
        con.rollback()
    finally:
        con.close()


class _SinVerExistencia:
    """Conexión que 'no ve' al profesional existente: simula otro proceso que se
    cuela entre la comprobación y la inserción. La base debe impedirlo igual."""

    def __init__(self, con):
        self._con = con

    def execute(self, sql, *args):
        if sql.startswith("SELECT 1 FROM usuarios WHERE rol"):
            return self._con.execute("SELECT 1 WHERE 0")
        return self._con.execute(sql, *args)

    def __getattr__(self, nombre):
        return getattr(self._con, nombre)


class _Espia:
    """Conexión que anota si había transaccion abierta al consultar y los rollback."""

    def __init__(self, con):
        self._con = con
        self.transaccion_al_consultar = None
        self.rollbacks = 0

    def execute(self, sql, *args):
        if sql.startswith("SELECT 1 FROM usuarios WHERE rol"):
            self.transaccion_al_consultar = self._con.in_transaction
        return self._con.execute(sql, *args)

    def rollback(self):
        self.rollbacks += 1
        return self._con.rollback()

    def __getattr__(self, nombre):
        return getattr(self._con, nombre)


def test_la_comprobacion_ocurre_dentro_de_una_transaccion_con_bloqueo_de_escritura(app, runner, monkeypatch):
    real = auth.get_db
    espia = {}
    monkeypatch.setattr(auth, "get_db", lambda: espia.setdefault("db", _Espia(real())))
    assert crear_pro(runner).exit_code == 0
    assert espia["db"].transaccion_al_consultar is True


def test_al_negarse_el_comando_revierte_la_transaccion_explicitamente(app, runner, monkeypatch):
    crear_pro(runner)
    real = auth.get_db
    espia = {}
    monkeypatch.setattr(auth, "get_db", lambda: espia.setdefault("db", _Espia(real())))
    assert crear_pro(runner, OTROS_ARGS).exit_code == 1
    assert espia["db"].rollbacks >= 1


def test_si_la_comprobacion_no_lo_ve_la_base_igual_lo_impide_con_el_mismo_mensaje(app, runner, monkeypatch):
    crear_pro(runner)
    real = auth.get_db
    monkeypatch.setattr(auth, "get_db", lambda: _SinVerExistencia(real()))
    r = crear_pro(runner, OTROS_ARGS)
    assert r.exit_code == 1
    assert MENSAJE_EXISTE in r.output
    assert "Traceback" not in r.output and r.exception is not None and isinstance(r.exception, SystemExit)
    assert len(filas(app)) == 1


def error_de_sqlite(sentencias):
    """La IntegrityError REAL que lanza SQLite al ejecutar `sentencias` en una base nueva."""
    con = sqlite3.connect(":memory:")
    from pathlib import Path
    con.executescript((Path(auth.__file__).parent / "schema.sql").read_text(encoding="utf-8"))
    with pytest.raises(sqlite3.IntegrityError) as info:
        for sql in sentencias:
            con.execute(sql)
    con.close()
    return info.value


INS = "INSERT INTO usuarios (nombre, email, password_hash, rol, creado_en) VALUES ('N', '{}', 'h', '{}', 'x')"


def test_es_profesional_duplicado_reconoce_solo_el_indice_de_rol():
    del_indice = error_de_sqlite([INS.format("a@x.cl", "profesional"), INS.format("b@x.cl", "profesional")])
    del_correo = error_de_sqlite([INS.format("a@x.cl", "paciente"), INS.format("A@x.cl", "paciente")])
    de_check = error_de_sqlite([INS.format("a@x.cl", "admin")])
    de_not_null = error_de_sqlite(["INSERT INTO usuarios (nombre) VALUES ('N')"])
    assert auth.es_profesional_duplicado(del_indice) and not auth.es_correo_duplicado(del_indice)
    assert auth.es_correo_duplicado(del_correo) and not auth.es_profesional_duplicado(del_correo)
    for otro in (de_check, de_not_null):
        assert not auth.es_profesional_duplicado(otro) and not auth.es_correo_duplicado(otro)
    # Un mensaje parecido sin el código de SQLite (no viene de la base) tampoco cuenta.
    assert not auth.es_profesional_duplicado(
        sqlite3.IntegrityError("UNIQUE constraint failed: usuarios.rol")
    )


@pytest.mark.parametrize("mensaje", ["NOT NULL constraint failed: usuarios.nombre", "UNIQUE constraint failed: usuarios.id"])
def test_otra_integrityerror_tampoco_se_disfraza_de_profesional_existente(runner, monkeypatch, mensaje):
    def falla(*args, **kwargs):
        raise sqlite3.IntegrityError(mensaje)

    monkeypatch.setattr(auth, "crear_usuario", falla)
    r = crear_pro(runner)
    assert isinstance(r.exception, sqlite3.IntegrityError)
    assert "Ya existe" not in r.output


def test_por_la_cli_real_la_segunda_ejecucion_se_niega(tmp_path):
    entorno = {k: v for k, v in os.environ.items() if k not in ("SECRET_KEY", "FLASK_DEBUG")}
    entorno["DATABASE"] = str(tmp_path / "cli2.db")
    base = [sys.executable, "-m", "flask", "--app", "app"]
    subprocess.run(base + ["init-db"], env=entorno, capture_output=True, text=True, check=True)

    def crear_por_cli(email):
        return subprocess.run(
            base + ["create-professional", "--email", email, "--nombre", "Pro"],
            env=entorno, input="clave-segura-1\nclave-segura-1\n", capture_output=True, text=True,
        )

    assert crear_por_cli("uno@example.cl").returncode == 0
    segundo = crear_por_cli("dos@example.cl")
    assert segundo.returncode == 1
    assert MENSAJE_EXISTE in segundo.stderr
    assert "Traceback" not in segundo.stderr
    con = sqlite3.connect(tmp_path / "cli2.db")
    assert con.execute("SELECT email FROM usuarios").fetchall() == [("uno@example.cl",)]
    con.close()


# ------------------------------------- T-08e (R-01 de la revisión de T-08d) ----


def test_el_comando_abre_begin_immediate_antes_de_comprobar_si_hay_profesional(app, runner, monkeypatch):
    """Caja blanca: la primera sentencia de la transacción es `BEGIN IMMEDIATE` (no `BEGIN`)
    y ocurre antes del `SELECT` que busca al profesional existente."""
    real = auth.get_db
    espia = {}

    def con_traza():
        db = espia.get("db") or real()
        if "db" not in espia:
            espia["db"] = db
            espia["sentencias"] = []
            db.set_trace_callback(espia["sentencias"].append)
        return db

    monkeypatch.setattr(auth, "get_db", con_traza)
    assert crear_pro(runner).exit_code == 0
    sentencias = espia["sentencias"]
    assert "BEGIN IMMEDIATE" in sentencias
    assert "BEGIN" not in sentencias
    comprobacion = next(i for i, s in enumerate(sentencias) if s.startswith("SELECT 1 FROM usuarios WHERE rol"))
    assert sentencias.index("BEGIN IMMEDIATE") < comprobacion
    assert not [s for s in sentencias[:comprobacion] if s.startswith(("INSERT", "UPDATE", "SELECT 1 FROM usuarios"))]


def test_mientras_comprueba_nadie_mas_puede_tomar_el_bloqueo_de_escritura(app, runner, monkeypatch):
    """Comportamiento en el mismo proceso: justo cuando el comando hace su `SELECT`, otra conexión
    intenta `BEGIN IMMEDIATE`. Con `BEGIN IMMEDIATE` ya tiene el bloqueo y la otra espera (`database
    is locked`); con un `BEGIN` normal el bloqueo de escritura aún está libre y la otra entra."""
    real = auth.get_db
    resultado = {}

    class Observador:
        def __init__(self, con):
            self._con = con

        def execute(self, sql, *args):
            if sql.startswith("SELECT 1 FROM usuarios WHERE rol"):
                rival = sqlite3.connect(app.config["DATABASE"], timeout=0.05)
                try:
                    rival.execute("BEGIN IMMEDIATE")
                    resultado["rival"] = "entró"
                    rival.rollback()
                except sqlite3.OperationalError as error:
                    resultado["rival"] = str(error)
                finally:
                    rival.close()
            return self._con.execute(sql, *args)

        def __getattr__(self, nombre):
            return getattr(self._con, nombre)

    monkeypatch.setattr(auth, "get_db", lambda: Observador(real()))
    assert crear_pro(runner).exit_code == 0
    assert resultado["rival"] == "database is locked"


SCRIPT_BARRERA = """
import sys, time
import app  # importar antes de la barrera: ambos procesos arrancan el comando a la vez
from flask.cli import main
salida, email = float(sys.argv[1]), sys.argv[2]
sys.argv = ["flask", "--app", "app", "create-professional", "--email", email, "--nombre", "Pro"]
time.sleep(max(0.0, salida - time.time()))
main()
"""


def lanzar_dos_create_professional(tmp_path, ronda):
    """Dos procesos reales de `create-professional` contra la misma base, arrancados a la vez."""
    entorno = {k: v for k, v in os.environ.items() if k not in ("SECRET_KEY", "FLASK_DEBUG")}
    ruta = tmp_path / f"carrera{ronda}.db"
    entorno["DATABASE"] = str(ruta)
    entorno["PYTHONPATH"] = str(Path(auth.__file__).parent.parent)  # el script vive en otra carpeta
    subprocess.run(
        [sys.executable, "-m", "flask", "--app", "app", "init-db"],
        env=entorno, capture_output=True, text=True, check=True,
    )
    script = tmp_path / "con_barrera.py"
    script.write_text(SCRIPT_BARRERA)
    salida = time.time() + 1.0
    procesos = [
        subprocess.Popen(
            [sys.executable, str(script), str(salida), email],
            env=entorno, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        for email in ("uno@example.cl", "dos@example.cl")
    ]
    for proceso in procesos:  # la contraseña a los dos antes de esperar a ninguno: si no, se serializan
        proceso.stdin.write("clave-segura-1\nclave-segura-1\n")
        proceso.stdin.close()
    resultados = []
    for proceso in procesos:
        out, err = proceso.communicate(timeout=60)
        resultados.append((proceso.returncode, out, err))
    con = sqlite3.connect(ruta)
    try:
        profesionales = con.execute("SELECT email FROM usuarios WHERE rol = 'profesional'").fetchall()
    finally:
        con.close()
    return resultados, profesionales


def test_dos_create_professional_simultaneos_uno_crea_y_el_otro_recibe_el_mensaje(tmp_path):
    """Comportamiento con dos procesos reales (R-01 de T-08d): con `BEGIN` normal ambos leen «no hay
    profesional» y uno termina con traceback `database is locked`; con `BEGIN IMMEDIATE` el segundo espera
    y recibe el mensaje en español con código 1."""
    resultados, profesionales = lanzar_dos_create_professional(tmp_path, 1)
    codigos = sorted(r[0] for r in resultados)
    detalle = repr(resultados)
    assert codigos == [0, 1], detalle
    (rechazado,) = [r for r in resultados if r[0] == 1]
    assert MENSAJE_EXISTE in rechazado[2], detalle
    for _, _, err in resultados:
        assert "Traceback" not in err and "database is locked" not in err, detalle
    assert len(profesionales) == 1
