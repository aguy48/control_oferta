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
    producto_id: str | None = None


class PartidaOut(PartidaIn):
    id: str
    orden: int
    precio_total: float
    requiere_serial: bool = False
    garantia_semanas: int | None = None
    tiempo_entrega_semanas: int | None = None

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
    margen_pct: float | None = Field(default=None, ge=0, le=500)
    origen: Literal["comercial", "tecnica"] = "comercial"
    semanas_totales: int | None = Field(default=None, ge=1)
    sede_destino: str | None = Field(default=None, max_length=120)
    # Id del SBC destino en el MCP (GET /mcp/destinos).
    mcp_destino_id: str | None = Field(default=None, max_length=80)
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
    margen_pct: float | None = Field(default=None, ge=0, le=500)
    origen: Literal["comercial", "tecnica"] | None = None
    semanas_totales: int | None = Field(default=None, ge=1)
    sede_destino: str | None = Field(default=None, max_length=120)
    # Id del SBC destino en el MCP (GET /mcp/destinos).
    mcp_destino_id: str | None = Field(default=None, max_length=80)
    notas: str | None = Field(default=None, max_length=4000)


class OfertaEstadoIn(BaseModel):
    estado: Literal["borrador", "enviada", "en_negociacion", "ganada", "perdida", "anulada"]
    seriales: list["SerialVentaIn"] = []


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
    margen_pct: float = 25
    origen: str = "comercial"
    semanas_totales: int | None = None
    sede_destino: str | None = None
    notas: str | None = None
    analista_nombre: str | None = None
    fecha_ganada: dt.datetime | None = None
    proyecto_cp_id: str | None = None
    contrato_cp_numero: str | None = None
    vinculado_en: dt.datetime | None = None
    traspasos_generados: int = 0
    mcp_destino_id: str | None = None
    mcp_traspaso_id: str | None = None
    mcp_version: int | None = None
    mcp_estado: str | None = None
    mcp_detalle: str | None = None
    mcp_actualizado_en: dt.datetime | None = None
    vinculado_por: str | None = None
    total_precio: float = 0
    partidas: list[PartidaOut] = []

    model_config = ConfigDict(from_attributes=True)


# ---------- Plataforma operativa (mismas opciones que Control de Proyecto) ----------
class ClienteIn(BaseModel):
    razon_social: str = Field(min_length=2, max_length=200)
    rif: str | None = Field(default=None, max_length=20)
    direccion: str | None = Field(default=None, max_length=400)
    telefono: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=120)
    tipo: Literal["directo", "aliado"] = "directo"
    condicion_pago: str | None = Field(default=None, max_length=80)
    notas: str | None = Field(default=None, max_length=4000)
    activo: bool = True


class ClienteUpdate(BaseModel):
    razon_social: str | None = Field(default=None, min_length=2, max_length=200)
    rif: str | None = Field(default=None, max_length=20)
    direccion: str | None = Field(default=None, max_length=400)
    telefono: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=120)
    tipo: Literal["directo", "aliado"] | None = None
    condicion_pago: str | None = Field(default=None, max_length=80)
    notas: str | None = Field(default=None, max_length=4000)
    activo: bool | None = None


class ClienteOut(ClienteIn):
    id: str
    rif_norm: str | None = None
    n_ofertas: int = 0
    creado_en: dt.datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ProveedorIn(BaseModel):
    razon_social: str = Field(min_length=2, max_length=200)
    rif: str | None = Field(default=None, max_length=20)
    contacto: str | None = Field(default=None, max_length=200)
    telefono: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=120)
    notas: str | None = Field(default=None, max_length=4000)
    activo: bool = True


class ProveedorUpdate(BaseModel):
    razon_social: str | None = Field(default=None, min_length=2, max_length=200)
    rif: str | None = Field(default=None, max_length=20)
    contacto: str | None = Field(default=None, max_length=200)
    telefono: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=120)
    notas: str | None = Field(default=None, max_length=4000)
    activo: bool | None = None


class ProveedorOut(ProveedorIn):
    id: str
    creado_en: dt.datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ProductoIn(BaseModel):
    tipo: Literal["producto", "servicio"] = "producto"
    codigo: str | None = Field(default=None, max_length=40)
    nombre: str = Field(min_length=2, max_length=200)
    descripcion: str | None = Field(default=None, max_length=4000)
    unidad: str = Field(default="UND", min_length=1, max_length=20)
    disciplina: str | None = Field(default=None, max_length=120)
    precio_ref: float | None = Field(default=None, ge=0)
    requiere_serial: bool = False
    garantia_semanas: int | None = Field(default=None, ge=0)
    tiempo_entrega_semanas: int | None = Field(default=None, ge=0)
    activo: bool = True


class ProductoUpdate(BaseModel):
    tipo: Literal["producto", "servicio"] | None = None
    codigo: str | None = Field(default=None, max_length=40)
    nombre: str | None = Field(default=None, min_length=2, max_length=200)
    descripcion: str | None = Field(default=None, max_length=4000)
    unidad: str | None = Field(default=None, min_length=1, max_length=20)
    disciplina: str | None = Field(default=None, max_length=120)
    precio_ref: float | None = Field(default=None, ge=0)
    requiere_serial: bool | None = None
    garantia_semanas: int | None = Field(default=None, ge=0)
    tiempo_entrega_semanas: int | None = Field(default=None, ge=0)
    activo: bool | None = None


class ProductoOut(ProductoIn):
    id: str
    n_cotizaciones: int = 0
    creado_en: dt.datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ProductoCotizacionOut(BaseModel):
    oferta_id: str
    codigo: str
    cliente: str
    fecha: dt.datetime | None = None
    estado: str
    cantidad: float
    precio_unitario: float
    monto: float
    moneda: str


class ProductoTopOut(BaseModel):
    id: str
    tipo: str
    codigo: str
    nombre: str
    n_cotizaciones: int
    cantidad: float
    monto: float


class SerialVentaIn(BaseModel):
    partida_id: str
    serial: str = Field(min_length=1, max_length=80)


class SerialVentaOut(BaseModel):
    id: str
    partida_id: str
    producto_id: str
    serial: str
    descripcion: str | None = None

    model_config = ConfigDict(from_attributes=True)


class SerialRequeridoOut(BaseModel):
    partida_id: str
    producto_id: str
    item: str
    descripcion: str
    cantidad: float
    n_seriales: int
    garantia_semanas: int | None = None
    seriales: list[str] = []


class ContactoIn(BaseModel):
    nombre: str = Field(min_length=2, max_length=200)
    cargo: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=120)
    telefono: str | None = Field(default=None, max_length=40)
    tipo_responsable: str | None = Field(default=None, max_length=80)
    cliente_id: str | None = None
    notas: str | None = Field(default=None, max_length=4000)


class ContactoUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=200)
    cargo: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=120)
    telefono: str | None = Field(default=None, max_length=40)
    tipo_responsable: str | None = Field(default=None, max_length=80)
    cliente_id: str | None = None
    notas: str | None = Field(default=None, max_length=4000)


class ContactoOut(ContactoIn):
    id: str
    cliente_razon: str | None = None
    creado_en: dt.datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class TareaIn(BaseModel):
    titulo: str = Field(min_length=2, max_length=200)
    descripcion: str | None = Field(default=None, max_length=4000)
    estado: Literal["pendiente", "en_curso", "hecha", "cancelada"] = "pendiente"
    vencimiento: dt.date | None = None
    asignado_a: str | None = Field(default=None, max_length=120)
    oferta_id: str | None = None
    cliente_id: str | None = None


class TareaUpdate(BaseModel):
    titulo: str | None = Field(default=None, min_length=2, max_length=200)
    descripcion: str | None = Field(default=None, max_length=4000)
    estado: Literal["pendiente", "en_curso", "hecha", "cancelada"] | None = None
    vencimiento: dt.date | None = None
    asignado_a: str | None = Field(default=None, max_length=120)
    oferta_id: str | None = None
    cliente_id: str | None = None


class TareaOut(TareaIn):
    id: str
    creado_en: dt.datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class DocumentoIn(BaseModel):
    titulo: str = Field(min_length=2, max_length=200)
    tipo: str = Field(default="general", max_length=40)
    url: str | None = Field(default=None, max_length=2000)
    notas: str | None = Field(default=None, max_length=4000)
    oferta_id: str | None = None
    cliente_id: str | None = None


class DocumentoUpdate(BaseModel):
    titulo: str | None = Field(default=None, min_length=2, max_length=200)
    tipo: str | None = Field(default=None, max_length=40)
    url: str | None = Field(default=None, max_length=2000)
    notas: str | None = Field(default=None, max_length=4000)
    oferta_id: str | None = None
    cliente_id: str | None = None


class DocumentoOut(DocumentoIn):
    id: str
    creado_en: dt.datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class SeguimientoIn(BaseModel):
    estado: Literal["pendiente", "en_curso", "hecho", "no_aplica"]
    notas: str | None = Field(default=None, max_length=4000)


class SeguimientoOut(BaseModel):
    id: str
    oferta_id: str
    oferta_codigo: str | None = None
    oferta_titulo: str | None = None
    cliente: str | None = None
    paso: str
    estado: str
    notas: str | None = None
    actualizado_en: dt.datetime | None = None


class GeneralesIn(BaseModel):
    razon_social: str | None = Field(default=None, max_length=200)
    rif: str | None = Field(default=None, max_length=20)
    direccion: str | None = Field(default=None, max_length=400)
    telefono: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=120)
    iva_pct: int = Field(default=16, ge=0, le=100)
    moneda: str = Field(default="USD", min_length=3, max_length=3)
    margen_pct: float = Field(default=25, ge=0, le=500)
    gemini_api_key: str | None = Field(default=None, max_length=200)
    gemini_model: str | None = Field(default=None, max_length=80)
    mcp_url: str | None = Field(default=None, max_length=400)
    mcp_token: str | None = Field(default=None, max_length=400)
    mcp_destino_id: str | None = Field(default=None, max_length=80)
    mcp_sede_nombre: str | None = Field(default=None, max_length=120)
    telegram_bot_token: str | None = Field(default=None, max_length=120)
    telegram_bot_username: str | None = Field(default=None, max_length=64)
    telegram_mode: str | None = Field(default=None, max_length=16)
    telegram_webhook_secret: str | None = Field(default=None, max_length=120)
    telegram_poll_seconds: int | None = Field(default=None, ge=2, le=60)
    telegram_emparejar_ttl_min: int | None = Field(default=None, ge=5, le=120)
    notas: str | None = Field(default=None, max_length=4000)


class OnlyOfficeIn(BaseModel):
    onlyoffice_url: str | None = Field(default=None, max_length=400)
    onlyoffice_app_url: str | None = Field(default=None, max_length=400)
    onlyoffice_jwt_secret: str | None = Field(default=None, max_length=200)
    onlyoffice_quitar_jwt: bool | None = None


class OnlyOfficeOut(BaseModel):
    configurado: bool = False
    fuente: str | None = None
    url: str | None = None
    app_url: str | None = None
    tiene_jwt: bool = False
    ds_script: str | None = None


class GeneralesOut(BaseModel):
    razon_social: str | None = None
    rif: str | None = None
    direccion: str | None = None
    telefono: str | None = None
    email: str | None = None
    iva_pct: int = 16
    moneda: str = "USD"
    margen_pct: float = 25
    gemini_model: str | None = None
    gemini_configurado: bool = False
    mcp_url: str | None = None
    mcp_token_configurado: bool = False
    mcp_configurado: bool = False
    mcp_fuente: str | None = None
    mcp_destino_id: str | None = None
    mcp_sede_nombre: str | None = None
    telegram_configurado: bool = False
    telegram_bot_username: str | None = None
    telegram_mode: str | None = None
    telegram_fuente: str | None = None
    telegram_poll_seconds: int | None = None
    telegram_emparejar_ttl_min: int | None = None
    onlyoffice: OnlyOfficeOut | None = None
    notas: str | None = None
    actualizado_en: dt.datetime | None = None
    actualizado_por: str | None = None


class AnexoOut(BaseModel):
    id: str
    oferta_id: str | None = None
    tipo: str
    nombre: str
    mime: str | None = None
    texto_ocr: str | None = None
    extraccion: dict | None = None
    creado_en: dt.datetime | None = None
    creado_por: str | None = None

    model_config = ConfigDict(from_attributes=True)


class InformeIn(BaseModel):
    titulo: str = Field(min_length=3, max_length=200)
    codigo: str | None = Field(default=None, max_length=80)
    cliente_razon_social: str | None = Field(default=None, max_length=200)
    cliente_rif: str | None = Field(default=None, max_length=20)
    resumen: str | None = Field(default=None, max_length=20000)
    anexo_id: str | None = None
    oferta_id: str | None = None


class InformeUpdate(BaseModel):
    titulo: str | None = Field(default=None, min_length=3, max_length=200)
    codigo: str | None = Field(default=None, max_length=80)
    cliente_razon_social: str | None = Field(default=None, max_length=200)
    cliente_rif: str | None = Field(default=None, max_length=20)
    resumen: str | None = Field(default=None, max_length=20000)
    oferta_id: str | None = None


class InformeOut(InformeIn):
    id: str
    anexo_nombre: str | None = None
    archivo_office: bool = False
    creado_en: dt.datetime | None = None
    creado_por: str | None = None

    model_config = ConfigDict(from_attributes=True)


class GenerarOfertaIn(BaseModel):
    margen_pct: float | None = Field(default=None, ge=0, le=500)
    anexo_ids: list[str] | None = None
    reemplazar_partidas: bool = True
    crear_informe: bool = True


class AnalisisGenerarIn(BaseModel):
    margen_pct: float | None = Field(default=None, ge=0, le=500)
    crear_informe: bool = True
    crear_oferta: bool = True
    oferta_id: str | None = None
    mcp_destino_id: str | None = None
    sede_destino: str | None = None


class AnalisisGenerarOut(BaseModel):
    extraccion: dict
    informe: InformeOut | None = None
    oferta: OfertaOut | None = None


class BitacoraOut(BaseModel):
    id: str
    timestamp: dt.datetime | None = None
    usuario_nombre: str | None = None
    rol: str | None = None
    accion: str
    entidad: str | None = None
    entidad_id: str | None = None
    resultado: str
    ip: str | None = None
    detalle: str | None = None

    model_config = ConfigDict(from_attributes=True)


class PanelOut(BaseModel):
    ofertas_por_estado: dict[str, int]
    total_abiertas: float
    total_ganadas: float
    n_clientes: int
    n_contactos: int
    n_tareas_abiertas: int
    n_documentos: int
    n_proveedores: int
    n_informes: int = 0
    n_productos: int = 0
    top_productos: list[dict] = []
    mcp: dict
    recientes: list[dict] = []


class AsistenteSugerencia(BaseModel):
    paso: int
    etiqueta: str
    id: str
    mensaje: str
    destino: str | None = None
    ctab: str | None = None


class AsistenteOpcionOut(BaseModel):
    id: str
    paso: int
    destino: str
    etiqueta: str
    grupo: str
    ctab: str | None = None
    ayuda: str


class AsistenteCatalogo(BaseModel):
    rol: str
    opciones: list[AsistenteOpcionOut]


class AsistenteMensaje(BaseModel):
    mensaje: str = ""
    modo: str = "ayuda"


class AsistenteRespuesta(BaseModel):
    respuesta: str
    sugerencias: list[AsistenteSugerencia] = []
    destino: str | None = None
    ctab: str | None = None
    opcion_id: str | None = None
    recomendaciones: list[str] | None = None
    metricas: dict | None = None
    modo: str = "ayuda"


class TelegramEstado(BaseModel):
    habilitado: bool
    vinculado: bool
    bot_username: str | None = None
    telegram_username: str | None = None
    vinculado_en: dt.datetime | None = None


class TelegramEmparejarOut(BaseModel):
    token: str
    enlace: str | None = None
    expira_en: dt.datetime
    bot_username: str | None = None
    instruccion: str


class TelegramVinculoOut(BaseModel):
    id: str
    usuario: str
    nombre: str
    rol: str
    telegram_username: str | None = None
    vinculado_en: dt.datetime | None = None


class TelegramVinculosOut(BaseModel):
    bot_configurado: bool
    bot_username: str | None = None
    modo: str
    n_vinculados: int
    usuarios: list[TelegramVinculoOut] = []


class TelegramProbarIn(BaseModel):
    telegram_bot_token: str | None = Field(default=None, max_length=120)
