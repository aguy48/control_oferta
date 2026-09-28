"""Catálogo de productos/servicios, historial de cotización y serial al ganar."""
from .conftest import crear_usuario, token, auth_headers


def _h(client):
    crear_usuario("analista", "analista")
    return auth_headers(token(client, "analista"))


def _prod(client, h, **extra):
    body = {
        "tipo": "producto", "nombre": "UPS Eaton 9PX 3 kVA",
        "unidad": "UND", "precio_ref": 1500, "requiere_serial": True,
        "garantia_semanas": 52, "tiempo_entrega_semanas": 3, **extra,
    }
    r = client.post("/productos", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_alta_busqueda_y_codigo(client):
    h = _h(client)
    p = _prod(client, h)
    assert p["codigo"].startswith("PRD-")
    assert p["requiere_serial"] is True
    r = client.get("/productos", headers=h, params={"q": "Eaton"})
    assert r.status_code == 200
    assert any(x["id"] == p["id"] for x in r.json())


def test_cotizar_historial_top_y_serial_al_ganar(client):
    h = _h(client)
    ups = _prod(client, h)
    srv = _prod(client, h, tipo="servicio", nombre="Instalación UPS",
                requiere_serial=False, garantia_semanas=None, precio_ref=400,
                tiempo_entrega_semanas=1)
    o = client.post("/ofertas", headers=h, json={
        "titulo": "Suministro UPS planta", "cliente_razon_social": "CIMAS",
        "cliente_rif": "J-12345678-9", "modalidad": "suministro",
    }).json()
    r = client.put(f"/ofertas/{o['id']}/partidas", headers=h, json=[
        {"disciplina": "ENERGIA", "item": "1", "descripcion": ups["nombre"],
         "unidad": "UND", "cantidad": 2, "precio_unitario": 1500,
         "producto_id": ups["id"], "duracion_semanas": 3},
        {"disciplina": "ENERGIA", "item": "2", "descripcion": srv["nombre"],
         "unidad": "GLB", "cantidad": 1, "precio_unitario": 400,
         "producto_id": srv["id"]},
    ])
    assert r.status_code == 200, r.text
    hist = client.get(f"/productos/{ups['id']}/cotizaciones", headers=h).json()
    assert len(hist) == 1
    assert hist[0]["cliente"] == "CIMAS"
    assert hist[0]["monto"] == 3000
    top = client.get("/productos/estadistica/top", headers=h).json()
    assert top[0]["id"] == ups["id"]
    assert top[0]["n_cotizaciones"] == 1
    client.post(f"/ofertas/{o['id']}/estado", headers=h, json={"estado": "enviada"})
    r = client.post(f"/ofertas/{o['id']}/estado", headers=h, json={"estado": "ganada"})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["codigo"] == "seriales_requeridos"
    req = client.get(f"/ofertas/{o['id']}/seriales-requeridos", headers=h).json()
    assert len(req) == 1
    assert req[0]["n_seriales"] == 2
    pid = req[0]["partida_id"]
    r = client.post(f"/ofertas/{o['id']}/estado", headers=h, json={
        "estado": "ganada",
        "seriales": [
            {"partida_id": pid, "serial": "SN-001"},
            {"partida_id": pid, "serial": "SN-002"},
        ],
    })
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "ganada"


def test_servicio_sin_serial_se_gana(client):
    h = _h(client)
    srv = _prod(client, h, tipo="servicio", nombre="Gerencia de proyecto",
                requiere_serial=False, precio_ref=2000)
    o = client.post("/ofertas", headers=h, json={
        "titulo": "Gerencia Aprada", "cliente_razon_social": "CIMAS",
        "cliente_rif": "J-12345678-9", "modalidad": "suministro",
    }).json()
    client.put(f"/ofertas/{o['id']}/partidas", headers=h, json=[{
        "disciplina": "SERVICIOS", "item": "1", "descripcion": srv["nombre"],
        "unidad": "GLB", "cantidad": 1, "precio_unitario": 2000,
        "producto_id": srv["id"],
    }])
    client.post(f"/ofertas/{o['id']}/estado", headers=h, json={"estado": "enviada"})
    r = client.post(f"/ofertas/{o['id']}/estado", headers=h, json={"estado": "ganada"})
    assert r.status_code == 200, r.text
