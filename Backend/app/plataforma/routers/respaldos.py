from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.kernel.audit import registrar
from app.kernel.db import get_db
from app.kernel.deps import client_ip, require_roles
from app.kernel.models import Usuario
from app.plataforma import respaldo_ops

router = APIRouter(prefix="/respaldos", tags=["respaldos"])
_VER = require_roles("admin", "auditor")
_ADMIN = require_roles("admin")


class RespaldoCrearIn(BaseModel):
    tipo: str = Field(pattern="^(datos|aplicacion)$")


class RespaldoRestaurarIn(BaseModel):
    confirmar: str = Field(min_length=3, max_length=80)
    entendido: bool = False


@router.get("")
def listar(_u: Usuario = Depends(_VER)):
    return respaldo_ops.listar()


@router.post("")
def crear(body: RespaldoCrearIn, request: Request, db: Session = Depends(get_db),
          admin: Usuario = Depends(_ADMIN)):
    try:
        info = respaldo_ops.generar(db, body.tipo)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from e
    registrar(
        db, usuario=admin, accion="respaldo_creado", entidad="respaldo",
        entidad_id=info["nombre"], ip=client_ip(request),
        detalle=f"tipo={info['tipo']} {info.get('tamano')}",
    )
    return info


@router.get("/{nombre}")
def descargar(nombre: str, _u: Usuario = Depends(_VER)):
    path = respaldo_ops.ruta_segura(nombre)
    if not path:
        raise HTTPException(404, "Respaldo no encontrado")
    return FileResponse(path, filename=path.name, media_type="application/zip")


@router.post("/{nombre}/restaurar")
def restaurar(nombre: str, body: RespaldoRestaurarIn, request: Request,
              db: Session = Depends(get_db), admin: Usuario = Depends(_ADMIN)):
    path = respaldo_ops.ruta_segura(nombre)
    if not path:
        raise HTTPException(404, "Respaldo no encontrado")
    try:
        respaldo_ops.validar_confirmacion(body.confirmar, body.entendido)
        if not nombre.startswith("datos_"):
            raise ValueError("Solo se restauran respaldos de datos desde aquí.")
        out = respaldo_ops.restaurar_datos(path)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from e
    from app.kernel.db import SessionLocal
    db2 = SessionLocal()
    try:
        registrar(
            db2, usuario=admin, accion="respaldo_restaurado", entidad="respaldo",
            entidad_id=nombre, ip=client_ip(request),
            detalle=f"archivos={out.get('n_archivos')}",
        )
    finally:
        db2.close()
    return out
