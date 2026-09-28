from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.crm import anexo_ops
from app.crm.reportes import html_informe
from app.crm.oferta_ops import ROLES_ESCRITURA, ROLES_LECTURA
from app.identity import escenario_ops
from app.kernel.audit import registrar
from app.kernel.db import get_db
from app.kernel.deps import client_ip, require_roles
from app.kernel.models import AjusteGeneral, AnexoOferta, Usuario
from app.kernel.schemas import GenerarOfertaIn, InformeIn, InformeOut, InformeUpdate, OfertaOut

router = APIRouter(prefix="/informes", tags=["informes"])


def _out_informe(db: Session, inf, anexo=None) -> InformeOut:
    if anexo is None and inf.anexo_id:
        anexo = db.query(AnexoOferta).filter(AnexoOferta.id == inf.anexo_id).first()
    meta = anexo_ops.meta_anexo_informe(anexo)
    return InformeOut(
        id=inf.id,
        titulo=inf.titulo,
        codigo=inf.codigo,
        cliente_razon_social=inf.cliente_razon_social,
        cliente_rif=inf.cliente_rif,
        resumen=inf.resumen,
        anexo_id=inf.anexo_id,
        oferta_id=inf.oferta_id,
        anexo_nombre=meta["anexo_nombre"],
        archivo_office=meta["archivo_office"],
        creado_en=inf.creado_en,
        creado_por=inf.creado_por,
    )


@router.get("", response_model=list[InformeOut])
def listar(db: Session = Depends(get_db),
           usuario: Usuario = Depends(require_roles(*ROLES_LECTURA))):
    filas = anexo_ops.listar_informes(db, usuario)
    anexos = anexo_ops.anexos_de_informes(db, filas)
    return [_out_informe(db, inf, anexos.get(inf.anexo_id)) for inf in filas]


@router.post("", response_model=InformeOut, status_code=status.HTTP_201_CREATED)
def crear(body: InformeIn, request: Request, db: Session = Depends(get_db),
          usuario: Usuario = Depends(require_roles(*ROLES_ESCRITURA))):
    inf = anexo_ops.crear_informe(db, body, usuario)
    db.commit()
    db.refresh(inf)
    registrar(db, usuario=usuario, accion="informe_creado", entidad="informe",
              entidad_id=inf.id, ip=client_ip(request), detalle=inf.titulo)
    return _out_informe(db, inf)


@router.post("/desde-anexo/{anexo_id}", response_model=InformeOut, status_code=status.HTTP_201_CREATED)
def desde_anexo(anexo_id: str, request: Request, db: Session = Depends(get_db),
                usuario: Usuario = Depends(require_roles(*ROLES_ESCRITURA))):
    a = anexo_ops.cargar_anexo(db, anexo_id, usuario)
    inf = anexo_ops.informe_desde_anexo(db, a, usuario)
    db.commit()
    db.refresh(inf)
    registrar(db, usuario=usuario, accion="informe_creado", entidad="informe",
              entidad_id=inf.id, ip=client_ip(request), detalle=f"anexo {a.nombre}")
    return _out_informe(db, inf, a)


@router.get("/{informe_id}", response_model=InformeOut)
def obtener(informe_id: str, db: Session = Depends(get_db),
            usuario: Usuario = Depends(require_roles(*ROLES_LECTURA))):
    return _out_informe(db, anexo_ops.cargar_informe(db, informe_id, usuario))


@router.patch("/{informe_id}", response_model=InformeOut)
def actualizar(informe_id: str, body: InformeUpdate, request: Request,
               db: Session = Depends(get_db),
               usuario: Usuario = Depends(require_roles(*ROLES_ESCRITURA))):
    escenario_ops.exigir_escritura(usuario)
    inf = anexo_ops.cargar_informe(db, informe_id, usuario)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(inf, k, v)
    db.commit()
    db.refresh(inf)
    registrar(db, usuario=usuario, accion="informe_actualizado", entidad="informe",
              entidad_id=inf.id, ip=client_ip(request), detalle=inf.titulo)
    return _out_informe(db, inf)


@router.delete("/{informe_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar(informe_id: str, request: Request, db: Session = Depends(get_db),
             usuario: Usuario = Depends(require_roles(*ROLES_ESCRITURA))):
    inf = anexo_ops.cargar_informe(db, informe_id, usuario)
    detalle = inf.titulo
    anexo_ops.eliminar_informe(db, inf, usuario)
    db.commit()
    registrar(db, usuario=usuario, accion="informe_eliminado", entidad="informe",
              entidad_id=informe_id, ip=client_ip(request), detalle=detalle)


@router.post("/{informe_id}/generar-oferta", response_model=OfertaOut, status_code=status.HTTP_201_CREATED)
def generar_oferta(informe_id: str, body: GenerarOfertaIn, request: Request,
                   db: Session = Depends(get_db),
                   usuario: Usuario = Depends(require_roles(*ROLES_ESCRITURA))):
    inf = anexo_ops.cargar_informe(db, informe_id, usuario)
    o = anexo_ops.generar_oferta_desde_informe(db, inf, usuario, margen_pct=body.margen_pct)
    db.commit()
    db.refresh(o)
    registrar(db, usuario=usuario, accion="oferta_desde_informe", entidad="oferta",
              entidad_id=o.codigo, ip=client_ip(request), detalle=informe_id)
    return o


@router.get("/{informe_id}/reporte.html")
def reporte(informe_id: str, db: Session = Depends(get_db),
            usuario: Usuario = Depends(require_roles(*ROLES_LECTURA))):
    inf = anexo_ops.cargar_informe(db, informe_id, usuario)
    texto = inf.resumen
    if inf.anexo_id:
        a = db.query(AnexoOferta).filter(AnexoOferta.id == inf.anexo_id).first()
        extra = (a.extraccion if a else None) or {}
        texto = extra.get("informe_tecnico") or inf.resumen or (a.texto_ocr if a else None)
    az = db.query(AjusteGeneral).filter(AjusteGeneral.id == "default").first()
    return HTMLResponse(html_informe(inf, az, texto))
