from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.crm import acceso
from app.kernel.audit import registrar
from app.kernel.db import get_db
from app.kernel.deps import client_ip, require_roles
from app.kernel.models import Tarea, Usuario, now
from app.kernel.schemas import TareaIn, TareaOut, TareaUpdate

router = APIRouter(prefix="/tareas", tags=["tareas"])
CAMPOS = ("titulo", "descripcion", "estado", "vencimiento", "asignado_a", "oferta_id", "cliente_id")


def _cargar(db: Session, tarea_id: str, usuario: Usuario) -> Tarea:
    esc = acceso.escenario(usuario)
    t = db.query(Tarea).filter(Tarea.id == tarea_id, Tarea.escenario_id == esc.id).first()
    return acceso.o_404(t, "Tarea no encontrada")


@router.get("", response_model=list[TareaOut])
def listar(db: Session = Depends(get_db),
           usuario: Usuario = Depends(require_roles(*acceso.ROLES_LECTURA))):
    esc = acceso.escenario(usuario)
    return db.query(Tarea).filter(Tarea.escenario_id == esc.id).order_by(Tarea.creado_en.desc()).all()


@router.post("", response_model=TareaOut, status_code=status.HTTP_201_CREATED)
def crear(body: TareaIn, request: Request, db: Session = Depends(get_db),
          usuario: Usuario = Depends(require_roles(*acceso.ROLES_ESCRITURA))):
    acceso.escritura(usuario)
    esc = acceso.escenario(usuario)
    t = Tarea(escenario_id=esc.id, creado_por=usuario.id, **body.model_dump())
    db.add(t)
    db.commit()
    db.refresh(t)
    registrar(db, usuario=usuario, accion="tarea_creada", entidad="tarea",
              entidad_id=t.id, ip=client_ip(request), detalle=t.titulo)
    return t


@router.patch("/{tarea_id}", response_model=TareaOut)
def actualizar(tarea_id: str, body: TareaUpdate, request: Request,
               db: Session = Depends(get_db),
               usuario: Usuario = Depends(require_roles(*acceso.ROLES_ESCRITURA))):
    acceso.escritura(usuario)
    t = _cargar(db, tarea_id, usuario)
    cambios = acceso.aplicar(t, body, CAMPOS)
    t.actualizado_en = now()
    db.commit()
    db.refresh(t)
    registrar(db, usuario=usuario, accion="tarea_actualizada", entidad="tarea",
              entidad_id=t.id, ip=client_ip(request), detalle=", ".join(cambios) or "sin cambios")
    return t


@router.delete("/{tarea_id}")
def eliminar(tarea_id: str, request: Request, db: Session = Depends(get_db),
             usuario: Usuario = Depends(require_roles(*acceso.ROLES_ESCRITURA))):
    acceso.escritura(usuario)
    t = _cargar(db, tarea_id, usuario)
    detalle = t.titulo
    db.delete(t)
    db.commit()
    registrar(db, usuario=usuario, accion="tarea_eliminada", entidad="tarea",
              entidad_id=tarea_id, ip=client_ip(request), detalle=detalle)
    return {"ok": True}
