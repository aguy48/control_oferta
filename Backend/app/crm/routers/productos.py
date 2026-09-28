from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.crm import acceso, producto_ops
from app.kernel.audit import registrar
from app.kernel.db import get_db
from app.kernel.deps import client_ip, require_roles
from app.kernel.models import Usuario, now
from app.kernel.schemas import (
    ProductoCotizacionOut, ProductoIn, ProductoOut, ProductoTopOut, ProductoUpdate,
)

router = APIRouter(prefix="/productos", tags=["productos"])


@router.get("", response_model=list[ProductoOut])
def listar(q: str | None = Query(None), tipo: str | None = Query(None),
           todos: bool = Query(False),
           db: Session = Depends(get_db),
           usuario: Usuario = Depends(require_roles(*acceso.ROLES_LECTURA))):
    return producto_ops.listar(db, usuario, q=q, tipo=tipo, activos=not todos)


@router.get("/estadistica/top", response_model=list[ProductoTopOut])
def top(limite: int = Query(10, ge=1, le=20), db: Session = Depends(get_db),
        usuario: Usuario = Depends(require_roles(*acceso.ROLES_LECTURA))):
    return producto_ops.top_cotizados(db, usuario, limite)


@router.post("", response_model=ProductoOut, status_code=status.HTTP_201_CREATED)
def crear(body: ProductoIn, request: Request, db: Session = Depends(get_db),
          usuario: Usuario = Depends(require_roles(*acceso.ROLES_ESCRITURA))):
    p = producto_ops.crear(db, body, usuario)
    db.commit()
    registrar(db, usuario=usuario, accion="producto_creado", entidad="producto",
              entidad_id=p.id, ip=client_ip(request), detalle=f"{p.codigo} {p.nombre}")
    return p


@router.get("/{producto_id}", response_model=ProductoOut)
def obtener(producto_id: str, db: Session = Depends(get_db),
            usuario: Usuario = Depends(require_roles(*acceso.ROLES_LECTURA))):
    return producto_ops._out(db, producto_ops.cargar(db, producto_id, usuario))


@router.get("/{producto_id}/cotizaciones", response_model=list[ProductoCotizacionOut])
def cotizaciones(producto_id: str, db: Session = Depends(get_db),
                 usuario: Usuario = Depends(require_roles(*acceso.ROLES_LECTURA))):
    p = producto_ops.cargar(db, producto_id, usuario)
    return producto_ops.cotizaciones(db, p)


@router.patch("/{producto_id}", response_model=ProductoOut)
def actualizar(producto_id: str, body: ProductoUpdate, request: Request,
               db: Session = Depends(get_db),
               usuario: Usuario = Depends(require_roles(*acceso.ROLES_ESCRITURA))):
    acceso.escritura(usuario)
    p = producto_ops.cargar(db, producto_id, usuario)
    cambios = producto_ops.actualizar(db, p, body)
    db.commit()
    db.refresh(p)
    registrar(db, usuario=usuario, accion="producto_actualizado", entidad="producto",
              entidad_id=p.id, ip=client_ip(request), detalle=", ".join(cambios) or "sin cambios")
    return producto_ops._out(db, p)


@router.delete("/{producto_id}")
def eliminar(producto_id: str, request: Request, db: Session = Depends(get_db),
             usuario: Usuario = Depends(require_roles("admin"))):
    p = producto_ops.cargar(db, producto_id, usuario)
    detalle = f"{p.codigo} {p.nombre}"
    p.activo = False
    p.actualizado_en = now()
    db.commit()
    registrar(db, usuario=usuario, accion="producto_desactivado", entidad="producto",
              entidad_id=producto_id, ip=client_ip(request), detalle=detalle)
    return {"ok": True}
