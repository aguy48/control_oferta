"""
Traspaso de la oferta ganada a Control de Proyecto (ING-COT-003 §5).

Entrega por descarga + importación manual: no hay red entre instancias.
1. GET  /ofertas/{id}/traspaso            → descarga del archivo JSON.
2. (El analista lo sube en el formulario de Contrato de Control de Proyecto.)
3. POST /ofertas/{id}/vinculacion         → registra a mano el proyecto creado.
   POST /ofertas/{id}/importacion-fallida → registra que la importación falló.
4. GET  /ofertas/{id}/eventos             → bitácora de la conexión.
"""
import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.kernel.audit import registrar
from app.kernel.db import get_db
from app.kernel.deps import client_ip, require_roles
from app.kernel.models import BitacoraEvento, Usuario, now
from app.kernel.schemas import OfertaOut, OfertaVinculacionIn
from app.crm import oferta_ops
from app.crm.oferta_ops import ROLES_ESCRITURA, ROLES_LECTURA
from app.conexion_control_proyecto.traspaso import (
    TraspasoInvalido, construir_traspaso, nombre_archivo,
)

router = APIRouter(prefix="/ofertas", tags=["conexion_control_proyecto"])

ACCIONES_CONEXION = (
    "oferta_ganada", "traspaso_generado", "proyecto_vinculado", "proyecto_creacion_fallida",
    "traspaso_mcp_enviado", "traspaso_mcp_entregado", "traspaso_mcp_recibido", "traspaso_mcp_error",
)


def _exigir_ganada(o) -> None:
    if o.estado != "ganada":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "El traspaso a Control de Proyecto solo está disponible con la oferta ganada.",
        )


@router.get("/{oferta_id}/traspaso")
def descargar_traspaso(oferta_id: str, request: Request, db: Session = Depends(get_db),
                       usuario: Usuario = Depends(require_roles(*ROLES_ESCRITURA))):
    o = oferta_ops.cargar_oferta(db, oferta_id, usuario)
    _exigir_ganada(o)
    try:
        data = construir_traspaso(o)
    except TraspasoInvalido as e:
        raise HTTPException(422, str(e))
    o.traspasos_generados = (o.traspasos_generados or 0) + 1
    db.commit()
    registrar(db, usuario=usuario, accion="traspaso_generado", entidad="oferta",
              entidad_id=o.codigo, ip=client_ip(request),
              detalle=f"n={o.traspasos_generados} huella={data['origen']['huella_sha256'][:12]}")
    nombre = nombre_archivo(o)
    return Response(
        content=json.dumps(data, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


@router.post("/{oferta_id}/vinculacion", response_model=OfertaOut)
def vincular_proyecto(oferta_id: str, body: OfertaVinculacionIn, request: Request,
                      db: Session = Depends(get_db),
                      usuario: Usuario = Depends(require_roles(*ROLES_ESCRITURA))):
    """Referencia cruzada al proyecto creado en Control de Proyecto (§7.5 y §7.7)."""
    o = oferta_ops.cargar_oferta(db, oferta_id, usuario, escritura=True)
    _exigir_ganada(o)
    anterior = o.proyecto_cp_id
    o.proyecto_cp_id = body.proyecto_cp_id.strip()
    o.contrato_cp_numero = (body.contrato_cp_numero or "").strip() or None
    o.vinculado_en = now()
    o.vinculado_por = usuario.id
    db.commit()
    db.refresh(o)
    detalle = f"proyecto={o.proyecto_cp_id} contrato={o.contrato_cp_numero or '-'}"
    if anterior and anterior != o.proyecto_cp_id:
        detalle += f" (antes {anterior})"
    registrar(db, usuario=usuario, accion="proyecto_vinculado", entidad="oferta",
              entidad_id=o.codigo, ip=client_ip(request), detalle=detalle)
    return o


class ImportacionFallidaIn(BaseModel):
    motivo: str = Field(min_length=3, max_length=1000)


@router.post("/{oferta_id}/importacion-fallida", status_code=status.HTTP_204_NO_CONTENT)
def registrar_importacion_fallida(oferta_id: str, body: ImportacionFallidaIn, request: Request,
                                  db: Session = Depends(get_db),
                                  usuario: Usuario = Depends(require_roles(*ROLES_ESCRITURA))):
    o = oferta_ops.cargar_oferta(db, oferta_id, usuario, escritura=True)
    _exigir_ganada(o)
    registrar(db, usuario=usuario, accion="proyecto_creacion_fallida", entidad="oferta",
              entidad_id=o.codigo, resultado="error", ip=client_ip(request), detalle=body.motivo)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{oferta_id}/eventos")
def eventos_conexion(oferta_id: str, db: Session = Depends(get_db),
                     usuario: Usuario = Depends(require_roles(*ROLES_LECTURA))):
    o = oferta_ops.cargar_oferta(db, oferta_id, usuario)
    filas = (
        db.query(BitacoraEvento)
        .filter(BitacoraEvento.entidad == "oferta", BitacoraEvento.entidad_id == o.codigo)
        .order_by(BitacoraEvento.timestamp)
        .all()
    )
    return [
        {
            "timestamp": e.timestamp, "accion": e.accion, "resultado": e.resultado,
            "usuario": e.usuario_nombre, "detalle": e.detalle,
            "conexion": e.accion in ACCIONES_CONEXION,
        }
        for e in filas
    ]


# ---------------------------------------------------------------- MCP
mcp_router = APIRouter(tags=["conexion_control_proyecto"])


@mcp_router.get("/mcp/estado")
def estado_mcp(db: Session = Depends(get_db),
               _u: Usuario = Depends(require_roles(*ROLES_LECTURA))):
    """Si el MCP está configurado y responde, con la lista de SBC y el destino único."""
    from app.conexion_control_proyecto import mcp
    dest_id, sede = mcp.destino_instancia(db)
    url, _token, fuente = mcp.credenciales(db)
    if not url:
        return {"configurado": False, "url": None, "ok": False, "destinos": [],
                "destino_id": dest_id, "sede_nombre": sede, "fuente": None,
                "escenarios": [],
                "detalle": "Sin MCP: el administrador lo configura en Generales (URL, token y SBC)."}
    try:
        destinos = mcp.destinos()
        escenarios = []
        for d in destinos:
            if d.get("id") == dest_id:
                escenarios = d.get("escenarios") or []
                break
        return {"configurado": True, "url": url, "ok": True, "destinos": destinos,
                "destino_id": dest_id, "sede_nombre": sede, "fuente": fuente,
                "escenarios": escenarios}
    except mcp.McpError as e:
        return {"configurado": True, "url": url, "ok": False, "destinos": [],
                "destino_id": dest_id, "sede_nombre": sede, "fuente": fuente,
                "escenarios": [], "detalle": str(e)}


@mcp_router.post("/ofertas/{oferta_id}/mcp/enviar", response_model=OfertaOut)
def enviar_por_mcp(oferta_id: str, request: Request, db: Session = Depends(get_db),
                   usuario: Usuario = Depends(require_roles(*ROLES_ESCRITURA))):
    """Envía (o reenvía) la oferta ganada al SBC fijado en Generales."""
    from app.conexion_control_proyecto import mcp
    o = oferta_ops.cargar_oferta(db, oferta_id, usuario, escritura=True)
    _exigir_ganada(o)
    try:
        mcp.enviar(db, o, usuario, client_ip(request))
    except mcp.McpError as e:
        codigo = e.http_status if e.http_status in (404, 409, 422) else status.HTTP_502_BAD_GATEWAY
        raise HTTPException(codigo, str(e))
    db.refresh(o)
    return o


@mcp_router.post("/mcp/sincronizar")
def sincronizar_mcp(db: Session = Depends(get_db),
                    usuario: Usuario = Depends(require_roles(*ROLES_ESCRITURA))):
    """Consulta ya los acuses del MCP (sin esperar el ciclo periódico)."""
    from app.conexion_control_proyecto import mcp
    try:
        return mcp.sincronizar(db)
    except mcp.McpError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))


@mcp_router.post("/mcp/escenarios/sincronizar")
def sincronizar_escenarios_sbc(db: Session = Depends(get_db),
                               _u: Usuario = Depends(require_roles("admin"))):
    """Espeja en esta instancia los escenarios del SBC elegido en Generales."""
    from app.conexion_control_proyecto import escenario_sbc
    return escenario_sbc.sincronizar(db)
