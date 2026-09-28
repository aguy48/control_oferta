from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.crm import anexo_ops, oferta_ops
from app.crm.oferta_ops import ROLES_LECTURA
from app.crm.reportes import html_oferta
from app.identity import escenario_ops
from app.kernel.db import get_db
from app.kernel.deps import require_roles
from app.kernel.models import AjusteGeneral, InformeTecnico, Oferta, Usuario

router = APIRouter(tags=["reportes"])


@router.get("/reportes")
def listar(db: Session = Depends(get_db),
           usuario: Usuario = Depends(require_roles(*ROLES_LECTURA))):
    esc = escenario_ops.exigir_escenario(usuario)
    ofertas = (
        db.query(Oferta).filter(Oferta.escenario_id == esc.id)
        .order_by(Oferta.codigo.desc()).all()
    )
    informes = (
        db.query(InformeTecnico).filter(InformeTecnico.escenario_id == esc.id)
        .order_by(InformeTecnico.creado_en.desc()).all()
    )
    anexos = anexo_ops.anexos_de_informes(db, informes)
    return {
        "ofertas": [
            {"id": o.id, "codigo": o.codigo, "titulo": o.titulo, "estado": o.estado,
             "cliente": o.cliente_razon_social, "origen": o.origen,
             "total": o.total_precio, "margen_pct": o.margen_pct}
            for o in ofertas
        ],
        "informes": [
            {
                "id": i.id, "codigo": i.codigo, "titulo": i.titulo,
                "cliente": i.cliente_razon_social, "oferta_id": i.oferta_id,
                **anexo_ops.meta_anexo_informe(anexos.get(i.anexo_id)),
            }
            for i in informes
        ],
    }


@router.get("/ofertas/{oferta_id}/reporte.html")
def reporte_oferta(oferta_id: str, db: Session = Depends(get_db),
                   usuario: Usuario = Depends(require_roles(*ROLES_LECTURA))):
    o = oferta_ops.cargar_oferta(db, oferta_id, usuario)
    az = db.query(AjusteGeneral).filter(AjusteGeneral.id == "default").first()
    return HTMLResponse(html_oferta(o, az))
