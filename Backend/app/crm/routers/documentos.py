from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.crm import acceso
from app.kernel.audit import registrar
from app.kernel.db import get_db
from app.kernel.deps import client_ip, require_roles
from app.kernel.models import Documento, Usuario, now
from app.kernel.schemas import DocumentoIn, DocumentoOut, DocumentoUpdate

router = APIRouter(prefix="/documentos", tags=["documentos"])
CAMPOS = ("titulo", "tipo", "url", "notas", "oferta_id", "cliente_id")


def _cargar(db: Session, documento_id: str, usuario: Usuario) -> Documento:
    esc = acceso.escenario(usuario)
    d = db.query(Documento).filter(Documento.id == documento_id, Documento.escenario_id == esc.id).first()
    return acceso.o_404(d, "Documento no encontrado")


@router.get("", response_model=list[DocumentoOut])
def listar(db: Session = Depends(get_db),
           usuario: Usuario = Depends(require_roles(*acceso.ROLES_LECTURA))):
    esc = acceso.escenario(usuario)
    return db.query(Documento).filter(Documento.escenario_id == esc.id).order_by(Documento.creado_en.desc()).all()


@router.post("", response_model=DocumentoOut, status_code=status.HTTP_201_CREATED)
def crear(body: DocumentoIn, request: Request, db: Session = Depends(get_db),
          usuario: Usuario = Depends(require_roles(*acceso.ROLES_ESCRITURA))):
    acceso.escritura(usuario)
    esc = acceso.escenario(usuario)
    d = Documento(escenario_id=esc.id, creado_por=usuario.id, **body.model_dump())
    db.add(d)
    db.commit()
    db.refresh(d)
    registrar(db, usuario=usuario, accion="documento_creado", entidad="documento",
              entidad_id=d.id, ip=client_ip(request), detalle=d.titulo)
    return d


@router.patch("/{documento_id}", response_model=DocumentoOut)
def actualizar(documento_id: str, body: DocumentoUpdate, request: Request,
               db: Session = Depends(get_db),
               usuario: Usuario = Depends(require_roles(*acceso.ROLES_ESCRITURA))):
    acceso.escritura(usuario)
    d = _cargar(db, documento_id, usuario)
    cambios = acceso.aplicar(d, body, CAMPOS)
    d.actualizado_en = now()
    db.commit()
    db.refresh(d)
    registrar(db, usuario=usuario, accion="documento_actualizado", entidad="documento",
              entidad_id=d.id, ip=client_ip(request), detalle=", ".join(cambios) or "sin cambios")
    return d


@router.delete("/{documento_id}")
def eliminar(documento_id: str, request: Request, db: Session = Depends(get_db),
             usuario: Usuario = Depends(require_roles(*acceso.ROLES_ESCRITURA))):
    acceso.escritura(usuario)
    d = _cargar(db, documento_id, usuario)
    detalle = d.titulo
    db.delete(d)
    db.commit()
    registrar(db, usuario=usuario, accion="documento_eliminado", entidad="documento",
              entidad_id=documento_id, ip=client_ip(request), detalle=detalle)
    return {"ok": True}
