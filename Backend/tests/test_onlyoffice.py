"""OnlyOffice: estado, Generales, anexos y archivo firmado."""
import io
import zipfile

from .conftest import crear_usuario, token, auth_headers


def _admin(client):
    crear_usuario("oo_admin", "admin")
    return auth_headers(token(client, "oo_admin"))


def _oferta(client, h):
    r = client.post("/ofertas", headers=h, json={
        "titulo": "Oferta OnlyOffice",
        "cliente_razon_social": "ORIOL QA",
        "margen_pct": 25,
    })
    assert r.status_code == 201, r.text
    return r.json()


def test_onlyoffice_01_sin_config_estado_y_config(client):
    h = _admin(client)
    client.put("/generales/onlyoffice", json={"onlyoffice_url": ""}, headers=h)
    r = client.get("/onlyoffice/estado", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["habilitado"] is False
    r = client.post("/onlyoffice/config", json={
        "origen": "anexo", "id": "no-existe", "modo": "view",
    }, headers=h)
    assert r.status_code == 503


def test_onlyoffice_02_guardar_generales_y_nuevo_anexo(client):
    h = _admin(client)
    r = client.put("/generales/onlyoffice", json={
        "onlyoffice_url": "http://127.0.0.1:8082",
        "onlyoffice_app_url": "http://127.0.0.1:8100",
        "onlyoffice_jwt_secret": "jwt-de-prueba-oo",
    }, headers=h)
    assert r.status_code == 200, r.text
    oo = r.json().get("onlyoffice") or {}
    assert oo.get("configurado") is True
    assert oo.get("url") == "http://127.0.0.1:8082"
    assert oo.get("tiene_jwt") is True
    r = client.get("/onlyoffice/estado", headers=h)
    assert r.status_code == 200
    assert r.json()["habilitado"] is True

    o = _oferta(client, h)
    r = client.post("/onlyoffice/nuevo", json={
        "oferta_id": o["id"], "tipo": "word", "nombre": "Acta",
    }, headers=h)
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["origen"] == "anexo"
    assert doc["nombre"].endswith(".docx")
    assert doc["id"]
    assert doc["oferta_id"] == o["id"]

    r = client.post("/onlyoffice/config", json={
        "origen": "anexo", "id": doc["id"], "modo": "edit",
    }, headers=h)
    assert r.status_code == 200, r.text
    cfg = r.json()
    assert cfg["documentType"] == "word"
    assert cfg["document"]["fileType"] == "docx"
    assert cfg["token"]
    assert "/onlyoffice/archivo/" in cfg["document"]["url"]
    token = cfg["document"]["url"].rsplit("/", 1)[-1]

    r = client.get("/onlyoffice/archivo/" + token)
    assert r.status_code == 200, r.text
    data = r.content
    assert zipfile.is_zipfile(io.BytesIO(data))

    r = client.post("/onlyoffice/callback?t=" + token, json={"status": 1})
    assert r.status_code == 200, r.text
    assert r.json().get("error") == 0

    r = client.post("/onlyoffice/nuevo", json={
        "oferta_id": o["id"], "tipo": "cell",
    }, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["nombre"].endswith(".xlsx")
    r = client.post("/onlyoffice/nuevo", json={
        "oferta_id": o["id"], "tipo": "slide",
    }, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["nombre"].endswith(".pptx")

    pdf = (
        b"%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
    )
    r = client.post(
        f"/ofertas/{o['id']}/anexos",
        headers=h,
        data={"tipo": "oferta_proveedor", "ocr": "false"},
        files={"archivo": ("pliego.pdf", pdf, "application/pdf")},
    )
    assert r.status_code == 201, r.text
    pdf_id = r.json()["id"]
    r = client.post("/onlyoffice/config", json={
        "origen": "anexo", "id": pdf_id, "modo": "edit",
    }, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["documentType"] == "pdf"
    assert r.json()["modo"] == "view"


def test_onlyoffice_03b_url_misma_lan_usa_host_docker():
    from app.plataforma.onlyoffice_ops import url_para_document_server
    assert url_para_document_server(
        "http://192.168.88.201:8082", "http://192.168.88.201"
    ) == "http://host.docker.internal"
    assert url_para_document_server(
        "http://192.168.88.201:8082", "http://192.168.88.125:8100"
    ) == "http://192.168.88.125:8100"
    assert url_para_document_server(
        "http://127.0.0.1:8082", "http://127.0.0.1:8100"
    ) == "http://127.0.0.1:8100"


def test_onlyoffice_03_url_invalida(client):
    h = _admin(client)
    r = client.put("/generales/onlyoffice", json={
        "onlyoffice_url": "ftp://no-vale",
    }, headers=h)
    assert r.status_code == 400
