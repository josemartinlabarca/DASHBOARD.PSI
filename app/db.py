"""Conexión SQLite, `init-db` y comprobaciones del esquema (D-006, D-050).

`init-db` es **aditivo**: crea lo que falta (tablas, índices, la columna `usuarios.sesion_version`)
y anota la versión del esquema en `PRAGMA user_version`; nunca borra ni reescribe datos y nunca
reconstruye una tabla existente. Lo que no puede arreglar sin reconstruir (restricciones nuevas
de tablas antiguas) lo avisa, sin tocarlo. Detalle en D-050.
"""
import os
import re
import sqlite3

import click
from flask import current_app, g
from flask.cli import with_appcontext
from werkzeug.routing import BaseConverter, ValidationError

# Versión del esquema que escribe `init-db` en `PRAGMA user_version`. Una base creada por una
# versión anterior (T-14a o antes) tiene 0. Sube este número cuando `schema.sql` exija algo
# que una base vieja no tiene y que `init-db` pueda agregar sin reconstruir tablas.
VERSION_ESQUEMA = 1

# Tiempo de espera del bloqueo de escritura de SQLite (el valor por defecto de `sqlite3`).
# Se puede cambiar con la configuración `DATABASE_TIMEOUT` (solo las pruebas lo hacen).
TIMEOUT_DEFECTO_S = 5.0

ID_MAX = 2**63 - 1  # mayor INTEGER de SQLite: un id mayor es 404, no 500 (T-05 R-10)

TABLAS_REQUERIDAS = frozenset({"usuarios", "horas", "notificaciones", "intentos_acceso"})

MENSAJE_BASE_OCUPADA = (
    "El sistema está ocupado en este momento. Espera unos segundos e inténtalo de nuevo."
)
MENSAJE_BASE_ANTIGUA = (
    "La base de datos de la aplicación es de una versión anterior y necesita actualizarse. "
    "Avisa a quien administra el sistema: debe ejecutar «flask --app app init-db» "
    "(no borra datos)."
)
MENSAJE_BASE_ANTIGUA_LOG = (
    "La base de datos {ruta} es de una versión anterior (PRAGMA user_version = {version}, se "
    "necesita {necesaria}) y falló una consulta ({error}). Ejecuta `flask --app app init-db`: "
    "agrega lo que falta sin borrar datos."
)


def get_db():
    """Devuelve la conexión de la petición actual (se crea una sola vez)."""
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["DATABASE"],
            timeout=current_app.config.get("DATABASE_TIMEOUT", TIMEOUT_DEFECTO_S),
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


class ConvertidorId(BaseConverter):
    """Id de ruta: solo dígitos ASCII, sin ceros a la izquierda, de 1 a `ID_MAX` (T-05 R-06).

    El convertidor `int` de Werkzeug acepta cualquier dígito Unicode (`%D9%A1` es el 1 en
    árabe-índico, `%EF%BC%91` el 1 de ancho completo) y ceros a la izquierda: varias direcciones
    distintas llegaban a la misma hora. Aquí cada hora tiene UNA dirección; el resto es 404.
    """

    regex = r"[1-9][0-9]{0,18}"

    def to_python(self, valor):
        numero = int(valor)
        if numero > ID_MAX:
            raise ValidationError()
        return numero

    def to_url(self, valor):
        return str(int(valor))


# ------------------------------------------------------------ base ocupada ----


def esta_ocupada(error):
    """True si `error` es SQLite diciendo que otro proceso retiene el bloqueo (BUSY o LOCKED)."""
    if not isinstance(error, sqlite3.OperationalError):
        return False
    codigo = getattr(error, "sqlite_errorcode", None)
    if codigo is not None:
        return (codigo & 0xFF) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
    return "locked" in str(error) or "busy" in str(error)


# ---------------------------------------------------------- versión de esquema ----


def version_esquema(db):
    """`PRAGMA user_version` de la base (0 si nunca pasó por el `init-db` de T-14b o posterior)."""
    return db.execute("PRAGMA user_version").fetchone()[0]


def es_esquema_antiguo(error):
    """True si `error` es «no such table/column» y la base no tiene la versión de esquema actual.

    Es el síntoma de actualizar el código sin correr `init-db` (T-14a R-09). Si la base SÍ está
    al día, un «no such column» es un fallo del programa y no se disfraza. Nunca lanza: si no se
    puede ni leer la versión, no es este caso.
    """
    if not isinstance(error, sqlite3.OperationalError):
        return False
    texto = str(error)
    if "no such table" not in texto and "no such column" not in texto:
        return False
    try:
        version = version_esquema(get_db())
    except sqlite3.Error:
        return False
    if version >= VERSION_ESQUEMA:
        return False
    current_app.logger.error(
        MENSAJE_BASE_ANTIGUA_LOG.format(
            ruta=current_app.config["DATABASE"], version=version,
            necesaria=VERSION_ESQUEMA, error=texto,
        )
    )
    return True


# -------------------------------------------------------------- init-db ----


class Informe:
    """Resultado de `inicializar`: `acciones` (lo que se hizo) y `avisos` (lo que no se pudo)."""

    def __init__(self):
        self.base_nueva = False
        self.acciones = []
        self.avisos = []


def _tablas(db):
    return {
        f[0]
        for f in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _indices(db):
    return {
        f[0]
        for f in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _columnas(db, tabla):
    return [c[1] for c in db.execute(f"PRAGMA table_info({tabla})")]


def _normalizar(sql):
    """Texto de un `CREATE` sin espacios ni mayúsculas, para comparar dos definiciones."""
    return re.sub(r"\s+", "", sql or "").lower()


def _definiciones(db):
    return {
        f[0]: _normalizar(f[1])
        for f in db.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _texto_del_esquema():
    with current_app.open_resource("schema.sql") as archivo:
        return archivo.read().decode("utf-8")


def _tablas_distintas_del_esquema(db, texto_esquema):
    """Tablas existentes cuya definición no es la de `schema.sql` (les faltan restricciones)."""
    referencia = sqlite3.connect(":memory:")
    try:
        referencia.executescript(texto_esquema)
        esperadas = _definiciones(referencia)
    finally:
        referencia.close()
    actuales = _definiciones(db)
    return sorted(t for t, sql in actuales.items() if t in esperadas and sql != esperadas[t])


def _profesionales_de_mas(db):
    """Cuántos profesionales hay (0 si no hay tabla `usuarios` o columna `rol`)."""
    if "rol" not in _columnas(db, "usuarios"):
        return 0
    return db.execute("SELECT COUNT(*) FROM usuarios WHERE rol = 'profesional'").fetchone()[0]


MENSAJE_DOS_PROFESIONALES = (
    "La base tiene {cantidad} profesionales y esta versión admite uno solo (D-004, D-023): no se "
    "puede crear el índice un_solo_profesional. No se cambió nada. Decide cuál cuenta conservar "
    "y elimina las demás (por ejemplo con sqlite3: DELETE FROM usuarios WHERE id = <id>; antes "
    "hay que borrar sus horas y notificaciones), o usa otra base. Luego vuelve a ejecutar init-db."
)
MENSAJE_TABLA_ANTIGUA = (
    "La tabla {tabla} se creó con un esquema anterior y no tiene todas las restricciones actuales "
    "(CHECK, claves foráneas o UNIQUE de versiones posteriores). Funciona, pero sin esas "
    "protecciones. init-db no reconstruye tablas existentes (D-006). Si no necesitas sus datos, "
    "borra el archivo de la base y vuelve a ejecutar init-db (ver README)."
)
MENSAJE_BASE_MAS_NUEVA = (
    "Esta base la preparó una versión más nueva de la aplicación (user_version {version}, esta "
    "versión conoce {conocida}). No se cambió su número."
)


def inicializar(db):
    """Deja la base con todo lo que `schema.sql` define y que se puede agregar sin destruir nada.

    Pasos, en una sola transacción (si algo falla no queda nada a medias):
    1. Si hay más de un profesional, se detiene SIN cambiar nada (`ClickException`): el índice
       `un_solo_profesional` no se puede crear y seguir sería dejar una base a medias.
    2. Si `usuarios` existe sin `sesion_version`, la agrega (`ALTER TABLE ... ADD COLUMN`, con valor
       por defecto 0: no reescribe filas).
    3. Ejecuta `schema.sql` (`CREATE ... IF NOT EXISTS`): crea las tablas e índices que falten.
    4. Escribe `PRAGMA user_version = VERSION_ESQUEMA` (si era menor).
    Después compara las tablas con `schema.sql` y avisa de las que son de un esquema anterior
    (no las toca). Devuelve un `Informe`.
    """
    informe = Informe()
    tablas_antes, indices_antes = _tablas(db), _indices(db)
    informe.base_nueva = not tablas_antes
    texto = _texto_del_esquema()
    if "usuarios" in tablas_antes:
        cantidad = _profesionales_de_mas(db)
        if cantidad > 1:
            raise click.ClickException(MENSAJE_DOS_PROFESIONALES.format(cantidad=cantidad))
    version = version_esquema(db)
    pasos = ["BEGIN IMMEDIATE;"]
    if "usuarios" in tablas_antes and "sesion_version" not in _columnas(db, "usuarios"):
        pasos.append("ALTER TABLE usuarios ADD COLUMN sesion_version INTEGER NOT NULL DEFAULT 0;")
        informe.acciones.append("se agregó la columna usuarios.sesion_version")
    pasos.append(texto)
    if version < VERSION_ESQUEMA:
        pasos.append(f"PRAGMA user_version = {int(VERSION_ESQUEMA)};")
    pasos.append("COMMIT;")
    try:
        db.executescript("\n".join(pasos))
    except BaseException:
        if db.in_transaction:
            db.rollback()
        raise
    if not informe.base_nueva:
        for tabla in sorted(_tablas(db) - tablas_antes):
            informe.acciones.append(f"se creó la tabla {tabla}")
        for indice in sorted(_indices(db) - indices_antes):
            informe.acciones.append(f"se creó el índice {indice}")
        for tabla in _tablas_distintas_del_esquema(db, texto):
            informe.avisos.append(MENSAJE_TABLA_ANTIGUA.format(tabla=tabla))
    if version > VERSION_ESQUEMA:
        informe.avisos.append(
            MENSAJE_BASE_MAS_NUEVA.format(version=version, conocida=VERSION_ESQUEMA)
        )
    return informe


def init_db():
    """Crea o completa las tablas; no borra datos existentes (D-006, D-050). Devuelve el `Informe`."""
    return inicializar(get_db())


@click.command("init-db")
@with_appcontext
def init_db_command():
    """Crea las tablas de la base de datos o completa las que faltan (sin borrar datos)."""
    informe = inicializar(get_db())
    if informe.acciones:
        click.echo("Base de datos actualizada: " + "; ".join(informe.acciones) + ".")
    else:
        click.echo("Base de datos inicializada.")
    for aviso in informe.avisos:
        click.echo(f"Aviso: {aviso}", err=True)


# ------------------------------------------------- comandos que exigen la base ----

MENSAJE_SIN_BASE = (
    "No existe la base de datos {ruta}. Revisa la variable DATABASE (el comando debe ver la "
    "misma que el servidor) o créala con: flask --app app init-db"
)
MENSAJE_SIN_CARPETA = (
    "No existe la carpeta de la base de datos ({carpeta}), así que no hay base en {ruta}. "
    "Revisa la variable DATABASE."
)
MENSAJE_BASE_ES_CARPETA = "{ruta} es una carpeta, no un archivo de base de datos. Revisa DATABASE."
MENSAJE_SIN_TABLAS = (
    "La base de datos {ruta} no tiene las tablas {faltan}. Ejecuta: flask --app app init-db"
)
MENSAJE_BASE_ILEGIBLE = (
    "No se pudo leer la base de datos {ruta} ({error}). ¿Es un archivo de SQLite? Revisa DATABASE."
)
MENSAJE_COMANDO_BASE_OCUPADA = (
    "La base de datos está ocupada (otro proceso la tiene bloqueada). No se cambió nada; "
    "vuelve a ejecutar el comando en unos segundos."
)


def abrir_base_existente():
    """Conexión a una base que YA existe y tiene sus tablas; si no, `ClickException` sin traza.

    Para los comandos de mantenimiento que no deben crear una base (`send-reminders`,
    `create-professional`): `sqlite3.connect` crearía un archivo vacío ante un error de tipeo en
    `DATABASE`. Aquí se comprueba el archivo ANTES de conectar (T-10 R-01).
    """
    ruta = current_app.config["DATABASE"]
    if os.path.isdir(ruta):
        raise click.ClickException(MENSAJE_BASE_ES_CARPETA.format(ruta=ruta))
    if not os.path.isfile(ruta):
        carpeta = os.path.dirname(os.path.abspath(ruta))
        if not os.path.isdir(carpeta):
            raise click.ClickException(MENSAJE_SIN_CARPETA.format(carpeta=carpeta, ruta=ruta))
        raise click.ClickException(MENSAJE_SIN_BASE.format(ruta=ruta))
    db = get_db()
    try:
        presentes = _tablas(db)
    except sqlite3.Error as error:
        if esta_ocupada(error):
            raise click.ClickException(MENSAJE_COMANDO_BASE_OCUPADA) from error
        raise click.ClickException(MENSAJE_BASE_ILEGIBLE.format(ruta=ruta, error=error)) from error
    faltan = sorted(TABLAS_REQUERIDAS - presentes)
    if faltan:
        raise click.ClickException(MENSAJE_SIN_TABLAS.format(ruta=ruta, faltan=", ".join(faltan)))
    return db


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
