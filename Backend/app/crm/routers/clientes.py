from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.crm import acceso
from app.kernel.audit import registrar
from app.kernel.db import get_db
from app.kernel.deps import client_ip, require_roles
from app.kernel.models import Cliente, Oferta, Usuario, now
from app.kernel.schemas import ClienteIn, ClienteOut, ClienteUpdate

router = APIRouter(prefix="/clientes", tags=["clientes"])
CAMPOS = ("razon_social", "rif", "direccion", "telefono", "email", "tipo",
          "condicion_pago", "notas", "activo")


def _out(db: Session, c: Cliente) -> ClienteOut:
    n = 0
    ofertas = db.query(Oferta).filter(Oferta.escenario_id == c.escenario_id).all()
    for o in ofertas:
        if c.rif_norm and acceso.rif_norm(o.cliente_rif) == c.rif_norm:
            n += 1
        elif not c.rif_norm and o.cliente_razon_social == c.razon_social:
            n += 1
    return ClienteOut(
        id=c.id, razon_social=c.razon_social, rif=c.rif, rif_norm=c.rif_norm,
        direccion=c.direccion, telefono=c.telefono, email=c.email, tipo=c.tipo,
        condicion_pago=c.condicion_pago, notas=c.notas, activo=c.activo,
        n_ofertas=n, creado_en=c.creado_en,
    )


def _cargar(db: Session, cliente_id: str, usuario: Usuario) -> Cliente:
    esc = acceso.escenario(usuario)
    c = db.query(Cliente).filter(Cliente.id == cliente_id, Cliente.escenario_id == esc.id).first()
    return acceso.o_404(c, "Cliente no encontrado")


@router.get("", response_model=list[ClienteOut])
def listar(db: Session = Depends(get_db),
           usuario: Usuario = Depends(require_roles(*acceso.ROLES_LECTURA))):
    esc = acceso.escenario(usuario)
    filas = db.query(Cliente).filter(Cliente.escenario_id == esc.id).order_by(Cliente.razon_social).all()
    return [_out(db, c) for c in filas]


@router.post("", response_model=ClienteOut, status_code=status.HTTP_201_CREATED)
def crear(body: ClienteIn, request: Request, db: Session = Depends(get_db),
          usuario: Usuario = Depends(require_roles(*acceso.ROLES_ESCRITURA))):
    acceso.escritura(usuario)
    esc = acceso.escenario(usuario)
    c = Cliente(
        escenario_id=esc.id, creado_por=usuario.id,
        **body.model_dump(),
        rif_norm=acceso.rif_norm(body.rif),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    registrar(db, usuario=usuario, accion="cliente_creado", entidad="cliente",
              entidad_id=c.id, ip=client_ip(request), detalle=c.razon_social)
    return _out(db, c)


@router.patch("/{cliente_id}", response_model=ClienteOut)
def actualizar(cliente_id: str, body: ClienteUpdate, request: Request,
               db: Session = Depends(get_db),
               usuario: Usuario = Depends(require_roles(*acceso.ROLES_ESCRITURA))):
    acceso.escritura(usuario)
    c = _cargar(db, cliente_id, usuario)
    cambios = acceso.aplicar(c, body, CAMPOS)
    if "rif" in cambios or (body.rif is not None):
        c.rif_norm = acceso.rif_norm(c.rif)
    c.actualizado_en = now()
    db.commit()
    db.refresh(c)
    registrar(db, usuario=usuario, accion="cliente_actualizado", entidad="cliente",
              entidad_id=c.id, ip=client_ip(request), detalle=", ".join(cambios) or "sin cambios")
    return _out(db, c)


@router.delete("/{cliente_id}")
def eliminar(cliente_id: str, request: Request, db: Session = Depends(get_db),
             usuario: Usuario = Depends(require_roles("admin"))):
    c = _cargar(db, cliente_id, usuario)
    detalle = c.razon_social
    db.delete(c)
    db.commit()
    registrar(db, usuario=usuario, accion="cliente_eliminado", entidad="cliente",
              entidad_id=cliente_id, ip=client_ip(request), detalle=detalle)
    return {"ok": True}
