import os

from flask import Flask, render_template

NOMBRE_PROYECTO = "Agenda Psi"


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-no-usar-en-produccion"),
        DATABASE=os.environ.get(
            "DATABASE", os.path.join(app.root_path, os.pardir, "agenda.db")
        ),
    )
    if test_config:
        app.config.update(test_config)

    from . import db

    db.init_app(app)

    @app.route("/")
    def inicio():
        return render_template("inicio.html", nombre_proyecto=NOMBRE_PROYECTO)

    return app
