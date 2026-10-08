import sqlite3

import click
from flask import current_app, g
from flask.cli import with_appcontext


def get_db():
    """Devuelve la conexión de la petición actual (se crea una sola vez)."""
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Crea las tablas que falten; no borra datos existentes."""
    db = get_db()
    with current_app.open_resource("schema.sql") as archivo:
        db.executescript(archivo.read().decode("utf-8"))
    db.commit()


@click.command("init-db")
@with_appcontext
def init_db_command():
    """Crea las tablas de la base de datos (sin borrar datos existentes)."""
    init_db()
    click.echo("Base de datos inicializada.")


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
