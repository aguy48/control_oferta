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
