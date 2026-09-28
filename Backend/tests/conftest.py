import os
import sys
import tempfile

import pytest

# Entorno ANTES de importar la app: BD SQLite temporal y aislada.
TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite:///{TMP_DB.name}"
os.environ["SECRET_KEY"] = "clave-de-pruebas-cotizacion-no-usar-en-produccion"
os.environ["INITIAL_ADMIN_USER"] = "admin"
os.environ["INITIAL_ADMIN_PASSWORD"] = "AdminPass!2026"
os.environ["STORAGE_DIR"] = tempfile.mkdtemp()
# Las pruebas de negocio no ejercitan el TOTP (lo cubre la suite de
# identity en Control de Proyecto, de donde se copia el módulo tal cual).
os.environ["REQUIRE_2FA"] = "false"
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_BOT_USERNAME"] = ""
os.environ["TELEGRAM_WEBHOOK_SECRET"] = ""
os.environ["ONLYOFFICE_URL"] = ""
os.environ["ONLYOFFICE_APP_URL"] = ""
os.environ["ONLYOFFICE_JWT_SECRET"] = ""

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

PASSWORD = "ClavePruebas!2026"


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def crear_usuario(usuario: str, rol: str, nombre: str | None = None) -> None:
    """Alta directa en BD, con la clave temporal ya cambiada."""
    from app.kernel import security
    from app.kernel.db import SessionLocal
    from app.kernel.models import Usuario, Escenario
    from app.identity import escenario_ops
    db = SessionLocal()
    try:
        if db.query(Usuario).filter(Usuario.usuario == usuario).first():
            return
        u = Usuario(usuario=usuario, nombre=nombre or usuario.title(), rol=rol,
                    password_hash=security.hash_password(PASSWORD))
        db.add(u)
        db.flush()
        esc = db.query(Escenario).filter(Escenario.estado == "activo").first()
        escenario_ops.asignar(db, u.id, esc.id, escenario_ops.acceso_por_rol(rol))
        db.commit()
    finally:
        db.close()


def token(client, usuario: str) -> str:
    r = client.post("/auth/login", json={"usuario": usuario, "password": PASSWORD})
    assert r.status_code == 200, r.text
    data = r.json()
    if data.get("paso") == "escenario" or not data.get("escenario"):
        esc = (data.get("escenarios") or [])[0]
        r = client.post("/auth/escenario", json={"escenario_id": esc["id"]},
                        headers=auth_headers(data["access_token"]))
        assert r.status_code == 200, r.text
        data = r.json()
    return data["access_token"]
