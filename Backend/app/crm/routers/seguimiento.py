from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.crm import acceso
from app.kernel.audit import registrar
from app.kernel.db import get_db
from app.kernel.deps import client_ip, require_roles
from app.kernel.models import Oferta, PASOS_CICLO_CP, SeguimientoPaso, Usuario, now
from app.kernel.schemas import SeguimientoIn, SeguimientoOut

router = APIRouter(prefix="/seguimiento", tags=["seguimiento"])


def _out(fila: SeguimientoPaso, oferta: Oferta | None) -> SeguimientoOut:
    return SeguimientoOut(
        id=fila.id,
        oferta_id=fila.oferta_id,
        oferta_codigo=oferta.codigo if oferta else None,
        oferta_titulo=oferta.titulo if oferta else None,
        cliente=oferta.cliente_razon_social if oferta else None,
        paso=fila.paso,
        estado=fila.estado,
        notas=fila.notas,
        actualizado_en=fila.actualizado_en,
    )


@router.get("", response_model=list[SeguimientoOut])
def listar(paso: str | None = None, db: Session = Depends(get_db),
           usuario: Usuario = Depends(require_roles(*acceso.ROLES_LECTURA))):
    esc = acceso.escenario(usuario)
    ganadas = db.query(Oferta).filter(Oferta.escenario_id == esc.id, Oferta.estado == "ganada").all()
    por_id = {o.id: o for o in ganadas}
    if not ganadas:
        return []
    q = db.query(SeguimientoPaso).filter(SeguimientoPaso.oferta_id.in_(list(por_id)))
    if paso:
        if paso not in PASOS_CICLO_CP:
            raise HTTPException(400, "Paso del ciclo desconocido")
        q = q.filter(SeguimientoPaso.paso == paso)
    filas = { (f.oferta_id, f.paso): f for f in q.all() }
    pasos = [paso] if paso else list(PASOS_CICLO_CP)
    out = []
    for o in ganadas:
        for p in pasos:
            fila = filas.get((o.id, p))
            if fila is None:
                fila = SeguimientoPaso(oferta_id=o.id, paso=p, estado="pendiente")
            out.append(_out(fila, o))
    return out


@router.put("/{oferta_id}/{paso}", response_model=SeguimientoOut)
def guardar(oferta_id: str, paso: str, body: SeguimientoIn, request: Request,
            db: Session = Depends(get_db),
            usuario: Usuario = Depends(require_roles(*acceso.ROLES_ESCRITURA))):
    acceso.escritura(usuario)
    if paso not in PASOS_CICLO_CP:
        raise HTTPException(400, "Paso del ciclo desconocido")
    esc = acceso.escenario(usuario)
    o = db.query(Oferta).filter(Oferta.id == oferta_id, Oferta.escenario_id == esc.id).first()
    if not o or o.estado != "ganada":
        raise HTTPException(404, "Solo se hace seguimiento de ofertas ganadas")
    fila = db.query(SeguimientoPaso).filter(
        SeguimientoPaso.oferta_id == o.id, SeguimientoPaso.paso == paso,
    ).first()
    if fila is None:
        fila = SeguimientoPaso(oferta_id=o.id, paso=paso)
        db.add(fila)
    fila.estado = body.estado
    fila.notas = body.notas
    fila.actualizado_por = usuario.id
    fila.actualizado_en = now()
    db.commit()
    db.refresh(fila)
    registrar(db, usuario=usuario, accion="seguimiento_ciclo", entidad="oferta",
              entidad_id=o.codigo, ip=client_ip(request),
              detalle=f"{paso}={body.estado}")
    return _out(fila, o)
