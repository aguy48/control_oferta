"""
Telegram del Sistema de Cotización: emparejar chat, avisos de seguridad
y las mismas opciones 01–16 del asistente. Un grupo se ignora.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import secrets

from sqlalchemy.orm import Session

from app.kernel import security
from app.kernel.audit import registrar
from app.kernel.config import APP_VERSION, settings
from app.kernel.crypto_secrets import descifrar
from app.kernel.models import AjusteGeneral, TelegramEmparejamiento, TelegramKV, Usuario, now
from app.plataforma import telegram_api
from app.plataforma.asistente_conocimiento import opciones_para_rol, rango_menu, responder_ayuda

logger = logging.getLogger("sistema_cotizacion")

_enviar = None  # inyectable en pruebas: (chat_id, texto) -> None
_runtime: dict = {
    "token": None,
    "username": None,
    "mode": None,
    "webhook_secret": None,
    "poll_seconds": None,
    "emparejar_ttl_min": None,
}


def _fila_generales(db: Session) -> AjusteGeneral | None:
    return db.query(AjusteGeneral).filter(AjusteGeneral.id == "default").first()


def recargar_desde_db(db: Session | None = None) -> None:
    close = False
    if db is None:
        from app.kernel.db import SessionLocal
        db = SessionLocal()
        close = True
    try:
        az = _fila_generales(db)
        enc = getattr(az, "telegram_bot_token_enc", None) if az is not None else None
        _runtime["token"] = (descifrar(enc) or None) if enc else None
        user = (getattr(az, "telegram_bot_username", None) or "").lstrip("@") if az is not None else ""
        _runtime["username"] = user or None
        modo = (getattr(az, "telegram_mode", None) or "").strip().lower() if az is not None else ""
        _runtime["mode"] = modo if modo in ("polling", "webhook") else None
        sec_enc = getattr(az, "telegram_webhook_secret_enc", None) if az is not None else None
        _runtime["webhook_secret"] = (descifrar(sec_enc) or None) if sec_enc else None
        poll = getattr(az, "telegram_poll_seconds", None) if az is not None else None
        try:
            _runtime["poll_seconds"] = int(poll) if poll is not None else None
        except (TypeError, ValueError):
            _runtime["poll_seconds"] = None
        ttl = getattr(az, "telegram_emparejar_ttl_min", None) if az is not None else None
        try:
            _runtime["emparejar_ttl_min"] = int(ttl) if ttl is not None else None
        except (TypeError, ValueError):
            _runtime["emparejar_ttl_min"] = None
    except Exception:
        logger.exception("No se pudo cargar Telegram desde Generales")
    finally:
        if close:
            db.close()


def aplicar_en_vivo() -> None:
    recargar_desde_db()


def token_activo() -> str:
    t = _runtime.get("token")
    if t is not None and str(t).strip():
        return str(t).strip()
    return (settings.TELEGRAM_BOT_TOKEN or "").strip()


def username_activo() -> str:
    u = (_runtime.get("username") or "").lstrip("@")
    if u:
        return u
    return (settings.TELEGRAM_BOT_USERNAME or "").lstrip("@")


def modo_activo() -> str:
    m = (str(_runtime.get("mode") or "").strip().lower()
         or (settings.TELEGRAM_MODE or "polling").strip().lower())
    return m if m in ("polling", "webhook") else "polling"


def webhook_secret() -> str:
    s = _runtime.get("webhook_secret")
    if s is not None and str(s).strip():
        return str(s).strip()
    return (settings.TELEGRAM_WEBHOOK_SECRET or "").strip()


def poll_seconds_activo() -> int:
    n = _runtime.get("poll_seconds")
    if n is not None:
        try:
            return max(2, min(60, int(n)))
        except (TypeError, ValueError):
            pass
    return max(2, int(settings.TELEGRAM_POLL_SECONDS or 3))


def emparejar_ttl_activo() -> int:
    n = _runtime.get("emparejar_ttl_min")
    if n is not None:
        try:
            return max(5, min(120, int(n)))
        except (TypeError, ValueError):
            pass
    return max(5, int(settings.TELEGRAM_EMPAREJAR_TTL_MIN or 15))


def bot_configurado() -> bool:
    return bool(token_activo())


def leer_kv(db: Session, clave: str) -> str | None:
    fila = db.query(TelegramKV).filter(TelegramKV.clave == clave).first()
    return fila.valor if fila else None


def escribir_kv(db: Session, clave: str, valor: str | None) -> None:
    fila = db.query(TelegramKV).filter(TelegramKV.clave == clave).first()
    if fila is None:
        db.add(TelegramKV(clave=clave, valor=valor, actualizado_en=now()))
    else:
        fila.valor = valor
        fila.actualizado_en = now()
    db.commit()


def bot_username(db: Session | None = None) -> str | None:
    fijo = username_activo() or None
    if fijo:
        return fijo
    if db is not None:
        cache = leer_kv(db, "bot_username")
        if cache:
            return cache
    if not bot_configurado():
        return None
    try:
        me = telegram_api.get_me()
        nombre = (me or {}).get("username")
        if nombre and db is not None:
            escribir_kv(db, "bot_username", nombre)
        return nombre
    except Exception:
        logger.exception("No se pudo obtener el username del bot de Telegram")
        return None


def estado_para(usuario: Usuario, db: Session) -> dict:
    return {
        "habilitado": bot_configurado(),
        "vinculado": bool(usuario.telegram_chat_id),
        "bot_username": bot_username(db),
        "telegram_username": usuario.telegram_username,
        "vinculado_en": usuario.telegram_vinculado_en,
    }


def listar_vinculos(db: Session) -> dict:
    filas = (
        db.query(Usuario)
        .filter(Usuario.telegram_chat_id.isnot(None))
        .order_by(Usuario.usuario)
        .all()
    )
    return {
        "bot_configurado": bot_configurado(),
        "bot_username": bot_username(db),
        "modo": modo_activo(),
        "n_vinculados": len(filas),
        "usuarios": [
            {
                "id": u.id, "usuario": u.usuario, "nombre": u.nombre, "rol": u.rol,
                "telegram_username": u.telegram_username,
                "vinculado_en": u.telegram_vinculado_en,
            }
            for u in filas
        ],
    }


def crear_emparejamiento(db: Session, usuario: Usuario) -> dict:
    if not bot_configurado():
        raise RuntimeError("Telegram no está configurado (falta el token del bot en 16 Generales)")
    db.query(TelegramEmparejamiento).filter(
        TelegramEmparejamiento.usuario_id == usuario.id,
        TelegramEmparejamiento.usado_en.is_(None),
    ).delete(synchronize_session=False)
    raw = secrets.token_urlsafe(18)
    ttl = emparejar_ttl_activo()
    expira = now() + dt.timedelta(minutes=ttl)
    db.add(TelegramEmparejamiento(
        usuario_id=usuario.id,
        token_hash=security.hash_refresh_token(raw),
        expira_en=expira,
    ))
    db.commit()
    userbot = bot_username(db)
    enlace = f"https://t.me/{userbot}?start={raw}" if userbot else None
    instruccion = (
        "Abre el enlace en Telegram y pulsa Iniciar. El código caduca en "
        f"{ttl} minutos y solo sirve una vez."
        if enlace else
        "En Telegram, busca el bot configurado y envía: /start " + raw
    )
    return {
        "token": raw,
        "enlace": enlace,
        "expira_en": expira,
        "bot_username": userbot,
        "instruccion": instruccion,
    }


def desvincular(db: Session, usuario: Usuario, *, actor: Usuario | None = None, ip: str | None = None) -> None:
    chat = usuario.telegram_chat_id
    usuario.telegram_chat_id = None
    usuario.telegram_username = None
    usuario.telegram_vinculado_en = None
    db.query(TelegramEmparejamiento).filter(
        TelegramEmparejamiento.usuario_id == usuario.id,
        TelegramEmparejamiento.usado_en.is_(None),
    ).delete(synchronize_session=False)
    db.commit()
    registrar(
        db, usuario=actor or usuario, accion="telegram_desvinculado",
        entidad="usuario", entidad_id=usuario.id, ip=ip,
        detalle=f"chat_id_previo={chat or '—'}",
    )


def _naive(cuando: dt.datetime | None) -> dt.datetime | None:
    if cuando is None:
        return None
    if getattr(cuando, "tzinfo", None) is not None:
        return cuando.replace(tzinfo=None)
    return cuando


def redimir(db: Session, token: str, chat_id: str, username: str | None) -> tuple[bool, str]:
    token = (token or "").strip()
    if not token:
        return False, (
            "Para vincular, genera el enlace desde el Sistema de Cotización "
            "(botón Telegram, con la sesión iniciada) y pulsa Iniciar."
        )
    hashed = security.hash_refresh_token(token)
    emp = db.query(TelegramEmparejamiento).filter(
        TelegramEmparejamiento.token_hash == hashed,
    ).first()
    if not emp or emp.usado_en is not None:
        return False, "Ese código no es válido o ya se usó. Genera uno nuevo en la aplicación."
    if emp.expira_en and _naive(emp.expira_en) < _naive(now()):
        return False, "Ese código caducó. Genera uno nuevo en la aplicación (botón Telegram)."
    usuario = db.query(Usuario).filter(Usuario.id == emp.usuario_id).first()
    if not usuario or not usuario.activo:
        return False, "La cuenta del Sistema de Cotización ya no está activa."
    ocupado = db.query(Usuario).filter(
        Usuario.telegram_chat_id == str(chat_id),
        Usuario.id != usuario.id,
    ).first()
    if ocupado:
        return False, (
            "Este Telegram ya está vinculado a otra cuenta. "
            "Desvincula allí (o pide al administrador) antes de volver a emparejar."
        )
    emp.usado_en = now()
    usuario.telegram_chat_id = str(chat_id)
    usuario.telegram_username = (username or "").lstrip("@") or None
    usuario.telegram_vinculado_en = now()
    db.commit()
    registrar(
        db, usuario=usuario, accion="telegram_vinculado",
        entidad="usuario", entidad_id=usuario.id,
        detalle=f"username={usuario.telegram_username or '—'}",
    )
    etiqueta = f"@{usuario.telegram_username}" if usuario.telegram_username else usuario.nombre
    return True, (
        f"Listo, {etiqueta}. Este chat recibirá avisos del Sistema de Cotización "
        f"(alertas de seguridad si eres administrador). "
        f"El menú es el mismo que en pantalla: {rango_menu(rol=usuario.rol)}. "
        f"/ayuda, /status, /desvincular."
    )


def _usuario_por_chat(db: Session, chat_id) -> Usuario | None:
    return db.query(Usuario).filter(Usuario.telegram_chat_id == str(chat_id)).first()


def _boton_opcion(opcion: dict) -> str:
    etq = (opcion.get("etiqueta") or "").strip()
    if len(etq) > 28:
        etq = etq[:27] + "…"
    return f"{int(opcion['paso']):02d} {etq}"


def teclado_opciones(usuario: Usuario | None) -> dict | None:
    if usuario is None:
        return {
            "keyboard": [["Ayuda", "Status"]],
            "resize_keyboard": True,
        }
    ops = opciones_para_rol(usuario.rol)
    filas = []
    fila = []
    for o in ops:
        fila.append(_boton_opcion(o))
        if len(fila) == 2:
            filas.append(fila)
            fila = []
    if fila:
        filas.append(fila)
    filas.append(["Status", "Ayuda"])
    return {"keyboard": filas, "resize_keyboard": True}


def enviar(chat_id: str | int, texto: str, usuario: Usuario | None = None,
           con_teclado: bool = False) -> bool:
    markup = teclado_opciones(usuario) if con_teclado else None
    if _enviar is not None:
        _enviar(str(chat_id), texto)
        return True
    if not bot_configurado():
        return False
    try:
        telegram_api.send_message(chat_id, texto, reply_markup=markup)
        return True
    except Exception:
        logger.exception("No se pudo enviar aviso Telegram a %s", chat_id)
        return False


def _usuarios_telegram(db: Session, roles: tuple[str, ...] | None = None) -> list[Usuario]:
    q = db.query(Usuario).filter(
        Usuario.activo.is_(True),
        Usuario.telegram_chat_id.isnot(None),
    )
    if roles:
        q = q.filter(Usuario.rol.in_(roles))
    return q.all()


def _ya_enviada(db: Session, clave: str, ventana: dt.timedelta) -> bool:
    raw = leer_kv(db, clave)
    if not raw:
        return False
    try:
        cuando = dt.datetime.fromisoformat(raw)
    except ValueError:
        return False
    inst = _naive(now()) or dt.datetime.utcnow()
    return (_naive(cuando) or cuando) + ventana > inst


def _marcar_enviada(db: Session, clave: str) -> None:
    escribir_kv(db, clave, now().isoformat())


def notificar_roles(
    db: Session, texto: str, *, clave: str,
    roles: tuple[str, ...] = ("admin",), ventana_horas: float = 24,
) -> int:
    if not bot_configurado():
        return 0
    if _ya_enviada(db, clave, dt.timedelta(hours=ventana_horas)):
        return 0
    n = 0
    for dest in _usuarios_telegram(db, roles):
        if enviar(dest.telegram_chat_id, texto):
            n += 1
    if n:
        _marcar_enviada(db, clave)
    return n


def notificar_admins(db: Session, texto: str, *, clave: str | None = None,
                     ventana_horas: float = 24) -> int:
    if not clave:
        return 0
    return notificar_roles(db, texto, clave=clave, roles=("admin",), ventana_horas=ventana_horas)


def texto_status(db: Session, usuario: Usuario) -> str:
    lineas = [
        f"Sistema de Cotización v{APP_VERSION}",
        f"Usuario: {usuario.usuario} ({usuario.rol})",
    ]
    if usuario.rol not in ("admin", "auditor"):
        lineas.append("El resumen de sesiones y bitácora lo consulta el administrador o auditor.")
        return "\n".join(lineas)
    instante = _naive(now()) or dt.datetime.utcnow()
    hace_24h = instante - dt.timedelta(hours=24)
    from app.kernel.models import BitacoraEvento
    n_u = db.query(Usuario).filter(Usuario.activo.is_(True)).count()
    n_tg = db.query(Usuario).filter(Usuario.telegram_chat_id.isnot(None)).count()
    ev = db.query(BitacoraEvento).filter(BitacoraEvento.timestamp >= hace_24h).count()
    fail = db.query(BitacoraEvento).filter(
        BitacoraEvento.timestamp >= hace_24h,
        BitacoraEvento.accion == "login",
        BitacoraEvento.resultado == "denegado",
    ).count()
    lineas += [
        f"Usuarios activos: {n_u} · Telegram vinculados: {n_tg}",
        f"Bitácora 24 h: {ev} eventos · logins fallidos: {fail}",
    ]
    if usuario.rol == "admin":
        lineas.append("MCP y SBC se configuran en 16 Generales. Eventos es 13 y Respaldo es 14.")
    else:
        lineas.append("Eventos (13) es el visor de sistema. Respaldo (14) lista ZIP. Generales es solo del administrador.")
    return "\n".join(lineas)


def _texto_ayuda_bot(usuario: Usuario | None) -> str:
    rango = rango_menu(rol=usuario.rol) if usuario is not None else "01 Panel al 16 Generales"
    return (
        "Este bot es del Sistema de Cotización (no el de Control de Proyecto).\n"
        f"Pulsa un botón o escribe el número ({rango}): recibes la guía de ese paso.\n"
        "Status o /status — resumen de la instancia.\n"
        "Ayuda — esta guía.\n"
        "Vincular: botón Telegram en la aplicación, con la sesión iniciada.\n"
        "/desvincular — deja de recibir avisos."
    )


def procesar_update(db: Session, update: dict) -> None:
    msg = (update or {}).get("message") or {}
    chat = msg.get("chat") or {}
    if chat.get("type") and chat.get("type") != "private":
        return
    chat_id = chat.get("id")
    if chat_id is None:
        return
    texto = (msg.get("text") or "").strip()
    from_user = msg.get("from") or {}
    username = from_user.get("username")
    usuario = _usuario_por_chat(db, chat_id)
    if not texto:
        enviar(chat_id, "Pulsa una opción del teclado, o escribe Status o Ayuda.",
               usuario=usuario, con_teclado=True)
        return
    cmd, *resto = texto.split(maxsplit=1)
    cmd_raw = cmd.split("@", 1)[0]
    payload = resto[0].strip() if resto else ""
    clave = (cmd_raw[1:] if cmd_raw.startswith("/") else cmd_raw).lower()
    m_paso = re.match(r"^/?0*(\d{1,2})$", cmd_raw, re.I)
    paso = int(m_paso.group(1)) if m_paso else None
    if not m_paso:
        m_btn = re.match(r"^0*(\d{1,2})\s+", texto)
        if m_btn:
            paso = int(m_btn.group(1))

    if clave == "start":
        ok, respuesta = redimir(db, payload, str(chat_id), username)
        usuario = _usuario_por_chat(db, chat_id)
        enviar(chat_id, respuesta, usuario=usuario, con_teclado=True)
        return
    if clave in ("desvincular", "stop"):
        if not usuario:
            enviar(chat_id, "Este chat no está vinculado al Sistema de Cotización.",
                   con_teclado=True)
            return
        desvincular(db, usuario, actor=usuario)
        enviar(chat_id, "Avisos cancelados. Puedes volver a vincular desde la aplicación.",
               con_teclado=True)
        return
    if clave in ("ayuda", "help"):
        enviar(chat_id, _texto_ayuda_bot(usuario), usuario=usuario, con_teclado=True)
        return
    if clave in ("status", "resumen", "estado"):
        if not usuario:
            enviar(chat_id, "Este chat no está vinculado. Genera el enlace desde la aplicación.",
                   con_teclado=True)
            return
        enviar(chat_id, texto_status(db, usuario), usuario=usuario, con_teclado=True)
        return
    if not usuario:
        enviar(chat_id, "Este chat no está vinculado. Genera el enlace desde el botón Telegram.",
               con_teclado=True)
        return
    consulta = texto if paso is None else str(paso)
    raw = responder_ayuda(consulta, usuario.rol, usuario.nombre)
    enviar(chat_id, raw.get("respuesta") or f"Pregunta por un paso ({rango_menu(rol=usuario.rol)}).",
           usuario=usuario, con_teclado=True)


def poll_once(db: Session) -> int:
    if not bot_configurado():
        return 0
    raw_off = leer_kv(db, "update_offset")
    offset = int(raw_off) if raw_off and str(raw_off).isdigit() else 0
    try:
        updates = telegram_api.get_updates(offset=offset, timeout=0)
    except Exception:
        logger.exception("getUpdates de Telegram falló")
        return 0
    n = 0
    last = offset
    for upd in updates:
        procesar_update(db, upd)
        uid = upd.get("update_id")
        if isinstance(uid, int):
            last = uid + 1
        n += 1
    if n:
        escribir_kv(db, "update_offset", str(last))
    return n


def ciclo_periodico(db_factory) -> None:
    recargar_desde_db()
    if not bot_configurado() or modo_activo() != "polling":
        return
    db = db_factory()
    try:
        poll_once(db)
    except Exception:
        logger.exception("Fallo inesperado en el ciclo de Telegram")
    finally:
        db.close()
