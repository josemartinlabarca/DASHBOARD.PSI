import ipaddress
import os
import unicodedata

import click
from flask import Flask, render_template
from werkzeug.middleware.proxy_fix import ProxyFix

NOMBRE_PROYECTO = "Agenda Psi"
TAMANO_MAX_PETICION = 16 * 1024  # bytes; ver D-014
SECRET_KEY_DESARROLLO = "dev-no-usar-en-produccion"
MENSAJE_SIN_SECRET_KEY = (
    "Falta la variable de entorno SECRET_KEY. Defínela antes de servir la "
    "aplicación (por ejemplo: export SECRET_KEY=$(python3 -c \"import secrets; "
    "print(secrets.token_hex(32))\")). Solo en modo debug (--debug) o en "
    "pruebas se usa un valor de desarrollo."
)
MENSAJE_COOKIE_SIN_SECURE = (
    "SESSION_COOKIE_SECURE no está activada: la cookie de sesión también viaja por HTTP "
    "sin cifrar. Si sirves la aplicación con HTTPS (lo normal fuera de tu máquina), "
    "define SESSION_COOKIE_SECURE=1."
)
MENSAJE_DEBUG_PUBLICO = (
    "Me niego a arrancar: el modo debug está activo y el servidor escucharía en {host!r}, "
    "que no es una dirección local. En debug la SECRET_KEY es un valor público fijo (cualquiera "
    "podría falsificar una sesión del profesional) y se ofrece un depurador interactivo. "
    "Quita --debug / FLASK_DEBUG o escucha solo en 127.0.0.1."
)
MENSAJE_DEBUG_EN_SERVIDOR = (
    "El modo debug está activo fuera de `flask run`: la SECRET_KEY es un valor público "
    "fijo y cualquiera podría falsificar una sesión. No uses FLASK_DEBUG en un servidor."
)
# Versión de Unicode con la que se probó la política de caracteres del correo (T-03c R-12).
UNICODE_PROBADO = (15, 1, 0)
MENSAJE_UNICODE_ANTIGUO = (
    "Esta versión de Python usa Unicode {actual} y el proyecto se probó con {probado} o más "
    "reciente (Python 3.13+). La política de caracteres del correo juzga cada letra según la "
    "versión de Unicode: un correo con una letra añadida después podría rechazarse al iniciar "
    "sesión aunque la cuenta exista. Usa Python 3.13 o más nuevo."
)
VALORES_VERDADEROS = frozenset({"1", "true", "yes", "on", "si", "sí"})
VALORES_FALSOS = frozenset({"0", "false", "no", "off"})


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        MAX_CONTENT_LENGTH=TAMANO_MAX_PETICION,
        # Cookie de sesión (T-04). HttpOnly ya es el valor por defecto de Flask;
        # se fija para que quede explícito y probado. `Secure` exige HTTPS y se
        # activa con la variable SESSION_COOKIE_SECURE (D-042).
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # D-042: `Secure` se activa con la variable de entorno (HTTPS en producción).
        SESSION_COOKIE_SECURE=_booleano_de_entorno("SESSION_COOKIE_SECURE"),
        # D-045: cuántos proxies propios hay delante (0 = ninguno: X-Forwarded-For se ignora).
        TRUSTED_PROXY_COUNT=_proxies_de_confianza(),
        # T-09: simulación del correo. Vacío = `outbox.log` junto a la base de datos.
        OUTBOX_PATH=os.environ.get("OUTBOX_PATH") or None,
        DATABASE=os.environ.get(
            "DATABASE", os.path.join(app.root_path, os.pardir, "agenda.db")
        ),
    )
    if test_config:
        app.config.update(test_config)

    _preparar_secret_key(app)
    _exigir_debug_solo_local(app)
    _avisar_de_configuracion(app)
    if app.config["TRUSTED_PROXY_COUNT"]:
        # Solo la dirección del cliente (X-Forwarded-For) y solo de los n proxies propios:
        # el cliente no puede falsificarla anteponiendo valores. No se tocan host, esquema
        # ni prefijo.
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=app.config["TRUSTED_PROXY_COUNT"],
            x_proto=0, x_host=0, x_port=0, x_prefix=0,
        )

    from . import db

    db.init_app(app)

    from . import auth, errores, notificaciones, paciente, profesional, seguridad

    # Después de _preparar_secret_key: su before_request (D-008) corre primero.
    seguridad.init_app(app)
    errores.init_app(app)
    app.context_processor(lambda: {"destino_marca": auth.destino_marca})
    app.register_blueprint(auth.bp)
    app.register_blueprint(paciente.bp)
    app.register_blueprint(profesional.bp)
    app.cli.add_command(auth.create_professional_command)
    app.cli.add_command(notificaciones.send_reminders_command)
    auth.preparar_hash_falso(app, calcular_ahora=_se_va_a_servir())

    @app.route("/")
    def inicio():
        return render_template("inicio.html", nombre_proyecto=NOMBRE_PROYECTO)

    return app


def _fallar_configuracion(mensaje):
    """Aborta con un mensaje claro: sin traza dentro de un comando de `flask`, `RuntimeError` fuera."""
    if click.get_current_context(silent=True) is not None:
        raise click.ClickException(mensaje)
    raise RuntimeError(mensaje)


def _booleano_de_entorno(nombre):
    """Lee un valor verdadero/falso explícito de una variable de entorno (D-042).

    Sin definir o vacía: falso. `1/true/yes/on/si` (en cualquier caja y con espacios) es
    verdadero y `0/false/no/off` es falso. Cualquier otro valor se rechaza con un error:
    interpretar en silencio «ON-PLEASE» o «activada» como falso dejaría la cookie sin
    protección sin que nadie lo note.
    """
    bruto = os.environ.get(nombre)
    valor = (bruto or "").strip().lower()
    if not valor or valor in VALORES_FALSOS:
        return False
    if valor in VALORES_VERDADEROS:
        return True
    _fallar_configuracion(
        f"{nombre}={bruto!r} no es un valor válido. Usa 1 (activado) o 0 (desactivado)."
    )


def _proxies_de_confianza():
    """`TRUSTED_PROXY_COUNT`: cantidad de proxies propios delante de la app (entero >= 0)."""
    bruto = os.environ.get("TRUSTED_PROXY_COUNT")
    if bruto is None or not bruto.strip():
        return 0
    try:
        cantidad = int(bruto.strip())
    except ValueError:
        cantidad = -1
    if not 0 <= cantidad <= 10:
        _fallar_configuracion(
            f"TRUSTED_PROXY_COUNT={bruto!r} no es válido. Usa la cantidad de proxies propios "
            "delante de la aplicación (0 si no hay ninguno)."
        )
    return cantidad


def es_host_local(host):
    """True para localhost y las direcciones de bucle local (127.0.0.0/8, ::1)."""
    host = str(host).strip().strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _exigir_debug_solo_local(app):
    """D-043: con debug (o `--debugger`) y un host que no es local, no se arranca.

    El único lugar donde la aplicación conoce el host es el comando `flask run`: sus
    parámetros ya están leídos cuando se carga la app, así que se comprueba aquí, antes
    de abrir el puerto. Cubre `--debug`, `FLASK_DEBUG`, `--host` y `FLASK_RUN_HOST`. Bajo
    `flask run`, Click lee `FLASK_DEBUG` como booleano (`off`, `no`, `false`, `0` = falso,
    comprobado con un servidor real); fuera de `flask run`, `Flask` solo trata `0`, `false`
    y `no` como falso y `off` queda como debug (ver el aviso de abajo). Con otro servidor (gunicorn,
    etc.) el host no se conoce: solo se avisa en el log si hay debug fuera de pruebas.
    """
    contexto = click.get_current_context(silent=True)
    if contexto is None:
        if app.debug and not app.testing:
            app.logger.warning(MENSAJE_DEBUG_EN_SERVIDOR)
        return
    if contexto.command.name != "run":
        return
    host = contexto.params.get("host")
    if host is None:  # contexto sin parámetros (pruebas): `flask run` siempre trae el valor por defecto
        host = "127.0.0.1"
    # `--debugger` aislado también abre el depurador interactivo de Werkzeug.
    if (app.debug or contexto.params.get("debugger") is True) and not es_host_local(host):
        _fallar_configuracion(MENSAJE_DEBUG_PUBLICO.format(host=host))


def _avisar_de_configuracion(app):
    """Avisos al arrancar para servir (no en comandos de mantenimiento ni pruebas)."""
    if not _se_va_a_servir() or app.testing:
        return
    if not app.debug and not app.config.get("SESSION_COOKIE_SECURE"):
        app.logger.warning(MENSAJE_COOKIE_SIN_SECURE)
    actual = tuple(int(parte) for parte in unicodedata.unidata_version.split("."))
    if actual < UNICODE_PROBADO:
        app.logger.warning(
            MENSAJE_UNICODE_ANTIGUO.format(
                actual=unicodedata.unidata_version, probado=".".join(map(str, UNICODE_PROBADO))
            )
        )


def _preparar_secret_key(app):
    """Fija la SECRET_KEY de desarrollo si corresponde y exige la clave al servir.

    No lanza error al crear la app: así los comandos CLI de mantenimiento
    (`init-db`, etc.) funcionan sin clave. La exigencia se aplica en
    `before_request`, por lo que una app sin clave nunca atiende una petición,
    sin importar cómo se sirva (`flask run`, gunicorn, etc.).
    """
    clave = app.config.get("SECRET_KEY")
    if isinstance(clave, str) and clave.strip():
        return  # clave válida: se respeta tal cual, sin modificarla
    # app.config["DEBUG"] ya refleja FLASK_DEBUG (lo fija `flask run --debug`).
    if app.config.get("TESTING") or app.config.get("DEBUG"):
        app.config["SECRET_KEY"] = SECRET_KEY_DESARROLLO
        return
    app.config["SECRET_KEY"] = None  # ausente, vacía o solo espacios
    if _se_va_a_servir():
        app.logger.warning(MENSAJE_SIN_SECRET_KEY)

    @app.before_request
    def exigir_secret_key():
        raise RuntimeError(MENSAJE_SIN_SECRET_KEY)


def _se_va_a_servir():
    """True si esta app se está cargando para atender peticiones.

    Es así con `flask run` (comando `run`) y con un servidor WSGI como gunicorn
    (no hay contexto de click). Los demás comandos CLI (`init-db`,
    `create-professional`, ...) cargan la app sin servir, así que no avisan.
    Solo decide si se muestra un aviso: la exigencia real de la clave sigue
    siendo el `before_request` (D-008), que no depende de esto.
    """
    contexto = click.get_current_context(silent=True)
    return contexto is None or contexto.command.name == "run"
