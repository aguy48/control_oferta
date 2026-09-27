"""identity/ copiado tal cual de Control de Proyecto funciona en esta instancia."""
from .conftest import auth_headers, crear_usuario, token


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["modo"] == "cotizacion"


def test_admin_inicial_debe_cambiar_clave(client):
    r = client.post("/auth/login", json={"usuario": "admin", "password": "AdminPass!2026"})
    assert r.status_code == 200, r.text
    assert r.json()["paso"] == "cambiar_password"
    assert not r.json().get("access_token")


def test_clave_incorrecta_se_rechaza_y_audita(client):
    r = client.post("/auth/login", json={"usuario": "admin", "password": "mala"})
    assert r.status_code == 401


def test_login_y_me_con_escenario(client):
    crear_usuario("analista_id", "analista", "Ana Identidad")
    t = token(client, "analista_id")
    r = client.get("/auth/me", headers=auth_headers(t))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["usuario"] == "analista_id"
    assert body["escenario"]["razon_social"] == "ORIOL CONSULTORES"


def test_token_de_otra_instancia_no_sirve(client):
    """Cuentas separadas (§6): un JWT firmado con otra SECRET_KEY se rechaza."""
    from jose import jwt
    ajeno = jwt.encode({"sub": "x", "type": "access", "rol": "admin"}, "clave-de-control-de-proyecto",
                       algorithm="HS256")
    r = client.get("/auth/me", headers=auth_headers(ajeno))
    assert r.status_code == 401
