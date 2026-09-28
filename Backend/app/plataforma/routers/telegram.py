"""Vinculación Telegram y recepción de updates (webhook)."""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.kernel.db import get_db
from app.kernel.deps import get_current_user, require_roles, client_ip
from app.kernel.models import Usuario
from app.kernel.schemas import TelegramEstado, TelegramEmparejarOut, TelegramVinculosOut
from app.plataforma import telegram_ops

router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.get("/estado", response_model=TelegramEstado)
def estado(db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user)):
    return telegram_ops.estado_para(usuario, db)


@router.get("/vinculos", response_model=TelegramVinculosOut)
def vinculos(db: Session = Depends(get_db),
             _u: Usuario = Depends(require_roles("admin", "auditor"))):
    return telegram_ops.listar_vinculos(db)


@router.post("/emparejar", response_model=TelegramEmparejarOut)
def emparejar(request: Request, db: Session = Depends(get_db),
              usuario: Usuario = Depends(get_current_user)):
    if not telegram_ops.bot_configurado():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Telegram no está configurado. El administrador pega el token de @BotFather en 16 Generales.",
        )
    try:
        out = telegram_ops.crear_emparejamiento(db, usuario)
    except RuntimeError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    from app.kernel.audit import registrar
    registrar(db, usuario=usuario, accion="telegram_emparejar",
              entidad="usuario", entidad_id=usuario.id, ip=client_ip(request),
              detalle="código de un solo uso generado")
    return out


@router.delete("/vinculo")
def desvincular_propio(request: Request, db: Session = Depends(get_db),
                       usuario: Usuario = Depends(get_current_user)):
    if not usuario.telegram_chat_id:
        return {"ok": True, "vinculado": False}
    telegram_ops.desvincular(db, usuario, actor=usuario, ip=client_ip(request))
    return {"ok": True, "vinculado": False}


@router.delete("/vinculo/{usuario_id}")
def desvincular_admin(usuario_id: str, request: Request, db: Session = Depends(get_db),
                      admin: Usuario = Depends(require_roles("admin"))):
    obj = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not obj:
        raise HTTPException(404, "Usuario no encontrado")
    telegram_ops.desvincular(db, obj, actor=admin, ip=client_ip(request))
    return {"ok": True, "vinculado": False}


@router.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    if not telegram_ops.bot_configurado():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Telegram no está configurado")
    secreto = telegram_ops.webhook_secret()
    if secreto:
        got = request.headers.get("x-telegram-bot-api-secret-token")
        if got != secreto:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Webhook no autorizado")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cuerpo inválido")
    if not isinstance(payload, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cuerpo inválido")
    telegram_ops.procesar_update(db, payload)
    return {"ok": True}
