"""Esquemas Pydantic. Bloques Auth/Usuarios/Escenarios: copia de Control de Proyecto (kernel/schemas.py) para identity/."""
import datetime as dt
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator


# ---------- Auth ----------
class LoginRequest(BaseModel):
    usuario: str
    password: str
    totp: str | None = None


class LoginResponse(BaseModel):
    # Tokens solo cuando el login ya superó contraseña (y el cambio
    # obligatorio, si aplica). En los pasos intermedios van en null.
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "bearer"
    usuario: str
    nombre: str
    rol: str
    # ok | cambiar_password | totp | 2fa_setup | escenario
    paso: str = "ok"
    requiere_2fa_setup: bool = False
    debe_cambiar_password: bool = False
    requiere_totp: bool = False
    escenarios: list["EscenarioSesionOut"] = []
    escenario: "EscenarioSesionOut | None" = None


class CambiarPasswordRequest(BaseModel):
    usuario: str
    password_actual: str
    password_nueva: str = Field(min_length=8)


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    escenario: "EscenarioSesionOut | None" = None


class TotpSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str
    qr_data_url: str = ""


class TotpVerifyRequest(BaseModel):
    codigo: str


# ---------- Usuarios ----------
class UsuarioCreate(BaseModel):
    usuario: str = Field(min_length=3, max_length=50)
    nombre: str
    rol: str
    password: str = Field(min_length=8)
    email: str | None = None
    ips_seguras: list[str] | None = None


class UsuarioUpdate(BaseModel):
    nombre: str | None = None
    rol: str | None = None
    activo: bool | None = None
    email: str | None = None
    ips_seguras: list[str] | None = None


class UsuarioResetPassword(BaseModel):
    password: str = Field(min_length=8)


class UsuarioOut(BaseModel):
    id: str
    usuario: str
    nombre: str
    rol: str
    activo: bool
    totp_activo: bool
    ultimo_login: dt.datetime | None = None
    telegram_vinculado: bool = False
    telegram_username: str | None = None
    email: str | None = None
    ips_seguras: list[str] = []
    sesiones_activas: int = 0
    sesiones_max: int = 1

    model_config = ConfigDict(from_attributes=True)

    @field_validator("ips_seguras", mode="before")
    @classmethod
    def _ips_seguras_lista(cls, v):
        return v or []



# ---------- Escenarios ----------
class EscenarioSesionOut(BaseModel):
    id: str
    nombre: str
    razon_social: str
    periodo_contratacion: str
    fecha_inicio: dt.date | None = None
    fecha_fin: dt.date | None = None
    estado: str
    consultable: bool = True
    por_defecto: bool = False
    acceso: str
    solo_lectura: bool = False


class EscenarioCreate(BaseModel):
    razon_social: str = Field(min_length=2, max_length=120)
    periodo_contratacion: str = Field(min_length=4, max_length=40)
    fecha_inicio: dt.date
    fecha_fin: dt.date


class EscenarioUpdate(BaseModel):
    razon_social: str | None = Field(default=None, min_length=2, max_length=120)
    periodo_contratacion: str | None = Field(default=None, min_length=4, max_length=40)
    fecha_inicio: dt.date | None = None
    fecha_fin: dt.date | None = None
    estado: str | None = None
    consultable: bool | None = None
    por_defecto: bool | None = None


class EscenarioAsignacionIn(BaseModel):
    usuario_id: str
    acceso: str = "lectura"


class EscenarioAsignacionesIn(BaseModel):
    asignaciones: list[EscenarioAsignacionIn]


class EscenarioAsignacionOut(BaseModel):
    usuario_id: str
    usuario: str
    nombre: str
    rol: str
    acceso: str


class EscenarioOut(BaseModel):
    id: str
    nombre: str
    razon_social: str
    periodo_contratacion: str
    fecha_inicio: dt.date | None = None
    fecha_fin: dt.date | None = None
    estado: str
    consultable: bool
    por_defecto: bool = False
    n_proyectos: int = 0
    n_usuarios: int = 0

    model_config = ConfigDict(from_attributes=True)


class EscenarioElegirIn(BaseModel):
    escenario_id: str


class EscenariosDisponiblesOut(BaseModel):
    escenarios: list[EscenarioSesionOut]
    actual: EscenarioSesionOut | None = None


class MeOut(UsuarioOut):
    escenario: EscenarioSesionOut | None = None
    requiere_escenario: bool = False



# ---------- Ofertas (propio del Sistema de Cotización) ----------
class PartidaIn(BaseModel):
    disciplina: str = Field(default="GENERAL", min_length=1, max_length=120)
    item: str = Field(min_length=1, max_length=40)
    descripcion: str = Field(min_length=1, max_length=4000)
    unidad: str = Field(default="UND", min_length=1, max_length=20)
    cantidad: float = Field(ge=0)
    precio_unitario: float = Field(ge=0)
    semana_inicio: int | None = Field(default=None, ge=1)
    duracion_semanas: int | None = Field(default=None, ge=1)


class PartidaOut(PartidaIn):
    id: str
    orden: int
    precio_total: float

    model_config = ConfigDict(from_attributes=True)


class OfertaCreate(BaseModel):
    titulo: str = Field(min_length=3, max_length=200)
    cliente_razon_social: str = Field(min_length=2, max_length=200)
    cliente_rif: str | None = Field(default=None, max_length=20)
    cliente_tipo: Literal["directo", "aliado"] = "directo"
    cliente_contacto: str | None = Field(default=None, max_length=200)
    modalidad: Literal["suministro", "ejecucion"] | None = None
    facturacion: Literal["resumida", "detallada"] | None = None
    moneda: str = Field(default="USD", min_length=3, max_length=3)
    iva_pct: int = Field(default=16, ge=0, le=100)
    semanas_totales: int | None = Field(default=None, ge=1)
    sede_destino: str | None = Field(default=None, max_length=120)
    notas: str | None = Field(default=None, max_length=4000)


class OfertaUpdate(BaseModel):
    titulo: str | None = Field(default=None, min_length=3, max_length=200)
    cliente_razon_social: str | None = Field(default=None, min_length=2, max_length=200)
    cliente_rif: str | None = Field(default=None, max_length=20)
    cliente_tipo: Literal["directo", "aliado"] | None = None
    cliente_contacto: str | None = Field(default=None, max_length=200)
    modalidad: Literal["suministro", "ejecucion"] | None = None
    facturacion: Literal["resumida", "detallada"] | None = None
    moneda: str | None = Field(default=None, min_length=3, max_length=3)
    iva_pct: int | None = Field(default=None, ge=0, le=100)
    semanas_totales: int | None = Field(default=None, ge=1)
    sede_destino: str | None = Field(default=None, max_length=120)
    notas: str | None = Field(default=None, max_length=4000)


class OfertaEstadoIn(BaseModel):
    estado: Literal["borrador", "enviada", "en_negociacion", "ganada", "perdida", "anulada"]


class OfertaVinculacionIn(BaseModel):
    """Referencia al proyecto creado en Control de Proyecto (registro manual)."""
    proyecto_cp_id: str = Field(min_length=1, max_length=120)
    contrato_cp_numero: str | None = Field(default=None, max_length=80)


class OfertaOut(BaseModel):
    id: str
    codigo: str
    titulo: str
    estado: str
    cliente_razon_social: str
    cliente_rif: str | None = None
    cliente_tipo: str
    cliente_contacto: str | None = None
    modalidad: str | None = None
    facturacion: str | None = None
    moneda: str
    iva_pct: int
    semanas_totales: int | None = None
    sede_destino: str | None = None
    notas: str | None = None
    analista_nombre: str | None = None
    fecha_ganada: dt.datetime | None = None
    proyecto_cp_id: str | None = None
    contrato_cp_numero: str | None = None
    vinculado_en: dt.datetime | None = None
    traspasos_generados: int = 0
    total_precio: float = 0
    partidas: list[PartidaOut] = []

    model_config = ConfigDict(from_attributes=True)
