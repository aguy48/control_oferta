"""Cifrado de secretos de instancia (Gemini, token MCP) con Fernet derivado del SECRET_KEY."""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.kernel.config import settings


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def cifrar(texto: str | None) -> str | None:
    if not texto:
        return None
    return _fernet().encrypt(texto.encode("utf-8")).decode("ascii")


def descifrar(blob: str | None) -> str | None:
    if not blob:
        return None
    try:
        return _fernet().decrypt(blob.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
