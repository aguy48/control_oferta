"""OnlyOffice: estado, config del editor, archivo para el Document Server y callback."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.kernel.audit import registrar
from app.kernel.db import get_db
from app.kernel.deps import client_ip, require_roles
from app.kernel.models import Usuario
from app.plataforma import onlyoffice_ops

router = APIRouter(prefix="/onlyoffice", tags=["onlyoffice"])

_LECTURA = require_roles(*onlyoffice_ops.ROLES_LECTURA)
_ESCRITURA = require_roles(*onlyoffice_ops.ROLES_EDICION)


class ConfigIn(BaseModel):
    origen: str = Field(min_length=3, max_length=20)
    id: str = Field(min_length=1, max_length=400)
    modo: str | None = Field(default="edit", max_length=8)


class NuevoIn(BaseModel):
    oferta_id: str | None = Field(default=None, max_length=64)
    tipo: str = Field(min_length=4, max_length=12)
    nombre: str | None = Field(default=None, max_length=120)


def _base_api(request: Request, db: Session) -> str:
    fallback = str(request.base_url).rstrip("/")
    return onlyoffice_ops.app_url(db, fallback=fallback)


@router.get("/estado")
def estado_onlyoffice(db: Session = Depends(get_db), _u: Usuario = Depends(_LECTURA)):
    return onlyoffice_ops.estado(db)


@router.post("/config")
def config_onlyoffice(
    body: ConfigIn,
    request: Request,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(_LECTURA),
):
    try:
        return onlyoffice_ops.config_editor(
            db,
            origen=body.origen,
            ident=body.id,
            usuario=usuario,
            modo=body.modo or "edit",
            base_api=_base_api(request, db),
        )
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/nuevo")
def nuevo_onlyoffice(
    body: NuevoIn,
    request: Request,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(_ESCRITURA),
):
    try:
        doc = onlyoffice_ops.crear_nuevo(
            db,
            oferta_id=body.oferta_id,
            tipo=body.tipo,
            usuario=usuario,
            nombre=body.nombre,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    registrar(
        db, usuario=usuario, accion="onlyoffice_nuevo", entidad="anexo",
        entidad_id=doc.id, ip=client_ip(request),
        detalle=f"tipo={body.tipo} archivo={doc.nombre}",
    )
    return {
        "id": doc.id,
        "nombre": doc.nombre,
        "oferta_id": doc.oferta_id,
        "origen": "anexo",
    }


@router.get("/archivo/{token}")
def archivo_onlyoffice(token: str, db: Session = Depends(get_db)):
    """El Document Server descarga el archivo con un JWT propio (sin sesión de usuario)."""
    try:
        claims = onlyoffice_ops.leer_token_archivo(token, db)
        rec = onlyoffice_ops.resolver(db, claims["origen"], claims["id"])
    except (ValueError, FileNotFoundError, KeyError) as e:
        raise HTTPException(404, "Archivo no disponible") from e
    return FileResponse(
        rec["path"],
        filename=rec["nombre"],
        media_type=onlyoffice_ops.mime_de(rec["nombre"]),
    )


@router.post("/callback")
async def callback_onlyoffice(
    request: Request,
    t: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    try:
        out = onlyoffice_ops.procesar_callback(
            db, body, token_q=t, auth_header=request.headers.get("Authorization"),
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    return JSONResponse(out)
