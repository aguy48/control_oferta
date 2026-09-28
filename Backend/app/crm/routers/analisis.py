from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.crm import anexo_ops, oferta_ops
from app.crm.oferta_ops import ROLES_ESCRITURA
from app.kernel.audit import registrar
from app.kernel.db import get_db
from app.kernel.deps import client_ip, require_roles
from app.kernel.models import Usuario
from app.kernel.schemas import AnalisisGenerarOut, GenerarOfertaIn

router = APIRouter(tags=["analisis"])


@router.post("/analisis", response_model=AnalisisGenerarOut, status_code=status.HTTP_201_CREATED)
async def analizar_y_generar(
    request: Request,
    tipo: str = Form("otro"),
    margen_pct: float | None = Form(None),
    crear_informe: bool = Form(True),
    crear_oferta: bool = Form(True),
    oferta_id: str | None = Form(None),
    mcp_destino_id: str | None = Form(None),
    sede_destino: str | None = Form(None),
    archivos: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(require_roles(*ROLES_ESCRITURA)),
):
    """Carga PDF, audio y/o chat de WhatsApp; Gemini redacta informe y oferta."""
    o = None
    if oferta_id:
        o = oferta_ops.cargar_oferta(db, oferta_id, usuario, escritura=True)
    anexos = []
    for archivo in archivos:
        a = await anexo_ops.guardar_upload(
            db, usuario, archivo, tipo, o.id if o else None, ocr=False,
        )
        anexos.append(a)
    extra, inf, oferta = anexo_ops.generar_informe_y_oferta(
        db, usuario, anexos, oferta=o, crear_informe=crear_informe,
        crear_oferta=crear_oferta, margen_pct=margen_pct,
        mcp_destino_id=mcp_destino_id, sede_destino=sede_destino,
    )
    db.commit()
    if inf:
        db.refresh(inf)
    if oferta:
        db.refresh(oferta)
    registrar(db, usuario=usuario, accion="analisis_gemini", entidad="informe" if inf else "oferta",
              entidad_id=(inf.id if inf else (oferta.id if oferta else "")),
              ip=client_ip(request),
              detalle=f"fuentes={len(anexos)} motor={(extra or {}).get('motor')}")
    return AnalisisGenerarOut(extraccion=extra or {}, informe=inf, oferta=oferta)


@router.post("/ofertas/{oferta_id}/analizar-fuentes", response_model=AnalisisGenerarOut)
def analizar_fuentes_oferta(
    oferta_id: str, body: GenerarOfertaIn, request: Request,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(require_roles(*ROLES_ESCRITURA)),
):
    """Relee juntos los anexos de la oferta (PDF + audio + WhatsApp)."""
    o = oferta_ops.cargar_oferta(db, oferta_id, usuario, escritura=True)
    anexos = anexo_ops.listar_anexos(db, usuario, oferta_id)
    if body.anexo_ids:
        ids = set(body.anexo_ids)
        anexos = [a for a in anexos if a.id in ids]
    extra, inf, oferta = anexo_ops.generar_informe_y_oferta(
        db, usuario, anexos, oferta=o,
        crear_informe=body.crear_informe, crear_oferta=True,
        margen_pct=body.margen_pct,
    )
    db.commit()
    if inf:
        db.refresh(inf)
    db.refresh(oferta)
    registrar(db, usuario=usuario, accion="analisis_gemini", entidad="oferta",
              entidad_id=oferta.codigo, ip=client_ip(request),
              detalle=f"fuentes={len(anexos)} margen={oferta.margen_pct}")
    return AnalisisGenerarOut(extraccion=extra or {}, informe=inf, oferta=oferta)
