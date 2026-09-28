"""Cliente mínimo de la Bot API de Telegram (HTTPS JSON, sin SDK)."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from app.kernel.config import settings

logger = logging.getLogger("sistema_cotizacion")
_API = "https://api.telegram.org/bot{token}/{method}"


def token_actual(explicit: str | None = None) -> str:
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    try:
        from app.plataforma import telegram_ops
        t = telegram_ops.token_activo()
        if t:
            return t
    except Exception:
        pass
    return (settings.TELEGRAM_BOT_TOKEN or "").strip()


def habilitado() -> bool:
    return bool(token_actual())


def _post(method: str, payload: dict, timeout: int = 20, token: str | None = None) -> dict:
    token = token_actual(token)
    if not token:
        raise RuntimeError("Telegram no está configurado (falta el token del bot)")
    url = _API.format(token=token, method=method)
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detalle = e.read().decode("utf-8", errors="replace")
        logger.warning("Telegram %s HTTP %s: %s", method, e.code, detalle[:300])
        raise
    except Exception:
        logger.exception("Telegram %s falló", method)
        raise
    if not body.get("ok"):
        raise RuntimeError(body.get("description") or f"Telegram {method} rechazado")
    return body.get("result") if "result" in body else body


def get_me(token: str | None = None) -> dict:
    return _post("getMe", {}, timeout=10, token=token)


def get_updates(*, offset: int = 0, timeout: int = 0) -> list:
    payload = {
        "offset": offset,
        "timeout": timeout,
        "allowed_updates": ["message"],
    }
    result = _post("getUpdates", payload, timeout=max(15, timeout + 5))
    return result or []


def send_message(chat_id: str | int, texto: str, reply_markup: dict | None = None) -> dict | None:
    if not texto:
        return None
    chunks = []
    resto = texto
    while resto:
        chunks.append(resto[:4000])
        resto = resto[4000:]
    last = None
    for i, chunk in enumerate(chunks):
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": True,
        }
        if reply_markup and i == len(chunks) - 1:
            payload["reply_markup"] = reply_markup
        last = _post("sendMessage", payload)
    return last
