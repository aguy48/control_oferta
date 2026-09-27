"""
Traspaso de ofertas ganadas por el MCP (MASTER CONTROL PROJECT).

El Sistema de Cotización es un nodo del MCP con rol "cotizacion" (alta en el
paso 28 del MCP, token X-SBC-Token). No hay conexión directa con los SBC:

  1. publicar()     POST /nodos-sbc/traspasos          la oferta, dirigida a un SBC
  2. (el MCP encola importar_oferta; el SBC la baja a su bandeja y acusa)
  3. sincronizar()  GET  /nodos-sbc/traspasos?codigo=  lee los acuses y, si el
                    SBC la aceptó, vincula la oferta al proyecto y contrato.

La descarga manual del archivo sigue disponible como contingencia.
"""
from __future__ import annotations

import json
import logging
import socket
import urllib.error
import urllib.parse
import urllib.request

from sqlalchemy.orm import Session

from app.kernel.audit import registrar
from app.kernel.config import APP_VERSION, settings
from app.kernel.models import Oferta, now
from app.conexion_control_proyecto.traspaso import construir_traspaso

logger = logging.getLogger("sistema_cotizacion")

# Estados del buzón del MCP que ya no cambian.
FINALES = ("aceptado", "rechazado")


class McpError(RuntimeError):
    def __init__(self, mensaje: str, http_status: int | None = None):
        super().__init__(mensaje)
        self.http_status = http_status


def _llamar(method: str, path: str, body: dict | None = None) -> dict | list:
    if not settings.mcp_configurado():
        raise McpError("El MCP no está configurado (MCP_URL y MCP_TOKEN en Backend/.env).")
    req = urllib.request.Request(
        settings.MCP_URL + path,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None,
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "X-SBC-Token": settings.MCP_TOKEN},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=settings.MCP_TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        cuerpo = e.read().decode("utf-8", errors="replace")
        try:
            detalle = json.loads(cuerpo).get("detail") or cuerpo
        except ValueError:
            detalle = cuerpo
        raise McpError(f"El MCP respondió {e.code}: {str(detalle)[:400]}", e.code) from e
    except (urllib.error.URLError, OSError) as e:
        raise McpError(f"No se alcanzó el MCP en {settings.MCP_URL}: {getattr(e, 'reason', e)}") from e
    return json.loads(raw) if raw else {}


def latido() -> dict:
    """Para que el MCP muestre este nodo en línea (Monitoreo / paso 28)."""
    return _llamar("POST", "/nodos-sbc/latido", {
        "hostname": socket.gethostname(),
        "version_api": APP_VERSION,
        "version_html": APP_VERSION,
    })


def destinos() -> list[dict]:
    return _llamar("GET", "/nodos-sbc/traspasos/destinos")


def _aplicar_estado(db: Session, o: Oferta, t: dict) -> bool:
    """Refleja en la oferta el estado del buzón. Devuelve True si cambió."""
    estado = t.get("estado")
    cambio = estado != o.mcp_estado or (t.get("version") and t.get("version") != o.mcp_version)
    o.mcp_traspaso_id = t.get("id") or o.mcp_traspaso_id
    o.mcp_version = t.get("version") or o.mcp_version
    o.mcp_estado = estado
    o.mcp_detalle = t.get("detalle")
    o.mcp_actualizado_en = now()
    if not cambio:
        db.commit()
        return False
    if estado == "aceptado":
        o.proyecto_cp_id = t.get("proyecto_id") or o.proyecto_cp_id
        o.contrato_cp_numero = t.get("contrato_numero") or o.contrato_cp_numero
        o.vinculado_en = now()
        o.vinculado_por = "MCP"
    db.commit()
    destino = t.get("destino_nombre") or "SBC"
    if estado == "aceptado":
        registrar(db, accion="proyecto_vinculado", entidad="oferta", entidad_id=o.codigo,
                  detalle=f"vía MCP: {destino} proyecto={o.proyecto_cp_id} contrato={o.contrato_cp_numero or '-'}")
    elif estado == "rechazado":
        registrar(db, accion="proyecto_creacion_fallida", entidad="oferta", entidad_id=o.codigo,
                  resultado="error", detalle=f"vía MCP: {destino} rechazó la oferta: {o.mcp_detalle or 'sin motivo'}")
    elif estado in ("entregado", "recibido"):
        registrar(db, accion=f"traspaso_mcp_{estado}", entidad="oferta", entidad_id=o.codigo,
                  detalle=f"{destino} v{o.mcp_version}")
    elif estado == "error":
        registrar(db, accion="traspaso_mcp_error", entidad="oferta", entidad_id=o.codigo,
                  resultado="error", detalle=f"{destino}: {o.mcp_detalle or ''}")
    return True


def enviar(db: Session, o: Oferta, usuario=None, ip: str | None = None) -> Oferta:
    """Publica la oferta ganada en el MCP para su SBC destino."""
    if o.estado != "ganada":
        raise McpError("Solo se envían por el MCP ofertas ganadas.", 409)
    if not o.mcp_destino_id:
        raise McpError("Elige el SBC destino de la oferta antes de enviarla por el MCP.", 422)
    datos = construir_traspaso(o)
    try:
        t = _llamar("POST", "/nodos-sbc/traspasos", {"destino_nodo_id": o.mcp_destino_id, "traspaso": datos})
    except McpError as e:
        o.mcp_estado = "error_envio"
        o.mcp_detalle = str(e)
        o.mcp_actualizado_en = now()
        db.commit()
        registrar(db, usuario=usuario, accion="traspaso_mcp_error", entidad="oferta", entidad_id=o.codigo,
                  resultado="error", ip=ip, detalle=str(e))
        raise
    o.traspasos_generados = (o.traspasos_generados or 0) + 1
    sin_cambios = bool(t.get("sin_cambios"))
    o.mcp_traspaso_id = t.get("id")
    o.mcp_version = t.get("version")
    o.mcp_estado = t.get("estado")
    o.mcp_detalle = t.get("detalle")
    o.mcp_actualizado_en = now()
    db.commit()
    registrar(db, usuario=usuario, accion="traspaso_mcp_enviado", entidad="oferta", entidad_id=o.codigo, ip=ip,
              detalle=f"→ {t.get('destino_nombre') or o.sede_destino or o.mcp_destino_id} v{o.mcp_version}"
                      + (" (sin cambios)" if sin_cambios else "")
                      + f" huella={datos['origen']['huella_sha256'][:12]}")
    return o


def sincronizar(db: Session) -> dict:
    """Lee del MCP los acuses de las ofertas enviadas que aún no terminan."""
    pendientes = (
        db.query(Oferta)
        .filter(Oferta.mcp_traspaso_id.isnot(None))
        .filter((Oferta.mcp_estado.is_(None)) | (~Oferta.mcp_estado.in_(FINALES)))
        .all()
    )
    if not pendientes:
        return {"consultadas": 0, "cambios": 0}
    por_codigo = {o.codigo: o for o in pendientes}
    qs = urllib.parse.urlencode([("codigo", c) for c in por_codigo])
    filas = _llamar("GET", "/nodos-sbc/traspasos?" + qs)
    cambios = 0
    for t in filas or []:
        o = por_codigo.get(t.get("codigo_oferta"))
        if o is not None and _aplicar_estado(db, o, t):
            cambios += 1
    return {"consultadas": len(por_codigo), "cambios": cambios}


def ciclo_periodico(db_factory) -> None:
    """Un paso del planificador: latido + acuses (sin romper si el MCP no responde)."""
    if not settings.mcp_configurado():
        return
    db = db_factory()
    try:
        latido()
        sincronizar(db)
    except McpError as e:
        logger.info("MCP no disponible: %s", e)
    except Exception:
        logger.exception("Fallo inesperado sincronizando con el MCP")
    finally:
        db.close()
