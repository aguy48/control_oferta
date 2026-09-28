"""
Configuración del backend del Sistema de Cotización (ORIOL Consultores C.A.).

Instancia propia y separada de Control de Proyecto (ING-COT-003 §1 y §6):
su propia base de datos (DATABASE_URL) y su propio SECRET_KEY, por lo que
las cuentas de usuario NO se comparten con Control de Proyecto.

Los nombres de las variables son los mismos que en Control de Proyecto
porque los módulos reutilizados tal cual (identity/, seguridad_ops,
geoip_ops, deps, security) los leen de aquí.
"""
import os
import secrets

# Coincide con el archivo VERSION de la raíz del proyecto.
APP_VERSION = "0.3.9"


def _env(name, default=None, required=False):
    val = os.environ.get(name, default)
    if required and not val:
        raise RuntimeError(
            f"Falta la variable de entorno obligatoria {name}. "
            f"Revisa Backend/.env.example antes de arrancar el backend."
        )
    return val


class Settings:
    # --- Base de datos (propia de esta instancia) ---
    #   dev:  sqlite:///./sistema_cotizacion.db
    #   prod: postgresql+psycopg2://usuario:clave@db:5432/sistema_cotizacion
    DATABASE_URL: str = _env("DATABASE_URL", "sqlite:///./sistema_cotizacion.db")

    # --- JWT (clave propia: NUNCA la de Control de Proyecto) ---
    SECRET_KEY_ES_AUTOGENERADA: bool = not bool(_env("SECRET_KEY"))
    SECRET_KEY: str = _env("SECRET_KEY") or secrets.token_urlsafe(48)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_TTL_MIN: int = int(_env("ACCESS_TOKEN_TTL_MIN", "15"))
    REFRESH_TOKEN_TTL_MIN: int = int(_env("REFRESH_TOKEN_TTL_MIN", str(8 * 60)))

    # --- Primer usuario administrador (sin contraseña por defecto) ---
    INITIAL_ADMIN_USER: str | None = _env("INITIAL_ADMIN_USER")
    INITIAL_ADMIN_PASSWORD: str | None = _env("INITIAL_ADMIN_PASSWORD")
    INITIAL_ADMIN_NOMBRE: str = _env("INITIAL_ADMIN_NOMBRE", "Administrador")

    # --- Bloqueo por intentos fallidos ---
    MAX_INTENTOS_FALLIDOS: int = int(_env("MAX_INTENTOS_FALLIDOS", "3"))
    VENTANA_BLOQUEO_MIN: int = int(_env("VENTANA_BLOQUEO_MIN", "5"))
    DURACION_BLOQUEO_MIN: int = int(_env("DURACION_BLOQUEO_MIN", "10"))

    # --- Sesiones concurrentes ---
    SESIONES_MAX_ABSOLUTO: int = int(_env("SESIONES_MAX_ABSOLUTO", "130"))
    SESIONES_LIMITE_DEFECTO: int = int(_env("SESIONES_LIMITE_DEFECTO", "130"))
    SESIONES_MAX_ADMIN: int = int(_env("SESIONES_MAX_ADMIN", "2"))
    SESIONES_MAX_OTROS: int = int(_env("SESIONES_MAX_OTROS", "1"))
    IPS_SEGURAS_MAX: int = int(_env("IPS_SEGURAS_MAX", "3"))

    # --- GeoIP ---
    GEOIP_DB: str = _env("GEOIP_DB", "") or ""
    GEOIP_LOOKUP_URL: str = _env(
        "GEOIP_LOOKUP_URL",
        "http://ip-api.com/json/{ip}?fields=status,country,countryCode,message",
    ) or ""
    GEOIP_TIMEOUT_S: float = float(_env("GEOIP_TIMEOUT_S", "2.5"))

    # --- SMTP opcional para alertas de seguridad a administradores ---
    # En esta instancia no hay cuentas de correo por proyecto: si está vacío,
    # las alertas de seguridad solo quedan en la bitácora.
    ALERT_SMTP_HOST: str = _env("ALERT_SMTP_HOST", "") or ""
    ALERT_SMTP_PORT: int = int(_env("ALERT_SMTP_PORT", "587"))
    ALERT_SMTP_USUARIO: str = _env("ALERT_SMTP_USUARIO", "") or ""
    ALERT_SMTP_PASSWORD: str = _env("ALERT_SMTP_PASSWORD", "") or ""
    ALERT_SMTP_SEGURIDAD: str = (_env("ALERT_SMTP_SEGURIDAD", "starttls") or "starttls").lower()
    ALERT_EMAIL_FROM: str = _env("ALERT_EMAIL_FROM", "") or ""
    ALERT_EMAIL_EXTRA: str = _env("ALERT_EMAIL_EXTRA", "") or ""

    # --- CORS / proxies ---
    CORS_ORIGINS: list[str] = [o.strip() for o in _env("CORS_ORIGINS", "*").split(",")]
    TRUSTED_PROXIES: frozenset[str] = frozenset(
        p.strip() for p in (_env("TRUSTED_PROXIES", "127.0.0.1,::1") or "").split(",")
        if p.strip()
    )

    ORGANIZACION: str = "ORIOL Consultores C.A."
    PROYECTO: str = "Sistema de Cotización (ATLAS MET-002)"
    AMBIENTE: str = (_env("AMBIENTE", "") or "").strip().lower()
    STORAGE_DIR: str = _env("STORAGE_DIR", "./data")

    # --- Traspaso por MCP (MASTER CONTROL PROJECT) ---
    # Preferido: URL, token y SBC único en Generales (solo admin).
    # .env queda como reserva si Generales aún no está lleno.
    MCP_URL: str = (_env("MCP_URL", "") or "").strip().rstrip("/")
    MCP_TOKEN: str = (_env("MCP_TOKEN", "") or "").strip()
    MCP_POLL_SECONDS: int = int(_env("MCP_POLL_SECONDS", "60"))
    MCP_TIMEOUT_S: float = float(_env("MCP_TIMEOUT_S", "15"))

    def mcp_configurado(self) -> bool:
        return bool(self.MCP_URL and self.MCP_TOKEN)

    # Gemini (OCR de ofertas de proveedor / informe técnico → partidas).
    # Si está vacío se usa la clave cifrada de Generales.
    GEMINI_API_KEY: str = (_env("GEMINI_API_KEY", "") or "").strip()
    GEMINI_MODEL: str = (_env("GEMINI_MODEL", "gemini-2.5-flash") or "gemini-2.5-flash").strip()

    # Bot de Telegram (preferido en Generales; .env como reserva).
    TELEGRAM_BOT_TOKEN: str = (_env("TELEGRAM_BOT_TOKEN", "") or "").strip()
    TELEGRAM_BOT_USERNAME: str = (_env("TELEGRAM_BOT_USERNAME", "") or "").lstrip("@")
    TELEGRAM_MODE: str = (_env("TELEGRAM_MODE", "polling") or "polling").strip().lower()
    TELEGRAM_WEBHOOK_SECRET: str = (_env("TELEGRAM_WEBHOOK_SECRET", "") or "").strip()
    TELEGRAM_POLL_SECONDS: int = int(_env("TELEGRAM_POLL_SECONDS", "3"))
    TELEGRAM_EMPAREJAR_TTL_MIN: int = int(_env("TELEGRAM_EMPAREJAR_TTL_MIN", "15"))

    # OnlyOffice Document Server (el mismo del NUC que usa Control de Proyecto).
    # ONLYOFFICE_APP_URL es ESTA API (:8100) vista por el contenedor, no la de CP.
    ONLYOFFICE_URL: str = (_env("ONLYOFFICE_URL", "") or "").strip().rstrip("/")
    ONLYOFFICE_APP_URL: str = (_env("ONLYOFFICE_APP_URL", "") or "").strip().rstrip("/")
    ONLYOFFICE_JWT_SECRET: str = (_env("ONLYOFFICE_JWT_SECRET", "") or "").strip()

    # 2FA obligatorio para admin/analista (REQUIRE_2FA=0 solo en el puesto local).
    REQUIRE_2FA: bool = (_env("REQUIRE_2FA", "true") or "true").lower() in ("1", "true", "yes", "si")

    # Rol de la instancia. Fijo: el Sistema de Cotización no es MASTER ni SBC
    # (ING-COT-003 §6); deps.get_current_user solo consulta la política del
    # MASTER cuando es_sbc() es verdadero.
    APP_ROL: str = "cotizacion"

    def es_master(self) -> bool:
        return False

    def es_sbc(self) -> bool:
        return False

    def modo_app(self) -> str:
        return "cotizacion"


settings = Settings()
