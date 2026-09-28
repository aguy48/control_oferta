"""Eventos de sistema, respaldos y PUT parcial de Generales."""
from app.kernel.audit import registrar
from app.kernel.db import SessionLocal
from app.kernel.models import Usuario
from .conftest import crear_usuario, token, auth_headers


def _h(client, usuario, rol):
    crear_usuario(usuario, rol)
    return auth_headers(token(client, usuario))


def test_eventos_lista_error_no_en_auditoria(client):
    h = _h(client, "ev_admin", "admin")
    db = SessionLocal()
    try:
        u = db.query(Usuario).filter(Usuario.usuario == "ev_admin").first()
        registrar(
            db, usuario=u, accion="traspaso_mcp_error", entidad="oferta",
            entidad_id="of-ev", resultado="error", detalle="timeout MCP",
        )
        registrar(
            db, usuario=u, accion="oferta_creada", entidad="oferta",
            entidad_id="of-ok", resultado="ok", detalle="alta",
        )
    finally:
        db.close()

    ev = client.get("/eventos", headers=h)
    assert ev.status_code == 200, ev.text
    acciones = [e["accion"] for e in ev.json()]
    assert "traspaso_mcp_error" in acciones
    assert "oferta_creada" not in acciones

    aud = client.get("/auditoria", headers=h)
    assert aud.status_code == 200, aud.text
    aud_acc = [e["accion"] for e in aud.json()]
    assert "traspaso_mcp_error" not in aud_acc
    assert "oferta_creada" in aud_acc

    res = client.get("/eventos/resumen", headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    assert "errores_24h" in body
    assert body["errores_24h"] >= 1
    assert "telegram" in body


def test_eventos_y_respaldo_por_rol(client):
    h_ana = _h(client, "ev_ana", "analista")
    h_aud = _h(client, "ev_aud", "auditor")
    h_adm = _h(client, "ev_adm2", "admin")

    assert client.get("/eventos", headers=h_ana).status_code == 403
    assert client.get("/respaldos", headers=h_ana).status_code == 403

    assert client.get("/eventos", headers=h_aud).status_code == 200
    assert client.get("/respaldos", headers=h_aud).status_code == 200
    r = client.post("/respaldos", json={"tipo": "datos"}, headers=h_aud)
    assert r.status_code == 403

    r = client.get("/eventos", headers=h_adm)
    assert r.status_code == 200


def test_respaldo_datos_descarga_y_frase(client):
    h = _h(client, "rb_admin", "admin")
    r = client.post("/respaldos", json={"tipo": "datos"}, headers=h)
    assert r.status_code == 200, r.text
    info = r.json()
    assert info["tipo"] == "datos"
    nombre = info["nombre"]
    assert nombre.startswith("datos_") and nombre.endswith(".zip")

    lista = client.get("/respaldos", headers=h)
    assert lista.status_code == 200, lista.text
    nombres = [a["nombre"] for a in lista.json()["archivos"]]
    assert nombre in nombres
    assert lista.json()["frase_restaurar"] == "restaurar cotizacion"

    dl = client.get(f"/respaldos/{nombre}", headers=h)
    assert dl.status_code == 200, dl.text
    assert dl.content[:2] == b"PK"

    mal = client.post(
        f"/respaldos/{nombre}/restaurar",
        json={"confirmar": "otra frase", "entendido": True},
        headers=h,
    )
    assert mal.status_code == 400
    sin = client.post(
        f"/respaldos/{nombre}/restaurar",
        json={"confirmar": "restaurar cotizacion", "entendido": False},
        headers=h,
    )
    assert sin.status_code == 400


def test_generales_put_parcial_no_borra_mcp(client):
    h = _h(client, "gen_admin", "admin")
    prev = client.get("/generales", headers=h).json()
    try:
        r = client.put("/generales", json={
            "mcp_url": "http://127.0.0.1:9",
            "mcp_destino_id": "sbc-centro",
            "mcp_sede_nombre": "SBC Centro",
        }, headers=h)
        assert r.status_code == 200, r.text
        r = client.put("/generales", json={"razon_social": "ORIOL QA Eventos"}, headers=h)
        assert r.status_code == 200, r.text
        g = client.get("/generales", headers=h).json()
        assert g["razon_social"] == "ORIOL QA Eventos"
        assert g["mcp_destino_id"] == "sbc-centro"
        assert g["mcp_sede_nombre"] == "SBC Centro"
        assert g["mcp_url"] == "http://127.0.0.1:9"
    finally:
        r = client.put("/generales", json={
            "razon_social": prev.get("razon_social") or "ORIOL Consultores C.A.",
            "mcp_url": None,
            "mcp_destino_id": None,
            "mcp_sede_nombre": None,
        }, headers=h)
        assert r.status_code == 200, r.text
