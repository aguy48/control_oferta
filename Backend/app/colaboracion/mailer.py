"""
ADAPTADOR (Sistema de Cotización).

Solo el envío SMTP que seguridad_ops usa para las alertas a administradores
(ALERT_SMTP_*). El mailer completo de Control de Proyecto (POP3, buzones por
proyecto, credenciales cifradas) no aplica a esta instancia.
"""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid


class MailError(Exception):
    pass


def cuenta_como_dict(cuenta) -> dict:
    # CuentaCorreoProyecto queda siempre vacía en esta instancia.
    raise MailError("El Sistema de Cotización no maneja cuentas de correo por proyecto")


def smtp_enviar(cfg: dict, destino: str, asunto: str, cuerpo: str) -> None:
    msg = EmailMessage()
    remitente = cfg.get("email") or cfg.get("smtp_usuario")
    nombre = cfg.get("nombre_mostrar") or "Sistema de Cotización"
    msg["From"] = f"{nombre} <{remitente}>"
    msg["To"] = destino
    msg["Subject"] = asunto
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid()
    msg.set_content(cuerpo)
    host, puerto = cfg.get("smtp_host"), int(cfg.get("smtp_puerto") or 587)
    seguridad = (cfg.get("smtp_seguridad") or "starttls").lower()
    try:
        if seguridad == "ssl":
            srv = smtplib.SMTP_SSL(host, puerto, context=ssl.create_default_context(), timeout=20)
        else:
            srv = smtplib.SMTP(host, puerto, timeout=20)
            if seguridad == "starttls":
                srv.starttls(context=ssl.create_default_context())
        with srv:
            if cfg.get("smtp_usuario"):
                srv.login(cfg["smtp_usuario"], cfg.get("smtp_password") or "")
            srv.send_message(msg)
    except (OSError, smtplib.SMTPException) as e:
        raise MailError(str(e)) from e
