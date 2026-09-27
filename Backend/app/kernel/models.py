"""
Modelos del Sistema de Cotización.

Las tablas de identidad y seguridad (Usuario, RefreshToken, BitacoraEvento,
Escenario, UsuarioEscenario, BloqueoIp, AjustesSeguridad) son copia del
esquema de Control de Proyecto (kernel/models.py), para que identity/ y
seguridad_ops funcionen sin cambios — ING-COT-003 §6. Viven en la base de
datos PROPIA de esta instancia: no hay usuarios compartidos.

Las tablas de negocio (Oferta, PartidaOferta) son propias de Cotización.
"""
import uuid
import datetime as dt

from sqlalchemy import (
    Column, String, Boolean, Date, DateTime, Float, ForeignKey, JSON, Integer, Text,
    UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship

from .db import Base

# Roles válidos — mismos nombres que GTEC-006 (Keycloak) del Sistema Atlas,
# para que la migración futura sea directa.
# TECNICO_NOC_SOC: usuarios, monitoreo, actividad (personas) y eventos (recursos).
ROL_TECNICO_NOC_SOC = "TECNICO_NOC_SOC"
ROLES = ("admin", "analista", "tecnico", "auditor", ROL_TECNICO_NOC_SOC)
ROLES_ALIAS = {
    "analist_NOC_SOC": ROL_TECNICO_NOC_SOC,
    "analista_NOC_SOC": ROL_TECNICO_NOC_SOC,
    "tecnico_noc_soc": ROL_TECNICO_NOC_SOC,
}


def normalizar_rol(rol: str | None) -> str | None:
    if rol is None:
        return None
    clave = str(rol).strip()
    return ROLES_ALIAS.get(clave, clave)


def es_rol_noc_soc(rol: str | None) -> bool:
    return normalizar_rol(rol) == ROL_TECNICO_NOC_SOC
ACCESOS_ESCENARIO = ("lectura", "lectura_escritura")
ESTADOS_ESCENARIO = ("activo", "cerrado")


def gen_uuid():
    return str(uuid.uuid4())


def now():
    # Naive UTC deliberadamente: SQLite no conserva el offset de tz en las
    # columnas DateTime, lo que produce comparaciones "naive vs aware" al
    # releer filas. Se estandariza todo el backend en UTC "naive" (se asume
    # UTC siempre, nunca hora local) para que las comparaciones funcionen
    # igual en SQLite (desarrollo) y PostgreSQL (producción).
    return dt.datetime.utcnow()


def as_utc_naive(cuando: dt.datetime | None) -> dt.datetime | None:
    """Postgres timestamptz vuelve aware; now() es naive UTC. Unificar para restar."""
    if cuando is None:
        return None
    if getattr(cuando, "tzinfo", None) is not None:
        return cuando.replace(tzinfo=None)
    return cuando


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(String, primary_key=True, default=gen_uuid)
    usuario = Column(String, unique=True, nullable=False, index=True)
    nombre = Column(String, nullable=False)
    rol = Column(String, nullable=False, default="analista")
    password_hash = Column(String, nullable=False)
    activo = Column(Boolean, nullable=False, default=True)
    # True tras alta o "Restablecer clave": el usuario debe cambiarla
    # antes de 2FA y de obtener una sesión completa.
    debe_cambiar_password = Column(Boolean, nullable=False, default=False)

    # 2FA (TOTP) — obligatorio para admin y analista, según MET-002 GTEC-006.
    totp_secret = Column(String, nullable=True)
    totp_activo = Column(Boolean, nullable=False, default=False)

    # Bloqueo por intentos fallidos (MET-002 GTEC-007, regla de alerta Wazuh).
    intentos_fallidos = Column(Integer, nullable=False, default=0)
    bloqueado_hasta = Column(DateTime(timezone=True), nullable=True)
    ultimo_login = Column(DateTime(timezone=True), nullable=True)

    creado_en = Column(DateTime(timezone=True), default=now)
    creado_por = Column(String, nullable=True)

    # Telegram fase 1: avisos. El chat_id es la identidad; el username es solo
    # etiqueta. Vincular exige una sesión web ya autenticada (código de un uso).
    telegram_chat_id = Column(String, unique=True, nullable=True, index=True)
    telegram_username = Column(String, nullable=True)
    telegram_vinculado_en = Column(DateTime(timezone=True), nullable=True)

    # Correo del usuario (alertas de seguridad a administradores).
    email = Column(String, nullable=True)
    # Hasta 3 IPs públicas desde las que este usuario puede entrar.
    ips_seguras = Column(JSON, nullable=True)

    refresh_tokens = relationship("RefreshToken", back_populates="usuario", cascade="all, delete-orphan")
    escenarios = relationship("UsuarioEscenario", back_populates="usuario", cascade="all, delete-orphan")

    @property
    def requiere_2fa(self):
        return self.rol in ("admin", "analista") or es_rol_noc_soc(self.rol)

    @property
    def telegram_vinculado(self):
        return bool(self.telegram_chat_id)


class RefreshToken(Base):
    """Refresh tokens de sesión — revocables individualmente (logout / rotación)."""
    __tablename__ = "refresh_tokens"

    id = Column(String, primary_key=True, default=gen_uuid)
    usuario_id = Column(String, ForeignKey("usuarios.id"), nullable=False)
    token_hash = Column(String, nullable=False, index=True)
    creado_en = Column(DateTime(timezone=True), default=now)
    expira_en = Column(DateTime(timezone=True), nullable=False)
    revocado = Column(Boolean, nullable=False, default=False)
    ip = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    # Escenario elegido tras el 2FA; se conserva al rotar el refresh.
    escenario_id = Column(String, ForeignKey("escenarios.id"), nullable=True, index=True)

    usuario = relationship("Usuario", back_populates="refresh_tokens")


class BitacoraEvento(Base):
    """
    Bitácora de auditoría, append-only.

    Esquema alineado deliberadamente con el evento JSON que MET-002 GTEC-007
    define para el envío a Wazuh SIEM, de modo que estos mismos registros se
    puedan reenviar sin transformación cuando exista un Wazuh desplegado:
    {timestamp, tenant_id, usuario_id, rol, accion, entidad, entidad_id,
     resultado, ip, sesion_id}. 'detalle' es una extensión propia de este
     backend (resumen del cambio), aditiva y no rompe el esquema base.
    """
    __tablename__ = "bitacora_eventos"

    id = Column(String, primary_key=True, default=gen_uuid)
    timestamp = Column(DateTime(timezone=True), default=now, index=True)
    tenant_id = Column(String, nullable=False, default="sistema-cotizacion")
    usuario_id = Column(String, nullable=True, index=True)
    usuario_nombre = Column(String, nullable=True)
    rol = Column(String, nullable=True)
    accion = Column(String, nullable=False, index=True)
    entidad = Column(String, nullable=True)
    entidad_id = Column(String, nullable=True)
    resultado = Column(String, nullable=False, default="ok")  # ok | error | denegado
    ip = Column(String, nullable=True)
    sesion_id = Column(String, nullable=True)
    detalle = Column(Text, nullable=True)


class Escenario(Base):
    """
    Ciclo de trabajo de la empresa: periodo_contratacion + razón social
    (p. ej. ORIOL CONSULTORES 2025-2026). Agrupa los proyectos del periodo.
    Al vencer se cierra y queda histórico: el administrador decide si sigue
    siendo consultable (solo lectura) o queda fuera del selector.
    """
    __tablename__ = "escenarios"
    __table_args__ = (
        UniqueConstraint("razon_social", "periodo_contratacion", name="uq_escenario_razon_periodo"),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    razon_social = Column(String, nullable=False)
    periodo_contratacion = Column(String, nullable=False)
    fecha_inicio = Column(Date, nullable=True)
    fecha_fin = Column(Date, nullable=True)
    estado = Column(String, nullable=False, default="activo")  # activo | cerrado
    consultable = Column(Boolean, nullable=False, default=True)
    por_defecto = Column(Boolean, nullable=False, default=False)
    creado_en = Column(DateTime(timezone=True), default=now)
    creado_por = Column(String, nullable=True)

    asignaciones = relationship("UsuarioEscenario", back_populates="escenario", cascade="all, delete-orphan")
    # En el Sistema de Cotización el escenario agrupa las ofertas del periodo.
    proyectos = relationship("Oferta", back_populates="escenario")

    @property
    def nombre(self):
        return f"{self.razon_social} {self.periodo_contratacion}".strip()


class UsuarioEscenario(Base):
    """Acceso de un usuario a un escenario: lectura o lectura/escritura."""
    __tablename__ = "usuarios_escenarios"
    __table_args__ = (
        UniqueConstraint("usuario_id", "escenario_id", name="uq_usuario_escenario"),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    usuario_id = Column(String, ForeignKey("usuarios.id"), nullable=False, index=True)
    escenario_id = Column(String, ForeignKey("escenarios.id"), nullable=False, index=True)
    acceso = Column(String, nullable=False, default="lectura")  # lectura | lectura_escritura

    usuario = relationship("Usuario", back_populates="escenarios")
    escenario = relationship("Escenario", back_populates="asignaciones")


class BloqueoIp(Base):
    """Intentos fallidos y bloqueo temporal por dirección IP (anti-fuerza bruta)."""
    __tablename__ = "bloqueos_ip"

    ip = Column(String, primary_key=True)
    intentos_fallidos = Column(Integer, nullable=False, default=0)
    bloqueado_hasta = Column(DateTime(timezone=True), nullable=True)
    actualizado_en = Column(DateTime(timezone=True), default=now)


class AjustesSeguridad(Base):
    """Cupo de sesiones y control GeoIP por país (una sola fila)."""
    __tablename__ = "ajustes_seguridad"

    id = Column(String, primary_key=True, default="default")
    sesiones_limite = Column(Integer, nullable=False, default=130)
    geoip_habilitado = Column(Boolean, nullable=False, default=False)
    # permitir_todos | allowlist | denylist
    geoip_modo = Column(String, nullable=False, default="permitir_todos")
    geoip_paises = Column(JSON, nullable=True)
    geoip_bloquear_si_no_hay_geo = Column(Boolean, nullable=False, default=False)
    ip_whitelist = Column(JSON, nullable=True)
    ip_blacklist = Column(JSON, nullable=True)
    actualizado_en = Column(DateTime(timezone=True), default=now)
    actualizado_por = Column(String, nullable=True)


class CuentaCorreoProyecto(Base):
    """
    Marcador de compatibilidad para seguridad_ops (copiado tal cual de Control
    de Proyecto), que busca una cuenta de correo de proyecto como SMTP de
    respaldo para las alertas. En el Sistema de Cotización no hay buzones por
    proyecto: esta tabla queda siempre vacía y las alertas usan ALERT_SMTP_*.
    """
    __tablename__ = "cuentas_correo_proyecto"

    id = Column(String, primary_key=True, default=gen_uuid)
    activo = Column(Boolean, nullable=False, default=False)


# ---------------------------------------------------------------------------
# Negocio: ofertas (ING-COT-003 §3–§5)
# ---------------------------------------------------------------------------

# Ciclo de vida comercial. "ganada" es el punto de enganche con Control de
# Proyecto (ING-COT-003 §2).
ESTADOS_OFERTA = ("borrador", "enviada", "en_negociacion", "ganada", "perdida", "anulada")
TRANSICIONES_OFERTA = {
    "borrador": ("enviada", "anulada"),
    "enviada": ("en_negociacion", "ganada", "perdida", "anulada"),
    "en_negociacion": ("ganada", "perdida", "anulada"),
    "ganada": (),
    "perdida": (),
    "anulada": (),
}
# ING-COT-003 §4: granularidad configurable por oferta.
MODALIDADES_OFERTA = ("suministro", "ejecucion")
FACTURACIONES_OFERTA = ("resumida", "detallada")
TIPOS_CLIENTE = ("directo", "aliado")


class Oferta(Base):
    __tablename__ = "ofertas"

    id = Column(String, primary_key=True, default=gen_uuid)
    escenario_id = Column(String, ForeignKey("escenarios.id"), nullable=True, index=True)
    # ORI-AAAA-MM-NNN — viaja a Control de Proyecto como referencia cruzada.
    codigo = Column(String, nullable=False, unique=True, index=True)
    titulo = Column(String, nullable=False)
    estado = Column(String, nullable=False, default="borrador")

    cliente_razon_social = Column(String, nullable=False)
    # Control de Proyecto identifica al cliente por RIF (tabla clientes).
    cliente_rif = Column(String, nullable=True)
    cliente_tipo = Column(String, nullable=False, default="directo")
    cliente_contacto = Column(String, nullable=True)

    modalidad = Column(String, nullable=True)     # suministro | ejecucion
    facturacion = Column(String, nullable=True)   # resumida | detallada (solo ejecucion)

    moneda = Column(String, nullable=False, default="USD")
    iva_pct = Column(Integer, nullable=False, default=16)
    semanas_totales = Column(Integer, nullable=True)
    # SBC/sede de Control de Proyecto que debe importar el traspaso
    # (el MASTER no opera obra — PARA_CLAUDE_arquitectura_nucleo_borde.md).
    sede_destino = Column(String, nullable=True)
    notas = Column(Text, nullable=True)

    analista_id = Column(String, ForeignKey("usuarios.id"), nullable=True)
    analista_nombre = Column(String, nullable=True)

    fecha_ganada = Column(DateTime(timezone=True), nullable=True)
    # Referencia cruzada al proyecto creado en Control de Proyecto (§7.7).
    # Se registra a mano tras la importación (no hay red entre instancias).
    proyecto_cp_id = Column(String, nullable=True)
    contrato_cp_numero = Column(String, nullable=True)
    vinculado_en = Column(DateTime(timezone=True), nullable=True)
    vinculado_por = Column(String, nullable=True)
    traspasos_generados = Column(Integer, nullable=False, default=0)

    # Traspaso por el MCP: SBC destino (id de nodo en el MCP) y último estado
    # informado por el buzón (pendiente, entregado, recibido, aceptado,
    # rechazado, error) o "error_envio" si no se pudo publicar.
    mcp_destino_id = Column(String, nullable=True)
    mcp_traspaso_id = Column(String, nullable=True)
    mcp_version = Column(Integer, nullable=True)
    mcp_estado = Column(String, nullable=True)
    mcp_detalle = Column(Text, nullable=True)
    mcp_actualizado_en = Column(DateTime(timezone=True), nullable=True)

    creado_en = Column(DateTime(timezone=True), default=now)
    creado_por = Column(String, nullable=True)
    actualizado_en = Column(DateTime(timezone=True), default=now, onupdate=now)
    actualizado_por = Column(String, nullable=True)

    escenario = relationship("Escenario", back_populates="proyectos")
    partidas = relationship(
        "PartidaOferta", back_populates="oferta", cascade="all, delete-orphan",
        order_by="PartidaOferta.orden",
    )

    @property
    def total_precio(self) -> float:
        return round(sum(p.precio_total for p in self.partidas), 2)


class PartidaOferta(Base):
    """Partida de venta, agrupada por disciplina (→ frente en Control de Proyecto)."""
    __tablename__ = "ofertas_partidas"

    id = Column(String, primary_key=True, default=gen_uuid)
    oferta_id = Column(String, ForeignKey("ofertas.id"), nullable=False, index=True)
    orden = Column(Integer, nullable=False, default=0)
    disciplina = Column(String, nullable=False, default="GENERAL")
    item = Column(String, nullable=False)
    descripcion = Column(Text, nullable=False)
    unidad = Column(String, nullable=False, default="UND")
    cantidad = Column(Float, nullable=False, default=0)
    precio_unitario = Column(Float, nullable=False, default=0)
    # Tiempos de entrega/ejecución (§5.3 del esquemático) → cronograma inicial.
    semana_inicio = Column(Integer, nullable=True)
    duracion_semanas = Column(Integer, nullable=True)

    oferta = relationship("Oferta", back_populates="partidas")

    @property
    def precio_total(self) -> float:
        return round((self.cantidad or 0) * (self.precio_unitario or 0), 2)


# identity/escenario_ops.py (copiado tal cual) consulta "Proyecto" para
# validar visibilidad por escenario y enlazar registros huérfanos. En esta
# instancia la unidad de trabajo del escenario es la oferta.
Proyecto = Oferta
