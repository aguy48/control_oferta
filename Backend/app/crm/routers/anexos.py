from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.crm import anexo_ops, oferta_ops
from app.crm.oferta_ops import ROLES_ESCRITURA, ROLES_LECTURA
from app.kernel.audit import registrar
from app.kernel.db import get_db
from app.kernel.deps import client_ip, require_roles
from app.kernel.models import Usuario
from app.kernel.schemas import AnexoOut, GenerarOfertaIn, OfertaOut

router = APIRouter(tags=["anexos"])


@router.get("/ofertas/{oferta_id}/anexos", response_model=list[AnexoOut])
def listar(oferta_id: str, db: Session = Depends(get_db),
           usuario: Usuario = Depends(require_roles(*ROLES_LECTURA))):
    oferta_ops.cargar_oferta(db, oferta_id, usuario)
    return anexo_ops.listar_anexos(db, usuario, oferta_id)


@router.post("/ofertas/{oferta_id}/anexos", response_model=AnexoOut, status_code=status.HTTP_201_CREATED)
async def subir(oferta_id: str, request: Request,
                tipo: str = Form("oferta_proveedor"),
                ocr: bool = Form(True),
                archivo: UploadFile = File(...),
                db: Session = Depends(get_db),
                usuario: Usuario = Depends(require_roles(*ROLES_ESCRITURA))):
    a = await anexo_ops.guardar_upload(db, usuario, archivo, tipo, oferta_id, ocr=ocr)
    db.commit()
    db.refresh(a)
    registrar(db, usuario=usuario, accion="anexo_cargado", entidad="oferta",
              entidad_id=oferta_id, ip=client_ip(request), detalle=f"{a.tipo} {a.nombre}")
    return a


@router.post("/anexos", response_model=AnexoOut, status_code=status.HTTP_201_CREATED)
async def subir_suelto(request: Request,
                       tipo: str = Form("informe_tecnico"),
                       ocr: bool = Form(True),
                       archivo: UploadFile = File(...),
                       db: Session = Depends(get_db),
                       usuario: Usuario = Depends(require_roles(*ROLES_ESCRITURA))):
    a = await anexo_ops.guardar_upload(db, usuario, archivo, tipo, None, ocr=ocr)
    db.commit()
    db.refresh(a)
    registrar(db, usuario=usuario, accion="anexo_cargado", entidad="anexo",
              entidad_id=a.id, ip=client_ip(request), detalle=f"{a.tipo} {a.nombre}")
    return a


@router.get("/anexos", response_model=list[AnexoOut])
def listar_escenario(db: Session = Depends(get_db),
                     usuario: Usuario = Depends(require_roles(*ROLES_LECTURA))):
    return anexo_ops.listar_anexos(db, usuario)


@router.post("/anexos/{anexo_id}/ocr", response_model=AnexoOut)
def ocr(anexo_id: str, request: Request, db: Session = Depends(get_db),
        usuario: Usuario = Depends(require_roles(*ROLES_ESCRITURA))):
    a = anexo_ops.cargar_anexo(db, anexo_id, usuario)
    anexo_ops.ocr_anexo(db, a, usuario)
    db.commit()
    db.refresh(a)
    registrar(db, usuario=usuario, accion="anexo_ocr", entidad="anexo",
              entidad_id=a.id, ip=client_ip(request),
              detalle=(a.extraccion or {}).get("motor", "ocr"))
    return a


@router.get("/anexos/{anexo_id}/archivo")
def descargar(anexo_id: str, db: Session = Depends(get_db),
              usuario: Usuario = Depends(require_roles(*ROLES_LECTURA))):
    a = anexo_ops.cargar_anexo(db, anexo_id, usuario)
    path = Path(a.ruta)
    if not path.is_file():
        raise HTTPException(404, "El archivo ya no está en disco.")
    return FileResponse(path, filename=a.nombre, media_type=a.mime or "application/pdf")


@router.post("/ofertas/{oferta_id}/generar-desde-anexos", response_model=OfertaOut)
def generar(oferta_id: str, body: GenerarOfertaIn, request: Request,
            db: Session = Depends(get_db),
            usuario: Usuario = Depends(require_roles(*ROLES_ESCRITURA))):
    o = oferta_ops.cargar_oferta(db, oferta_id, usuario, escritura=True)
    anexos = anexo_ops.listar_anexos(db, usuario, oferta_id)
    if body.anexo_ids:
        ids = set(body.anexo_ids)
        anexos = [a for a in anexos if a.id in ids]
    anexo_ops.aplicar_extraccion_a_oferta(
        db, o, anexos, usuario, margen_pct=body.margen_pct,
        reemplazar=body.reemplazar_partidas,
    )
    db.commit()
    db.refresh(o)
    registrar(db, usuario=usuario, accion="oferta_generada_gemini", entidad="oferta",
              entidad_id=o.codigo, ip=client_ip(request),
              detalle=f"margen={o.margen_pct} n={len(o.partidas)}")
    return o
