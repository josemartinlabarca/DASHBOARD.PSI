"""La suite no depende del entorno del equipo (T-14a ronda 2, R-03)."""
import os
import re
from pathlib import Path

from tests.conftest import VARIABLES_DE_ENTORNO_DE_LA_APP

RAIZ = Path(__file__).resolve().parent.parent
LECTURAS = re.compile(
    r"""(?:environ(?:\.get)?\s*[\[(]|getenv\(|_booleano_de_entorno\()\s*["']([A-Z][A-Z0-9_]*)["']"""
)


def _variables_que_lee_la_app():
    leidas = set()
    for archivo in (RAIZ / "app").rglob("*.py"):
        leidas.update(LECTURAS.findall(archivo.read_text(encoding="utf-8")))
    return leidas


def test_la_lista_de_conftest_cubre_todo_lo_que_lee_app():
    """Si `app/` empieza a leer otra variable, hay que agregarla a la lista de conftest.py."""
    leidas = _variables_que_lee_la_app()
    assert {"SECRET_KEY", "DATABASE", "OUTBOX_PATH", "SESSION_COOKIE_SECURE", "TRUSTED_PROXY_COUNT"} <= leidas
    assert leidas <= set(VARIABLES_DE_ENTORNO_DE_LA_APP), leidas - set(VARIABLES_DE_ENTORNO_DE_LA_APP)


def test_la_lista_incluye_las_variables_de_flask_que_cambian_el_comportamiento():
    assert {"FLASK_DEBUG", "FLASK_APP", "FLASK_RUN_HOST", "FLASK_RUN_PORT"} <= set(VARIABLES_DE_ENTORNO_DE_LA_APP)


def test_ninguna_prueba_ve_las_variables_de_la_app_ni_otra_FLASK_():
    """Con la fixture activa, el entorno del equipo no llega a las pruebas (con o sin `monkeypatch`).

    Verificado corriendo la suite entera con todas definidas (ver PROGRESS): sin la fixture esto falla.
    """
    visibles = [n for n in os.environ if n in VARIABLES_DE_ENTORNO_DE_LA_APP or n.startswith("FLASK_")]
    assert visibles == []
