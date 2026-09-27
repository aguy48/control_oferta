from contextvars import ContextVar
from ipaddress import ip_address

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Usuario, RefreshToken
from .security import decode_token

bearer_scheme = HTTPBearer(auto_error=False)
_usuario_ctx: ContextVar[Usuario | None] = ContextVar("usuario_ctx", default=None)


def usuario_en_contexto() -> Usuario | None:
    return _usuario_ctx.get()


def _ip_literal(valor: str) -> bool:
    try:
        ip_address(valor)
        return True
    except ValueError:
        return False


def client_ip(request: Request) -> str:
    """IP del cliente para bloqueo y GeoIP.

    X-Forwarded-For solo se usa si el peer TCP está en TRUSTED_PROXIES
    (nginx local o el nodo HTML). Si la API queda expuesta directa, esa
    cabecera se ignora y no se puede falsificar la IP.
    """
    peer = (request.client.host if request.client else "") or ""
    if peer in settings.TRUSTED_PROXIES:
        fwd = (request.headers.get("x-forwarded-for") or "").strip()
        if fwd:
            cand = fwd.split(",")[0].strip()
            if cand and _ip_literal(cand):
                return cand
    return peer or "desconocida"


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Usuario:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No autenticado")
    payload = decode_token(creds.credentials)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido o expirado")
    usuario = db.query(Usuario).filter(Usuario.id == payload["sub"]).first()
    if not usuario or not usuario.activo:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario inactivo o inexistente")
    from app.kernel.config import settings
    if settings.es_sbc():
        from app.plataforma import modulos_ops
        if not modulos_ops.usuario_permitido(usuario.usuario):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "El MASTER SOC/NOC deshabilitó el acceso de este usuario a la aplicación de este SBC.",
            )
        if not modulos_ops.aplicacion_permitida():
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "El MASTER SOC/NOC deshabilitó la aplicación en este SBC.",
            )
    usuario._sesion_id = payload.get("sid")
    esc_id = payload.get("esc")
    if not esc_id and usuario._sesion_id:
        rt = db.query(RefreshToken).filter(RefreshToken.id == usuario._sesion_id).first()
        if rt and not rt.revocado:
            esc_id = rt.escenario_id
    from app.identity import escenario_ops
    escenario_ops.hidratar_sesion(db, usuario, esc_id)
    _usuario_ctx.set(usuario)
    return usuario


def require_roles(*roles):
    def _dep(usuario: Usuario = Depends(get_current_user)) -> Usuario:
        if usuario.rol not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes permiso para esta acción")
        return usuario
    return _dep
