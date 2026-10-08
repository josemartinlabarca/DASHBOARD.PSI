import os
import sqlite3
import subprocess
import sys

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
