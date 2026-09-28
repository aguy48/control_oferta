"""SBC en alta, margen, anexos OCR heurístico, informe → oferta y reportes."""
from io import BytesIO

from app.crm.gemini_oferta import (
    aplicar_margen, clasificar_fuente, extraer_heuristicas, extraer_whatsapp,
)
from .conftest import crear_usuario, token, auth_headers


def _oferta(client, h, **extra):
    body = {
        "titulo": "Oferta FERMETAL UPS",
        "cliente_razon_social": "FERREMETAL, C.A.",
        "cliente_rif": "J-00020730-1",
        "mcp_destino_id": "sbc-valencia",
        "sede_destino": "SBC Valencia",
        "margen_pct": 30,
        **extra,
    }
    r = client.post("/ofertas", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_aplicar_margen():
    partidas = aplicar_margen(
        [{"descripcion": "UPS Eaton 9PX", "cantidad": 2, "precio_costo": 100, "unidad": "UND"}],
        25,
    )
    assert partidas[0]["precio_unitario"] == 125.0
    assert partidas[0]["precio_costo"] == 100.0


def test_heuristicas_lineas_y_rif():
    texto = (
        "FACTURA PROVEEDOR RIF J-12345678-9\n"
        "1 Cable THHN 12 AWG 10 UND 5.50\n"
        "2 Breaker 20A  2 UND 12.00\n"
    )
    extra = extraer_heuristicas(texto)
    assert extra["rif"] == "J-12345678-9"
    assert extra["tipo_documento"] == "factura_proveedor"
    assert len(extra["partidas"]) == 2
    assert extra["partidas"][0]["precio_costo"] == 5.5


def test_heuristicas_tabla_ve_aprada():
    texto = (
        "Tienda Aprada – CIMAS Proyecto · oferta ORI-26-09-001-AG\n"
        "ORIOL Consultores C.A. · Tienda Aprada – Cableado estructurado\n"
        "Patch panel 24 puertos Cat 6, 1U LAN WAN (equivalente) und 6 31,02 186,12 24,82 148,90 37,22\n"
        "2.1 UPS online doble conversión 3 kVA, rack LAN WAN (equivalente) und 2 1.500,00 3.000,00 1.200,00 2.400,00 600,00\n"
        "Partida 1 – Audiovisual, control y señalización 136.700,00 109.360,00 27.340,00\n"
    )
    extra = extraer_heuristicas(texto, "oferta_comercial")
    assert extra["cliente"] == "CIMAS"
    assert extra["tipo_documento"] == "oferta_comercial"
    assert len(extra["partidas"]) == 2
    assert extra["partidas"][0]["precio_costo"] == 24.82
    assert extra["partidas"][0]["cantidad"] == 6
    assert extra["partidas"][1]["precio_costo"] == 1200.0
    assert extra["partidas"][0]["disciplina"] == "Cableado estructurado"


def test_crear_oferta_con_sbc_y_margen(client):
    crear_usuario("analista", "analista")
    h = auth_headers(token(client, "analista"))
    o = _oferta(client, h)
    assert o["mcp_destino_id"] == "sbc-valencia"
    assert o["sede_destino"] == "SBC Valencia"
    assert o["margen_pct"] == 30
    assert o["origen"] == "comercial"


def test_anexo_ocr_genera_partidas(client):
    crear_usuario("analista", "analista")
    h = auth_headers(token(client, "analista"))
    o = _oferta(client, h)
    pdf = BytesIO(
        b"%PDF-1.1\n1 0 obj<<>>endobj\n"
        b"2 0 obj<</Length 80>>stream\n"
        b"BT /F1 12 Tf 72 720 Td (1 Cable THHN 10 UND 5.50) Tj ET\n"
        b"endstream\nendobj\n"
        b"3 0 obj<</Type /Page /Parent 4 0 R /Contents 2 0 R>>endobj\n"
        b"4 0 obj<</Type /Pages /Kids[3 0 R] /Count 1>>endobj\n"
        b"5 0 obj<</Type /Catalog /Pages 4 0 R>>endobj\n"
        b"trailer<</Root 5 0 R>>\n%%EOF\n"
    )
    r = client.post(
        f"/ofertas/{o['id']}/anexos",
        headers=h,
        data={"tipo": "oferta_proveedor", "ocr": "true"},
        files={"archivo": ("oferta_proveedor.pdf", pdf, "application/pdf")},
    )
    assert r.status_code == 201, r.text
    anexo = r.json()
    assert anexo["tipo"] == "oferta_proveedor"
    assert anexo["oferta_id"] == o["id"]

    # Sin texto extraíble el PDF mínimo no produce partidas: inyectamos extracción.
    from app.kernel.db import SessionLocal
    from app.kernel.models import AnexoOferta
    db = SessionLocal()
    try:
        fila = db.query(AnexoOferta).filter(AnexoOferta.id == anexo["id"]).first()
        fila.extraccion = {
            "motor": "heuristicas",
            "partidas": [{"descripcion": "Cable THHN", "cantidad": 10, "precio_costo": 5.5, "unidad": "UND"}],
        }
        db.commit()
    finally:
        db.close()

    r = client.post(
        f"/ofertas/{o['id']}/generar-desde-anexos",
        headers=h,
        json={"margen_pct": 30, "reemplazar_partidas": True},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["margen_pct"] == 30
    assert len(data["partidas"]) == 1
    assert data["partidas"][0]["precio_unitario"] == 7.15


def test_informe_genera_oferta_y_reportes(client):
    crear_usuario("analista", "analista")
    h = auth_headers(token(client, "analista"))
    r = client.post("/informes", headers=h, json={
        "titulo": "Levantamiento FERMETAL almacén",
        "codigo": "NS-ORI-26-05-001-AG",
        "cliente_razon_social": "FERREMETAL, C.A.",
        "resumen": "Inspección de centrales y UPS. Se recomienda recambio.",
    })
    assert r.status_code == 201, r.text
    inf = r.json()

    r = client.post(f"/informes/{inf['id']}/generar-oferta", headers=h, json={"margen_pct": 20})
    assert r.status_code == 201, r.text
    o = r.json()
    assert o["origen"] == "tecnica"
    assert o["margen_pct"] == 20
    assert "Levantamiento" in o["titulo"]

    r = client.get(f"/ofertas/{o['id']}/reporte.html", headers=h)
    assert r.status_code == 200
    assert "FERREMETAL" in r.text
    assert "ORI-" in r.text

    r = client.get(f"/informes/{inf['id']}/reporte.html", headers=h)
    assert r.status_code == 200
    assert "NS-ORI-26-05-001-AG" in r.text
    assert "Informe técnico" in r.text

    r = client.get("/reportes", headers=h)
    assert r.status_code == 200
    assert any(x["id"] == o["id"] for x in r.json()["ofertas"])
    assert any(x["id"] == inf["id"] for x in r.json()["informes"])

    r = client.get("/panel", headers=h)
    assert r.json()["n_informes"] == 1

    r = client.delete(f"/informes/{inf['id']}", headers=h)
    assert r.status_code == 204, r.text
    assert client.get(f"/informes/{inf['id']}", headers=h).status_code == 404
    r = client.get("/reportes", headers=h)
    assert not any(x["id"] == inf["id"] for x in r.json()["informes"])


def test_informe_word_en_reportes_y_eliminar_anexo(client):
    from app.plataforma.onlyoffice_ops import plantilla_docx
    crear_usuario("analista", "analista")
    h = auth_headers(token(client, "analista"))
    o = _oferta(client, h)
    r = client.post(
        f"/ofertas/{o['id']}/anexos",
        headers=h,
        data={"tipo": "informe_tecnico", "ocr": "false"},
        files={"archivo": (
            "levantamiento.docx", plantilla_docx(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )},
    )
    assert r.status_code == 201, r.text
    anexo = r.json()
    r = client.post(f"/informes/desde-anexo/{anexo['id']}", headers=h)
    assert r.status_code == 201, r.text
    inf = r.json()
    assert inf["archivo_office"] is True
    assert inf["anexo_nombre"].endswith(".docx")

    r = client.get("/reportes", headers=h)
    fila = next(x for x in r.json()["informes"] if x["id"] == inf["id"])
    assert fila["archivo_office"] is True
    assert fila["anexo_id"] == anexo["id"]

    r = client.delete(f"/informes/{inf['id']}", headers=h)
    assert r.status_code == 204
    assert client.get(f"/anexos/{anexo['id']}/archivo", headers=h).status_code == 404


def test_whatsapp_y_clasificacion():
    chat = (
        "27/09/2026, 15:45 - Luis FERMETAL: Necesitamos oferta de UPS Eaton 9PX "
        "y mantenimiento trimestral. RIF J-00020730-1\n"
        "27/09/2026, 15:46 - ORIOL: Enviamos visita e informe NS-ORI.\n"
        "1 Cable THHN 12 AWG 10 UND 5.50\n"
    )
    texto = extraer_whatsapp(chat.encode("utf-8"), "Chat de WhatsApp.txt")
    assert "Luis FERMETAL" in texto
    extra = extraer_heuristicas(texto, "whatsapp")
    assert extra["tipo_documento"] == "whatsapp"
    assert extra["rif"] == "J-00020730-1"
    assert extra["informe_tecnico"]
    assert extra["partidas"]
    assert clasificar_fuente("nota.m4a", "audio/mp4", None) == "audio"
    assert clasificar_fuente("Chat de WhatsApp.zip", "application/zip", None) == "whatsapp"
    assert clasificar_fuente("tablero.jpg", "image/jpeg", None) == "imagen"


def test_analisis_whatsapp_genera_informe_y_oferta(client):
    crear_usuario("analista", "analista")
    h = auth_headers(token(client, "analista"))
    chat = (
        "27/09/2026, 10:02 - Ana FERMETAL: Solicito cotización de recambio UPS Eaton "
        "y plan de mantenimiento 2026-2028. RIF J-00020730-1\n"
        "1 UPS Eaton 9PX  1 UND 1200.00\n"
    )
    r = client.post(
        "/analisis",
        headers=h,
        data={"tipo": "whatsapp", "crear_informe": "true", "crear_oferta": "true", "margen_pct": "25"},
        files=[("archivos", ("Chat de WhatsApp con FERMETAL.txt", chat.encode("utf-8"), "text/plain"))],
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["informe"]
    assert data["oferta"]
    assert data["oferta"]["origen"] == "tecnica"
    assert data["informe"]["resumen"]
    assert data["extraccion"]["tipo_documento"] == "whatsapp"


def test_eliminar_solo_borrador(client):
    crear_usuario("analista", "analista")
    h = auth_headers(token(client, "analista"))
    o = _oferta(client, h)
    r = client.delete(f"/ofertas/{o['id']}", headers=h)
    assert r.status_code == 204, r.text
    assert client.get(f"/ofertas/{o['id']}", headers=h).status_code == 404

    g = _oferta(client, h, modalidad="ejecucion", facturacion="detallada")
    client.put(f"/ofertas/{g['id']}/partidas", headers=h, json=[{
        "disciplina": "GENERAL", "item": "1", "descripcion": "Item",
        "unidad": "UND", "cantidad": 1, "precio_unitario": 10,
    }])
    client.post(f"/ofertas/{g['id']}/estado", headers=h, json={"estado": "enviada"})
    r = client.delete(f"/ofertas/{g['id']}", headers=h)
    assert r.status_code == 409


def test_generales_margen_sin_exponer_clave(client):
    crear_usuario("jefe", "admin")
    h = auth_headers(token(client, "jefe"))
    r = client.put("/generales", headers=h, json={
        "razon_social": "ORIOL Consultores C.A.",
        "margen_pct": 18,
        "iva_pct": 16,
        "moneda": "USD",
        "gemini_api_key": "clave-de-prueba-no-real",
        "gemini_model": "gemini-2.5-flash",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["margen_pct"] == 18
    assert data["gemini_configurado"] is True
    assert "gemini_api_key" not in data
