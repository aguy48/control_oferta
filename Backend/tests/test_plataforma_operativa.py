"""Fichas operativas del Sistema de Cotización (espejo de Control de Proyecto)."""
from .conftest import crear_usuario, token, auth_headers


def test_panel_y_cliente(client):
    crear_usuario("analista", "analista")
    h = auth_headers(token(client, "analista"))
    r = client.get("/panel", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "ofertas_por_estado" in data
    assert data["n_clientes"] == 0

    r = client.post("/clientes", headers=h, json={
        "razon_social": "PDVSA QA", "rif": "J-00012345-6", "tipo": "directo",
    })
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert r.json()["rif_norm"] == "J000123456"

    r = client.get("/clientes", headers=h)
    assert r.status_code == 200
    assert any(c["id"] == cid for c in r.json())

    r = client.get("/panel", headers=h)
    assert r.json()["n_clientes"] == 1

    r = client.post("/contactos", headers=h, json={
        "nombre": "Ana Compradora", "email": "ana@pdvsa.test", "cliente_id": cid,
    })
    assert r.status_code == 201, r.text

    r = client.post("/tareas", headers=h, json={"titulo": "Enviar oferta PDVSA"})
    assert r.status_code == 201, r.text

    r = client.get("/generales", headers=h)
    assert r.status_code == 200


def test_auditoria_y_usuarios_solo_admin(client):
    crear_usuario("analista", "analista")
    ha = auth_headers(token(client, "analista"))
    assert client.get("/usuarios", headers=ha).status_code == 403
    assert client.get("/auditoria", headers=ha).status_code == 403

    crear_usuario("jefe", "admin")
    hadmin = auth_headers(token(client, "jefe"))
    assert client.get("/usuarios", headers=hadmin).status_code == 200
    assert client.get("/auditoria", headers=hadmin).status_code == 200
    assert client.get("/escenarios", headers=hadmin).status_code == 200
