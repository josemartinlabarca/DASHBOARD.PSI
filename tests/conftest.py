import importlib
import os
import pkgutil
import sys
import time

import pytest
from werkzeug import security

import app as paquete_app
from app import create_app

# Se importan todos los módulos de `app` para que la fixture los encuentre: así
# un módulo nuevo que haga `from werkzeug.security import generate_password_hash`
# queda cubierto sin tocar este archivo (R-07).
for _modulo in pkgutil.iter_modules(paquete_app.__path__):
    importlib.import_module(f"app.{_modulo.name}")

# Hash rápido para toda la suite (D-019). Sigue siendo scrypt con sal propia,
# pero con costo mínimo; las pruebas que verifican el hash real llevan
# `@pytest.mark.hash_real` y no lo usan.
METODO_RAPIDO = "scrypt:1024:8:1"  # el real es scrypt:32768:8:1
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


@pytest.fixture
def app(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.db")})
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


def fijar_zona_sistema(nombre):
    os.environ["TZ"] = nombre
    time.tzset()


@pytest.fixture(autouse=True)
def zona_del_sistema_fija():
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
    """Repite la prueba con el sistema en UTC, Tokio y Chile (la de Chile es la que escondía R-05)."""
    fijar_zona_sistema(request.param)
    return request.param
