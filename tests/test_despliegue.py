"""Configuración de despliegue (T-14a): cookie `Secure` (D-042) y debug en un host público (D-043)."""
import logging
import os
import subprocess
import sys
import threading
import time
import unicodedata

import click
import pytest
from flask.cli import ScriptInfo

from app import (
    MENSAJE_COOKIE_SIN_SECURE,
    MENSAJE_DEBUG_EN_SERVIDOR,
    MENSAJE_UNICODE_ANTIGUO,
    create_app,
    es_host_local,
)

CLAVE_VALIDA = "una-clave-larga-de-prueba"


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch):
    for nombre in ("SECRET_KEY", "FLASK_DEBUG", "SESSION_COOKIE_SECURE", "TRUSTED_PROXY_COUNT", "FLASK_RUN_HOST"):
        monkeypatch.delenv(nombre, raising=False)


def _config(tmp_path, **extra):
    return {"DATABASE": str(tmp_path / "test.db"), "SECRET_KEY": CLAVE_VALIDA, **extra}


def _cookie_de_sesion(app):
    """Cabecera Set-Cookie de la cookie de sesión (GET /login la crea con el token CSRF)."""
    respuesta = app.test_client().get("/login")
    (cookie,) = [v for v in respuesta.headers.getlist("Set-Cookie") if v.startswith("session=")]
    return cookie


# ------------------------------------------------------- D-042: cookie Secure


@pytest.mark.parametrize("valor", ["1", "true", "TRUE", "True", " yes ", "on", "ON", "si", "sí"])
def test_valores_verdaderos_activan_la_cookie_secure(tmp_path, monkeypatch, valor):
    monkeypatch.setenv("SESSION_COOKIE_SECURE", valor)
    app = create_app(_config(tmp_path))
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert "Secure" in _cookie_de_sesion(app)


@pytest.mark.parametrize("valor", ["0", "false", "False", "FALSE", "no", "off", "OFF", "Off", "", "   "])
def test_valores_falsos_o_vacios_no_la_activan(tmp_path, monkeypatch, valor):
    """Ojo con `0`, `off`, `false` y la cadena vacía: son la forma habitual de apagarla."""
    monkeypatch.setenv("SESSION_COOKIE_SECURE", valor)
    app = create_app(_config(tmp_path))
    assert app.config["SESSION_COOKIE_SECURE"] is False
    assert "Secure" not in _cookie_de_sesion(app)


def test_sin_la_variable_la_cookie_no_es_secure(tmp_path):
    app = create_app(_config(tmp_path))
    assert app.config["SESSION_COOKIE_SECURE"] is False
    assert "Secure" not in _cookie_de_sesion(app)


@pytest.mark.parametrize("valor", ["maybe", "2", "activada", "truee", "ON-PLEASE", "-1", "verdadero"])
def test_un_valor_que_no_es_ni_verdadero_ni_falso_se_rechaza(tmp_path, monkeypatch, valor):
    """Interpretarlo en silencio como falso dejaría la cookie sin protección sin que nadie lo note."""
    monkeypatch.setenv("SESSION_COOKIE_SECURE", valor)
    with pytest.raises(RuntimeError, match="SESSION_COOKIE_SECURE"):
        create_app(_config(tmp_path))


def test_un_valor_invalido_en_un_comando_de_flask_da_un_error_limpio(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "maybe")
    with click.Context(click.Command("init-db"), obj=ScriptInfo()), pytest.raises(click.ClickException, match="SESSION_COOKIE_SECURE"):
        create_app(_config(tmp_path))


def test_la_cookie_conserva_httponly_y_samesite(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "1")
    cookie = _cookie_de_sesion(create_app(_config(tmp_path)))
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie and "Secure" in cookie


def test_el_login_con_secure_activada_pone_secure_en_la_cookie_nueva(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "1")
    app = create_app(_config(tmp_path, TESTING=True))
    with app.app_context():
        from app.db import init_db

        init_db()
    from tests.test_login import crear, iniciar

    crear(app)
    cliente = app.test_client()
    respuesta = iniciar(cliente)
    assert respuesta.status_code == 302
    (cookie,) = [v for v in respuesta.headers.getlist("Set-Cookie") if v.startswith("session=")]
    assert "Secure" in cookie


def _avisos(caplog, mensaje):
    return [r for r in caplog.records if mensaje in r.getMessage()]


def test_aviso_si_se_sirve_sin_debug_y_sin_secure(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        create_app(_config(tmp_path))  # sin contexto de click: se carga para servir (gunicorn)
    (aviso,) = _avisos(caplog, MENSAJE_COOKIE_SIN_SECURE)
    assert aviso.levelno == logging.WARNING and "SESSION_COOKIE_SECURE=1" in aviso.getMessage()


def test_aviso_con_flask_run_una_sola_vez(tmp_path, caplog):
    with click.Context(click.Command("run"), obj=ScriptInfo()), caplog.at_level(logging.WARNING):
        create_app(_config(tmp_path))
    assert len(_avisos(caplog, MENSAJE_COOKIE_SIN_SECURE)) == 1


def test_sin_aviso_si_la_cookie_es_secure(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "1")
    with caplog.at_level(logging.WARNING):
        create_app(_config(tmp_path))
    assert _avisos(caplog, MENSAJE_COOKIE_SIN_SECURE) == []


@pytest.mark.parametrize("extra", [{"TESTING": True}, {"DEBUG": True}])
def test_sin_aviso_en_pruebas_ni_en_debug(tmp_path, caplog, extra):
    with caplog.at_level(logging.WARNING):
        create_app(_config(tmp_path, **extra))
    assert _avisos(caplog, MENSAJE_COOKIE_SIN_SECURE) == []


@pytest.mark.parametrize("comando", ["init-db", "create-professional", "send-reminders"])
def test_sin_aviso_en_los_comandos_de_mantenimiento(tmp_path, caplog, comando):
    with click.Context(click.Command(comando), obj=ScriptInfo()), caplog.at_level(logging.WARNING):
        create_app(_config(tmp_path))
    assert _avisos(caplog, MENSAJE_COOKIE_SIN_SECURE) == []


# --------------------------------------------- versión de Unicode (T-03c R-12)


@pytest.mark.parametrize(
    "version, avisa",
    [("9.0.0", True), ("14.0.0", True), ("15.0.0", True), ("15.1.0", False), ("15.10.0", False),
     ("16.0.0", False), ("100.0.0", False)],  # 9 y 100: el orden de TEXTO daría lo contrario
)
def test_aviso_si_el_unicode_de_python_es_mas_antiguo_que_el_probado(tmp_path, monkeypatch, caplog, version, avisa):
    monkeypatch.setattr(unicodedata, "unidata_version", version)
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "1")
    with caplog.at_level(logging.WARNING):
        create_app(_config(tmp_path))
    texto_base = MENSAJE_UNICODE_ANTIGUO.split("{")[0]
    assert bool([r for r in caplog.records if texto_base in r.getMessage()]) is avisa


# -------------------------------------------- D-043: debug en un host no local


@pytest.mark.parametrize(
    "host, local",
    [
        ("127.0.0.1", True), ("localhost", True), ("LOCALHOST", True), ("::1", True), ("[::1]", True),
        ("127.0.0.2", True),
        ("0.0.0.0", False), ("::", False), ("", False), ("192.168.1.10", False),
        ("10.0.0.5", False), ("example.com", False), ("localhost.example.com", False),
        ("127.0.0.1.example.com", False), ("8.8.8.8", False),
    ],
)
def test_es_host_local(host, local):
    assert es_host_local(host) is local


def _run(host=None, debugger=None):
    contexto = click.Context(click.Command("run"), obj=ScriptInfo(), info_name="run")
    contexto.params = {k: v for k, v in (("host", host), ("debugger", debugger)) if v is not None}
    return contexto


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10", "example.com", ""])
def test_debug_con_host_publico_no_arranca(tmp_path, host):
    with _run(host), pytest.raises(click.ClickException) as error:
        create_app(_config(tmp_path, DEBUG=True))
    mensaje = error.value.format_message()
    assert "debug" in mensaje and "no es una dirección local" in mensaje and "SECRET_KEY" in mensaje


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", None])
def test_debug_con_host_local_arranca(tmp_path, host):
    with _run(host):
        assert create_app(_config(tmp_path, DEBUG=True)).debug


@pytest.mark.parametrize("valor", ["1", "true", "True", "yes", "on", "off", "OFF", "x", "2"])
def test_flask_debug_verdadero_en_host_publico_no_arranca(tmp_path, monkeypatch, valor):
    """`Flask` solo trata `0`, `false` y `no` como falso: `off` es debug si la app se carga sin
    pasar por Click (el servidor real de `flask run` sí lo lee como falso; ver más abajo). Del
    lado seguro: ante la duda, se niega."""
    monkeypatch.setenv("FLASK_DEBUG", valor)
    with _run("0.0.0.0"), pytest.raises(click.ClickException, match="debug"):
        create_app(_config(tmp_path))


@pytest.mark.parametrize("valor", ["0", "false", "False", "no", "NO", ""])
def test_flask_debug_falso_en_host_publico_arranca(tmp_path, monkeypatch, valor):
    monkeypatch.setenv("FLASK_DEBUG", valor)
    with _run("0.0.0.0"):
        assert not create_app(_config(tmp_path)).debug


def test_sin_debug_el_host_publico_arranca(tmp_path):
    with _run("0.0.0.0"):
        create_app(_config(tmp_path))


def test_el_depurador_pedido_aparte_tampoco_se_expone_en_un_host_publico(tmp_path):
    with _run("0.0.0.0", debugger=True), pytest.raises(click.ClickException, match="no es una dirección local"):
        create_app(_config(tmp_path))
    with _run("127.0.0.1", debugger=True):
        create_app(_config(tmp_path))
    with _run("0.0.0.0", debugger=False):
        create_app(_config(tmp_path))


def test_otros_comandos_de_flask_no_comprueban_el_host(tmp_path):
    contexto = click.Context(click.Command("init-db"), obj=ScriptInfo())
    contexto.params = {"host": "0.0.0.0"}
    with contexto:
        assert create_app(_config(tmp_path, DEBUG=True)).debug


def test_debug_fuera_de_flask_run_avisa_en_el_log(tmp_path, caplog):
    """gunicorn y similares: el host no se conoce, así que no se puede negar; se avisa."""
    with caplog.at_level(logging.WARNING):
        create_app(_config(tmp_path, DEBUG=True))
    assert len(_avisos(caplog, MENSAJE_DEBUG_EN_SERVIDOR)) == 1


def test_en_pruebas_con_debug_no_hay_aviso_ni_negativa(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        create_app(_config(tmp_path, DEBUG=True, TESTING=True))
    assert _avisos(caplog, MENSAJE_DEBUG_EN_SERVIDOR) == []


# ------------------------- D-043 con un servidor real (`flask run` de verdad)


def _entorno(tmp_path, **extra):
    entorno = {k: v for k, v in os.environ.items() if k not in ("SECRET_KEY", "FLASK_DEBUG", "FLASK_RUN_HOST")}
    entorno["DATABASE"] = str(tmp_path / "real.db")
    entorno.update(extra)
    return entorno


def _flask_run(tmp_path, *argumentos, **entorno):
    return subprocess.Popen(
        [sys.executable, "-m", "flask", "--app", "app", "run", "--port", "0", "--no-reload", *argumentos],
        env=_entorno(tmp_path, **entorno), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def _terminar(proceso):
    if proceso.poll() is None:
        proceso.terminate()
    try:
        proceso.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proceso.kill()
        proceso.wait()


@pytest.mark.parametrize(
    "argumentos, entorno",
    [
        (["--host", "0.0.0.0", "--debug"], {}),
        (["--host", "0.0.0.0"], {"FLASK_DEBUG": "1"}),
        (["--debug"], {"FLASK_RUN_HOST": "0.0.0.0"}),
        (["--host", "0.0.0.0", "--debugger"], {"SECRET_KEY": CLAVE_VALIDA}),  # depurador sin debug
    ],
    ids=["--debug", "FLASK_DEBUG=1", "FLASK_RUN_HOST", "--debugger"],
)
def test_flask_run_real_con_debug_en_un_host_publico_se_niega_a_arrancar(tmp_path, argumentos, entorno):
    proceso = _flask_run(tmp_path, *argumentos, **entorno)
    try:
        salida, error = proceso.communicate(timeout=15)
    finally:
        _terminar(proceso)
    assert proceso.returncode == 1
    assert "no es una dirección local" in error and "Traceback" not in error
    assert "Running on" not in error + salida  # nunca llegó a abrir el puerto


def _esperar_en_stderr(proceso, texto, limite=20):
    leido = []
    hilo = threading.Thread(target=lambda: [leido.append(linea) for linea in proceso.stderr], daemon=True)
    hilo.start()
    fin = time.monotonic() + limite
    while time.monotonic() < fin and proceso.poll() is None:
        if texto in "".join(leido):
            break
        time.sleep(0.02)
    return "".join(leido), hilo


@pytest.mark.parametrize(
    "argumentos, entorno",
    [
        (["--host", "127.0.0.1", "--debug"], {}),
        (["--host", "0.0.0.0"], {"SECRET_KEY": CLAVE_VALIDA}),  # público pero sin debug
        # Bajo `flask run`, Click lee FLASK_DEBUG como booleano: estos valores NO son debug.
        (["--host", "0.0.0.0"], {"SECRET_KEY": CLAVE_VALIDA, "FLASK_DEBUG": "off"}),
    ],
    ids=["--debug local", "público sin debug", "público con FLASK_DEBUG=off"],
)
def test_flask_run_real_arranca_cuando_corresponde(tmp_path, argumentos, entorno):
    proceso = _flask_run(tmp_path, *argumentos, **entorno)
    try:
        error, hilo = _esperar_en_stderr(proceso, "Running on")
        _terminar(proceso)
        hilo.join(timeout=5)
    finally:
        _terminar(proceso)
    assert "Running on" in error, error
    assert "no es una dirección local" not in error
    assert proceso.poll() is not None


def test_flask_run_real_con_un_flask_debug_que_no_es_booleano_ni_arranca(tmp_path):
    """Click rechaza `FLASK_DEBUG=banana` antes de cargar la app: tampoco abre el puerto."""
    proceso = _flask_run(tmp_path, "--host", "0.0.0.0", FLASK_DEBUG="banana")
    try:
        salida, error = proceso.communicate(timeout=15)
    finally:
        _terminar(proceso)
    assert proceso.returncode == 2 and "Running on" not in error + salida


# ------------------------------- R-01 con procesos reales (servidor WSGI sin contexto de click)


def _python(codigo, tmp_path, **entorno):
    return subprocess.run(
        [sys.executable, "-c", codigo], env=_entorno(tmp_path, **entorno),
        capture_output=True, text=True, timeout=60, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )


@pytest.mark.parametrize("debug", ["1", "off"])
def test_r01_proceso_wsgi_con_debug_y_sin_clave_no_crea_la_app(tmp_path, debug):
    """Como `gunicorn 'app:create_app()'`: proceso sin click, FLASK_DEBUG activo (incluido `off`), sin SECRET_KEY."""
    r = _python("from app import create_app; create_app()", tmp_path, FLASK_DEBUG=debug)
    assert r.returncode != 0
    assert "RuntimeError: Me niego a servir" in r.stderr and "SECRET_KEY" in r.stderr


def test_r01_proceso_wsgi_con_clave_propia_crea_la_app(tmp_path):
    r = _python("from app import create_app; a = create_app(); print(a.config['SECRET_KEY'])", tmp_path,
                FLASK_DEBUG="off", SECRET_KEY=CLAVE_VALIDA)
    assert r.returncode == 0 and CLAVE_VALIDA in r.stdout


@pytest.mark.parametrize("debug", ["1", "off"])
@pytest.mark.parametrize("comando", [["init-db"], ["send-reminders"]])
def test_r01_los_comandos_de_mantenimiento_funcionan_con_debug_y_sin_clave(tmp_path, debug, comando):
    """D-008: sin SECRET_KEY, con FLASK_DEBUG definida, los comandos CLI siguen funcionando."""
    if comando != ["init-db"]:
        assert _flask_cli(tmp_path, ["init-db"], debug).returncode == 0
    r = _flask_cli(tmp_path, comando, debug)
    assert r.returncode == 0, r.stderr


def _flask_cli(tmp_path, comando, debug):
    return subprocess.run(
        [sys.executable, "-m", "flask", "--app", "app", *comando], env=_entorno(tmp_path, FLASK_DEBUG=debug),
        capture_output=True, text=True, timeout=60,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
