from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.kernel.audit import registrar
from app.kernel.db import get_db
from app.kernel.deps import client_ip, require_roles
from app.kernel.models import Usuario
from app.kernel.schemas import OfertaCreate, OfertaEstadoIn, OfertaOut, OfertaUpdate, PartidaIn, SerialRequeridoOut
from app.crm import oferta_ops, producto_ops
from app.crm.oferta_ops import ROLES_ESCRITURA, ROLES_LECTURA

router = APIRouter(prefix="/ofertas", tags=["ofertas"])


@router.get("", response_model=list[OfertaOut])
def listar(estado: str | None = Query(None), db: Session = Depends(get_db),
           usuario: Usuario = Depends(require_roles(*ROLES_LECTURA))):
    return oferta_ops.listar_ofertas(db, usuario, estado)


@router.post("", response_model=OfertaOut, status_code=status.HTTP_201_CREATED)
def crear(body: OfertaCreate, request: Request, db: Session = Depends(get_db),
          usuario: Usuario = Depends(require_roles(*ROLES_ESCRITURA))):
    o = oferta_ops.crear_oferta(db, body, usuario)
    db.commit()
    db.refresh(o)
    registrar(db, usuario=usuario, accion="oferta_creada", entidad="oferta",
              entidad_id=o.codigo, ip=client_ip(request), detalle=o.titulo)
    return o


@router.get("/{oferta_id}", response_model=OfertaOut)
def obtener(oferta_id: str, db: Session = Depends(get_db),
            usuario: Usuario = Depends(require_roles(*ROLES_LECTURA))):
    return oferta_ops.cargar_oferta(db, oferta_id, usuario)


@router.patch("/{oferta_id}", response_model=OfertaOut)
def actualizar(oferta_id: str, body: OfertaUpdate, request: Request,
               db: Session = Depends(get_db),
               usuario: Usuario = Depends(require_roles(*ROLES_ESCRITURA))):
    o = oferta_ops.cargar_oferta(db, oferta_id, usuario, escritura=True)
    campos = oferta_ops.actualizar_oferta(o, body, usuario)
    db.commit()
    db.refresh(o)
    registrar(db, usuario=usuario, accion="oferta_actualizada", entidad="oferta",
              entidad_id=o.codigo, ip=client_ip(request), detalle=", ".join(campos) or "sin cambios")
    return o


@router.put("/{oferta_id}/partidas", response_model=OfertaOut)
def reemplazar_partidas(oferta_id: str, body: list[PartidaIn], request: Request,
                        db: Session = Depends(get_db),
                        usuario: Usuario = Depends(require_roles(*ROLES_ESCRITURA))):
    o = oferta_ops.cargar_oferta(db, oferta_id, usuario, escritura=True)
    oferta_ops.reemplazar_partidas(db, o, body, usuario)
    db.commit()
    db.refresh(o)
    registrar(db, usuario=usuario, accion="oferta_partidas", entidad="oferta",
              entidad_id=o.codigo, ip=client_ip(request),
              detalle=f"n={len(o.partidas)} total={o.total_precio}")
    return o


@router.get("/{oferta_id}/seriales-requeridos", response_model=list[SerialRequeridoOut])
def seriales_requeridos(oferta_id: str, db: Session = Depends(get_db),
                        usuario: Usuario = Depends(require_roles(*ROLES_LECTURA))):
    o = oferta_ops.cargar_oferta(db, oferta_id, usuario)
    return producto_ops.seriales_requeridos(db, o)


@router.post("/{oferta_id}/estado", response_model=OfertaOut)
def cambiar_estado(oferta_id: str, body: OfertaEstadoIn, request: Request,
                   db: Session = Depends(get_db),
                   usuario: Usuario = Depends(require_roles(*ROLES_ESCRITURA))):
    o = oferta_ops.cargar_oferta(db, oferta_id, usuario, escritura=True)
    if body.estado == "ganada":
        producto_ops.registrar_seriales(db, o, body.seriales, usuario)
    anterior = oferta_ops.cambiar_estado(o, body.estado, usuario)
    db.commit()
    db.refresh(o)
    # "oferta_ganada" es el evento que abre la conexión con Control de
    # Proyecto (ING-COT-003 §2 y §7.8).
    accion = "oferta_ganada" if o.estado == "ganada" else "oferta_estado"
    detalle = f"{anterior}->{o.estado}"
    if o.estado == "ganada":
        detalle += f" modalidad={o.modalidad} facturacion={o.facturacion or '-'} total={o.total_precio}"
    registrar(db, usuario=usuario, accion=accion, entidad="oferta",
              entidad_id=o.codigo, ip=client_ip(request), detalle=detalle)
    if o.estado == "ganada":
        from app.conexion_control_proyecto import mcp
        if mcp.activo(db):
            # El traspaso viaja por el MCP (ING-COT-003 §5). Si falla, la oferta
            # sigue ganada: queda "error_envio" para reenviar o descargar a mano.
            try:
                mcp.enviar(db, o, usuario, client_ip(request))
            except mcp.McpError:
                pass
            db.refresh(o)
    return o


@router.delete("/{oferta_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar(oferta_id: str, request: Request, db: Session = Depends(get_db),
             usuario: Usuario = Depends(require_roles(*ROLES_ESCRITURA))):
    o = oferta_ops.cargar_oferta(db, oferta_id, usuario, escritura=True)
    codigo = oferta_ops.eliminar_oferta(db, o, usuario)
    db.commit()
    registrar(db, usuario=usuario, accion="oferta_eliminada", entidad="oferta",
              entidad_id=codigo, ip=client_ip(request), detalle="borrador")
    return None
