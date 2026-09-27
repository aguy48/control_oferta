"""Ciclo de la oferta y archivo de traspaso a Control de Proyecto (ING-COT-003)."""
import datetime as dt
import json

import pytest

from .conftest import auth_headers, crear_usuario, token

# Claves que el frontend de Control de Proyecto lee de proyecto.master
# (js/control_de_proyecto_app.js y js/control_seed.js, formato V1).
CLAVES_RAIZ_V1 = {"formato", "generado", "nombre", "meta", "resumen", "frentes", "cronograma"}
CLAVES_ITEM_V1 = {"item", "descripcion", "unidad", "cantidad", "precio_unitario", "precio_total"}
CLAVES_CRONO_V1 = {"actividad", "frente_label", "fase", "semana_inicio", "semana_fin", "duracion_semanas"}

PARTIDAS = [
    {"disciplina": "Electricidad", "item": "1", "descripcion": "Tablero de transferencia",
     "unidad": "UND", "cantidad": 2, "precio_unitario": 1500.10, "semana_inicio": 1, "duracion_semanas": 4},
    {"disciplina": "Electricidad", "item": "2", "descripcion": "Cableado de potencia",
     "unidad": "ML", "cantidad": 120, "precio_unitario": 12.5, "semana_inicio": 3, "duracion_semanas": 3},
    {"disciplina": "Mecánica", "item": "1", "descripcion": "Mantenimiento de motor",
     "unidad": "UND", "cantidad": 1, "precio_unitario": 8000, "semana_inicio": 2, "duracion_semanas": 6},
]
TOTAL = round(2 * 1500.10 + 120 * 12.5 + 8000, 2)


@pytest.fixture(scope="module")
def h(client):
    crear_usuario("analista1", "analista", "Ana Lista")
    return auth_headers(token(client, "analista1"))


def _oferta(client, h, **extra):
    body = {"titulo": "Mantenimiento planta Centro", "cliente_razon_social": "PDVSA",
            "cliente_rif": "G-20000043-0", **extra}
    r = client.post("/ofertas", json=body, headers=h)
    assert r.status_code == 201, r.text
    o = r.json()
    r = client.put(f"/ofertas/{o['id']}/partidas", json=PARTIDAS, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _ganar(client, h, oid):
    for estado in ("enviada", "ganada"):
        r = client.post(f"/ofertas/{oid}/estado", json={"estado": estado}, headers=h)
        assert r.status_code == 200, r.text
    return r.json()


def _traspaso(client, h, oid):
    r = client.get(f"/ofertas/{oid}/traspaso", headers=h)
    assert r.status_code == 200, r.text
    return r, json.loads(r.content)


def test_codigo_correlativo_por_mes(client, h):
    a = _oferta(client, h)
    b = _oferta(client, h)
    hoy = dt.datetime.utcnow()
    assert a["codigo"].startswith(f"ORI-{hoy:%Y}-{hoy:%m}-")
    assert int(b["codigo"][-3:]) == int(a["codigo"][-3:]) + 1
    assert a["total_precio"] == TOTAL
    assert a["analista_nombre"] == "Ana Lista"


def test_no_se_gana_desde_borrador(client, h):
    o = _oferta(client, h, modalidad="ejecucion", facturacion="detallada")
    r = client.post(f"/ofertas/{o['id']}/estado", json={"estado": "ganada"}, headers=h)
    assert r.status_code == 409


def test_ganar_exige_modalidad_facturacion_y_rif(client, h):
    o = _oferta(client, h, cliente_rif=None)
    client.post(f"/ofertas/{o['id']}/estado", json={"estado": "enviada"}, headers=h)
    r = client.post(f"/ofertas/{o['id']}/estado", json={"estado": "ganada"}, headers=h)
    assert r.status_code == 422
    assert "modalidad" in r.text and "RIF" in r.text
    client.patch(f"/ofertas/{o['id']}", json={"modalidad": "ejecucion", "cliente_rif": "J-1"}, headers=h)
    r = client.post(f"/ofertas/{o['id']}/estado", json={"estado": "ganada"}, headers=h)
    assert r.status_code == 422 and "facturación" in r.text


def test_traspaso_solo_con_oferta_ganada(client, h):
    o = _oferta(client, h, modalidad="ejecucion", facturacion="detallada")
    r = client.get(f"/ofertas/{o['id']}/traspaso", headers=h)
    assert r.status_code == 409


def test_ejecucion_detallada_un_frente_por_disciplina(client, h):
    o = _oferta(client, h, modalidad="ejecucion", facturacion="detallada", sede_destino="SBC Caracas")
    o = _ganar(client, h, o["id"])
    assert o["fecha_ganada"]
    r, data = _traspaso(client, h, o["id"])
    assert f'{o["codigo"]}_traspaso_control_proyecto.json' in r.headers["content-disposition"]

    # Compatible con el importador actual de Control de Proyecto.
    assert CLAVES_RAIZ_V1 <= set(data)
    assert data["formato"] == "RESPALDO_OFERTA_CONTROL_PROYECTO_V1"
    assert isinstance(data["frentes"], list) and data["meta"]
    for f in data["frentes"]:
        for it in f["items"]:
            assert CLAVES_ITEM_V1 <= set(it)
    for c in data["cronograma"]:
        assert CLAVES_CRONO_V1 == set(c)

    assert [f["frente_label"] for f in data["frentes"]] == ["ELECTRICIDAD", "MECÁNICA"]
    assert [it["item"] for it in data["frentes"][0]["items"]] == ["1", "2"]
    assert data["frentes"][0]["subtotal_precio"] == round(3000.2 + 1500, 2)
    assert data["resumen"] == {"total_precio": TOTAL, "iva_monto": round(TOTAL * 0.16, 2),
                               "total_general": round(TOTAL * 1.16, 2)}
    assert data["meta"]["n_items"] == 3
    crono = {c["frente_label"]: c for c in data["cronograma"]}
    assert (crono["ELECTRICIDAD"]["semana_inicio"], crono["ELECTRICIDAD"]["semana_fin"]) == (1, 5)
    assert crono["MECÁNICA"]["duracion_semanas"] == 6
    assert data["meta"]["semanas_totales"] == 7

    origen = data["origen"]
    assert origen["codigo_oferta"] == o["codigo"]
    assert origen["cliente"]["rif"] == "G-20000043-0"
    assert (origen["modalidad"], origen["facturacion"]) == ("ejecucion", "detallada")
    assert origen["tipo_orden_sugerido"] == "contrato_obra"
    assert origen["sede_destino"] == "SBC Caracas"
    assert len(origen["huella_sha256"]) == 64


def test_ejecucion_resumida_un_solo_frente_global(client, h):
    o = _ganar(client, h, _oferta(client, h, modalidad="ejecucion", facturacion="resumida")["id"])
    _, data = _traspaso(client, h, o["id"])
    assert [f["frente_label"] for f in data["frentes"]] == ["GLOBAL"]
    items = data["frentes"][0]["items"]
    # Renumerado 1..N: el "1" de Electricidad y el de Mecánica no chocan.
    assert [it["item"] for it in items] == ["1", "2", "3"]
    assert [it["item_oferta"] for it in items] == ["1", "2", "1"]
    assert items[2]["disciplina"] == "MECÁNICA"
    assert data["frentes"][0]["subtotal_precio"] == TOTAL
    assert {c["frente_label"] for c in data["cronograma"]} == {"GLOBAL"}


def test_suministro_sin_facturacion_y_orden_de_compra(client, h):
    o = _oferta(client, h, modalidad="suministro", facturacion="detallada")
    assert o["facturacion"] is None
    o = _ganar(client, h, o["id"])
    _, data = _traspaso(client, h, o["id"])
    assert [f["frente_label"] for f in data["frentes"]] == ["SUMINISTRO"]
    assert data["origen"]["facturacion"] is None
    assert data["origen"]["tipo_orden_sugerido"] == "orden_compra"
    assert {c["actividad"] for c in data["cronograma"]} == {"ENTREGA DE SUMINISTRO"}


def test_huella_estable_entre_descargas(client, h):
    o = _ganar(client, h, _oferta(client, h, modalidad="ejecucion", facturacion="detallada")["id"])
    _, a = _traspaso(client, h, o["id"])
    _, b = _traspaso(client, h, o["id"])
    assert a["origen"]["huella_sha256"] == b["origen"]["huella_sha256"]
    assert client.get(f"/ofertas/{o['id']}", headers=h).json()["traspasos_generados"] == 2


def test_partida_repetida_en_disciplina_impide_ganar(client, h):
    o = _oferta(client, h, modalidad="ejecucion", facturacion="detallada")
    client.put(f"/ofertas/{o['id']}/partidas", json=PARTIDAS + [PARTIDAS[0]], headers=h)
    client.post(f"/ofertas/{o['id']}/estado", json={"estado": "enviada"}, headers=h)
    r = client.post(f"/ofertas/{o['id']}/estado", json={"estado": "ganada"}, headers=h)
    assert r.status_code == 422 and "repetida" in r.text


def test_oferta_ganada_queda_congelada(client, h):
    o = _ganar(client, h, _oferta(client, h, modalidad="ejecucion", facturacion="detallada")["id"])
    r = client.patch(f"/ofertas/{o['id']}", json={"iva_pct": 8}, headers=h)
    assert r.status_code == 409
    r = client.put(f"/ofertas/{o['id']}/partidas", json=PARTIDAS[:1], headers=h)
    assert r.status_code == 409
    r = client.patch(f"/ofertas/{o['id']}", json={"sede_destino": "SBC Maracaibo"}, headers=h)
    assert r.status_code == 200 and r.json()["sede_destino"] == "SBC Maracaibo"
    r = client.post(f"/ofertas/{o['id']}/estado", json={"estado": "perdida"}, headers=h)
    assert r.status_code == 409


def test_vinculacion_y_bitacora_de_la_conexion(client, h):
    o = _ganar(client, h, _oferta(client, h, modalidad="ejecucion", facturacion="detallada")["id"])
    _traspaso(client, h, o["id"])
    r = client.post(f"/ofertas/{o['id']}/importacion-fallida",
                    json={"motivo": "Cliente no registrado en Clientes (12)"}, headers=h)
    assert r.status_code == 204
    r = client.post(f"/ofertas/{o['id']}/vinculacion",
                    json={"proyecto_cp_id": "mant-centro-2026", "contrato_cp_numero": "4600012345"},
                    headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["proyecto_cp_id"] == "mant-centro-2026" and r.json()["vinculado_en"]

    ev = client.get(f"/ofertas/{o['id']}/eventos", headers=h).json()
    conexion = [e["accion"] for e in ev if e["conexion"]]
    assert conexion == ["oferta_ganada", "traspaso_generado", "proyecto_creacion_fallida",
                        "proyecto_vinculado"]
    assert next(e for e in ev if e["accion"] == "proyecto_creacion_fallida")["resultado"] == "error"


def test_vinculacion_exige_oferta_ganada(client, h):
    o = _oferta(client, h)
    r = client.post(f"/ofertas/{o['id']}/vinculacion", json={"proyecto_cp_id": "x"}, headers=h)
    assert r.status_code == 409


def test_permisos_por_rol(client, h):
    o = _ganar(client, h, _oferta(client, h, modalidad="ejecucion", facturacion="detallada")["id"])
    crear_usuario("auditor1", "auditor")
    crear_usuario("tecnico1", "tecnico")
    ha = auth_headers(token(client, "auditor1"))
    ht = auth_headers(token(client, "tecnico1"))
    assert client.get(f"/ofertas/{o['id']}", headers=ha).status_code == 200
    assert client.get(f"/ofertas/{o['id']}/traspaso", headers=ha).status_code == 403
    assert client.post("/ofertas", json={"titulo": "xxx", "cliente_razon_social": "yy"},
                       headers=ha).status_code == 403
    assert client.get("/ofertas", headers=ht).status_code == 403
    assert client.get("/ofertas", headers={}).status_code == 401
