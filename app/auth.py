"""Autenticación. Por ahora solo el registro de pacientes (T-03)."""
import re
import sqlite3
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Blueprint, flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from .correo import normalizar_email
from .db import get_db

bp = Blueprint("auth", __name__)

ZONA_CHILE = "America/Santiago"
NOMBRE_MAX = 100
EMAIL_MAX = 254
PASSWORD_MIN = 8
PASSWORD_MAX = 128
PATRON_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MENSAJE_EMAIL_INVALIDO = "Escribe un correo válido, por ejemplo nombre@ejemplo.cl."
MENSAJE_SIN_ZONA_HORARIA = (
    "No hay datos de zona horaria en el sistema. Instala el paquete tzdata "
    "(pip install -r requirements.txt) para poder registrar fechas de Chile."
)
MENSAJE_DUPLICADO = (
    "No pudimos registrarte con ese correo. Si ya tienes una cuenta, inicia "
    "sesión; si no, prueba con otro correo."
)


@lru_cache(maxsize=1)
def zona_chile():
    """`ZoneInfo` de Chile, creado al usarlo y no al importar (D-012).

    Así `create_app()` y `init-db` funcionan aunque falten los datos de zona
    horaria; solo falla (con un mensaje claro) lo que de verdad los necesita.
    """
    try:
        return ZoneInfo(ZONA_CHILE)
    except ZoneInfoNotFoundError as error:
        raise RuntimeError(MENSAJE_SIN_ZONA_HORARIA) from error


def validar_registro(nombre, email, password):
    """Devuelve un diccionario campo -> mensaje de error (vacío si todo está bien)."""
    errores = {}
    if not nombre:
        errores["nombre"] = "Escribe tu nombre."
    elif len(nombre) > NOMBRE_MAX:
        errores["nombre"] = f"El nombre no puede superar los {NOMBRE_MAX} caracteres."
    if not email:
        errores["email"] = "Escribe tu correo."
    elif len(email) > EMAIL_MAX or not PATRON_EMAIL.match(email):
        errores["email"] = MENSAJE_EMAIL_INVALIDO
    if len(password) < PASSWORD_MIN:
        errores["password"] = f"La contraseña debe tener al menos {PASSWORD_MIN} caracteres."
    elif len(password) > PASSWORD_MAX:
        errores["password"] = f"La contraseña no puede superar los {PASSWORD_MAX} caracteres."
    return errores


@bp.route("/registro", methods=["GET", "POST"])
def registro():
    if request.method == "GET":
        return render_template("registro.html", nombre="", email="", errores={})

    nombre = request.form.get("nombre", "").strip()
    email_bruto = request.form.get("email", "")
    try:
        email = normalizar_email(email_bruto)
        email_rechazado = False
    except ValueError:
        email = email_bruto.strip()  # se vuelve a mostrar tal cual (escapado)
        email_rechazado = True
    password = request.form.get("password", "")  # sin recortar
    errores = validar_registro(nombre, email, password)
    if email_rechazado:
        errores["email"] = MENSAJE_EMAIL_INVALIDO

    if not errores:
        db = get_db()
        try:
            db.execute(
                "INSERT INTO usuarios (nombre, email, password_hash, rol, creado_en)"
                " VALUES (?, ?, ?, 'paciente', ?)",
                (
                    nombre,
                    email,
                    generate_password_hash(password),
                    datetime.now(zona_chile()).isoformat(timespec="seconds"),
                ),
            )
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            errores["email"] = MENSAJE_DUPLICADO
        else:
            flash("Tu cuenta fue creada correctamente.", "exito")
            return redirect(url_for("inicio"))

    return render_template("registro.html", nombre=nombre, email=email, errores=errores)
