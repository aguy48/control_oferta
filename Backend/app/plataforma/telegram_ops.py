"""
ADAPTADOR (Sistema de Cotización).

Control de Proyecto tiene un bot de Telegram completo (vinculación, avisos,
asistente). Esta instancia no lo usa todavía; aquí solo está la interfaz
que consumen los módulos copiados tal cual (seguridad_ops, identity):

- notificar_admins: sin bot, no envía nada (devuelve 0).
- _ya_enviada / _marcar_enviada: anti-rebote de alertas en memoria del
  proceso (en Control de Proyecto se guarda en la tabla telegram_kv).
- desvincular: limpia los campos Telegram del usuario.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app.kernel.audit import registrar
from app.kernel.models import Usuario

_enviadas: dict[str, dt.datetime] = {}


def notificar_admins(db: Session, texto: str, *, clave: str | None = None,
                     ventana_horas: float = 0.2) -> int:
    return 0


def _ya_enviada(db: Session, clave: str, ventana: dt.timedelta) -> bool:
    cuando = _enviadas.get(clave)
    return bool(cuando and dt.datetime.utcnow() - cuando < ventana)


def _marcar_enviada(db: Session, clave: str) -> None:
    _enviadas[clave] = dt.datetime.utcnow()


def desvincular(db: Session, usuario: Usuario, *, actor=None, ip: str | None = None) -> None:
    usuario.telegram_chat_id = None
    usuario.telegram_username = None
    usuario.telegram_vinculado_en = None
    registrar(db, usuario=actor, accion="telegram_desvinculado", entidad="usuario",
              entidad_id=usuario.id, ip=ip)
