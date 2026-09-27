"""Lockout, cupo de sesiones, GeoIP y avisos de seguridad (correo + Telegram)."""
from __future__ import annotations

import datetime as dt
import logging
import re

from sqlalchemy.orm import Session

from app.kernel import audit
from app.plataforma import geoip_ops, telegram_ops
from app.kernel.config import settings
from app.kernel.models import (
    AjustesSeguridad, BitacoraEvento, BloqueoIp, CuentaCorreoProyecto,
    Escenario, RefreshToken, Usuario, now,
)

logger = logging.getLogger("control_proyecto")


def _naive_utc(cuando: dt.datetime | None) -> dt.datetime | None:
    """Postgres (timestamptz) devuelve datetimes con tz; utcnow() no. Unificar."""
    if cuando is None:
        return None
    if getattr(cuando, "tzinfo", None) is not None:
        return cuando.replace(tzinfo=None)
    return cuando

# Sucesos de recursos/sistema (análogo al Visor de eventos de Windows Server).
# La actividad de personas (login, CRUD, módulos) vive en /auditoria (Actividad).
ACCIONES_EVENTOS = (
    "umbral_recurso",
    "umbral_sesiones",
    "bloqueo_cuenta",
    "bloqueo_ip",
    "geoip_bloqueo",
    "geoip_permiso",
    "correo_servidor",
    "nodo_sbc",
    "nodo_sbc_acceso",
    "nodo_sbc_sync",
    "doc_contratacion_alerta",
)

MODOS_GEOIP = ("permitir_todos", "allowlist", "denylist")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Inyectable en pruebas: (destinatario, asunto, cuerpo) -> None
_enviar_email = None


def set_enviar_email(fn) -> None:
    global _enviar_email
    _enviar_email = fn


def reset_para_pruebas() -> None:
    geoip_ops.reset_cache_para_pruebas()
    geoip_ops.set_lookup(None)
    set_enviar_email(None)


def tope_sesiones() -> int:
    return max(1, int(settings.SESIONES_MAX_ABSOLUTO or 130))


def _clamp_limite(n) -> int:
    try:
        v = int(n)
    except (TypeError, ValueError):
        v = int(settings.SESIONES_LIMITE_DEFECTO or 130)
    return max(1, min(tope_sesiones(), v))


def _lista_str(valor) -> list[str]:
    if not valor:
        return []
    if isinstance(valor, str):
        partes = re.split(r"[\s,;]+", valor)
        return [p.strip() for p in partes if p.strip()]
    out = []
    for item in valor:
        s = str(item or "").strip()
        if s:
            out.append(s)
    return out


def _paises_norm(valor) -> list[str]:
    return [p.upper() for p in _lista_str(valor) if len(p) == 2]


def _ips_norm(valor) -> list[str]:
    return [p.strip() for p in _lista_str(valor)]


def ajustes_defecto() -> dict:
    return {
        "sesiones_limite": _clamp_limite(settings.SESIONES_LIMITE_DEFECTO),
        "sesiones_max": tope_sesiones(),
        "geoip_habilitado": False,
        "geoip_modo": "permitir_todos",
        "geoip_paises": [],
        "geoip_bloquear_si_no_hay_geo": False,
        "ip_whitelist": [],
        "ip_blacklist": [],
        "duracion_bloqueo_min": int(settings.DURACION_BLOQUEO_MIN or 10),
        "max_intentos_fallidos": int(settings.MAX_INTENTOS_FALLIDOS or 3),
        "paises_catalogo": geoip_ops.paises_catalogo(),
    }


def leer_ajustes(db: Session) -> dict:
    fila = db.query(AjustesSeguridad).filter(AjustesSeguridad.id == "default").first()
    base = ajustes_defecto()
    if not fila:
        return base
    tope = tope_sesiones()
    # Valores 20 y 50 eran el default y el techo antiguos: se suben a 130
    # para desbloquear varias sesiones por usuario sin que el admin tenga
    # que tocar el formulario.
    if fila.sesiones_limite in (20, 50) and tope >= 130:
        fila.sesiones_limite = min(130, tope)
        db.commit()
    base.update({
        "sesiones_limite": _clamp_limite(fila.sesiones_limite),
        "geoip_habilitado": bool(fila.geoip_habilitado),
        "geoip_modo": fila.geoip_modo if fila.geoip_modo in MODOS_GEOIP else "permitir_todos",
        "geoip_paises": _paises_norm(fila.geoip_paises),
        "geoip_bloquear_si_no_hay_geo": bool(fila.geoip_bloquear_si_no_hay_geo),
        "ip_whitelist": _ips_norm(fila.ip_whitelist),
        "ip_blacklist": _ips_norm(fila.ip_blacklist),
    })
    return base


def guardar_ajustes(db: Session, datos: dict, *, actor: Usuario | None = None) -> dict:
    fila = db.query(AjustesSeguridad).filter(AjustesSeguridad.id == "default").first()
    if fila is None:
        fila = AjustesSeguridad(id="default")
        db.add(fila)
    if "sesiones_limite" in datos and datos["sesiones_limite"] is not None:
        fila.sesiones_limite = _clamp_limite(datos["sesiones_limite"])
    if "geoip_habilitado" in datos and datos["geoip_habilitado"] is not None:
        fila.geoip_habilitado = bool(datos["geoip_habilitado"])
    if datos.get("geoip_modo"):
        modo = str(datos["geoip_modo"])
        if modo not in MODOS_GEOIP:
            raise ValueError("Modo GeoIP inválido. Use permitir_todos, allowlist o denylist.")
        fila.geoip_modo = modo
    if "geoip_paises" in datos and datos["geoip_paises"] is not None:
        fila.geoip_paises = _paises_norm(datos["geoip_paises"])
    if "geoip_bloquear_si_no_hay_geo" in datos and datos["geoip_bloquear_si_no_hay_geo"] is not None:
        fila.geoip_bloquear_si_no_hay_geo = bool(datos["geoip_bloquear_si_no_hay_geo"])
    if "ip_whitelist" in datos and datos["ip_whitelist"] is not None:
        fila.ip_whitelist = _ips_norm(datos["ip_whitelist"])
    if "ip_blacklist" in datos and datos["ip_blacklist"] is not None:
        fila.ip_blacklist = _ips_norm(datos["ip_blacklist"])
    fila.actualizado_en = now()
    fila.actualizado_por = actor.id if actor else None
    db.commit()
    db.refresh(fila)
    return leer_ajustes(db)


def contar_sesiones_activas(db: Session) -> int:
    """Usuarios distintos con al menos un refresh token vigente (no revocado)."""
    instante = dt.datetime.utcnow()
    return (
        db.query(RefreshToken.usuario_id)
        .filter(
            RefreshToken.revocado.is_(False),
            RefreshToken.expira_en > instante,
        )
        .distinct()
        .count()
    )


def usuario_tiene_sesion(db: Session, usuario_id: str) -> bool:
    instante = dt.datetime.utcnow()
    return db.query(RefreshToken).filter(
        RefreshToken.usuario_id == usuario_id,
        RefreshToken.revocado.is_(False),
        RefreshToken.expira_en > instante,
    ).first() is not None


def hay_cupo_sesion(db: Session, usuario_id: str | None = None) -> tuple[bool, int, int]:
    limite = leer_ajustes(db)["sesiones_limite"]
    actuales = contar_sesiones_activas(db)
    if usuario_id and usuario_tiene_sesion(db, usuario_id):
        return True, actuales, limite
    return actuales < limite, actuales, limite


def limite_sesiones_usuario(rol: str | None) -> int:
    if rol == "admin":
        return max(1, int(settings.SESIONES_MAX_ADMIN or 2))
    return max(1, int(settings.SESIONES_MAX_OTROS or 1))


def ips_seguras_max() -> int:
    return max(1, int(settings.IPS_SEGURAS_MAX or 3))


def contar_sesiones_usuario(db: Session, usuario_id: str) -> int:
    instante = dt.datetime.utcnow()
    return (
        db.query(RefreshToken)
        .filter(
            RefreshToken.usuario_id == usuario_id,
            RefreshToken.revocado.is_(False),
            RefreshToken.expira_en > instante,
        )
        .count()
    )


def hay_cupo_sesion_usuario(db: Session, usuario: Usuario) -> tuple[bool, int, int]:
    limite = limite_sesiones_usuario(usuario.rol)
    actuales = contar_sesiones_usuario(db, usuario.id)
    return actuales < limite, actuales, limite


def sesiones_usuario_vigentes(db: Session, usuario_id: str) -> list[RefreshToken]:
    instante = dt.datetime.utcnow()
    return (
        db.query(RefreshToken)
        .filter(
            RefreshToken.usuario_id == usuario_id,
            RefreshToken.revocado.is_(False),
            RefreshToken.expira_en > instante,
        )
        .order_by(RefreshToken.creado_en.asc())
        .all()
    )


def liberar_cupo_sesion_usuario(db: Session, usuario: Usuario) -> int:
    """Cierra las sesiones más antiguas hasta dejar un hueco para un login nuevo."""
    limite = limite_sesiones_usuario(usuario.rol)
    vigentes = sesiones_usuario_vigentes(db, usuario.id)
    cerradas = 0
    while vigentes and len(vigentes) >= limite:
        vieja = vigentes.pop(0)
        vieja.revocado = True
        cerradas += 1
    if cerradas:
        db.flush()
    return cerradas


def normalizar_ips_seguras(valor) -> list[str]:
    tope = ips_seguras_max()
    vistas: list[str] = []
    for cruda in _lista_str(valor):
        ip = cruda.strip()
        if not ip:
            continue
        if not geoip_ops.es_ip_publica(ip):
            raise ValueError(
                f"{ip} no es una IP pública. Solo se registran IPv4/IPv6 públicas "
                f"(máximo {tope} por usuario). La red local no cuenta."
            )
        if ip not in vistas:
            vistas.append(ip)
        if len(vistas) > tope:
            raise ValueError(f"Como máximo {tope} IPs públicas seguras por usuario")
    return vistas


def asegurar_ip_segura(usuario: Usuario, ip: str | None) -> str | None:
    """Si la IP es pública, la registra (hasta 3) o deniega si ya hay cupo."""
    if not geoip_ops.es_ip_publica(ip):
        return None
    actuales = [p for p in _ips_norm(usuario.ips_seguras) if geoip_ops.es_ip_publica(p)]
    if ip in actuales:
        if actuales != _ips_norm(usuario.ips_seguras):
            usuario.ips_seguras = actuales
        return None
    if len(actuales) < ips_seguras_max():
        actuales.append(ip)
        usuario.ips_seguras = actuales
        return ip
    raise ValueError(
        f"Esta IP pública no está registrada como segura para tu usuario "
        f"(máximo {ips_seguras_max()}). Pide al administrador que la agregue."
    )


def fmt_hasta(cuando: dt.datetime | None) -> str:
    cuando = _naive_utc(cuando)
    if not cuando:
        return "—"
    return cuando.strftime("%Y-%m-%d %H:%M UTC")


def _fila_ip(db: Session, ip: str) -> BloqueoIp:
    fila = db.query(BloqueoIp).filter(BloqueoIp.ip == ip).first()
    if fila is None:
        fila = BloqueoIp(ip=ip, intentos_fallidos=0)
        db.add(fila)
        db.flush()
    return fila


def bloqueo_vigente(db: Session, *, usuario: Usuario | None, ip: str | None) -> tuple[str | None, dt.datetime | None]:
    """Devuelve ('usuario'|'ip', hasta) si hay bloqueo activo.

    La LAN (loopback, RFC1918, link-local) no entra en este candado: ni
    bloqueo de cuenta ni de IP. El lockout es para orígenes públicos.
    """
    if geoip_ops.es_ip_local(ip):
        return None, None
    instante = dt.datetime.utcnow()
    hasta_u = _naive_utc(usuario.bloqueado_hasta) if usuario is not None else None
    if hasta_u and hasta_u > instante:
        return "usuario", usuario.bloqueado_hasta
    if ip:
        fila = db.query(BloqueoIp).filter(BloqueoIp.ip == ip).first()
        hasta_ip = _naive_utc(fila.bloqueado_hasta) if fila else None
        if hasta_ip and hasta_ip > instante:
            return "ip", fila.bloqueado_hasta
    return None, None


def mensaje_bloqueo(tipo: str, hasta: dt.datetime) -> str:
    ts = fmt_hasta(hasta)
    if tipo == "ip":
        return (
            f"Esta dirección IP está bloqueada por múltiples intentos fallidos. "
            f"Intenta de nuevo después de {ts}."
        )
    return (
        f"Cuenta bloqueada temporalmente por múltiples intentos fallidos. "
        f"Intenta de nuevo después de {ts}."
    )


def _duracion() -> dt.timedelta:
    return dt.timedelta(minutes=max(1, int(settings.DURACION_BLOQUEO_MIN or 10)))


def registrar_fallo(db: Session, *, usuario: Usuario | None, ip: str | None,
                    motivo: str) -> tuple[bool, str | None, dt.datetime | None]:
    """Suma un intento fallido (cuenta y, si la IP es pública, también la IP).

    Desde una IP local no se cuenta ni se bloquea. Devuelve
    (quedó_bloqueado, tipo, hasta).
    """
    if geoip_ops.es_ip_local(ip):
        return False, None, None

    instante = dt.datetime.utcnow()
    max_n = max(1, int(settings.MAX_INTENTOS_FALLIDOS or 3))
    bloqueado = False
    tipo = None
    hasta = None

    if usuario is not None:
        usuario.intentos_fallidos = (usuario.intentos_fallidos or 0) + 1
        if usuario.intentos_fallidos >= max_n:
            usuario.bloqueado_hasta = instante + _duracion()
            bloqueado = True
            tipo = "usuario"
            hasta = usuario.bloqueado_hasta

    if ip:
        fila = _fila_ip(db, ip)
        fila.intentos_fallidos = (fila.intentos_fallidos or 0) + 1
        fila.actualizado_en = instante
        if fila.intentos_fallidos >= max_n:
            fila.bloqueado_hasta = instante + _duracion()
            if not bloqueado:
                bloqueado = True
                tipo = "ip"
                hasta = fila.bloqueado_hasta
            elif hasta is None:
                hasta = fila.bloqueado_hasta

    db.commit()
    return bloqueado, tipo, hasta


def listar_bloqueos_ip(db: Session) -> list[dict]:
    instante = dt.datetime.utcnow()
    filas = db.query(BloqueoIp).order_by(BloqueoIp.actualizado_en.desc()).all()
    out = []
    for f in filas:
        hasta = _naive_utc(f.bloqueado_hasta)
        vigente = bool(hasta and hasta > instante)
        out.append({
            "ip": f.ip,
            "intentos_fallidos": int(f.intentos_fallidos or 0),
            "bloqueado_hasta": f.bloqueado_hasta,
            "vigente": vigente,
            "actualizado_en": f.actualizado_en,
        })
    return out


def quitar_bloqueo_ip(db: Session, ip: str) -> bool:
    ip_n = (ip or "").strip()
    if not ip_n:
        return False
    fila = db.query(BloqueoIp).filter(BloqueoIp.ip == ip_n).first()
    if not fila:
        return False
    db.delete(fila)
    db.commit()
    return True


def limpiar_fallos(db: Session, *, usuario: Usuario | None, ip: str | None) -> None:
    if usuario is not None:
        usuario.intentos_fallidos = 0
        usuario.bloqueado_hasta = None
    if ip and geoip_ops.es_ip_publica(ip):
        fila = db.query(BloqueoIp).filter(BloqueoIp.ip == ip).first()
        if fila:
            fila.intentos_fallidos = 0
            fila.bloqueado_hasta = None
            fila.actualizado_en = dt.datetime.utcnow()
    db.commit()


def evaluar_geoip(db: Session, ip: str | None) -> dict:
    """Decide si la IP puede entrar. No registra ni notifica."""
    az = leer_ajustes(db)
    ip_n = (ip or "").strip()
    geo = geoip_ops.lookup(ip_n)
    codigo = (geo.get("country_code") or "").upper()
    nombre = geo.get("country_name") or codigo or "Desconocido"
    decision = {
        "permitido": True,
        "razon": "permitido",
        "ip": ip_n,
        "country_code": codigo,
        "country_name": nombre,
        "source": geo.get("source"),
        "disponible": bool(geo.get("disponible")),
    }
    if ip_n and ip_n in az["ip_whitelist"]:
        decision["razon"] = "whitelist"
        return decision
    if ip_n and ip_n in az["ip_blacklist"]:
        decision["permitido"] = False
        decision["razon"] = "blacklist"
        return decision
    if not az["geoip_habilitado"]:
        decision["razon"] = "geoip-desactivado"
        return decision
    if codigo == "LOCAL":
        decision["razon"] = "red-local"
        return decision
    if not geo.get("disponible"):
        if az["geoip_bloquear_si_no_hay_geo"]:
            decision["permitido"] = False
            decision["razon"] = "geo-no-disponible"
        else:
            decision["razon"] = "geo-no-disponible-fail-open"
        return decision
    modo = az["geoip_modo"]
    paises = az["geoip_paises"]
    if modo == "allowlist":
        if not paises:
            decision["razon"] = "allowlist-vacia-permite-todos"
            return decision
        if codigo not in paises:
            decision["permitido"] = False
            decision["razon"] = "pais-no-permitido"
            return decision
    elif modo == "denylist":
        if codigo in paises:
            decision["permitido"] = False
            decision["razon"] = "pais-denegado"
            return decision
    decision["razon"] = "pais-permitido"
    return decision


def detalle_geo(decision: dict) -> str:
    code = decision.get("country_code") or "—"
    nombre = decision.get("country_name") or ""
    return f"ip={decision.get('ip') or '—'} país={code} {nombre} motivo={decision.get('razon')}"


def emails_admin(db: Session) -> list[str]:
    dest = []
    extra = (settings.ALERT_EMAIL_EXTRA or "").strip()
    if extra:
        dest.extend(_ips_norm(extra.replace(";", ",")))
    for u in db.query(Usuario).filter(
        Usuario.activo.is_(True), Usuario.rol == "admin", Usuario.email.isnot(None),
    ).all():
        mail = (u.email or "").strip()
        if mail and _EMAIL_RE.match(mail):
            dest.append(mail)
    # únicos conservando orden
    vistos = set()
    out = []
    for d in dest:
        k = d.lower()
        if k in vistos:
            continue
        vistos.add(k)
        out.append(d)
    return out


def _cfg_smtp_alerta(db: Session) -> dict | None:
    if (settings.ALERT_SMTP_HOST or "").strip():
        return {
            "email": settings.ALERT_EMAIL_FROM or settings.ALERT_SMTP_USUARIO,
            "nombre_mostrar": "Control de Proyecto",
            "smtp_host": settings.ALERT_SMTP_HOST,
            "smtp_puerto": int(settings.ALERT_SMTP_PORT or 587),
            "smtp_usuario": settings.ALERT_SMTP_USUARIO,
            "smtp_password": settings.ALERT_SMTP_PASSWORD,
            "smtp_seguridad": settings.ALERT_SMTP_SEGURIDAD or "starttls",
            "confirmacion_lectura": False,
            "_errores_password": [],
        }
    cuenta = db.query(CuentaCorreoProyecto).filter(
        CuentaCorreoProyecto.activo.is_(True),
    ).first()
    if not cuenta:
        return None
    from app.colaboracion.mailer import cuenta_como_dict
    cfg = cuenta_como_dict(cuenta)
    cfg["confirmacion_lectura"] = False
    cfg["nombre_mostrar"] = cfg.get("nombre_mostrar") or "Control de Proyecto"
    return cfg


def _enviar_correos(db: Session, asunto: str, cuerpo: str) -> int:
    destinos = emails_admin(db)
    if not destinos:
        return 0
    if _enviar_email is not None:
        for d in destinos:
            _enviar_email(d, asunto, cuerpo)
        return len(destinos)
    cfg = _cfg_smtp_alerta(db)
    if not cfg:
        logger.info("Alerta de seguridad sin SMTP configurado; no se envió correo.")
        return 0
    from app.colaboracion.mailer import smtp_enviar, MailError
    n = 0
    for dest in destinos:
        try:
            smtp_enviar(cfg, dest, asunto, cuerpo)
            n += 1
        except MailError:
            logger.exception("No se pudo enviar alerta de seguridad a %s", dest)
        except Exception:
            logger.exception("Error inesperado al enviar alerta a %s", dest)
    return n


def avisar_admins(
    db: Session, *, clave: str, asunto: str, cuerpo: str,
    telegram_texto: str | None = None, ventana_horas: float = 0.2,
) -> dict:
    """Correo a admins con email + Telegram a admins vinculados. Anti-rebote por clave."""
    enviados_tg = telegram_ops.notificar_admins(
        db, telegram_texto or cuerpo, clave=f"tg:{clave}",
        ventana_horas=ventana_horas,
    )
    # El anti-rebote de correo usa las mismas claves KV.
    if telegram_ops._ya_enviada(db, f"mail:{clave}", dt.timedelta(hours=ventana_horas)):
        enviados_mail = 0
    else:
        enviados_mail = _enviar_correos(db, asunto, cuerpo)
        if enviados_mail:
            telegram_ops._marcar_enviada(db, f"mail:{clave}")
    return {"telegram": enviados_tg, "correo": enviados_mail}


def avisar_bloqueo(db: Session, *, usuario: Usuario | None, ip: str | None,
                   tipo: str, hasta: dt.datetime, motivo: str) -> None:
    quien = usuario.usuario if usuario else "(desconocido)"
    ts = fmt_hasta(hasta)
    cuerpo = (
        f"Alerta de seguridad: bloqueo por intentos fallidos.\n"
        f"Usuario: {quien}\nIP: {ip or '—'}\nTipo: {tipo}\n"
        f"Hasta: {ts}\nMotivo: {motivo}\n"
        f"Revisa Eventos del sistema (paso 24) y Auditoría (paso 21)."
    )
    clave = f"bloqueo:{tipo}:{getattr(usuario, 'id', ip)}:{ts}"
    avisar_admins(
        db, clave=clave,
        asunto=f"[Control de Proyecto] Bloqueo de acceso ({quien})",
        cuerpo=cuerpo,
        telegram_texto=(
            f"Alerta de monitoreo: la cuenta «{quien}» quedó bloqueada "
            f"por intentos fallidos ({tipo}) hasta {ts}. Revisa Eventos (24) y Auditoría (21)."
        ),
        ventana_horas=12,
    )


def avisar_sesiones(db: Session, *, ip: str | None, actuales: int, limite: int,
                    usuario: Usuario | None = None) -> None:
    quien = usuario.usuario if usuario else "(desconocido)"
    cuerpo = (
        f"Alerta de seguridad: se rechazó un inicio de sesión porque el cupo de "
        f"sesiones concurrentes está lleno ({actuales}/{limite}; máximo absoluto "
        f"{tope_sesiones()}).\nUsuario: {quien}\nIP: {ip or '—'}\n"
        f"Revisa Eventos del sistema (paso 24)."
    )
    avisar_admins(
        db, clave=f"sesiones:{actuales}:{limite}",
        asunto="[Control de Proyecto] Cupo de sesiones concurrentes",
        cuerpo=cuerpo,
        telegram_texto=(
            f"Alerta: cupo de sesiones lleno ({actuales}/{limite}). "
            f"Se rechazó el acceso de «{quien}». Eventos (24)."
        ),
        ventana_horas=1,
    )


def avisar_geoip(db: Session, decision: dict, *, usuario: Usuario | None = None) -> None:
    quien = usuario.usuario if usuario else "(desconocido)"
    cuerpo = (
        f"Alerta de seguridad: inicio de sesión bloqueado por geolocalización de IP "
        f"(GeoIP).\nUsuario: {quien}\n{detalle_geo(decision)}\n"
        f"Revisa Eventos del sistema (paso 24) y la lista de países/IPs."
    )
    avisar_admins(
        db, clave=f"geoip:{decision.get('ip')}:{decision.get('razon')}",
        asunto="[Control de Proyecto] Acceso bloqueado por GeoIP",
        cuerpo=cuerpo,
        telegram_texto=(
            f"Alerta GeoIP: se bloqueó a «{quien}» "
            f"({decision.get('country_code') or '—'} / {decision.get('ip')}). "
            f"Motivo: {decision.get('razon')}. Eventos (24)."
        ),
        ventana_horas=6,
    )


def avisar_umbral_recurso(db: Session, clave_metrica: str, detalle: str) -> None:
    cuerpo = (
        f"Alerta de monitoreo: umbral de recurso cruzado.\n"
        f"Métrica: {clave_metrica}\n{detalle}\n"
        f"Revisa Monitoreo (paso 22) y Eventos del sistema (paso 24)."
    )
    avisar_admins(
        db, clave=f"umbral:{clave_metrica}",
        asunto=f"[Control de Proyecto] Umbral de recurso ({clave_metrica})",
        cuerpo=cuerpo,
        telegram_texto=f"Alerta de recurso: {detalle} Eventos (24).",
        ventana_horas=2,
    )


def avisar_nodo_sbc(db: Session, nodo_id: str, detalle: str) -> None:
    cuerpo = (
        f"Alerta de monitoreo: un nodo remoto del borde cambió de estado.\n"
        f"{detalle}\n"
        f"El control es solo central: revisa Monitoreo (23), Eventos (24) "
        f"y Sitios / SBC (28)."
    )
    avisar_admins(
        db, clave=f"nodo_sbc:{nodo_id}",
        asunto="[Control de Proyecto] Nodo remoto (borde)",
        cuerpo=cuerpo,
        telegram_texto=f"Alerta de nodo remoto: {detalle} Eventos (24).",
        ventana_horas=2,
    )


def email_valido(valor: str | None) -> str | None:
    mail = (valor or "").strip()
    if not mail:
        return None
    if not _EMAIL_RE.match(mail):
        raise ValueError("El correo no tiene un formato válido")
    return mail


def _iso_dt(cuando) -> str:
    if not cuando:
        return "—"
    if getattr(cuando, "tzinfo", None) is not None:
        cuando = cuando.replace(tzinfo=None)
    return cuando.strftime("%Y-%m-%d %H:%M:%S UTC")


def _pais_de_ip(ip: str | None) -> str:
    if not ip:
        return "—"
    try:
        geo = geoip_ops.lookup(ip)
    except Exception:
        return "—"
    code = (geo.get("country_code") or "").strip()
    name = (geo.get("country_name") or "").strip()
    if not code and not name:
        return "—"
    return " ".join(p for p in (code, name) if p)


def _nombre_escenario(esc: Escenario | None) -> str:
    if not esc:
        return "—"
    return f"{(esc.razon_social or '').strip()} {(esc.periodo_contratacion or '').strip()}".strip() or "—"


def detalle_usuarios_activos(db: Session) -> dict:
    instante = dt.datetime.utcnow()
    users = db.query(Usuario).filter(Usuario.activo.is_(True)).order_by(Usuario.usuario).all()
    filas = []
    for u in users:
        nombres = []
        for asg in (u.escenarios or []):
            n = _nombre_escenario(getattr(asg, "escenario", None))
            if n != "—":
                nombres.append(n)
        rt = (
            db.query(RefreshToken)
            .filter(
                RefreshToken.usuario_id == u.id,
                RefreshToken.revocado.is_(False),
                RefreshToken.expira_en > instante,
            )
            .order_by(RefreshToken.creado_en.desc())
            .first()
        )
        filas.append({
            "usuario": u.usuario,
            "nombre": u.nombre,
            "rol": u.rol,
            "escenario": ", ".join(nombres) or "—",
            "ultimo_acceso": _iso_dt(u.ultimo_login),
            "sesion": "activa" if rt else "sin sesión",
        })
    return {
        "tipo": "usuarios_activos",
        "titulo": "Usuarios activos",
        "columnas": [
            {"clave": "usuario", "titulo": "Usuario"},
            {"clave": "nombre", "titulo": "Nombre"},
            {"clave": "rol", "titulo": "Rol"},
            {"clave": "escenario", "titulo": "Escenario"},
            {"clave": "ultimo_acceso", "titulo": "Último acceso"},
            {"clave": "sesion", "titulo": "Sesión"},
        ],
        "filas": filas,
    }


def detalle_sesiones_activas(db: Session) -> dict:
    instante = dt.datetime.utcnow()
    tokens = (
        db.query(RefreshToken)
        .filter(RefreshToken.revocado.is_(False), RefreshToken.expira_en > instante)
        .order_by(RefreshToken.creado_en.desc())
        .all()
    )
    esc_ids = {rt.escenario_id for rt in tokens if rt.escenario_id}
    escenarios = {}
    if esc_ids:
        for esc in db.query(Escenario).filter(Escenario.id.in_(esc_ids)).all():
            escenarios[esc.id] = _nombre_escenario(esc)
    filas = []
    for rt in tokens:
        u = rt.usuario
        filas.append({
            "id": rt.id,
            "usuario": u.usuario if u else "—",
            "nombre": u.nombre if u else "—",
            "inicio": _iso_dt(rt.creado_en),
            "ip": rt.ip or "—",
            "pais": _pais_de_ip(rt.ip),
            "ultimo_uso": _iso_dt(u.ultimo_login if u else None),
            "escenario": escenarios.get(rt.escenario_id) or "—",
            "puede_cerrar": True,
        })
    return {
        "tipo": "sesiones_activas",
        "titulo": "Sesiones activas",
        "columnas": [
            {"clave": "usuario", "titulo": "Usuario"},
            {"clave": "inicio", "titulo": "Inicio"},
            {"clave": "ip", "titulo": "IP"},
            {"clave": "pais", "titulo": "País"},
            {"clave": "ultimo_uso", "titulo": "Último uso"},
            {"clave": "id", "titulo": "Id de sesión"},
        ],
        "filas": filas,
        "cerrar_sesion": True,
    }


def _filas_bitacora(eventos) -> list[dict]:
    filas = []
    for ev in eventos:
        filas.append({
            "fecha": _iso_dt(ev.timestamp),
            "usuario": ev.usuario_nombre or "—",
            "accion": ev.accion or "—",
            "entidad": ev.entidad or "—",
            "resultado": ev.resultado or "—",
            "ip": ev.ip or "—",
            "detalle": ev.detalle or "—",
            "motivo": ev.detalle or "—",
        })
    return filas


def detalle_auditoria_24h(db: Session, *, limite: int = 300) -> dict:
    hace_24h = dt.datetime.utcnow() - dt.timedelta(hours=24)
    eventos = (
        db.query(BitacoraEvento)
        .filter(BitacoraEvento.timestamp >= hace_24h)
        .order_by(BitacoraEvento.timestamp.desc())
        .limit(limite)
        .all()
    )
    return {
        "tipo": "auditoria",
        "titulo": "Eventos de auditoría (24 h)",
        "columnas": [
            {"clave": "fecha", "titulo": "Fecha"},
            {"clave": "usuario", "titulo": "Usuario"},
            {"clave": "accion", "titulo": "Acción"},
            {"clave": "entidad", "titulo": "Entidad"},
            {"clave": "resultado", "titulo": "Resultado"},
            {"clave": "ip", "titulo": "IP"},
            {"clave": "detalle", "titulo": "Detalle"},
        ],
        "filas": _filas_bitacora(eventos),
    }


def detalle_logins_24h(db: Session, *, resultado: str, limite: int = 300) -> dict:
    hace_24h = dt.datetime.utcnow() - dt.timedelta(hours=24)
    eventos = (
        db.query(BitacoraEvento)
        .filter(
            BitacoraEvento.timestamp >= hace_24h,
            BitacoraEvento.accion == "login",
            BitacoraEvento.resultado == resultado,
        )
        .order_by(BitacoraEvento.timestamp.desc())
        .limit(limite)
        .all()
    )
    ok = resultado == "ok"
    return {
        "tipo": "logins_ok" if ok else "logins_fallidos",
        "titulo": "Inicios de sesión exitosos (24 h)" if ok else "Inicios de sesión fallidos (24 h)",
        "columnas": [
            {"clave": "fecha", "titulo": "Fecha"},
            {"clave": "usuario", "titulo": "Usuario"},
            {"clave": "ip", "titulo": "IP"},
            {"clave": "motivo", "titulo": "Motivo"},
        ],
        "filas": _filas_bitacora(eventos),
    }


def revocar_sesion(db: Session, sesion_id: str, *, actor: Usuario | None = None) -> dict:
    rt = db.query(RefreshToken).filter(RefreshToken.id == sesion_id).first()
    if not rt:
        raise ValueError("Sesión no encontrada")
    quien = rt.usuario.usuario if rt.usuario else sesion_id
    rt.revocado = True
    db.commit()
    audit.registrar(
        db, usuario=actor, accion="sesion_cerrada", entidad="sesion",
        entidad_id=sesion_id, detalle=f"cierre administrativo de sesión de {quien}",
    )
    return {"ok": True, "id": sesion_id}
