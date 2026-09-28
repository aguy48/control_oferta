from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.crm import acceso
from app.kernel.audit import registrar
from app.kernel.db import get_db
from app.kernel.deps import client_ip, require_roles
from app.kernel.models import Cliente, Contacto, Usuario, now
from app.kernel.schemas import ContactoIn, ContactoOut, ContactoUpdate

router = APIRouter(prefix="/contactos", tags=["contactos"])
CAMPOS = ("nombre", "cargo", "email", "telefono", "tipo_responsable", "cliente_id", "notas")


def _out(db: Session, c: Contacto) -> ContactoOut:
    razon = None
    if c.cliente_id:
        cli = db.query(Cliente).filter(Cliente.id == c.cliente_id).first()
        razon = cli.razon_social if cli else None
    return ContactoOut(
        id=c.id, nombre=c.nombre, cargo=c.cargo, email=c.email, telefono=c.telefono,
        tipo_responsable=c.tipo_responsable, cliente_id=c.cliente_id, notas=c.notas,
        cliente_razon=razon, creado_en=c.creado_en,
    )


def _cargar(db: Session, contacto_id: str, usuario: Usuario) -> Contacto:
    esc = acceso.escenario(usuario)
    c = db.query(Contacto).filter(Contacto.id == contacto_id, Contacto.escenario_id == esc.id).first()
    return acceso.o_404(c, "Contacto no encontrado")


@router.get("", response_model=list[ContactoOut])
def listar(db: Session = Depends(get_db),
           usuario: Usuario = Depends(require_roles(*acceso.ROLES_LECTURA))):
    esc = acceso.escenario(usuario)
    filas = db.query(Contacto).filter(Contacto.escenario_id == esc.id).order_by(Contacto.nombre).all()
    return [_out(db, c) for c in filas]


@router.post("", response_model=ContactoOut, status_code=status.HTTP_201_CREATED)
def crear(body: ContactoIn, request: Request, db: Session = Depends(get_db),
          usuario: Usuario = Depends(require_roles(*acceso.ROLES_ESCRITURA))):
    acceso.escritura(usuario)
    esc = acceso.escenario(usuario)
    c = Contacto(escenario_id=esc.id, creado_por=usuario.id, **body.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    registrar(db, usuario=usuario, accion="contacto_creado", entidad="contacto",
              entidad_id=c.id, ip=client_ip(request), detalle=c.nombre)
    return _out(db, c)


@router.patch("/{contacto_id}", response_model=ContactoOut)
def actualizar(contacto_id: str, body: ContactoUpdate, request: Request,
               db: Session = Depends(get_db),
               usuario: Usuario = Depends(require_roles(*acceso.ROLES_ESCRITURA))):
    acceso.escritura(usuario)
    c = _cargar(db, contacto_id, usuario)
    cambios = acceso.aplicar(c, body, CAMPOS)
    c.actualizado_en = now()
    db.commit()
    db.refresh(c)
    registrar(db, usuario=usuario, accion="contacto_actualizado", entidad="contacto",
              entidad_id=c.id, ip=client_ip(request), detalle=", ".join(cambios) or "sin cambios")
    return _out(db, c)


@router.delete("/{contacto_id}")
def eliminar(contacto_id: str, request: Request, db: Session = Depends(get_db),
             usuario: Usuario = Depends(require_roles("admin"))):
    c = _cargar(db, contacto_id, usuario)
    detalle = c.nombre
    db.delete(c)
    db.commit()
    registrar(db, usuario=usuario, accion="contacto_eliminado", entidad="contacto",
              entidad_id=contacto_id, ip=client_ip(request), detalle=detalle)
    return {"ok": True}
