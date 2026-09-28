"""Eventos de sistema de esta instancia (distintos de Auditoría / personas)."""
from __future__ import annotations

import datetime as dt
import shutil

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.kernel.models import BitacoraEvento, Usuario, now
from app.plataforma.seguridad_ops import ACCIONES_EVENTOS

# Acciones propias de Cotización que no son CRUD de personas.
ACCIONES_COT = (
    "traspaso_mcp_error",
    "proyecto_creacion_fallida",
    "respaldo_creado",
    "respaldo_restaurado",
    "ajustes_onlyoffice",
)

ACCIONES = ACCIONES_EVENTOS + ACCIONES_COT


def es_evento(accion: str, resultado: str | None = None) -> bool:
    if accion in ACCIONES:
        return True
    return (resultado or "") in ("error", "denegado")


def query(db: Session):
    return db.query(BitacoraEvento).filter(
        or_(
            BitacoraEvento.accion.in_(ACCIONES),
            BitacoraEvento.resultado.in_(("error", "denegado")),
        )
    )


def listar(db: Session, *, limite: int = 150, accion: str | None = None) -> list:
    q = query(db).order_by(BitacoraEvento.timestamp.desc())
    if accion:
        q = q.filter(BitacoraEvento.accion == accion)
    return q.limit(limite).all()


def resumen(db: Session) -> dict:
    corte = now() - dt.timedelta(hours=24)
    base = query(db).filter(BitacoraEvento.timestamp >= corte)
    n_err = base.filter(BitacoraEvento.resultado.in_(("error", "denegado"))).count()
    n_mcp = base.filter(BitacoraEvento.accion.in_(
        ("traspaso_mcp_error", "proyecto_creacion_fallida", "nodo_sbc", "nodo_sbc_acceso")
    )).count()
    n_tg = db.query(Usuario).filter(Usuario.telegram_chat_id.isnot(None)).count()
    disco = None
    try:
        uso = shutil.disk_usage(".")
        disco = {
            "total": uso.total,
            "libre": uso.free,
            "usado_pct": round(100 * (1 - uso.free / max(uso.total, 1)), 1),
        }
    except OSError:
        disco = None
    return {
        "errores_24h": n_err,
        "alertas_mcp_24h": n_mcp,
        "telegram_vinculados": n_tg,
        "disco": disco,
    }
