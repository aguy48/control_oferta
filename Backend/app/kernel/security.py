import base64
import datetime as dt
import hashlib
import io
import secrets
import socket

import bcrypt
import pyotp
import qrcode
from jose import jwt, JWTError
from qrcode.image.svg import SvgPathImage

from .config import settings


# ---------- Contraseñas ----------
# Se usa la librería 'bcrypt' directamente (no passlib.CryptContext): la
# combinación passlib 1.7 + bcrypt >= 4.1 falla en la autodetección de
# backend (ValueError en su self-test interno), un problema de
# compatibilidad conocido de esa combinación de versiones.
def hash_password(password: str) -> str:
    pw_bytes = password.encode("utf-8")[:72]  # límite propio de bcrypt
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("utf-8"))
    except Exception:
        return False


# ---------- JWT (access tokens de corta duración) ----------
def create_access_token(usuario_id: str, rol: str, sesion_id: str,
                        escenario_id: str | None = None,
                        acceso: str | None = None) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": usuario_id,
        "rol": rol,
        "sid": sesion_id,
        "iat": now,
        "exp": now + dt.timedelta(minutes=settings.ACCESS_TOKEN_TTL_MIN),
        "type": "access",
    }
    if escenario_id:
        payload["esc"] = escenario_id
        payload["acc"] = acceso or "lectura"
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None


# ---------- Refresh tokens (opacos, hash almacenado en BD, revocables) ----------
def new_refresh_token_raw() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------- TOTP (2FA) ----------
def generar_totp_secret() -> str:
    return pyotp.random_base32()


def ip_instancia() -> str:
    """IPv4 de salida de esta máquina (la que debe verse en el 2FA)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("1.1.1.1", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    return "127.0.0.1"


def totp_es_consola_master() -> bool:
    """MASTER CONTROL PROJECT (no el núcleo/Control de Proyecto)."""
    return settings.APP_ROL in ("master", "maestro", "soc", "noc")


def totp_issuer() -> str:
    """Emisor que ve la app autenticadora: ORIOL MCP o Oriol CP, más la IP."""
    ip = ip_instancia()
    if totp_es_consola_master():
        return f"ORIOL MCP - {ip}"
    # ADAPTADO (Sistema de Cotización): emisor propio para que la app
    # autenticadora distinga esta instancia de Control de Proyecto.
    return f"Oriol COT - {ip}"


def totp_uri(secret: str, usuario: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(
        name=usuario, issuer_name=totp_issuer()
    )


def totp_qr_data_url(otpauth_uri: str) -> str:
    """QR en data-URL SVG (sin Pillow) para mostrarlo en el HTML de setup."""
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2)
    qr.add_data(otpauth_uri)
    qr.make(fit=True)
    img = qr.make_image(image_factory=SvgPathImage)
    buf = io.BytesIO()
    img.save(buf)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


def normalizar_codigo_totp(codigo: str) -> str:
    # Google Authenticator y similares muestran "123 456"; el espacio rompe pyotp.verify.
    return "".join(c for c in (codigo or "") if c.isdigit())


def verificar_totp(secret: str, codigo: str) -> bool:
    if not secret:
        return False
    codigo = normalizar_codigo_totp(codigo)
    if len(codigo) != 6:
        return False
    return pyotp.totp.TOTP(secret).verify(codigo, valid_window=1)
