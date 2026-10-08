"""Autenticación: registro (T-03), login, logout y control de rol (T-04)."""
import re
import secrets
import sqlite3
import threading
import unicodedata
from datetime import datetime
from functools import lru_cache, wraps
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import click
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask.cli import with_appcontext
from werkzeug.security import check_password_hash, generate_password_hash

from .correo import normalizar_email
from .db import get_db
from .seguridad import generar_token

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
MENSAJE_NOMBRE_CARACTERES = (
    "El nombre no puede incluir saltos de línea ni caracteres de control o invisibles."
)
MENSAJE_LOGIN_INVALIDO = "Correo o contraseña incorrectos."
CLAVE_SESION_USUARIO = "usuario_id"


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


def es_correo_duplicado(error):
    """True solo si `error` es la violación de UNIQUE sobre `usuarios.email`.

    Cualquier otra `IntegrityError` (NOT NULL, CHECK, clave foránea, UNIQUE de
    otra columna) es un fallo del programa y no debe presentarse al usuario
    como «correo duplicado» (hallazgo 7 de la revisión de T-02c).
    """
    return (
        getattr(error, "sqlite_errorcode", None) == sqlite3.SQLITE_CONSTRAINT_UNIQUE
        and "UNIQUE constraint failed: usuarios.email" in str(error)
    )


def crear_usuario(db, nombre, email, password, rol):
    """Inserta un usuario y confirma. `email` ya viene normalizado.

    Lanza `sqlite3.IntegrityError` si la base rechaza la fila; quien llama
    decide qué hacer (ver `es_correo_duplicado`). Es el único lugar que hashea
    contraseñas al crear cuentas.
    """
    db.execute(
        "INSERT INTO usuarios (nombre, email, password_hash, rol, creado_en)"
        " VALUES (?, ?, ?, ?, ?)",
        (
            nombre,
            email,
            generate_password_hash(password),
            rol,
            datetime.now(zona_chile()).isoformat(timespec="seconds"),
        ),
    )
    db.commit()


def tiene_caracteres_no_permitidos(texto):
    """True si `texto` trae categorías `C*` (control, formato/bidi, uso privado...)
    o separadores de línea/párrafo (`Zl`, `Zp`). Los espacios internos normales,
    tildes, ñ, guiones y apóstrofes no entran aquí."""
    return any(
        unicodedata.category(c).startswith("C") or unicodedata.category(c) in ("Zl", "Zp")
        for c in texto
    )


def validar_registro(nombre, email, password):
    """Devuelve un diccionario campo -> mensaje de error (vacío si todo está bien)."""
    errores = {}
    if not nombre:
        errores["nombre"] = "Escribe tu nombre."
    elif len(nombre) > NOMBRE_MAX:
        errores["nombre"] = f"El nombre no puede superar los {NOMBRE_MAX} caracteres."
    elif tiene_caracteres_no_permitidos(nombre):
        errores["nombre"] = MENSAJE_NOMBRE_CARACTERES
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
            crear_usuario(db, nombre, email, password, "paciente")
        except sqlite3.IntegrityError as error:
            db.rollback()
            if not es_correo_duplicado(error):
                raise  # cualquier otra violación es un error interno (500)
            errores["email"] = MENSAJE_DUPLICADO
        else:
            flash("Tu cuenta fue creada correctamente.", "exito")
            return redirect(url_for("inicio"))

    return render_template("registro.html", nombre=nombre, email=email, errores=errores)


# ---------------------------------------------------------------- login ----


class HashFalso:
    """Hash de una contraseña aleatoria que nadie conoce, con el costo normal.

    Se verifica cuando el usuario no existe (o el correo es inaceptable) para
    que esa respuesta tarde lo mismo que la de una contraseña errónea. Se usa
    el mismo `generate_password_hash` del registro, así que tiene el costo real.
    `obtener()` es seguro entre hilos: aunque lleguen varias peticiones a la vez
    antes de que exista, el hash se calcula una sola vez (R-06).
    """

    def __init__(self):
        self._candado = threading.Lock()
        self._valor = None

    def obtener(self):
        if self._valor is None:
            with self._candado:
                if self._valor is None:
                    self._valor = generate_password_hash(secrets.token_urlsafe(16))
        return self._valor


def preparar_hash_falso(app, calcular_ahora):
    """Crea el `HashFalso` de la app; lo calcula ya si la app va a servir.

    En `flask run`, gunicorn y pruebas se calcula al construir la app, así el
    primer login de un correo inexistente no es más lento (R-06). En los
    comandos CLI de mantenimiento (`init-db`, `create-professional`...) no se
    calcula: sumaría ~0,15 s de scrypt que no usan (se calcularía igual, bajo
    candado, si alguna vez lo necesitaran).
    """
    app.extensions["hash_falso"] = HashFalso()
    if calcular_ahora:
        app.extensions["hash_falso"].obtener()


def hash_falso():
    return current_app.extensions["hash_falso"].obtener()


def buscar_usuario_por_credenciales(email_bruto, password):
    """Devuelve la fila del usuario si las credenciales son correctas; si no, `None`.

    Siempre se ejecuta exactamente un `check_password_hash`, exista o no el
    correo y sea aceptable o no, y no se distingue el motivo del rechazo.
    Una contraseña más larga que `PASSWORD_MAX` nunca puede ser la correcta
    (el registro no las admite): se verifica una cadena vacía para no pagar el
    costo de hashear texto arbitrariamente largo, y se rechaza igualmente.
    """
    try:
        email = normalizar_email(email_bruto)
    except ValueError:
        email = ""
    fila = None
    if email and len(email) <= EMAIL_MAX:
        fila = get_db().execute(
            "SELECT id, password_hash, rol FROM usuarios WHERE email = ?", (email,)
        ).fetchone()
    demasiado_larga = len(password) > PASSWORD_MAX
    candidata = "" if demasiado_larga else password
    hash_guardado = fila["password_hash"] if fila else hash_falso()
    correcta = check_password_hash(hash_guardado, candidata)
    if fila is None or demasiado_larga or not correcta:
        return None
    return fila


def iniciar_sesion(usuario_id):
    """Sesión nueva solo con el id y token CSRF nuevo (evita fijación de sesión)."""
    session.clear()
    session[CLAVE_SESION_USUARIO] = usuario_id
    generar_token()


def cerrar_sesion():
    session.clear()
    generar_token()


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html", email="", error=None)

    email_bruto = request.form.get("email", "")
    password = request.form.get("password", "")  # sin recortar
    usuario = buscar_usuario_por_credenciales(email_bruto, password)
    if usuario is None:
        return render_template(
            "login.html", email=email_bruto.strip(), error=MENSAJE_LOGIN_INVALIDO
        )
    iniciar_sesion(usuario["id"])
    return redirect(url_for(f"{usuario['rol']}.dashboard"))


# ----------------------------------------------------------- decoradores ----


def _es_id_valido(valor):
    """Un entero positivo que cabe en un INTEGER de SQLite (no `bool`)."""
    return isinstance(valor, int) and not isinstance(valor, bool) and 0 < valor < 2**63


def usuario_actual():
    """Fila (id, nombre, rol) del usuario de la sesión, o `None`.

    La sesión guarda solo el id; el rol se lee siempre de la base, así que un
    cambio de rol o un usuario borrado surte efecto en la siguiente petición.
    """
    if "usuario_actual" not in g:
        usuario_id = session.get(CLAVE_SESION_USUARIO)
        g.usuario_actual = None
        if _es_id_valido(usuario_id):
            g.usuario_actual = get_db().execute(
                "SELECT id, nombre, rol FROM usuarios WHERE id = ?", (usuario_id,)
            ).fetchone()
    return g.usuario_actual


def _exigir(rol=None):
    """Decorador: sin sesión redirige a /login; con otro rol responde 403."""

    def decorador(vista):
        @wraps(vista)
        def envoltura(*args, **kwargs):
            usuario = usuario_actual()
            if usuario is None:
                return redirect(url_for("auth.login"))
            if rol is not None and usuario["rol"] != rol:
                abort(make_response(render_template("acceso_denegado.html"), 403))
            return vista(*args, **kwargs)

        return envoltura

    return decorador


login_requerido = _exigir()
solo_paciente = _exigir("paciente")
solo_profesional = _exigir("profesional")


@bp.route("/logout", methods=["POST"])
@login_requerido
def logout():
    cerrar_sesion()
    return redirect(url_for("inicio"))


# ------------------------------------------------- create-professional ----


@click.command("create-professional")
@click.option("--email", required=True, help="Correo del profesional.")
@click.option("--nombre", required=True, help="Nombre del profesional.")
@with_appcontext
def create_professional_command(email, nombre):
    """Crea la cuenta del profesional. La contraseña se pide sin eco.

    La contraseña no se acepta como opción: así no queda en la lista de
    procesos ni en el historial del intérprete de comandos. Se escribe en el
    aviso interactivo (sin mostrarse) y se pide dos veces.
    """
    nombre = nombre.strip()
    try:
        email = normalizar_email(email)
        email_rechazado = False
    except ValueError:
        email_rechazado = True
    password = click.prompt("Contraseña", hide_input=True, confirmation_prompt=True)
    errores = validar_registro(nombre, "" if email_rechazado else email, password)
    if email_rechazado:
        errores["email"] = MENSAJE_EMAIL_INVALIDO
    if errores:
        raise click.ClickException(" ".join(errores.values()))
    db = get_db()
    try:
        crear_usuario(db, nombre, email, password, "profesional")
    except sqlite3.IntegrityError as error:
        db.rollback()
        if not es_correo_duplicado(error):
            raise
        raise click.ClickException("Ya existe un usuario con ese correo.") from error
    click.echo(f"Profesional creado: {email}")
