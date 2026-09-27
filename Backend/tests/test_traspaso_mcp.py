"""Traspaso por el MCP: envío al ganar, acuses y vinculación automática.

El MCP se simula con el mismo contrato de datos del buzón real
(oriol-control-de-proyecto: plataforma/traspaso_mcp_ops.py).
"""
import pytest

from .conftest import auth_headers, crear_usuario, token
from .test_ofertas_traspaso import PARTIDAS


class McpFalso:
    def __init__(self):
        self.traspasos = {}     # codigo -> fila del buzón
        self.caido = False
        self.latidos = 0

    def __call__(self, method, path, body=None):
        from app.conexion_control_proyecto.mcp import McpError
        if self.caido:
            raise McpError("No se alcanzó el MCP en http://mcp: sin túnel")
        if path == "/nodos-sbc/latido":
            self.latidos += 1
            return {"estado": "en_linea"}
        if path == "/nodos-sbc/traspasos/destinos":
            return [{"id": "nodo-sbc-1", "nombre": "sbc-centro", "sitio_codigo": "centro", "estado": "en_linea"}]
        if method == "POST" and path == "/nodos-sbc/traspasos":
            if body["destino_nodo_id"] != "nodo-sbc-1":
                raise McpError("El MCP respondió 404: El SBC destino no existe", 404)
            d = body["traspaso"]
            cod = d["origen"]["codigo_oferta"]
            t = self.traspasos.get(cod)
            if t and t["estado"] == "aceptado":
                raise McpError("El MCP respondió 409: ya aceptada", 409)
            if t and t["huella"] == d["origen"]["huella_sha256"]:
                return {**t, "sin_cambios": True}
            t = {"id": "t-" + cod, "codigo_oferta": cod, "estado": "pendiente",
                 "version": (t["version"] + 1) if t else 1, "huella": d["origen"]["huella_sha256"],
                 "destino_nombre": "sbc-centro", "datos": d}
            self.traspasos[cod] = t
            return {k: v for k, v in t.items() if k != "datos"}
        if method == "GET" and path.startswith("/nodos-sbc/traspasos?"):
            return [{k: v for k, v in t.items() if k != "datos"} for t in self.traspasos.values()]
        raise AssertionError(f"llamada inesperada {method} {path}")

    def acusar(self, cod, estado, **extra):
        self.traspasos[cod].update(estado=estado, **extra)


@pytest.fixture()
def mcp(monkeypatch):
    from app.conexion_control_proyecto import mcp as modulo
    from app.kernel.config import settings
    falso = McpFalso()
    monkeypatch.setattr(settings, "MCP_URL", "http://mcp")
    monkeypatch.setattr(settings, "MCP_TOKEN", "tok-cotizacion")
    monkeypatch.setattr(modulo, "_llamar", falso)
    return falso


@pytest.fixture(scope="module")
def h(client):
    crear_usuario("analista_mcp", "analista", "Ana MCP")
    return auth_headers(token(client, "analista_mcp"))


def _oferta_lista(client, h, **extra):
    body = {"titulo": "Mantenimiento por MCP", "cliente_razon_social": "PDVSA", "cliente_rif": "J-1",
            "modalidad": "ejecucion", "facturacion": "detallada", **extra}
    o = client.post("/ofertas", json=body, headers=h).json()
    client.put(f"/ofertas/{o['id']}/partidas", json=PARTIDAS, headers=h)
    client.post(f"/ofertas/{o['id']}/estado", json={"estado": "enviada"}, headers=h)
    return o


def _ganar(client, h, oid):
    r = client.post(f"/ofertas/{oid}/estado", json={"estado": "ganada"}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_estado_mcp_lista_destinos(client, h, mcp):
    r = client.get("/mcp/estado", headers=h).json()
    assert r["configurado"] and r["ok"] and r["destinos"][0]["nombre"] == "sbc-centro"


def test_sin_mcp_configurado_queda_la_descarga(client, h):
    assert client.get("/mcp/estado", headers=h).json()["configurado"] is False
    o = _ganar(client, h, _oferta_lista(client, h, mcp_destino_id="nodo-sbc-1")["id"])
    assert o["mcp_estado"] is None
    assert client.get(f"/ofertas/{o['id']}/traspaso", headers=h).status_code == 200


def test_ganar_publica_en_el_mcp_y_el_acuse_vincula(client, h, mcp):
    o = _oferta_lista(client, h, mcp_destino_id="nodo-sbc-1", sede_destino="sbc-centro")
    o = _ganar(client, h, o["id"])
    assert o["mcp_estado"] == "pendiente" and o["mcp_version"] == 1 and o["mcp_traspaso_id"]
    datos = mcp.traspasos[o["codigo"]]["datos"]
    assert datos["formato"] == "RESPALDO_OFERTA_CONTROL_PROYECTO_V1"
    assert datos["origen"]["codigo_oferta"] == o["codigo"]

    mcp.acusar(o["codigo"], "recibido")
    assert client.post("/mcp/sincronizar", headers=h).json()["cambios"] == 1
    assert client.get(f"/ofertas/{o['id']}", headers=h).json()["mcp_estado"] == "recibido"

    mcp.acusar(o["codigo"], "aceptado", proyecto_id="mant-centro-2026", contrato_numero="4600012345")
    client.post("/mcp/sincronizar", headers=h)
    o = client.get(f"/ofertas/{o['id']}", headers=h).json()
    assert (o["proyecto_cp_id"], o["contrato_cp_numero"], o["vinculado_por"]) == ("mant-centro-2026", "4600012345", "MCP")
    ev = [e["accion"] for e in client.get(f"/ofertas/{o['id']}/eventos", headers=h).json()]
    assert ev[-4:] == ["oferta_ganada", "traspaso_mcp_enviado", "traspaso_mcp_recibido", "proyecto_vinculado"]
    # Ya aceptada: no se sigue consultando ni se puede reenviar.
    assert client.post("/mcp/sincronizar", headers=h).json()["consultadas"] == 0
    assert client.post(f"/ofertas/{o['id']}/mcp/enviar", headers=h).status_code == 409


def test_rechazo_del_sbc_queda_como_importacion_fallida(client, h, mcp):
    o = _ganar(client, h, _oferta_lista(client, h, mcp_destino_id="nodo-sbc-1")["id"])
    mcp.acusar(o["codigo"], "rechazado", detalle="Cliente sin OC firmada")
    client.post("/mcp/sincronizar", headers=h)
    ev = client.get(f"/ofertas/{o['id']}/eventos", headers=h).json()
    fallo = next(e for e in ev if e["accion"] == "proyecto_creacion_fallida")
    assert fallo["resultado"] == "error" and "Cliente sin OC firmada" in fallo["detalle"]


def test_mcp_caido_no_impide_ganar_y_se_reenvia(client, h, mcp):
    mcp.caido = True
    o = _ganar(client, h, _oferta_lista(client, h, mcp_destino_id="nodo-sbc-1")["id"])
    assert o["estado"] == "ganada" and o["mcp_estado"] == "error_envio" and "sin túnel" in o["mcp_detalle"]
    assert client.post(f"/ofertas/{o['id']}/mcp/enviar", headers=h).status_code == 502
    mcp.caido = False
    r = client.post(f"/ofertas/{o['id']}/mcp/enviar", headers=h)
    assert r.status_code == 200 and r.json()["mcp_estado"] == "pendiente"
    # Reenviar sin cambios no crea otra versión.
    assert client.post(f"/ofertas/{o['id']}/mcp/enviar", headers=h).json()["mcp_version"] == 1


def test_cambiar_destino_de_oferta_ganada_y_destino_invalido(client, h, mcp):
    o = _ganar(client, h, _oferta_lista(client, h)["id"])
    assert o["mcp_estado"] is None  # sin destino no se envía
    assert client.post(f"/ofertas/{o['id']}/mcp/enviar", headers=h).status_code == 422
    r = client.patch(f"/ofertas/{o['id']}", json={"mcp_destino_id": "no-existe"}, headers=h)
    assert r.status_code == 200
    assert client.post(f"/ofertas/{o['id']}/mcp/enviar", headers=h).status_code == 404


def test_ciclo_periodico_late_y_sincroniza(client, h, mcp):
    from app.conexion_control_proyecto import mcp as modulo
    from app.kernel.db import SessionLocal
    antes = mcp.latidos
    modulo.ciclo_periodico(SessionLocal)
    assert mcp.latidos == antes + 1
    mcp.caido = True
    modulo.ciclo_periodico(SessionLocal)  # no lanza aunque el MCP no responda
