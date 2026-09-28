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
from app.kernel.crypto_secrets import descifrar
from app.kernel.models import AjusteGeneral, Oferta, now
from app.conexion_control_proyecto.traspaso import construir_traspaso

logger = logging.getLogger("sistema_cotizacion")

# Estados del buzón del MCP que ya no cambian.
FINALES = ("aceptado", "rechazado")


class McpError(RuntimeError):
    def __init__(self, mensaje: str, http_status: int | None = None):
        super().__init__(mensaje)
        self.http_status = http_status


def credenciales(db: Session | None = None) -> tuple[str, str, str]:
    """URL, token y fuente ('generales' | 'entorno' | ''). Generales manda sobre .env."""
    own = False
    if db is None:
        from app.kernel.db import SessionLocal
        db = SessionLocal()
        own = True
    try:
        fila = db.query(AjusteGeneral).filter(AjusteGeneral.id == "default").first()
        if fila is not None:
            url = (fila.mcp_url or "").strip().rstrip("/")
            token = (descifrar(fila.mcp_token_enc) or "").strip()
            if url and token:
                return url, token, "generales"
    finally:
        if own:
            db.close()
    if settings.MCP_URL and settings.MCP_TOKEN:
        return settings.MCP_URL, settings.MCP_TOKEN, "entorno"
    return "", "", ""


def activo(db: Session | None = None) -> bool:
    url, token, _ = credenciales(db)
    return bool(url and token)


def destino_instancia(db: Session | None = None) -> tuple[str | None, str | None]:
    """SBC único de esta instancia (Generales)."""
    own = False
    if db is None:
        from app.kernel.db import SessionLocal
        db = SessionLocal()
        own = True
    try:
        fila = db.query(AjusteGeneral).filter(AjusteGeneral.id == "default").first()
        if fila is None:
            return None, None
        dest = (fila.mcp_destino_id or "").strip() or None
        sede = (fila.mcp_sede_nombre or "").strip() or None
        return dest, sede
    finally:
        if own:
            db.close()


def aplicar_destino_instancia(db: Session, o: Oferta) -> str | None:
    dest, sede = destino_instancia(db)
    if dest:
        o.mcp_destino_id = dest
        if sede:
            o.sede_destino = sede
    elif sede and not o.sede_destino:
        o.sede_destino = sede
    return dest


def _llamar(method: str, path: str, body: dict | None = None) -> dict | list:
    url, token, _ = credenciales()
    if not url or not token:
        raise McpError("El MCP no está configurado (Generales: URL y token del nodo cotización).")
    req = urllib.request.Request(
        url + path,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None,
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "X-SBC-Token": token},
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
        raise McpError(f"No se alcanzó el MCP en {url}: {getattr(e, 'reason', e)}") from e
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
    """Publica la oferta ganada en el MCP para el SBC de esta instancia."""
    if o.estado != "ganada":
        raise McpError("Solo se envían por el MCP ofertas ganadas.", 409)
    aplicar_destino_instancia(db, o)
    if not o.mcp_destino_id:
        raise McpError("El administrador debe fijar el SBC destino en Generales.", 422)
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
    if not activo():
        return
    db = db_factory()
    try:
        latido()
        sincronizar(db)
        from app.conexion_control_proyecto import escenario_sbc
        escenario_sbc.sincronizar(db)
    except McpError as e:
        logger.info("MCP no disponible: %s", e)
    except Exception:
        logger.exception("Fallo inesperado sincronizando con el MCP")
    finally:
        db.close()
