"""
Bitácora de auditoría append-only (mismo esquema GTEC-007 que Control de
Proyecto). Aquí también se registran los eventos de negocio de la oferta
(oferta_ganada, traspaso_generado, proyecto_vinculado — ING-COT-003 §7.8).
"""
from .models import BitacoraEvento

TENANT_ID = "sistema-cotizacion"


def registrar(db, *, usuario=None, accion, entidad=None, entidad_id=None,
              resultado="ok", ip=None, sesion_id=None, detalle=None):
    evento = BitacoraEvento(
        tenant_id=TENANT_ID,
        usuario_id=usuario.id if usuario else None,
        usuario_nombre=usuario.nombre if usuario else None,
        rol=usuario.rol if usuario else None,
        accion=accion,
        entidad=entidad,
        entidad_id=entidad_id,
        resultado=resultado,
        ip=ip,
        sesion_id=sesion_id,
        detalle=detalle,
    )
    db.add(evento)
    db.commit()
    return evento
