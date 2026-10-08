import atexit
import importlib
import itertools
import os
import pkgutil
import shutil
import signal
import sqlite3
import sys
import tempfile
import time

import pytest
from jinja2 import BytecodeCache
from werkzeug import security
from werkzeug.routing import Rule

import app as paquete_app
from app import create_app
from app import db as modulo_db

# Se importan todos los módulos de `app` para que la fixture los encuentre: así
# un módulo nuevo que haga `from werkzeug.security import generate_password_hash`
# queda cubierto sin tocar este archivo (R-07).
for _modulo in pkgutil.iter_modules(paquete_app.__path__):
    importlib.import_module(f"app.{_modulo.name}")

# --- Carpeta temporal en memoria (T-08b, D-031; endurecida en T-08c) ------------
# Las bases de prueba van a /dev/shm (tmpfs) si hay sitio de sobra: cada commit de
# SQLite hace fsync y en disco costaba ~2 ms. Variable de entorno para forzar:
#
#   AGENDA_PSI_TMPFS=0     nunca usa /dev/shm (carpeta temporal normal del sistema)
#   AGENDA_PSI_TMPFS=1     lo usa aunque el espacio sea justo (si no existe, no lo usa)
#   sin definir / "auto"   lo usa solo si el espacio libre es >= HOLGURA x PICO_MEDIDO
#
# Si el usuario pasa --basetemp, se respeta siempre. La cabecera de pytest
# (`pytest_report_header`) dice qué carpeta se usa y por qué.
VARIABLE_TMPFS = "AGENDA_PSI_TMPFS"
DIRECTORIO_TMPFS = "/dev/shm"
PREFIJO_TMPFS = "pytest-agenda-psi-"
# Pico de uso de /dev/shm medido en T-08c con 1135 pruebas: 23 520 KiB (~23 MiB), que
# se redondea a 24 MiB. Si la suite crece mucho, vuelve a medirlo y sube la cifra.
PICO_MEDIDO_BYTES = 24 * 1024 * 1024
HOLGURA = 4
UMBRAL_TMPFS_BYTES = HOLGURA * PICO_MEDIDO_BYTES


def decidir_directorio_en_memoria(
    entorno=None, directorio=DIRECTORIO_TMPFS, uso_de_disco=None, acceso=None,
):
    """Devuelve (usar, motivo): si conviene poner la carpeta temporal en `directorio`."""
    entorno = os.environ if entorno is None else entorno
    uso_de_disco = shutil.disk_usage if uso_de_disco is None else uso_de_disco
    acceso = os.access if acceso is None else acceso
    ajuste = entorno.get(VARIABLE_TMPFS, "auto").strip().lower() or "auto"
    if ajuste == "0":
        return False, f"{VARIABLE_TMPFS}=0"
    if not acceso(directorio, os.W_OK):
        return False, f"{directorio} no existe o no se puede escribir"
    if ajuste == "1":
        return True, f"forzado con {VARIABLE_TMPFS}=1"
    try:
        libre = uso_de_disco(directorio).free
    except OSError as error:
        return False, f"no se pudo medir el espacio de {directorio} ({error})"
    if libre < UMBRAL_TMPFS_BYTES:
        return False, (
            f"{directorio} tiene {libre // 2**20} MiB libres y se piden "
            f"{UMBRAL_TMPFS_BYTES // 2**20} MiB ({HOLGURA} x pico de {PICO_MEDIDO_BYTES // 2**20} MiB)"
        )
    return True, f"{libre // 2**20} MiB libres en {directorio}"


def limpiar_directorio(ruta, pid_dueno):
    # En un proceso hijo (fork) heredado no se borra lo del padre.
    if ruta and os.getpid() == pid_dueno:
        shutil.rmtree(ruta, ignore_errors=True)


def instalar_limpieza(ruta):
    """Borra `ruta` al salir (atexit) y también ante SIGTERM, que atexit no cubre.

    El manejador de SIGTERM limpia, restaura la acción por defecto y se reenvía la
    señal: el proceso muere igual que sin manejador (código -SIGTERM). Solo se
    instala si SIGTERM tenía la acción por defecto (no pisa a otro manejador) y se
    omite donde no existe (Windows). En procesos hijos heredados por fork no borra.
    """
    pid = os.getpid()
    atexit.register(limpiar_directorio, ruta, pid)
    sigterm = getattr(signal, "SIGTERM", None)
    if sigterm is None:
        return

    def al_recibir_sigterm(numero, marco):
        limpiar_directorio(ruta, pid)
        signal.signal(sigterm, signal.SIG_DFL)
        os.kill(os.getpid(), sigterm)

    try:
        if signal.getsignal(sigterm) == signal.SIG_DFL:
            signal.signal(sigterm, al_recibir_sigterm)
    except ValueError:  # fuera del hilo principal
        pass


def crear_raiz_temporal(directorio):
    # Nombre impredecible y permisos 0700 (mkdtemp), sin chocar con otras corridas.
    ruta = tempfile.mkdtemp(prefix=PREFIJO_TMPFS, dir=directorio)
    instalar_limpieza(ruta)
    return ruta


def pytest_configure(config):
    config._tmpfs_raiz = None
    if config.option.basetemp is not None:
        config._tmpfs_motivo = f"carpeta temporal: {config.option.basetemp} (--basetemp)"
        return
    usar, motivo = decidir_directorio_en_memoria(directorio=DIRECTORIO_TMPFS)
    if not usar:
        config._tmpfs_motivo = f"carpeta temporal: la normal de pytest ({motivo})"
        return
    config._tmpfs_raiz = crear_raiz_temporal(DIRECTORIO_TMPFS)
    config.option.basetemp = os.path.join(config._tmpfs_raiz, "base")
    config._tmpfs_motivo = f"carpeta temporal: {config.option.basetemp} (memoria; {motivo})"


def pytest_report_header(config):
    return getattr(config, "_tmpfs_motivo", None)


def pytest_unconfigure(config):
    limpiar_directorio(getattr(config, "_tmpfs_raiz", None), os.getpid())


# Hash rápido para toda la suite (D-019). Sigue siendo scrypt con sal propia,
# pero con costo mínimo; las pruebas que verifican el hash real llevan
# `@pytest.mark.hash_real` y no lo usan.
METODO_RAPIDO = "scrypt:128:8:1"  # el real es scrypt:32768:8:1 (T-08b: antes 1024, ~3 ms por hash; N<64 falla por el límite de memoria de OpenSSL)
_generate_real = security.generate_password_hash


def generate_password_hash_rapido(password, method="scrypt", salt_length=16):
    # Solo se acelera el método por defecto: si una prueba pide otro
    # explícitamente, se respeta tal cual.
    if method == "scrypt":
        method = METODO_RAPIDO
    return _generate_real(password, method=method, salt_length=salt_length)


def _modulos_de_la_app_con_hash():
    return [
        modulo
        for nombre, modulo in list(sys.modules.items())
        if (nombre == "app" or nombre.startswith("app."))
        and modulo is not None
        and hasattr(modulo, "generate_password_hash")
    ]


@pytest.fixture(autouse=True)
def hash_rapido(request, monkeypatch):
    # El hash falso del login vive en cada app (app.extensions), así que no
    # cruza pruebas con distinto costo (rápido / real).
    if not request.node.get_closest_marker("hash_real"):
        monkeypatch.setattr(security, "generate_password_hash", generate_password_hash_rapido)
        for modulo in _modulos_de_la_app_con_hash():
            monkeypatch.setattr(modulo, "generate_password_hash", generate_password_hash_rapido)
    yield


# --- Base de datos de plantilla (T-08b, D-031) -----------------------------------
# Crear el esquema con `executescript` en cada prueba costaba ~7 ms (más el commit
# con fsync). El esquema se crea UNA vez por sesión con el `init_db` de verdad y
# cada prueba lo recibe copiado (`Connection.backup`) en su propio archivo, así que
# el aislamiento es el mismo: archivo nuevo en `tmp_path` por prueba. Si la base ya
# tiene tablas, o la prueba lleva `@pytest.mark.base_real`, se ejecuta el `init_db`
# real sin atajos (idempotencia, esquema exacto).
_init_db_real = modulo_db.init_db


_CACHE_MODULOS = {}


def _modulos_con_init_db():
    # Recorrer todo `sys.modules` en cada prueba costaba ~1 ms; solo se repite si
    # se importó algún módulo nuevo desde la última vez.
    cantidad = len(sys.modules)
    if _CACHE_MODULOS.get("cantidad") != cantidad:
        _CACHE_MODULOS["cantidad"] = cantidad
        _CACHE_MODULOS["modulos"] = [
            m for m in list(sys.modules.values())
            if m is not None and vars(m).get("init_db") is _init_db_real
        ]
    return _CACHE_MODULOS["modulos"]


@pytest.fixture(scope="session")
def plantilla_db(tmp_path_factory):
    """Devuelve una función que entrega la plantilla; se crea al primer uso (perezosa)."""
    estado = {}

    def obtener():
        if "memoria" not in estado:
            ruta = tmp_path_factory.mktemp("plantilla") / "plantilla.db"
            app_plantilla = create_app({"TESTING": True, "DATABASE": str(ruta)})
            with app_plantilla.app_context():
                _init_db_real()
            en_archivo = sqlite3.connect(ruta)
            estado["memoria"] = sqlite3.connect(":memory:")
            en_archivo.backup(estado["memoria"])
            en_archivo.close()
        return estado["memoria"]

    yield obtener
    if "memoria" in estado:
        estado["memoria"].close()


@pytest.fixture(autouse=True)
def init_db_con_plantilla(request, monkeypatch):
    if request.node.get_closest_marker("base_real"):
        yield
        return
    plantilla = request.getfixturevalue("plantilla_db")  # función perezosa

    def init_db_rapido():
        db = modulo_db.get_db()
        if db.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 0:
            plantilla().backup(db)  # base vacía: se copia el esquema ya creado
        else:
            _init_db_real()  # ya hay tablas: el comportamiento real (idempotencia)

    # Cada módulo que hizo `from app.db import init_db` tiene su propia referencia.
    for modulo in _modulos_con_init_db():
        monkeypatch.setattr(modulo, "init_db", init_db_rapido)
    yield


_NUMERO_DE_CARPETA = itertools.count()


@pytest.fixture
def tmp_path(tmp_path_factory):
    # El `tmp_path` de pytest numera cada carpeta listando las anteriores: con ~1100
    # pruebas era cuadrático (~1 s). Aquí es un contador (T-08b, D-031); sigue siendo
    # una carpeta nueva y vacía por prueba, dentro del directorio temporal de la sesión.
    ruta = tmp_path_factory.getbasetemp() / f"prueba{next(_NUMERO_DE_CARPETA)}"
    ruta.mkdir()
    return ruta


class _CacheDePlantillasEnMemoria(BytecodeCache):
    """Guarda en memoria el bytecode de las plantillas, compartido entre apps."""

    def __init__(self):
        self.almacen = {}

    def load_bytecode(self, bucket):
        guardado = self.almacen.get(bucket.key)
        if guardado is not None:
            bucket.bytecode_from_string(guardado)

    def dump_bytecode(self, bucket):
        self.almacen[bucket.key] = bucket.bytecode_to_string()


# Cada app tiene su propio entorno Jinja y recompilaba las plantillas en cada
# prueba (T-08b, D-031). El bytecode es válido mientras no cambie el fuente (la
# clave incluye un hash del texto), así que se comparte en toda la sesión.
CACHE_DE_PLANTILLAS = _CacheDePlantillasEnMemoria()


# Werkzeug compila (con `ast` y `compile`) el constructor de URL de cada ruta cada
# vez que se crea una app: ~12 ms por prueba con 12 rutas. El resultado depende
# solo de la forma de la ruta, así que se memoriza en toda la sesión (T-08b, D-031).
# `test_cache_de_rutas_da_las_mismas_urls` comprueba que construye las mismas URL.
_compilar_constructor_real = Rule._compile_builder
_CONSTRUCTORES = {}


def _clave_de_constructor(regla, append_unknown):
    convertidores = tuple(
        (nombre, type(c), tuple(sorted((k, repr(v)) for k, v in vars(c).items() if k != "map")))
        for nombre, c in sorted(regla._converters.items())
    )
    por_defecto = tuple(sorted((k, repr(v)) for k, v in (regla.defaults or {}).items()))
    return (append_unknown, tuple(regla._trace), convertidores, por_defecto)


def _compilar_constructor_con_cache(self, append_unknown=True):
    clave = _clave_de_constructor(self, append_unknown)
    if clave not in _CONSTRUCTORES:
        _CONSTRUCTORES[clave] = _compilar_constructor_real(self, append_unknown)
    return _CONSTRUCTORES[clave]


@pytest.fixture(scope="session", autouse=True)
def cache_de_constructores_de_url():
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Rule, "_compile_builder", _compilar_constructor_con_cache)
        yield


@pytest.fixture
def app(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.db")})
    app.jinja_env.bytecode_cache = CACHE_DE_PLANTILLAS
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


# --- Zona horaria del sistema (T-08, R-05 de la revisión de T-07) ---------------
# La aplicación decide con instantes absolutos y la zona de Chile (`zoneinfo`),
# nunca con la zona del equipo. Si las pruebas corrieran con la zona del equipo
# y esta fuera Chile, un error como `ahora.replace(tzinfo=None).timestamp()`
# (hora de Chile leída como hora del sistema) pasaría desapercibido. Por eso
# cada prueba corre con el sistema en UTC, sea cual sea el equipo; y las pruebas
# de borde piden además `zona_sistema` para repetirse en otras zonas.
ZONAS_DE_SISTEMA = ["UTC", "Asia/Tokyo", "America/Santiago"]


def hay_tzset():
    # `time.tzset` no existe en Windows (R-01 de la revisión de T-08). Se consulta
    # al usarlo, no al importar, para que una prueba pueda simular su ausencia.
    return hasattr(time, "tzset")


def fijar_zona_sistema(nombre):
    os.environ["TZ"] = nombre
    time.tzset()


@pytest.fixture(autouse=True)
def zona_del_sistema_fija():
    if not hay_tzset():
        # Windows: no se puede cambiar la zona del proceso; la fixture no hace nada
        # y las demás pruebas corren con la zona del equipo.
        yield
        return
    anterior = os.environ.get("TZ")
    fijar_zona_sistema("UTC")
    yield
    if anterior is None:
        os.environ.pop("TZ", None)
        time.tzset()
    else:
        fijar_zona_sistema(anterior)


@pytest.fixture(params=ZONAS_DE_SISTEMA)
def zona_sistema(request):
    """Repite la prueba con el sistema en UTC, Tokio y Chile (la de Chile es la que escondía R-05).

    Sin `time.tzset` (Windows) la prueba se salta, no falla.
    """
    if not hay_tzset():
        pytest.skip("este sistema no tiene time.tzset (Windows): no se puede cambiar la zona del proceso")
    fijar_zona_sistema(request.param)
    return request.param
