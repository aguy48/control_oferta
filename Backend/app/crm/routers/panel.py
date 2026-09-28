from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.crm import acceso, producto_ops
from app.kernel.db import get_db
from app.kernel.deps import require_roles
from app.kernel.models import (
    Cliente, Contacto, Documento, ESTADOS_OFERTA, InformeTecnico, Oferta,
    ProductoServicio, Proveedor, Tarea, Usuario,
)
from app.kernel.schemas import PanelOut

router = APIRouter(prefix="/panel", tags=["panel"])


@router.get("", response_model=PanelOut)
def resumen(db: Session = Depends(get_db),
            usuario: Usuario = Depends(require_roles(*acceso.ROLES_LECTURA))):
    esc = acceso.escenario(usuario)
    ofertas = db.query(Oferta).filter(Oferta.escenario_id == esc.id).all()
    por_estado = {e: 0 for e in ESTADOS_OFERTA}
    total_abiertas = 0.0
    total_ganadas = 0.0
    for o in ofertas:
        por_estado[o.estado] = por_estado.get(o.estado, 0) + 1
        if o.estado in ("borrador", "enviada", "en_negociacion"):
            total_abiertas += o.total_precio
        if o.estado == "ganada":
            total_ganadas += o.total_precio
    recientes = [
        {"id": o.id, "codigo": o.codigo, "titulo": o.titulo, "estado": o.estado,
         "cliente": o.cliente_razon_social, "total": o.total_precio}
        for o in sorted(ofertas, key=lambda x: x.actualizado_en or x.creado_en, reverse=True)[:8]
    ]
    from app.conexion_control_proyecto import mcp
    url, _token, fuente = mcp.credenciales(db)
    dest_id, sede = mcp.destino_instancia(db)
    mcp_info = {
        "configurado": bool(url),
        "url": url or None,
        "fuente": fuente or None,
        "destino_id": dest_id,
        "sede_nombre": sede,
    }
    return PanelOut(
        ofertas_por_estado=por_estado,
        total_abiertas=round(total_abiertas, 2),
        total_ganadas=round(total_ganadas, 2),
        n_clientes=db.query(Cliente).filter(Cliente.escenario_id == esc.id).count(),
        n_contactos=db.query(Contacto).filter(Contacto.escenario_id == esc.id).count(),
        n_tareas_abiertas=db.query(Tarea).filter(
            Tarea.escenario_id == esc.id, Tarea.estado.in_(("pendiente", "en_curso")),
        ).count(),
        n_documentos=db.query(Documento).filter(Documento.escenario_id == esc.id).count(),
        n_proveedores=db.query(Proveedor).filter(Proveedor.escenario_id == esc.id).count(),
        n_informes=db.query(InformeTecnico).filter(InformeTecnico.escenario_id == esc.id).count(),
        n_productos=db.query(ProductoServicio).filter(
            ProductoServicio.escenario_id == esc.id, ProductoServicio.activo.is_(True),
        ).count(),
        top_productos=producto_ops.top_cotizados(db, usuario, 10),
        mcp=mcp_info,
        recientes=recientes,
    )
