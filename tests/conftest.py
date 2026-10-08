import pytest
from werkzeug import security

from app import auth, create_app

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


@pytest.fixture(autouse=True)
def hash_rapido(request, monkeypatch):
    if request.node.get_closest_marker("hash_real"):
        return
    monkeypatch.setattr(security, "generate_password_hash", generate_password_hash_rapido)
    monkeypatch.setattr(auth, "generate_password_hash", generate_password_hash_rapido)


@pytest.fixture
def app(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.db")})
    yield app


@pytest.fixture
def client(app):
    return app.test_client()
