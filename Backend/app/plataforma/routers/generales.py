import os

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.kernel.audit import registrar
from app.kernel.config import settings
from app.kernel.crypto_secrets import cifrar, descifrar
from app.kernel.db import get_db
from app.kernel.deps import client_ip, require_roles
from app.kernel.models import AjusteGeneral, Usuario, now
from app.kernel.schemas import GeneralesIn, GeneralesOut, OnlyOfficeIn, OnlyOfficeOut, TelegramProbarIn

router = APIRouter(prefix="/generales", tags=["generales"])


def onlyoffice_publico(fila: AjusteGeneral) -> dict:
    from app.plataforma import onlyoffice_ops
    return onlyoffice_ops.publico(fila)


def _fila(db: Session) -> AjusteGeneral:
    fila = db.query(AjusteGeneral).filter(AjusteGeneral.id == "default").first()
    if fila is None:
        fila = AjusteGeneral(id="default", razon_social="ORIOL Consultores C.A.")
        db.add(fila)
        db.commit()
        db.refresh(fila)
    return fila


def _out(fila: AjusteGeneral, db: Session | None = None) -> GeneralesOut:
    from app.conexion_control_proyecto import mcp
    url, _token, fuente = mcp.credenciales(db)
    return GeneralesOut(
        razon_social=fila.razon_social,
        rif=fila.rif,
        direccion=fila.direccion,
        telefono=fila.telefono,
        email=fila.email,
        iva_pct=fila.iva_pct or 16,
        moneda=fila.moneda or "USD",
        margen_pct=float(fila.margen_pct if fila.margen_pct is not None else 25),
        gemini_model=fila.gemini_model,
        gemini_configurado=bool(descifrar(fila.gemini_api_key_enc) or settings.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY")),
        mcp_url=(fila.mcp_url or "").strip() or (url if fuente == "entorno" else None),
        mcp_token_configurado=bool(descifrar(fila.mcp_token_enc) or settings.MCP_TOKEN),
        mcp_configurado=bool(url),
        mcp_fuente=fuente or None,
        mcp_destino_id=fila.mcp_destino_id,
        mcp_sede_nombre=fila.mcp_sede_nombre,
        telegram_configurado=bool(descifrar(fila.telegram_bot_token_enc) or settings.TELEGRAM_BOT_TOKEN),
        telegram_bot_username=(fila.telegram_bot_username or "").lstrip("@") or settings.TELEGRAM_BOT_USERNAME or None,
        telegram_mode=(fila.telegram_mode or settings.TELEGRAM_MODE or "polling"),
        telegram_fuente=("generales" if descifrar(fila.telegram_bot_token_enc) else ("entorno" if settings.TELEGRAM_BOT_TOKEN else None)),
        telegram_poll_seconds=fila.telegram_poll_seconds or settings.TELEGRAM_POLL_SECONDS,
        telegram_emparejar_ttl_min=fila.telegram_emparejar_ttl_min or settings.TELEGRAM_EMPAREJAR_TTL_MIN,
        onlyoffice=OnlyOfficeOut(**onlyoffice_publico(fila)),
        notas=fila.notas,
        actualizado_en=fila.actualizado_en,
        actualizado_por=fila.actualizado_por,
    )


@router.get("", response_model=GeneralesOut)
def obtener(db: Session = Depends(get_db),
            _u: Usuario = Depends(require_roles("admin", "analista", "auditor"))):
    return _out(_fila(db), db)


@router.put("", response_model=GeneralesOut)
def guardar(body: GeneralesIn, request: Request, db: Session = Depends(get_db),
            admin: Usuario = Depends(require_roles("admin"))):
    fila = _fila(db)
    data = body.model_dump(exclude_unset=True)
    clave = data.pop("gemini_api_key", None)
    token_mcp = data.pop("mcp_token", None)
    token_tg = data.pop("telegram_bot_token", None)
    secret_tg = data.pop("telegram_webhook_secret", None)
    if data.get("mcp_url") is not None:
        data["mcp_url"] = (data["mcp_url"] or "").strip().rstrip("/") or None
    if data.get("mcp_destino_id") is not None:
        data["mcp_destino_id"] = (data["mcp_destino_id"] or "").strip() or None
    if data.get("mcp_sede_nombre") is not None:
        data["mcp_sede_nombre"] = (data["mcp_sede_nombre"] or "").strip() or None
    if data.get("telegram_bot_username") is not None:
        data["telegram_bot_username"] = (data["telegram_bot_username"] or "").lstrip("@") or None
    if data.get("telegram_mode") is not None:
        modo = (data["telegram_mode"] or "").strip().lower()
        data["telegram_mode"] = modo if modo in ("polling", "webhook") else "polling"
    for campo, valor in data.items():
        setattr(fila, campo, valor)
    if clave:
        fila.gemini_api_key_enc = cifrar(clave.strip())
    if token_mcp:
        fila.mcp_token_enc = cifrar(token_mcp.strip())
    if token_tg:
        fila.telegram_bot_token_enc = cifrar(token_tg.strip())
    if secret_tg:
        fila.telegram_webhook_secret_enc = cifrar(secret_tg.strip())
    fila.actualizado_en = now()
    fila.actualizado_por = admin.usuario
    db.commit()
    db.refresh(fila)
    registrar(db, usuario=admin, accion="generales_actualizados", entidad="generales",
              entidad_id="default", ip=client_ip(request),
              detalle=fila.razon_social or "")
    from app.plataforma import telegram_ops
    telegram_ops.aplicar_en_vivo()
    try:
        from app.conexion_control_proyecto import escenario_sbc
        escenario_sbc.sincronizar(db)
    except Exception:
        pass
    return _out(fila, db)


@router.post("/telegram/probar")
def probar_telegram(body: TelegramProbarIn | None = None,
                    _admin: Usuario = Depends(require_roles("admin"))):
    from fastapi import HTTPException
    from app.plataforma import telegram_api
    token = (body.telegram_bot_token if body else None) or None
    try:
        me = telegram_api.get_me(token)
    except Exception as e:
        raise HTTPException(502, f"Telegram no respondió: {e}")
    return {"ok": True, "username": (me or {}).get("username"), "id": (me or {}).get("id")}


@router.put("/onlyoffice", response_model=GeneralesOut)
def guardar_onlyoffice(body: OnlyOfficeIn, request: Request, db: Session = Depends(get_db),
                       admin: Usuario = Depends(require_roles("admin"))):
    from fastapi import HTTPException
    from app.plataforma import onlyoffice_ops
    try:
        onlyoffice_ops.guardar(db, body.model_dump(exclude_none=True), actor=admin)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    fila = _fila(db)
    registrar(db, usuario=admin, accion="ajustes_onlyoffice", entidad="generales",
              entidad_id="default", ip=client_ip(request),
              detalle=f"url={fila.onlyoffice_url or '-'}")
    return _out(fila, db)
