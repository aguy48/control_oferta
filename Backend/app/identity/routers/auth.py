import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.kernel.db import get_db
from app.kernel.config import settings
from app.kernel.models import Usuario, RefreshToken, es_rol_noc_soc
from app.kernel import security
from app.identity import escenario_ops
from app.plataforma import seguridad_ops
from app.kernel.audit import registrar
from app.kernel.deps import get_current_user, client_ip
from app.kernel.schemas import (
    LoginRequest, LoginResponse, RefreshRequest, RefreshResponse, TotpSetupResponse,
    TotpVerifyRequest, UsuarioOut, CambiarPasswordRequest, EscenarioElegirIn,
    EscenariosDisponiblesOut, MeOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _consola_master() -> bool:
    """MASTER CONTROL PROJECT no opera obra: no hay selector de escenario."""
    return settings.APP_ROL in ("master", "maestro", "soc", "noc")

# Nota de diseño (ver ING-001_Diseno_Backend_Seguridad.md §3.3):
# El refresh token se entrega en el cuerpo de la respuesta JSON, no en una
# cookie httpOnly. La razón es la forma de despliegue de esta aplicación:
# el frontend es un archivo HTML estático servido de forma independiente
# del backend (con frecuencia en otro origen/puerto), lo que obliga a
# SameSite=None en cualquier cookie de sesión — y SameSite=None exige HTTPS
# en todos los navegadores modernos, algo que no puede garantizarse en cada
# entorno de desarrollo/prueba. Se opta entonces por mantener el refresh
# token únicamente en memoria del navegador (igual que el access token,
# nunca en localStorage), aceptando que pierde la protección httpOnly frente
# a un ataque XSS. Cuando frontend y backend se sirvan desde el mismo origen
# (por ejemplo, ambos detrás de un único proxy inverso), este es el punto
# de partida recomendado para volver a una cookie httpOnly + Secure.


def _crear_sesion(db: Session, usuario: Usuario, request: Request,
                  escenario_id: str | None = None) -> tuple[str, str]:
    raw = security.new_refresh_token_raw()
    rt = RefreshToken(
        usuario_id=usuario.id,
        token_hash=security.hash_refresh_token(raw),
        expira_en=dt.datetime.utcnow() + dt.timedelta(minutes=settings.REFRESH_TOKEN_TTL_MIN),
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
        escenario_id=escenario_id,
    )
    db.add(rt)
    db.commit()
    db.refresh(rt)
    return rt.id, raw


def _claims_escenario(db: Session, usuario: Usuario, escenario_id: str | None):
    if not escenario_id:
        return None, None, None
    try:
        esc, acceso = escenario_ops.puede_elegir(db, usuario, escenario_id)
    except Exception:
        return None, None, None
    efectivo = escenario_ops.acceso_efectivo(esc, acceso)
    return esc.id, efectivo, escenario_ops.serializar(esc, acceso)


def _token_acceso(db: Session, usuario: Usuario, sesion_id: str,
                  escenario_id: str | None) -> tuple[str, dict | None]:
    esc_id, acc, serial = _claims_escenario(db, usuario, escenario_id)
    token = security.create_access_token(
        usuario.id, usuario.rol, sesion_id,
        escenario_id=esc_id, acceso=acc,
    )
    return token, serial


def _listar_disponibles(db: Session, usuario: Usuario) -> list[dict]:
    escenario_ops.asignar_por_defecto(db, usuario)
    return [escenario_ops.serializar(e, a) for e, a in escenario_ops.disponibles(db, usuario)]


def _emitir_sesion(db: Session, usuario: Usuario, request: Request, *,
                   paso: str, requiere_2fa_setup: bool = False,
                   geo: dict | None = None) -> LoginResponse:
    ip = client_ip(request)
    try:
        ip_nueva = seguridad_ops.asegurar_ip_segura(usuario, ip)
    except ValueError as e:
        registrar(
            db, usuario=usuario, accion="ip_segura_denegada", entidad="acceso",
            resultado="denegado", ip=ip, detalle=str(e),
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))
    if ip_nueva:
        registrar(
            db, usuario=usuario, accion="ip_segura_registrada", entidad="usuario",
            entidad_id=usuario.id, resultado="ok", ip=ip,
            detalle=f"registrada {ip_nueva} ({len(usuario.ips_seguras or [])}/{seguridad_ops.ips_seguras_max()})",
        )
        db.commit()

    cerradas = seguridad_ops.liberar_cupo_sesion_usuario(db, usuario)
    if cerradas:
        registrar(
            db, usuario=usuario, accion="umbral_sesiones", entidad="sesion",
            resultado="ok", ip=ip,
            detalle=(
                f"se cerró la sesión más antigua para respetar el tope "
                f"({seguridad_ops.limite_sesiones_usuario(usuario.rol)} para rol {usuario.rol})"
            ),
        )

    cabe, actuales, limite = seguridad_ops.hay_cupo_sesion(db, usuario_id=usuario.id)
    if not cabe:
        registrar(
            db, usuario=usuario, accion="umbral_sesiones", entidad="sesion",
            resultado="denegado", ip=ip,
            detalle=f"cupo lleno {actuales}/{limite} (máx. {seguridad_ops.tope_sesiones()})",
        )
        seguridad_ops.avisar_sesiones(
            db, ip=ip, actuales=actuales, limite=limite, usuario=usuario,
        )
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"No hay cupo de sesiones concurrentes ({actuales}/{limite}; "
            f"máximo absoluto {seguridad_ops.tope_sesiones()}). "
            "Espera a que expire una sesión o pide al administrador que cierre sesiones.",
        )

    now = dt.datetime.utcnow()
    seguridad_ops.limpiar_fallos(db, usuario=usuario, ip=ip)
    usuario.ultimo_login = now
    db.commit()

    disponibles = _listar_disponibles(db, usuario)
    # Tras autenticarse (y el 2FA si aplica) el usuario elige escenario,
    # salvo MASTER CONTROL PROJECT (no opera obra) y TECNICO_NOC_SOC
    # (entra al escenario técnico asignado, sin selector).
    paso_final = paso
    escenario_id = None
    if paso == "ok" and not requiere_2fa_setup:
        if _consola_master():
            paso_final = "ok"
        elif es_rol_noc_soc(usuario.rol):
            elegido = escenario_ops.preferido_noc(disponibles)
            if elegido:
                escenario_id = elegido["id"]
                paso_final = "ok"
            else:
                paso_final = "escenario"
        else:
            paso_final = "escenario"

    sesion_id, refresh_raw = _crear_sesion(db, usuario, request, escenario_id=escenario_id)
    access, serial = _token_acceso(db, usuario, sesion_id, escenario_id)
    geo = geo or seguridad_ops.evaluar_geoip(db, ip)
    detalle_login = seguridad_ops.detalle_geo(geo)
    registrar(db, usuario=usuario, accion="login", resultado="ok",
              ip=ip, sesion_id=sesion_id, detalle=detalle_login)
    az = seguridad_ops.leer_ajustes(db)
    if az.get("geoip_habilitado"):
        registrar(
            db, usuario=usuario, accion="geoip_permiso", entidad="acceso",
            resultado="ok", ip=ip, sesion_id=sesion_id, detalle=detalle_login,
        )
    return LoginResponse(
        access_token=access,
        refresh_token=refresh_raw,
        usuario=usuario.usuario,
        nombre=usuario.nombre,
        rol=usuario.rol,
        paso=paso_final,
        requiere_2fa_setup=requiere_2fa_setup,
        escenarios=disponibles if paso_final == "escenario" else [],
        escenario=serial if paso_final != "escenario" else None,
    )


def _respuesta_tras_password(db: Session, usuario: Usuario, request: Request,
                              totp: str | None) -> LoginResponse:
    """
    La contraseña ya se validó. Orden fijo:
      1) si la clave es temporal / fue restablecida → cambiarla
      2) si 2FA está activo → pedir código (aún sin sesión)
      3) si el rol exige 2FA y no está activo → sesión limitada para configurarlo
      4) si no exige 2FA → sesión completa
    """
    if usuario.debe_cambiar_password:
        return LoginResponse(
            usuario=usuario.usuario, nombre=usuario.nombre, rol=usuario.rol,
            paso="cambiar_password", debe_cambiar_password=True,
        )

    from app.kernel.config import settings
    if settings.es_sbc():
        from app.plataforma import modulos_ops
        if not modulos_ops.aplicacion_permitida() or not modulos_ops.usuario_permitido(usuario.usuario):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "El MASTER SOC/NOC deshabilitó el acceso a la aplicación de este SBC.",
            )

    if settings.REQUIRE_2FA and usuario.requiere_2fa and usuario.totp_activo:
        if not totp:
            return LoginResponse(
                usuario=usuario.usuario, nombre=usuario.nombre, rol=usuario.rol,
                paso="totp", requiere_totp=True,
            )
        if not security.verificar_totp(usuario.totp_secret, totp):
            _fallo_acceso(
                db, request, usuario=usuario, ip=client_ip(request),
                detalle="código 2FA inválido",
                mensaje_401="Código de verificación en dos pasos inválido",
            )
        return _emitir_sesion(db, usuario, request, paso="ok")

    if settings.REQUIRE_2FA and usuario.requiere_2fa and not usuario.totp_activo:
        return _emitir_sesion(db, usuario, request, paso="2fa_setup",
                              requiere_2fa_setup=True)

    return _emitir_sesion(db, usuario, request, paso="ok")


def _fallo_acceso(db: Session, request: Request, *, usuario: Usuario | None,
                  ip: str, detalle: str, mensaje_401: str) -> None:
    bloqueado, tipo, hasta = seguridad_ops.registrar_fallo(
        db, usuario=usuario, ip=ip, motivo=detalle,
    )
    registrar(db, usuario=usuario, accion="login", resultado="denegado", ip=ip, detalle=detalle)
    if bloqueado and tipo and hasta:
        accion_b = "bloqueo_cuenta" if tipo == "usuario" else "bloqueo_ip"
        registrar(
            db, usuario=usuario, accion=accion_b, entidad="acceso",
            resultado="denegado", ip=ip,
            detalle=f"{detalle}; hasta={seguridad_ops.fmt_hasta(hasta)}",
        )
        try:
            seguridad_ops.avisar_bloqueo(
                db, usuario=usuario, ip=ip, tipo=tipo, hasta=hasta, motivo=detalle,
            )
        except Exception:
            pass
        raise HTTPException(status.HTTP_423_LOCKED, seguridad_ops.mensaje_bloqueo(tipo, hasta))
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, mensaje_401)


def _exigir_geo_y_bloqueo_ip(db: Session, request: Request, usuario: Usuario | None = None) -> tuple[str, dict]:
    ip = client_ip(request)
    tipo, hasta = seguridad_ops.bloqueo_vigente(db, usuario=usuario, ip=ip)
    if tipo == "ip" and hasta:
        registrar(
            db, usuario=usuario, accion="login", resultado="denegado", ip=ip,
            detalle="IP bloqueada temporalmente por intentos fallidos",
        )
        raise HTTPException(status.HTTP_423_LOCKED, seguridad_ops.mensaje_bloqueo("ip", hasta))
    decision = seguridad_ops.evaluar_geoip(db, ip)
    if not decision["permitido"]:
        registrar(
            db, usuario=usuario, accion="geoip_bloqueo", entidad="acceso",
            resultado="denegado", ip=ip, detalle=seguridad_ops.detalle_geo(decision),
        )
        try:
            seguridad_ops.avisar_geoip(db, decision, usuario=usuario)
        except Exception:
            pass
        pais = decision.get("country_name") or decision.get("country_code") or "desconocido"
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Acceso bloqueado por geolocalización de IP (país {pais}). "
            f"Contacta al administrador si deberías poder entrar desde esta red.",
        )
    return ip, decision


def _usuario_por_credenciales(db: Session, usuario_nombre: str, password: str,
                               request: Request) -> Usuario:
    ip, _geo = _exigir_geo_y_bloqueo_ip(db, request, usuario=None)
    usuario = db.query(Usuario).filter(Usuario.usuario == usuario_nombre).first()

    if not usuario or not usuario.activo:
        registrar(db, accion="login", resultado="denegado", ip=ip,
                   detalle=f"usuario desconocido o inactivo: {usuario_nombre}")
        seguridad_ops.registrar_fallo(db, usuario=None, ip=ip, motivo="usuario desconocido")
        tipo, hasta = seguridad_ops.bloqueo_vigente(db, usuario=None, ip=ip)
        if tipo == "ip" and hasta:
            raise HTTPException(status.HTTP_423_LOCKED, seguridad_ops.mensaje_bloqueo("ip", hasta))
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario o contraseña incorrectos")

    tipo, hasta = seguridad_ops.bloqueo_vigente(db, usuario=usuario, ip=ip)
    if tipo and hasta:
        registrar(db, usuario=usuario, accion="login", resultado="denegado", ip=ip,
                   detalle="cuenta bloqueada temporalmente por intentos fallidos")
        raise HTTPException(status.HTTP_423_LOCKED, seguridad_ops.mensaje_bloqueo(tipo, hasta))

    if not security.verify_password(password, usuario.password_hash):
        _fallo_acceso(
            db, request, usuario=usuario, ip=ip,
            detalle=f"contraseña incorrecta (intento {(usuario.intentos_fallidos or 0) + 1})",
            mensaje_401="Usuario o contraseña incorrectos",
        )

    return usuario


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    usuario = _usuario_por_credenciales(db, body.usuario, body.password, request)
    # Contraseña correcta: el 2FA, si aplica, es el paso siguiente. Los
    # fallos de TOTP sí cuentan hacia el bloqueo; no se resetea aquí.
    return _respuesta_tras_password(db, usuario, request, body.totp)


@router.post("/cambiar-password", response_model=LoginResponse)
def cambiar_password(body: CambiarPasswordRequest, request: Request,
                     db: Session = Depends(get_db)):
    usuario = _usuario_por_credenciales(db, body.usuario, body.password_actual, request)
    if body.password_nueva == body.password_actual:
        raise HTTPException(400, "La nueva contraseña debe ser distinta a la actual")
    usuario.password_hash = security.hash_password(body.password_nueva)
    usuario.debe_cambiar_password = False
    usuario.intentos_fallidos = 0
    usuario.bloqueado_hasta = None
    for rt in usuario.refresh_tokens:
        rt.revocado = True
    db.commit()
    registrar(db, usuario=usuario, accion="password_cambiada", entidad="usuario",
              entidad_id=usuario.id, ip=client_ip(request),
              detalle="cambio obligatorio en el inicio de sesión")
    return _respuesta_tras_password(db, usuario, request, totp=None)


@router.post("/refresh", response_model=RefreshResponse)
def refresh(body: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    token_hash = security.hash_refresh_token(body.refresh_token)
    rt = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    now = dt.datetime.utcnow()
    if not rt or rt.revocado or rt.expira_en < now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión expirada, inicia sesión de nuevo")

    usuario = db.query(Usuario).filter(Usuario.id == rt.usuario_id).first()
    if not usuario or not usuario.activo:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario inactivo")

    # Rotación del refresh token: se revoca el actual y se emite uno nuevo.
    escenario_id = rt.escenario_id
    rt.revocado = True
    db.commit()
    sesion_id, refresh_raw = _crear_sesion(db, usuario, request, escenario_id=escenario_id)
    access, serial = _token_acceso(db, usuario, sesion_id, escenario_id)
    return RefreshResponse(access_token=access, refresh_token=refresh_raw, escenario=serial)


@router.post("/logout")
def logout(body: RefreshRequest, db: Session = Depends(get_db),
           usuario: Usuario = Depends(get_current_user)):
    token_hash = security.hash_refresh_token(body.refresh_token)
    rt = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if rt:
        rt.revocado = True
        db.commit()
    registrar(db, usuario=usuario, accion="logout", resultado="ok")
    return {"ok": True}


@router.get("/me", response_model=MeOut)
def me(db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user)):
    serial = None
    esc = getattr(usuario, "_escenario", None)
    if esc is not None:
        serial = escenario_ops.serializar(esc, getattr(usuario, "_escenario_acceso", "lectura"))
    return MeOut(
        id=usuario.id, usuario=usuario.usuario, nombre=usuario.nombre,
        rol=usuario.rol, activo=usuario.activo, totp_activo=usuario.totp_activo,
        ultimo_login=usuario.ultimo_login,
        telegram_vinculado=usuario.telegram_vinculado,
        telegram_username=usuario.telegram_username,
        escenario=serial,
        requiere_escenario=(serial is None and not _consola_master()),
    )


@router.get("/escenarios", response_model=EscenariosDisponiblesOut)
def escenarios_sesion(db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user)):
    actual = None
    esc = getattr(usuario, "_escenario", None)
    if esc is not None:
        actual = escenario_ops.serializar(esc, getattr(usuario, "_escenario_acceso", "lectura"))
    return EscenariosDisponiblesOut(
        escenarios=_listar_disponibles(db, usuario),
        actual=actual,
    )


@router.post("/escenario", response_model=LoginResponse)
def elegir_escenario(
    body: EscenarioElegirIn, request: Request,
    db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user),
):
    esc, acceso = escenario_ops.puede_elegir(db, usuario, body.escenario_id)
    sid = getattr(usuario, "_sesion_id", None)
    rt = db.query(RefreshToken).filter(RefreshToken.id == sid).first() if sid else None
    if rt and not rt.revocado:
        rt.escenario_id = esc.id
        db.commit()
        access, serial = _token_acceso(db, usuario, rt.id, esc.id)
        refresh_raw = None
    else:
        sesion_id, refresh_raw = _crear_sesion(db, usuario, request, escenario_id=esc.id)
        access, serial = _token_acceso(db, usuario, sesion_id, esc.id)
    registrar(
        db, usuario=usuario, accion="escenario_elegido",
        entidad="escenario", entidad_id=esc.id, ip=client_ip(request),
        detalle=escenario_ops.nombre_escenario(esc),
    )
    return LoginResponse(
        access_token=access,
        refresh_token=refresh_raw,
        usuario=usuario.usuario, nombre=usuario.nombre, rol=usuario.rol,
        paso="ok", escenario=serial,
    )


@router.post("/2fa/setup", response_model=TotpSetupResponse)
def totp_setup(db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user)):
    secret = security.generar_totp_secret()
    usuario.totp_secret = secret
    usuario.totp_activo = False
    db.commit()
    registrar(db, usuario=usuario, accion="2fa_setup_iniciado", resultado="ok")
    uri = security.totp_uri(secret, usuario.usuario)
    return TotpSetupResponse(
        secret=secret,
        otpauth_uri=uri,
        qr_data_url=security.totp_qr_data_url(uri),
        issuer=security.totp_issuer(),
    )


@router.post("/2fa/verify")
def totp_verify(
    body: TotpVerifyRequest, request: Request,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    if not usuario.totp_secret or not security.verificar_totp(usuario.totp_secret, body.codigo):
        registrar(db, usuario=usuario, accion="2fa_activado", resultado="denegado")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Código inválido")
    usuario.totp_activo = True
    db.commit()
    registrar(db, usuario=usuario, accion="2fa_activado", resultado="ok")
    if _consola_master():
        return jsonable_encoder({"ok": True, "paso": "ok", "escenario": None, "escenarios": []})
    disp = _listar_disponibles(db, usuario)
    elegido = escenario_ops.preferido_noc(disp) if es_rol_noc_soc(usuario.rol) else None
    if elegido:
        esc, _acceso = escenario_ops.puede_elegir(db, usuario, elegido["id"])
        sid = getattr(usuario, "_sesion_id", None)
        rt = db.query(RefreshToken).filter(RefreshToken.id == sid).first() if sid else None
        if rt and not rt.revocado:
            rt.escenario_id = esc.id
            db.commit()
            access, serial = _token_acceso(db, usuario, rt.id, esc.id)
            return jsonable_encoder({
                "ok": True,
                "paso": "ok",
                "escenario": serial,
                "access_token": access,
            })
        sesion_id, refresh_raw = _crear_sesion(db, usuario, request, escenario_id=esc.id)
        access, serial = _token_acceso(db, usuario, sesion_id, esc.id)
        return jsonable_encoder({
            "ok": True,
            "paso": "ok",
            "escenario": serial,
            "access_token": access,
            "refresh_token": refresh_raw,
        })
    return {"ok": True}
