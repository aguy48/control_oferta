from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.kernel.db import get_db
from app.kernel.deps import require_roles
from app.kernel.models import ROL_TECNICO_NOC_SOC, Usuario
from app.kernel.schemas import BitacoraOut
from app.plataforma import eventos_ops, telegram_ops

router = APIRouter(prefix="/eventos", tags=["eventos"])
_VER = require_roles("admin", "auditor", ROL_TECNICO_NOC_SOC)


@router.get("", response_model=list[BitacoraOut])
def listar(
    limit: int = Query(150, ge=1, le=400),
    accion: str | None = None,
    db: Session = Depends(get_db),
    _u: Usuario = Depends(_VER),
):
    return eventos_ops.listar(db, limite=limit, accion=accion)


@router.get("/resumen")
def resumen(db: Session = Depends(get_db), _u: Usuario = Depends(_VER)):
    out = eventos_ops.resumen(db)
    out["telegram"] = telegram_ops.listar_vinculos(db)
    return out
