from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.crm import acceso
from app.kernel.audit import registrar
from app.kernel.db import get_db
from app.kernel.deps import client_ip, require_roles
from app.kernel.models import Proveedor, Usuario, now
from app.kernel.schemas import ProveedorIn, ProveedorOut, ProveedorUpdate

router = APIRouter(prefix="/proveedores", tags=["proveedores"])
CAMPOS = ("razon_social", "rif", "contacto", "telefono", "email", "notas", "activo")


def _cargar(db: Session, proveedor_id: str, usuario: Usuario) -> Proveedor:
    esc = acceso.escenario(usuario)
    p = db.query(Proveedor).filter(Proveedor.id == proveedor_id, Proveedor.escenario_id == esc.id).first()
    return acceso.o_404(p, "Proveedor no encontrado")


@router.get("", response_model=list[ProveedorOut])
def listar(db: Session = Depends(get_db),
           usuario: Usuario = Depends(require_roles(*acceso.ROLES_LECTURA))):
    esc = acceso.escenario(usuario)
    return db.query(Proveedor).filter(Proveedor.escenario_id == esc.id).order_by(Proveedor.razon_social).all()


@router.post("", response_model=ProveedorOut, status_code=status.HTTP_201_CREATED)
def crear(body: ProveedorIn, request: Request, db: Session = Depends(get_db),
          usuario: Usuario = Depends(require_roles(*acceso.ROLES_ESCRITURA))):
    acceso.escritura(usuario)
    esc = acceso.escenario(usuario)
    p = Proveedor(escenario_id=esc.id, creado_por=usuario.id, **body.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    registrar(db, usuario=usuario, accion="proveedor_creado", entidad="proveedor",
              entidad_id=p.id, ip=client_ip(request), detalle=p.razon_social)
    return p


@router.patch("/{proveedor_id}", response_model=ProveedorOut)
def actualizar(proveedor_id: str, body: ProveedorUpdate, request: Request,
               db: Session = Depends(get_db),
               usuario: Usuario = Depends(require_roles(*acceso.ROLES_ESCRITURA))):
    acceso.escritura(usuario)
    p = _cargar(db, proveedor_id, usuario)
    cambios = acceso.aplicar(p, body, CAMPOS)
    p.actualizado_en = now()
    db.commit()
    db.refresh(p)
    registrar(db, usuario=usuario, accion="proveedor_actualizado", entidad="proveedor",
              entidad_id=p.id, ip=client_ip(request), detalle=", ".join(cambios) or "sin cambios")
    return p


@router.delete("/{proveedor_id}")
def eliminar(proveedor_id: str, request: Request, db: Session = Depends(get_db),
             usuario: Usuario = Depends(require_roles("admin"))):
    p = _cargar(db, proveedor_id, usuario)
    detalle = p.razon_social
    db.delete(p)
    db.commit()
    registrar(db, usuario=usuario, accion="proveedor_eliminado", entidad="proveedor",
              entidad_id=proveedor_id, ip=client_ip(request), detalle=detalle)
    return {"ok": True}
