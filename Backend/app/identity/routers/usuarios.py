from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

from app.kernel.db import get_db
from app.kernel.models import Usuario, ROLES, ROL_TECNICO_NOC_SOC, normalizar_rol
from app.kernel import security
from app.kernel.audit import registrar
from app.kernel.deps import require_roles, client_ip
from app.kernel.schemas import UsuarioCreate, UsuarioUpdate, UsuarioOut, UsuarioResetPassword
from app.plataforma import seguridad_ops

router = APIRouter(prefix="/usuarios", tags=["usuarios"])


def _admins_activos(db: Session, exclude_id: str | None = None) -> int:
    q = db.query(Usuario).filter(Usuario.rol == "admin", Usuario.activo.is_(True))
    if exclude_id:
        q = q.filter(Usuario.id != exclude_id)
    return q.count()


def _admins_totales(db: Session, exclude_id: str | None = None) -> int:
    q = db.query(Usuario).filter(Usuario.rol == "admin")
    if exclude_id:
        q = q.filter(Usuario.id != exclude_id)
    return q.count()


def _usuario_out(db: Session, u: Usuario) -> UsuarioOut:
    out = UsuarioOut.model_validate(u)
    return out.model_copy(update={
        "ips_seguras": list(u.ips_seguras or []),
        "sesiones_activas": seguridad_ops.contar_sesiones_usuario(db, u.id),
        "sesiones_max": seguridad_ops.limite_sesiones_usuario(u.rol),
    })


def _aplicar_ips(obj: Usuario, ips) -> None:
    if ips is None:
        return
    obj.ips_seguras = seguridad_ops.normalizar_ips_seguras(ips)

router = APIRouter(prefix="/usuarios", tags=["usuarios"])


def _admins_activos(db: Session, exclude_id: str | None = None) -> int:
    q = db.query(Usuario).filter(Usuario.rol == "admin", Usuario.activo.is_(True))
    if exclude_id:
        q = q.filter(Usuario.id != exclude_id)
    return q.count()


def _admins_totales(db: Session, exclude_id: str | None = None) -> int:
    q = db.query(Usuario).filter(Usuario.rol == "admin")
    if exclude_id:
        q = q.filter(Usuario.id != exclude_id)
    return q.count()


@router.get("", response_model=list[UsuarioOut])
def listar(q: str | None = None, db: Session = Depends(get_db),
           _u: Usuario = Depends(require_roles("admin", ROL_TECNICO_NOC_SOC))):
    filas = db.query(Usuario).order_by(Usuario.usuario).all()
    if q and q.strip():
        needle = q.strip().lower()
        filas = [
            u for u in filas
            if needle in (u.usuario or "").lower()
            or needle in (u.nombre or "").lower()
            or needle in (u.rol or "").lower()
            or needle in (u.email or "").lower()
            or any(needle in ip.lower() for ip in (u.ips_seguras or []))
        ]
    return [_usuario_out(db, u) for u in filas]


@router.post("", response_model=UsuarioOut, status_code=status.HTTP_201_CREATED)
def crear(body: UsuarioCreate, request: Request, db: Session = Depends(get_db),
          admin: Usuario = Depends(require_roles("admin"))):
    rol = normalizar_rol(body.rol)
    if rol not in ROLES:
        raise HTTPException(400, f"Rol inválido. Debe ser uno de: {', '.join(ROLES)}")
    if db.query(Usuario).filter(Usuario.usuario == body.usuario).first():
        raise HTTPException(409, "Ya existe un usuario con ese nombre de acceso")

    nuevo = Usuario(
        usuario=body.usuario,
        nombre=body.nombre,
        rol=rol,
        password_hash=security.hash_password(body.password),
        debe_cambiar_password=True,
        creado_por=admin.id,
    )
    if body.email is not None:
        from app.plataforma import seguridad_ops as _seg
        try:
            nuevo.email = _seg.email_valido(body.email)
        except ValueError as e:
            raise HTTPException(400, str(e))
    try:
        _aplicar_ips(nuevo, body.ips_seguras)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    registrar(db, usuario=admin, accion="usuario_creado", entidad="usuario", entidad_id=nuevo.id,
              ip=client_ip(request), detalle=f"usuario={nuevo.usuario} rol={nuevo.rol}")
    from app.identity import escenario_ops
    escenario_ops.asignar_por_defecto(db, nuevo)
    return _usuario_out(db, nuevo)


@router.patch("/{usuario_id}", response_model=UsuarioOut)
def actualizar(usuario_id: str, body: UsuarioUpdate, request: Request, db: Session = Depends(get_db),
               admin: Usuario = Depends(require_roles("admin"))):
    obj = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not obj:
        raise HTTPException(404, "Usuario no encontrado")
    rol_nuevo = normalizar_rol(body.rol) if body.rol is not None else None
    if rol_nuevo is not None and rol_nuevo not in ROLES:
        raise HTTPException(400, f"Rol inválido. Debe ser uno de: {', '.join(ROLES)}")

    nuevo_rol = rol_nuevo if rol_nuevo is not None else obj.rol
    nuevo_activo = body.activo if body.activo is not None else obj.activo
    pierde_admin = obj.rol == "admin" and (nuevo_rol != "admin" or nuevo_activo is False)
    if pierde_admin and _admins_activos(db, exclude_id=obj.id) == 0:
        raise HTTPException(400, "No se puede dejar el sistema sin un administrador activo")

    cambios = []
    if body.nombre is not None and body.nombre != obj.nombre:
        cambios.append(f"nombre={body.nombre}")
        obj.nombre = body.nombre
    if rol_nuevo is not None and rol_nuevo != obj.rol:
        cambios.append(f"rol={obj.rol}->{rol_nuevo}")
        obj.rol = rol_nuevo
    if body.activo is not None and body.activo != obj.activo:
        obj.activo = body.activo
        cambios.append("desactivado" if not body.activo else "reactivado")
        if not body.activo:
            # Al desactivar un usuario, se revocan todas sus sesiones activas
            # y se corta el canal de avisos Telegram.
            for rt in obj.refresh_tokens:
                rt.revocado = True
            if obj.telegram_chat_id:
                from app.plataforma import telegram_ops
                telegram_ops.desvincular(db, obj, actor=admin, ip=client_ip(request))
    if body.email is not None:
        from app.plataforma import seguridad_ops
        try:
            nuevo_email = seguridad_ops.email_valido(body.email)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if nuevo_email != obj.email:
            cambios.append(f"email={nuevo_email or '—'}")
            obj.email = nuevo_email
    if body.ips_seguras is not None:
        try:
            _aplicar_ips(obj, body.ips_seguras)
        except ValueError as e:
            raise HTTPException(400, str(e))
        cambios.append("ips_seguras=" + ",".join(obj.ips_seguras or []) or "—")
    db.commit()
    db.refresh(obj)
    registrar(db, usuario=admin, accion="usuario_actualizado", entidad="usuario", entidad_id=obj.id,
              ip=client_ip(request), detalle=", ".join(cambios) or "datos actualizados")
    return _usuario_out(db, obj)


@router.post("/{usuario_id}/reset-password")
def resetear_password(usuario_id: str, body: UsuarioResetPassword, request: Request,
                       db: Session = Depends(get_db), admin: Usuario = Depends(require_roles("admin"))):
    obj = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not obj:
        raise HTTPException(404, "Usuario no encontrado")
    obj.password_hash = security.hash_password(body.password)
    obj.debe_cambiar_password = True
    obj.intentos_fallidos = 0
    obj.bloqueado_hasta = None
    for rt in obj.refresh_tokens:
        rt.revocado = True
    db.commit()
    registrar(db, usuario=admin, accion="password_restablecida", entidad="usuario", entidad_id=obj.id,
              ip=client_ip(request))
    return {"ok": True}


@router.post("/{usuario_id}/reset-2fa")
def resetear_2fa(usuario_id: str, request: Request,
                 db: Session = Depends(get_db), admin: Usuario = Depends(require_roles("admin"))):
    """El administrador borra el TOTP para que el usuario vuelva a enrolarse.
    Obligatorio para admin, analista y TECNICO_NOC_SOC: no pueden saltarse el 2FA."""
    obj = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not obj:
        raise HTTPException(404, "Usuario no encontrado")
    obj.totp_secret = None
    obj.totp_activo = False
    for rt in obj.refresh_tokens:
        rt.revocado = True
    db.commit()
    registrar(
        db, usuario=admin, accion="2fa_restablecido", entidad="usuario",
        entidad_id=obj.id, ip=client_ip(request),
        detalle=f"usuario={obj.usuario}",
    )
    return {"ok": True}


@router.delete("/{usuario_id}")
def eliminar(usuario_id: str, request: Request, db: Session = Depends(get_db),
             admin: Usuario = Depends(require_roles("admin"))):
    obj = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not obj:
        raise HTTPException(404, "Usuario no encontrado")
    if obj.id == admin.id:
        raise HTTPException(400, "No puedes eliminar tu propio usuario")
    if obj.rol == "admin" and _admins_totales(db, exclude_id=obj.id) == 0:
        raise HTTPException(400, "No se puede eliminar el último administrador")

    detalle = f"usuario={obj.usuario} rol={obj.rol} nombre={obj.nombre}"
    entidad_id = obj.id
    db.delete(obj)
    db.commit()
    registrar(db, usuario=admin, accion="usuario_eliminado", entidad="usuario", entidad_id=entidad_id,
              ip=client_ip(request), detalle=detalle)
    return {"ok": True}
