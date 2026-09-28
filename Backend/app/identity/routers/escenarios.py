"""CRUD de escenarios (admin) y consulta de asignaciones."""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.kernel.db import get_db
from app.kernel.deps import require_roles, client_ip
from app.kernel.models import ESTADOS_ESCENARIO, Escenario, Proyecto, Usuario, UsuarioEscenario
from app.kernel.audit import registrar
from app.identity import escenario_ops
from app.kernel.schemas import (
    EscenarioCreate, EscenarioUpdate, EscenarioOut, EscenarioAsignacionesIn,
    EscenarioAsignacionOut,
)

router = APIRouter(prefix="/escenarios", tags=["escenarios"])


def _out(esc: Escenario, db: Session) -> EscenarioOut:
    return EscenarioOut(
        id=esc.id,
        nombre=escenario_ops.nombre_escenario(esc),
        razon_social=esc.razon_social,
        periodo_contratacion=esc.periodo_contratacion,
        fecha_inicio=esc.fecha_inicio,
        fecha_fin=esc.fecha_fin,
        estado=esc.estado,
        consultable=bool(esc.consultable),
        por_defecto=bool(getattr(esc, "por_defecto", False)),
        n_proyectos=db.query(Proyecto).filter(Proyecto.escenario_id == esc.id).count(),
        n_usuarios=db.query(UsuarioEscenario).filter(UsuarioEscenario.escenario_id == esc.id).count(),
    )


@router.get("", response_model=list[EscenarioOut])
def listar(db: Session = Depends(get_db), admin: Usuario = Depends(require_roles("admin"))):
    filas = db.query(Escenario).order_by(
        Escenario.periodo_contratacion.desc(), Escenario.razon_social
    ).all()
    return [_out(e, db) for e in filas]


@router.post("", response_model=EscenarioOut, status_code=status.HTTP_201_CREATED)
def crear(body: EscenarioCreate, request: Request, db: Session = Depends(get_db),
          admin: Usuario = Depends(require_roles("admin"))):
    # ADAPTADO (Sistema de Cotización): con SBC destino, el catálogo no se crea aquí.
    from app.conexion_control_proyecto import escenario_sbc
    if not escenario_sbc.alta_local_permitida(db):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Los escenarios vienen del SBC seleccionado en Generales. No se crean aquí.",
        )
    razon = body.razon_social.strip()
    periodo = body.periodo_contratacion.strip()
    escenario_ops.validar_fechas(body.fecha_inicio, body.fecha_fin)
    dup = db.query(Escenario).filter(
        Escenario.razon_social == razon,
        Escenario.periodo_contratacion == periodo,
    ).first()
    if dup:
        raise HTTPException(409, "Ya existe ese periodo de contratación para esa razón social")
    esc = Escenario(
        razon_social=razon,
        periodo_contratacion=periodo,
        fecha_inicio=body.fecha_inicio,
        fecha_fin=body.fecha_fin,
        estado="activo",
        consultable=True,
        creado_por=admin.id,
    )
    db.add(esc)
    db.flush()
    escenario_ops.asignar(db, admin.id, esc.id, "lectura_escritura")
    db.commit()
    db.refresh(esc)
    registrar(
        db, usuario=admin, accion="escenario_creado", entidad="escenario",
        entidad_id=esc.id, ip=client_ip(request),
        detalle=escenario_ops.nombre_escenario(esc),
    )
    return _out(esc, db)


@router.patch("/{escenario_id}", response_model=EscenarioOut)
def actualizar(escenario_id: str, body: EscenarioUpdate, request: Request,
               db: Session = Depends(get_db), admin: Usuario = Depends(require_roles("admin"))):
    esc = db.query(Escenario).filter(Escenario.id == escenario_id).first()
    if not esc:
        raise HTTPException(404, "Escenario no encontrado")
    if body.razon_social is not None:
        esc.razon_social = body.razon_social.strip()
    if body.periodo_contratacion is not None:
        esc.periodo_contratacion = body.periodo_contratacion.strip()
    if body.fecha_inicio is not None or body.fecha_fin is not None:
        ini = body.fecha_inicio if body.fecha_inicio is not None else esc.fecha_inicio
        fin = body.fecha_fin if body.fecha_fin is not None else esc.fecha_fin
        escenario_ops.validar_fechas(
            ini, fin, inicio_min=esc.fecha_inicio, fin_min=esc.fecha_fin,
        )
        esc.fecha_inicio = ini
        esc.fecha_fin = fin
    if body.estado is not None:
        if body.estado not in ESTADOS_ESCENARIO:
            raise HTTPException(400, "estado debe ser 'activo' o 'cerrado'")
        esc.estado = body.estado
        if body.estado == "cerrado" and body.consultable is None:
            esc.consultable = True
    if body.consultable is not None:
        esc.consultable = body.consultable
    if body.por_defecto is True:
        escenario_ops.marcar_por_defecto(db, esc.id)
    elif body.por_defecto is False and esc.por_defecto:
        esc.por_defecto = False
    dup = db.query(Escenario).filter(
        Escenario.razon_social == esc.razon_social,
        Escenario.periodo_contratacion == esc.periodo_contratacion,
        Escenario.id != esc.id,
    ).first()
    if dup:
        raise HTTPException(409, "Ya existe ese periodo de contratación para esa razón social")
    db.commit()
    db.refresh(esc)
    registrar(
        db, usuario=admin, accion="escenario_actualizado", entidad="escenario",
        entidad_id=esc.id, ip=client_ip(request),
        detalle=f"{escenario_ops.nombre_escenario(esc)} estado={esc.estado} consultable={esc.consultable}",
    )
    return _out(esc, db)


@router.get("/{escenario_id}/asignaciones", response_model=list[EscenarioAsignacionOut])
def listar_asignaciones(escenario_id: str, db: Session = Depends(get_db),
                        admin: Usuario = Depends(require_roles("admin"))):
    esc = db.query(Escenario).filter(Escenario.id == escenario_id).first()
    if not esc:
        raise HTTPException(404, "Escenario no encontrado")
    filas = db.query(UsuarioEscenario).filter(UsuarioEscenario.escenario_id == escenario_id).all()
    out = []
    for a in filas:
        u = a.usuario
        if not u:
            continue
        out.append(EscenarioAsignacionOut(
            usuario_id=u.id, usuario=u.usuario, nombre=u.nombre,
            rol=u.rol, acceso=a.acceso,
        ))
    return out


@router.put("/{escenario_id}/asignaciones", response_model=list[EscenarioAsignacionOut])
def reemplazar_asignaciones(
    escenario_id: str, body: EscenarioAsignacionesIn, request: Request,
    db: Session = Depends(get_db), admin: Usuario = Depends(require_roles("admin")),
):
    esc = db.query(Escenario).filter(Escenario.id == escenario_id).first()
    if not esc:
        raise HTTPException(404, "Escenario no encontrado")
    db.query(UsuarioEscenario).filter(UsuarioEscenario.escenario_id == escenario_id).delete(
        synchronize_session=False
    )
    vistos = set()
    for item in body.asignaciones:
        if item.usuario_id in vistos:
            continue
        u = db.query(Usuario).filter(Usuario.id == item.usuario_id).first()
        if not u:
            raise HTTPException(404, f"Usuario no encontrado: {item.usuario_id}")
        escenario_ops.asignar(db, u.id, escenario_id, item.acceso)
        vistos.add(item.usuario_id)
    if admin.id not in vistos:
        escenario_ops.asignar(db, admin.id, escenario_id, "lectura_escritura")
    db.commit()
    registrar(
        db, usuario=admin, accion="escenario_asignaciones", entidad="escenario",
        entidad_id=esc.id, ip=client_ip(request),
        detalle=f"{len(vistos)} usuario(s)",
    )
    return listar_asignaciones(escenario_id, db, admin)
