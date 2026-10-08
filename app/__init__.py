import os

from flask import Flask, render_template

NOMBRE_PROYECTO = "Agenda Psi"
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
        DATABASE=os.environ.get(
            "DATABASE", os.path.join(app.root_path, os.pardir, "agenda.db")
        ),
    )
    if test_config:
        app.config.update(test_config)

    _preparar_secret_key(app)

    from . import db

    db.init_app(app)

    from . import auth, seguridad

    # Después de _preparar_secret_key: su before_request (D-008) corre primero.
    seguridad.init_app(app)
    app.register_blueprint(auth.bp)

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

    @app.before_request
    def exigir_secret_key():
        raise RuntimeError(MENSAJE_SIN_SECRET_KEY)
