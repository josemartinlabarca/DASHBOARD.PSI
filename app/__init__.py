import os

import click
from flask import Flask, render_template

NOMBRE_PROYECTO = "Agenda Psi"
TAMANO_MAX_PETICION = 16 * 1024  # bytes; ver D-014
SECRET_KEY_DESARROLLO = "dev-no-usar-en-produccion"
MENSAJE_SIN_SECRET_KEY = (
    "Falta la variable de entorno SECRET_KEY. Defínela antes de servir la "
    "aplicación (por ejemplo: export SECRET_KEY=$(python3 -c \"import secrets; "
    "print(secrets.token_hex(32))\")). Solo en modo debug (--debug) o en "
    "pruebas se usa un valor de desarrollo."
)


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        MAX_CONTENT_LENGTH=TAMANO_MAX_PETICION,
        # Cookie de sesión (T-04). HttpOnly ya es el valor por defecto de Flask;
        # se fija para que quede explícito y probado. `Secure` exige HTTPS y se
        # activará con el despliegue (T-14): SESSION_COOKIE_SECURE=True.
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # T-09: simulación del correo. Vacío = `outbox.log` junto a la base de datos.
        OUTBOX_PATH=os.environ.get("OUTBOX_PATH") or None,
        DATABASE=os.environ.get(
            "DATABASE", os.path.join(app.root_path, os.pardir, "agenda.db")
        ),
    )
    if test_config:
        app.config.update(test_config)

    _preparar_secret_key(app)

    from . import db

    db.init_app(app)

    from . import auth, notificaciones, paciente, profesional, seguridad

    # Después de _preparar_secret_key: su before_request (D-008) corre primero.
    seguridad.init_app(app)
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
