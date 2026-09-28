"""Asistente de ayuda (01–16) y modo mejora (solo admin)."""
from .conftest import crear_usuario, token, auth_headers


def _h(client, usuario, rol):
    crear_usuario(usuario, rol)
    return auth_headers(token(client, usuario))


def test_asistente_exige_autenticacion(client):
    r = client.get("/asistente/opciones")
    assert r.status_code == 401
    r = client.post("/asistente/consultar", json={"mensaje": "ofertas"})
    assert r.status_code == 401


def test_asistente_catalogo_numerado_por_rol(client):
    h_admin = _h(client, "bot_admin", "admin")
    r = client.get("/asistente/opciones", headers=h_admin)
    assert r.status_code == 200, r.text
    ops = r.json()["opciones"]
    assert ops[0]["paso"] == 1
    assert ops[0]["id"] == "panel"
    ids = [o["id"] for o in ops]
    assert ops[-1]["id"] == "generales"
    assert ops[-1]["paso"] == 16
    assert "ofertas" in ids
    assert "productos" in ids
    assert "usuarios" in ids
    assert "escenarios" in ids
    assert "eventos" in ids
    assert "respaldo" in ids
    assert next(o["paso"] for o in ops if o["id"] == "ofertas") == 2
    assert next(o["paso"] for o in ops if o["id"] == "clientes") == 5
    assert next(o["paso"] for o in ops if o["id"] == "eventos") == 13
    assert next(o["paso"] for o in ops if o["id"] == "respaldo") == 14
    assert next(o["paso"] for o in ops if o["id"] == "escenarios") == 15

    h_ana = _h(client, "bot_analista", "analista")
    r = client.get("/asistente/opciones", headers=h_ana)
    ids_ana = [o["id"] for o in r.json()["opciones"]]
    assert "ofertas" in ids_ana
    assert "usuarios" not in ids_ana
    assert "generales" not in ids_ana
    assert "escenarios" not in ids_ana
    assert "eventos" not in ids_ana
    assert "respaldo" not in ids_ana
    ofe = next(o for o in r.json()["opciones"] if o["id"] == "ofertas")
    assert ofe["paso"] == 2

    h_aud = _h(client, "bot_auditor", "auditor")
    ids_aud = [o["id"] for o in client.get("/asistente/opciones", headers=h_aud).json()["opciones"]]
    assert "auditoria" in ids_aud
    assert "eventos" in ids_aud
    assert "respaldo" in ids_aud
    assert "usuarios" not in ids_aud
    assert "generales" not in ids_aud

    h_noc = _h(client, "bot_noc", "TECNICO_NOC_SOC")
    ids_noc = [o["id"] for o in client.get("/asistente/opciones", headers=h_noc).json()["opciones"]]
    assert "auditoria" in ids_noc
    assert "eventos" in ids_noc
    assert "respaldo" not in ids_noc
    assert "generales" not in ids_noc


def test_asistente_ayuda_por_nombre_y_por_paso(client):
    h = _h(client, "bot_ana2", "analista")

    r = client.post("/asistente/consultar", json={"mensaje": ""}, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["modo"] == "ayuda"
    assert "01" in body["respuesta"]
    assert "16 Generales" not in body["respuesta"]
    assert "10 Documentos" in body["respuesta"]
    assert body["sugerencias"]

    r = client.post("/asistente/consultar", json={"mensaje": "ofertas"}, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["opcion_id"] == "ofertas"
    assert body["destino"] == "ofertas"
    assert "02" in body["respuesta"] or "Ofertas" in body["respuesta"]

    r = client.post("/asistente/consultar", json={"mensaje": "reportes onlyoffice"}, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["opcion_id"] == "reportes"
    assert "word" in body["respuesta"].lower() or "onlyoffice" in body["respuesta"].lower()

    r = client.post("/asistente/consultar", json={"mensaje": "secuencia"}, headers=h)
    assert r.status_code == 200
    texto = r.json()["respuesta"]
    assert "01" in texto and "Panel" in texto
    assert "02" in texto and "Ofertas" in texto

    h_adm = _h(client, "bot_adm2", "admin")
    r = client.post("/asistente/consultar", json={"mensaje": "escenarios sbc"}, headers=h_adm)
    assert r.status_code == 200
    esc = r.json()
    assert esc["opcion_id"] == "escenarios"
    assert "sbc" in esc["respuesta"].lower()

    r = client.post("/asistente/consultar", json={"mensaje": "generales telegram"}, headers=h_adm)
    assert r.status_code == 200
    gen = r.json()
    assert gen["opcion_id"] == "generales"
    gtxt = gen["respuesta"].lower()
    assert "telegram" in gtxt
    assert "mcp" in gtxt or "sbc" in gtxt
    assert "onlyoffice" in gtxt

    r = client.post("/asistente/consultar", json={"mensaje": "eventos mcp"}, headers=h_adm)
    assert r.status_code == 200
    assert r.json()["opcion_id"] == "eventos"

    r = client.post("/asistente/consultar", json={"mensaje": "respaldo"}, headers=h_adm)
    assert r.status_code == 200
    assert r.json()["opcion_id"] == "respaldo"

    r = client.post("/asistente/consultar", json={"mensaje": "paso 16"}, headers=h_adm)
    assert r.status_code == 200
    assert r.json()["opcion_id"] == "generales"

    r = client.post("/asistente/consultar", json={"mensaje": ""}, headers=h_adm)
    assert r.status_code == 200
    bien = r.json()["respuesta"]
    assert "16 Generales" in bien
    assert "Eventos (13)" in bien
    assert "Respaldo (14)" in bien


def test_asistente_mejora_solo_admin(client):
    h_ana = _h(client, "bot_ana3", "analista")
    r = client.post("/asistente/consultar", json={"mensaje": "", "modo": "mejora"}, headers=h_ana)
    assert r.status_code == 403

    h_adm = _h(client, "bot_adm3", "admin")
    r = client.post("/asistente/consultar", json={"mensaje": "", "modo": "mejora"}, headers=h_adm)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["modo"] == "mejora"
    assert "administrador" in body["respuesta"].lower() or body["recomendaciones"]
    assert "14 Generales" not in body["respuesta"]
    assert "16 Generales" in body["respuesta"]
    recs = " ".join(body.get("recomendaciones") or [])
    assert "Eventos (13)" in recs or "Eventos (13)" in body["respuesta"]
    assert "Respaldo (14)" in recs or "Respaldo (14)" in body["respuesta"]
    ids = [s["id"] for s in body["sugerencias"]]
    assert "eventos" in ids and "respaldo" in ids and "generales" in ids
