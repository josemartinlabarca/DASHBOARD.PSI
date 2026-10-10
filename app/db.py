"""Conexión SQLite, `init-db` y comprobaciones del esquema (D-006, D-050).

`init-db` es **aditivo**: crea lo que falta (tablas, índices, la columna `usuarios.sesion_version`)
y anota la versión del esquema en `PRAGMA user_version`; nunca borra ni reescribe datos y nunca
reconstruye una tabla existente. Lo que no puede arreglar sin reconstruir (restricciones nuevas
de tablas antiguas) lo avisa, sin tocarlo. Detalle en D-050.
"""
import contextlib
import os
import re
import sqlite3
from pathlib import Path

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


def regex_de_ids_hasta(maximo):
    """Expresión regular de los enteros decimales de 1 a `maximo`, sin ceros a la izquierda.

    Sin grupos de captura (Werkzeug la envuelve en uno propio). Se construye cifra a cifra: los
    números con menos cifras que `maximo`, y los de igual largo que se separan de `maximo` en la
    primera cifra menor, más `maximo` mismo. Así un id mayor al máximo ni siquiera coincide con la
    ruta (404 para cualquier método) y no hace falta rechazarlo después (T-14b R-10: la validación
    en `to_python` dejaba el GET de una ruta solo-POST en 405).
    """
    cifras = str(maximo)
    alternativas = [rf"[1-9][0-9]{{0,{len(cifras) - 2}}}"] if len(cifras) > 1 else []
    for i, cifra in enumerate(cifras):
        minima = "1" if i == 0 else "0"
        if cifra > minima:
            alternativas.append(
                f"{cifras[:i]}[{minima}-{int(cifra) - 1}][0-9]{{{len(cifras) - i - 1}}}"
            )
    alternativas.append(cifras)
    return "|".join(alternativas)


class ConvertidorId(BaseConverter):
    """Id de ruta: solo dígitos ASCII, sin ceros a la izquierda, de 1 a `ID_MAX` (T-05 R-06).

    El convertidor `int` de Werkzeug acepta cualquier dígito Unicode (`%D9%A1` es el 1 en
    árabe-índico, `%EF%BC%91` el 1 de ancho completo) y ceros a la izquierda: varias direcciones
    distintas llegaban a la misma hora. Aquí cada hora tiene UNA dirección; el resto es 404.
    """

    regex = regex_de_ids_hasta(ID_MAX)

    def to_python(self, valor):
        numero = int(valor)
        if numero > ID_MAX:  # no debería ocurrir: la expresión ya lo excluye
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
        self.sin_cambios = False  # base de una versión más nueva: no se tocó
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
# T-14c (a), R-01 de la revisión de T-14b: la FK `notificaciones.hora_id` sin `ON DELETE SET NULL`
# (D-016) NO es inocua: eliminar una hora libre que tuvo avisos (reservar -> cancelar -> eliminar)
# falla. `init-db` no puede arreglarla sin reconstruir la tabla (D-006), así que da el
# procedimiento. Lo ve cada vez que se ejecuta `init-db`, también con `user_version` ya anotado.
MENSAJE_FK_SIN_SET_NULL = (
    "La tabla notificaciones es de un esquema anterior a D-016: su clave foránea hora_id no tiene "
    "ON DELETE SET NULL. Consecuencia: el profesional NO podrá eliminar una hora que alguna vez "
    "tuvo avisos (por ejemplo una reserva que se canceló): la aplicación responderá con un "
    "mensaje de error y la hora seguirá en la agenda. Reservar, cancelar y el resto funcionan, y no "
    "se perderá ningún dato. init-db no reconstruye tablas, así que no cambió nada. Para corregirlo: "
    "1) detén el servidor y guarda una copia: cp {ruta} {ruta}.respaldo ; 2) si es una base de "
    "práctica y no necesitas sus datos, borra {ruta} y vuelve a ejecutar «flask --app app "
    "init-db» (se pierden usuarios, horas y avisos); 3) si necesitas los datos, déjala como está y "
    "evita eliminar horas que ya tuvieron reservas hasta que se decida cómo reconstruir la tabla "
    "(ver README, «Bases creadas por versiones antiguas», y D-052)."
)
MENSAJE_FK_SIN_SET_NULL_LOG = (
    "La base {ruta} tiene notificaciones.hora_id sin ON DELETE SET NULL (esquema anterior a "
    "D-016): eliminar una hora que tuvo avisos fallará. Ejecuta `flask --app app init-db` para ver "
    "el procedimiento (README, «Bases creadas por versiones antiguas»)."
)
MENSAJE_BASE_MAS_NUEVA = (
    "Esta base la preparó una versión más nueva de la aplicación (user_version {version}, esta "
    "versión conoce {conocida}). No se cambió nada: ni su número ni sus tablas ni sus índices."
)


def fk_de_avisos_sin_set_null(db):
    """True si `notificaciones.hora_id` tiene una FK hacia `horas` SIN `ON DELETE SET NULL`.

    Es el caso de las bases creadas con los esquemas `748f18e` y `cd9f209` (antes de T-02f/D-016).
    `PRAGMA foreign_key_list` devuelve (id, seq, tabla, desde, hasta, on_update, on_delete, match).
    Sin tabla, sin la columna o sin FK no hay nada que avisar (False): sin FK no hay error al borrar.
    """
    for fila in db.execute("PRAGMA foreign_key_list(notificaciones)"):
        if fila[2] == "horas" and fila[3] == "hora_id":
            return str(fila[6]).upper() != "SET NULL"
    return False


def _sentencias(texto):
    """Las sentencias de un script SQL, una por una (`executescript` haría COMMIT por su cuenta)."""
    pendiente = ""
    for linea in texto.splitlines(keepends=True):
        pendiente += linea
        if sqlite3.complete_statement(pendiente):
            yield pendiente.strip()
            pendiente = ""
    resto = "\n".join(l for l in pendiente.splitlines() if l.strip() and not l.strip().startswith("--"))
    if resto.strip():
        yield pendiente.strip()


def inicializar(db):
    """Deja la base con todo lo que `schema.sql` define y que se puede agregar sin destruir nada.

    TODO el estado se lee y se decide DENTRO de `BEGIN IMMEDIATE` (T-14b R-02: dos `init-db`
    simultáneos decidían con datos viejos y el segundo repetía el `ALTER TABLE`). Pasos, en una sola
    transacción (si algo falla no queda nada a medias):
    0. Si la base es de una versión MÁS NUEVA (`user_version` mayor y con tablas), no toca nada: avisa.
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
    db.execute("BEGIN IMMEDIATE")
    try:
        tablas_antes, indices_antes = _tablas(db), _indices(db)
        informe.base_nueva = not tablas_antes
        version = version_esquema(db)
        if tablas_antes and version > VERSION_ESQUEMA:
            db.rollback()
            informe.sin_cambios = True
            informe.avisos.append(
                MENSAJE_BASE_MAS_NUEVA.format(version=version, conocida=VERSION_ESQUEMA)
            )
            return informe
        if "usuarios" in tablas_antes:
            cantidad = _profesionales_de_mas(db)
            if cantidad > 1:
                raise click.ClickException(MENSAJE_DOS_PROFESIONALES.format(cantidad=cantidad))
        texto = _texto_del_esquema()
        if "usuarios" in tablas_antes and "sesion_version" not in _columnas(db, "usuarios"):
            db.execute("ALTER TABLE usuarios ADD COLUMN sesion_version INTEGER NOT NULL DEFAULT 0")
            informe.acciones.append("se agregó la columna usuarios.sesion_version")
        for sentencia in _sentencias(texto):
            db.execute(sentencia)
        if version < VERSION_ESQUEMA:
            db.execute(f"PRAGMA user_version = {int(VERSION_ESQUEMA)}")
        db.commit()
    except BaseException:
        if db.in_transaction:
            db.rollback()
        raise
    if not informe.base_nueva:
        for tabla in sorted(_tablas(db) - tablas_antes):
            informe.acciones.append(f"se creó la tabla {tabla}")
        for indice in sorted(_indices(db) - indices_antes):
            informe.acciones.append(f"se creó el índice {indice}")
        sin_set_null = fk_de_avisos_sin_set_null(db)
        for tabla in _tablas_distintas_del_esquema(db, texto):
            if tabla == "notificaciones" and sin_set_null:
                continue  # lo dice el aviso específico, que es el que importa
            informe.avisos.append(MENSAJE_TABLA_ANTIGUA.format(tabla=tabla))
        if sin_set_null:
            informe.avisos.append(
                MENSAJE_FK_SIN_SET_NULL.format(ruta=current_app.config["DATABASE"])
            )
    return informe


def init_db():
    """Crea o completa las tablas; no borra datos existentes (D-006, D-050). Devuelve el `Informe`."""
    return inicializar(get_db())


@click.command("init-db")
@with_appcontext
def init_db_command():
    """Crea las tablas de la base de datos o completa las que faltan (sin borrar datos).

    Ante un problema con el archivo (no es SQLite, está dañado, es una carpeta, la carpeta no
    existe, es de solo lectura, está bloqueado) responde con un mensaje en español, sin traza y
    con código 1 (T-14c, R-03 de la revisión de T-14b).
    """
    ruta = current_app.config["DATABASE"]
    comprobar_ruta(ruta, debe_existir=False)
    with errores_de_sqlite_como_mensaje(ruta):
        informe = inicializar(get_db())
    if informe.sin_cambios:
        click.echo("Base de datos sin cambios.")
    elif informe.acciones:
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


MENSAJE_BASE_SOLO_LECTURA = (
    "No se puede escribir en la base de datos {ruta}: es de solo lectura o está en un lugar sin "
    "permiso de escritura. No se cambió nada. Revisa los permisos del archivo y de su carpeta "
    "(el usuario que ejecuta el comando debe poder escribir en ambos)."
)
MENSAJE_BASE_DANADA = (
    "La base de datos {ruta} está dañada ({error}). No se cambió nada. Restaura una copia de "
    "respaldo del archivo (si no tienes una, guarda este archivo antes de intentar rescatarlo)."
)
MENSAJE_BASE_NO_SE_ABRE = (
    "No se pudo abrir la base de datos {ruta} ({error}). Revisa que la carpeta exista y que tengas "
    "permiso para usarla."
)
MENSAJE_BASE_ERROR = "Error de la base de datos: {error}"

# Códigos primarios de SQLite (`sqlite3.SQLITE_*`; el código extendido se corta con `& 0xFF`).
_READONLY, _CORRUPT, _NOTADB, _CANTOPEN = 8, 11, 26, 14


def mensaje_de_error_sqlite(error, ruta):
    """El texto en español, sin traza, para un `sqlite3.Error` ante un archivo de base inservible.

    Usa el código de SQLite (`sqlite_errorcode`, Python 3.11+) y, si falta, el texto del error.
    Cubre: base ocupada, solo lectura, no es SQLite, dañada y no se puede abrir; todo lo demás
    se informa tal cual, también sin traza.
    """
    codigo = getattr(error, "sqlite_errorcode", None)
    primario = None if codigo is None else codigo & 0xFF
    texto = str(error).lower()
    if esta_ocupada(error):
        return MENSAJE_COMANDO_BASE_OCUPADA
    if primario == _READONLY or "readonly" in texto:
        return MENSAJE_BASE_SOLO_LECTURA.format(ruta=ruta)
    if primario == _NOTADB or "not a database" in texto:
        return MENSAJE_BASE_ILEGIBLE.format(ruta=ruta, error=error)
    if primario == _CORRUPT or "malformed" in texto:
        return MENSAJE_BASE_DANADA.format(ruta=ruta, error=error)
    if primario == _CANTOPEN or "unable to open" in texto:
        return MENSAJE_BASE_NO_SE_ABRE.format(ruta=ruta, error=error)
    return MENSAJE_BASE_ERROR.format(error=error)


@contextlib.contextmanager
def errores_de_sqlite_como_mensaje(ruta):
    """Dentro del bloque, un `sqlite3.Error` se vuelve `ClickException` (mensaje claro, código 1).

    Un `IntegrityError` NO se traduce: es un fallo del programa (una restricción que el código debió
    respetar), no del archivo, y se deja subir con su traza para no disfrazarlo.
    """
    try:
        yield
    except sqlite3.IntegrityError:
        raise
    except sqlite3.Error as error:
        raise click.ClickException(mensaje_de_error_sqlite(error, ruta)) from error


def comprobar_ruta(ruta, debe_existir):
    """Falla con un mensaje claro si `ruta` es una carpeta o está en una carpeta inexistente.

    Con `debe_existir` también falla si el archivo no existe (comandos que no deben crear la
    base: `sqlite3.connect` crearía un archivo vacío ante un error de tipeo, T-10 R-01).
    """
    if os.path.isdir(ruta):
        raise click.ClickException(MENSAJE_BASE_ES_CARPETA.format(ruta=ruta))
    carpeta = os.path.dirname(os.path.abspath(ruta))
    if not os.path.isdir(carpeta):
        raise click.ClickException(MENSAJE_SIN_CARPETA.format(carpeta=carpeta, ruta=ruta))
    if debe_existir and not os.path.isfile(ruta):
        raise click.ClickException(MENSAJE_SIN_BASE.format(ruta=ruta))


def abrir_base_existente():
    """Conexión a una base que YA existe y tiene sus tablas; si no, `ClickException` sin traza.

    Para los comandos de mantenimiento que no deben crear una base (`send-reminders`,
    `create-professional`): `sqlite3.connect` crearía un archivo vacío ante un error de tipeo en
    `DATABASE`. Aquí se comprueba el archivo ANTES de conectar (T-10 R-01).
    """
    ruta = current_app.config["DATABASE"]
    comprobar_ruta(ruta, debe_existir=True)
    with errores_de_sqlite_como_mensaje(ruta):
        db = get_db()
        presentes = _tablas(db)
    faltan = sorted(TABLAS_REQUERIDAS - presentes)
    if faltan:
        raise click.ClickException(MENSAJE_SIN_TABLAS.format(ruta=ruta, faltan=", ".join(faltan)))
    return db


def comprobar_que_se_puede_escribir():
    """Falla ya, con un mensaje claro, si la base está bloqueada o es de solo lectura.

    `BEGIN IMMEDIATE` + `ROLLBACK` no cambia nada. Sirve para avisar ANTES de pedir una contraseña
    (`create-professional`); la escritura real vuelve a manejar los mismos errores.
    """
    ruta = current_app.config["DATABASE"]
    db = get_db()
    with errores_de_sqlite_como_mensaje(ruta):
        db.execute("BEGIN IMMEDIATE")
        db.rollback()


# ------------------------------------------- aviso al arrancar el servidor ----


def avisar_si_la_base_es_antigua(app):
    """Al servir, avisa en el log si `notificaciones.hora_id` no tiene `ON DELETE SET NULL`.

    Abre la base SOLO LECTURA y nunca falla ni crea nada: sin archivo, sin tablas o con cualquier
    error de SQLite no dice nada (ya lo dirán `init-db` y las páginas). Ver `fk_de_avisos_sin_set_null`.
    """
    ruta = app.config["DATABASE"]
    try:
        if not os.path.isfile(ruta):
            return
        conexion = sqlite3.connect(Path(os.path.abspath(ruta)).as_uri() + "?mode=ro", uri=True, timeout=0.5)
        try:
            sin_set_null = fk_de_avisos_sin_set_null(conexion)
        finally:
            conexion.close()
    except (sqlite3.Error, OSError, ValueError):
        return
    if sin_set_null:
        app.logger.warning(MENSAJE_FK_SIN_SET_NULL_LOG.format(ruta=ruta))


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
