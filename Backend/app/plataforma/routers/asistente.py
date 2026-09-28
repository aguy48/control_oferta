"""Asistente de usuarios (ayuda por opciones) y de administrador (mejora)."""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.kernel.db import get_db
from app.kernel.deps import get_current_user
from app.kernel.models import BitacoraEvento, Usuario
from app.kernel.schemas import AsistenteMensaje, AsistenteRespuesta, AsistenteOpcionOut, AsistenteCatalogo
from app.plataforma.asistente_conocimiento import opciones_para_rol, responder_ayuda, respuesta_bienvenida

router = APIRouter(prefix="/asistente", tags=["asistente"])


def _opcion_out(o: dict) -> AsistenteOpcionOut:
    return AsistenteOpcionOut(
        id=o["id"], paso=o["paso"], destino=o.get("destino") or o["id"],
        etiqueta=o["etiqueta"], grupo=o["grupo"], ctab=o.get("ctab"), ayuda=o["ayuda"],
    )


@router.get("/opciones", response_model=AsistenteCatalogo)
def listar_opciones(usuario: Usuario = Depends(get_current_user)):
    ops = opciones_para_rol(usuario.rol)
    return AsistenteCatalogo(rol=usuario.rol, opciones=[_opcion_out(o) for o in ops])


@router.post("/consultar", response_model=AsistenteRespuesta)
def consultar(body: AsistenteMensaje, request: Request, db: Session = Depends(get_db),
              usuario: Usuario = Depends(get_current_user)):
    modo = (body.modo or "ayuda").strip().lower()
    if modo not in ("ayuda", "mejora"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "modo debe ser 'ayuda' o 'mejora'")
    if modo == "mejora":
        if usuario.rol != "admin":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "El asistente de mejora es solo para el administrador")
        raw = _mejora(db, body.mensaje, usuario)
        return _a_respuesta(raw, "mejora")
    raw = (
        respuesta_bienvenida(usuario.rol, usuario.nombre)
        if not (body.mensaje or "").strip()
        else responder_ayuda(body.mensaje, usuario.rol, usuario.nombre)
    )
    return _a_respuesta(raw, "ayuda")


def _mejora(db: Session, mensaje: str, usuario: Usuario) -> dict:
    import datetime as dt
    from app.kernel.models import now
    instante = now()
    hace = instante - dt.timedelta(hours=24)
    n_u = db.query(Usuario).filter(Usuario.activo.is_(True)).count()
    n_tg = db.query(Usuario).filter(Usuario.telegram_chat_id.isnot(None)).count()
    ev = db.query(BitacoraEvento).filter(BitacoraEvento.timestamp >= hace).count()
    fail = db.query(BitacoraEvento).filter(
        BitacoraEvento.timestamp >= hace, BitacoraEvento.accion == "login",
        BitacoraEvento.resultado == "denegado",
    ).count()
    recs = [
        "Revisa 16 Generales por bloques: empresa, Gemini, MCP/SBC único, Telegram y OnlyOffice. Cada Guardar toca solo ese bloque.",
        "En Eventos (13) mira errores de MCP, bloqueos y disco; en Auditoría (12) la actividad de personas.",
        "En Respaldo (14) genera un ZIP de datos. Restaurar pide exactamente «restaurar cotizacion».",
        "Los privilegiados deben tener 2FA. Las cuentas de esta instancia no sirven en Control de Proyecto.",
    ]
    if fail:
        recs.insert(0, f"Hubo {fail} inicios fallidos en 24 h. Mira Auditoría (12) y Eventos (13).")
    cuerpo = (
        "Asistente de administrador — Sistema de Cotización:\n"
        f"• Usuarios activos {n_u}, Telegram vinculados {n_tg}.\n"
        f"• Bitácora 24 h: {ev} eventos, logins fallidos {fail}.\n\n"
        "Recomendaciones:\n" + "\n".join(f"{i+1}. {r}" for i, r in enumerate(recs))
    )
    if (mensaje or "").strip() and "diagnost" not in (mensaje or "").lower():
        base = responder_ayuda(mensaje, usuario.rol, usuario.nombre)
        base["recomendaciones"] = recs
        base["metricas"] = {"usuarios": n_u, "telegram": n_tg, "eventos_24h": ev}
        return base
    return {
        "respuesta": cuerpo,
        "sugerencias": [
            {"paso": 1, "etiqueta": "Panel", "id": "panel", "mensaje": "panel", "destino": "panel"},
            {"paso": 12, "etiqueta": "Auditoría", "id": "auditoria", "mensaje": "auditoría", "destino": "auditoria"},
            {"paso": 13, "etiqueta": "Eventos", "id": "eventos", "mensaje": "eventos", "destino": "eventos"},
            {"paso": 14, "etiqueta": "Respaldo", "id": "respaldo", "mensaje": "respaldo", "destino": "respaldo"},
            {"paso": 16, "etiqueta": "Generales", "id": "generales", "mensaje": "generales", "destino": "generales"},
        ],
        "destino": "generales",
        "opcion_id": "generales",
        "recomendaciones": recs,
        "metricas": {"usuarios": n_u, "telegram": n_tg, "eventos_24h": ev},
    }


def _a_respuesta(raw: dict, modo: str) -> AsistenteRespuesta:
    datos = dict(raw or {})
    datos.pop("_sin_match", None)
    return AsistenteRespuesta(
        respuesta=datos.get("respuesta") or "",
        sugerencias=datos.get("sugerencias") or [],
        destino=datos.get("destino"),
        ctab=datos.get("ctab"),
        opcion_id=datos.get("opcion_id"),
        recomendaciones=datos.get("recomendaciones"),
        metricas=datos.get("metricas"),
        modo=modo,
    )
