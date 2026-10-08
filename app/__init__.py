import os

from flask import Flask, render_template

NOMBRE_PROYECTO = "Agenda Psi"
SECRET_KEY_DESARROLLO = "dev-no-usar-en-produccion"


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

    _validar_secret_key(app)

    from . import db

    db.init_app(app)

    @app.route("/")
    def inicio():
        return render_template("inicio.html", nombre_proyecto=NOMBRE_PROYECTO)

    return app


def _validar_secret_key(app):
    """Exige SECRET_KEY salvo en debug/testing, donde usa un valor de desarrollo."""
    if app.config.get("SECRET_KEY"):
        return
    # app.config["DEBUG"] ya refleja FLASK_DEBUG (lo fija `flask run --debug`).
    if app.config.get("TESTING") or app.config.get("DEBUG"):
        app.config["SECRET_KEY"] = SECRET_KEY_DESARROLLO
        return
    raise RuntimeError(
        "Falta la variable de entorno SECRET_KEY. Defínela antes de iniciar la "
        "aplicación (por ejemplo: export SECRET_KEY=$(python3 -c \"import secrets; "
        "print(secrets.token_hex(32))\")). Solo en modo debug (--debug) o en "
        "pruebas se usa un valor de desarrollo."
    )
