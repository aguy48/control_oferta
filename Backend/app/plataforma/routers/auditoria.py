from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.kernel.db import get_db
from app.kernel.deps import require_roles
from app.kernel.models import BitacoraEvento, ROL_TECNICO_NOC_SOC, Usuario
from app.kernel.schemas import BitacoraOut
from app.plataforma.eventos_ops import ACCIONES as ACCIONES_EVENTOS

router = APIRouter(prefix="/auditoria", tags=["auditoria"])


@router.get("", response_model=list[BitacoraOut])
def listar(
    limit: int = Query(80, ge=1, le=400),
    accion: str | None = None,
    entidad: str | None = None,
    db: Session = Depends(get_db),
    _u: Usuario = Depends(require_roles("admin", "auditor", ROL_TECNICO_NOC_SOC)),
):
    q = db.query(BitacoraEvento).filter(
        ~BitacoraEvento.accion.in_(ACCIONES_EVENTOS),
        ~BitacoraEvento.resultado.in_(("error", "denegado")),
    ).order_by(BitacoraEvento.timestamp.desc())
    if accion:
        q = q.filter(BitacoraEvento.accion == accion)
    if entidad:
        q = q.filter(BitacoraEvento.entidad == entidad)
    return q.limit(limit).all()
