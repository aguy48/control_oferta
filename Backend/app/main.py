"""
Backend del Sistema de Cotización — ORIOL Consultores C.A.

Instancia propia (ING-COT-003 §1 y §6). Reutiliza identity/ de Control de
Proyecto sin cambios, sobre su propia base de datos y su propio SECRET_KEY.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app import identity, crm, conexion_control_proyecto, plataforma
from app.kernel import security
from app.kernel.config import APP_VERSION, settings
from app.kernel.db import Base, SessionLocal, engine
from app.kernel.models import Usuario

logger = logging.getLogger("sistema_cotizacion")


def _inicializar_datos():
    if settings.SECRET_KEY_ES_AUTOGENERADA:
        logger.warning(
            "SECRET_KEY no está definida: se generó una aleatoria y las sesiones "
            "se pierden en cada reinicio. Fíjala en Backend/.env (distinta de la "
            "de Control de Proyecto)."
        )
    Path(settings.STORAGE_DIR).mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _asegurar_columnas()
    db = SessionLocal()
    try:
        if db.query(Usuario).count() == 0:
            if settings.INITIAL_ADMIN_USER and settings.INITIAL_ADMIN_PASSWORD:
                db.add(Usuario(
                    usuario=settings.INITIAL_ADMIN_USER,
                    nombre=settings.INITIAL_ADMIN_NOMBRE,
                    rol="admin",
                    password_hash=security.hash_password(settings.INITIAL_ADMIN_PASSWORD),
                    debe_cambiar_password=True,
                ))
                db.commit()
                logger.info("Usuario administrador inicial creado: %s", settings.INITIAL_ADMIN_USER)
            else:
                logger.info(
                    "No hay usuarios y no se definieron INITIAL_ADMIN_USER / "
                    "INITIAL_ADMIN_PASSWORD: arrancando sin administrador."
                )
        from app.identity import escenario_ops
        escenario_ops.sembrar_inicial(db)
        escenario_ops.asegurar_marcado_por_defecto(db)
    finally:
        db.close()


def _asegurar_columnas():
    """create_all no agrega columnas a tablas existentes."""
    tablas = inspect(engine).get_table_names()

    def agregar(tabla: str, nuevas: dict[str, str]) -> None:
        if tabla not in tablas:
            return
        existentes = {c["name"] for c in inspect(engine).get_columns(tabla)}
        with engine.begin() as con:
            for col, tipo in nuevas.items():
                if col not in existentes:
                    con.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {col} {tipo}"))
                    logger.info("Columna %s.%s agregada.", tabla, col)

    agregar("ofertas", {
        "mcp_destino_id": "VARCHAR", "mcp_traspaso_id": "VARCHAR", "mcp_version": "INTEGER",
        "mcp_estado": "VARCHAR", "mcp_detalle": "TEXT", "mcp_actualizado_en": "TIMESTAMP",
        "margen_pct": "FLOAT DEFAULT 25", "origen": "VARCHAR DEFAULT 'comercial'",
    })
    agregar("ofertas_partidas", {
        "producto_id": "VARCHAR",
    })
    agregar("usuarios", {
        "telegram_chat_id": "VARCHAR",
        "telegram_username": "VARCHAR",
        "telegram_vinculado_en": "TIMESTAMP",
    })
    agregar("ajustes_generales", {
        "margen_pct": "FLOAT DEFAULT 25",
        "gemini_api_key_enc": "TEXT",
        "gemini_model": "VARCHAR",
        "mcp_url": "VARCHAR",
        "mcp_token_enc": "TEXT",
        "mcp_destino_id": "VARCHAR",
        "mcp_sede_nombre": "VARCHAR",
        "telegram_bot_token_enc": "TEXT",
        "telegram_bot_username": "VARCHAR",
        "telegram_mode": "VARCHAR",
        "telegram_webhook_secret_enc": "TEXT",
        "telegram_poll_seconds": "INTEGER",
        "telegram_emparejar_ttl_min": "INTEGER",
        "onlyoffice_url": "VARCHAR",
        "onlyoffice_jwt_secret_enc": "TEXT",
        "onlyoffice_app_url": "VARCHAR",
    })


async def _ciclo_mcp():
    """Latido al MCP y lectura de acuses cada MCP_POLL_SECONDS."""
    from app.conexion_control_proyecto import mcp
    while True:
        await asyncio.to_thread(mcp.ciclo_periodico, SessionLocal)
        await asyncio.sleep(max(15, settings.MCP_POLL_SECONDS))


async def _ciclo_telegram():
    from app.plataforma import telegram_ops
    while True:
        await asyncio.to_thread(telegram_ops.ciclo_periodico, SessionLocal)
        await asyncio.sleep(max(2, telegram_ops.poll_seconds_activo()))


@asynccontextmanager
async def lifespan(app: FastAPI):
    _inicializar_datos()
    from app.conexion_control_proyecto import mcp
    from app.plataforma import telegram_ops
    telegram_ops.recargar_desde_db()
    tarea_mcp = asyncio.create_task(_ciclo_mcp())
    tarea_tg = asyncio.create_task(_ciclo_telegram())
    if mcp.activo():
        url, _tok, fuente = mcp.credenciales()
        logger.info("Traspaso por MCP activo (%s): %s", fuente, url)
    else:
        logger.info("MCP no configurado: el administrador lo fija en Generales.")
    if telegram_ops.bot_configurado():
        logger.info("Telegram activo (%s) @%s", telegram_ops.modo_activo(),
                    telegram_ops.username_activo() or "—")
    else:
        logger.info("Telegram no configurado: el administrador lo fija en Generales.")
    logger.info("Backend del Sistema de Cotización iniciado.")
    yield
    tarea_mcp.cancel()
    tarea_tg.cancel()


app = FastAPI(
    title="Sistema de Cotización — API",
    description="Ofertas comerciales de ORIOL Consultores C.A. y traspaso de ofertas "
                "ganadas a Control de Proyecto (ING-COT-003, MET-002).",
    version=APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

identity.montar(app)
crm.montar(app)
plataforma.montar(app)
conexion_control_proyecto.montar(app)


@app.get("/health")
def health():
    from app.conexion_control_proyecto import mcp
    return {"status": "ok", "version": APP_VERSION, "modo": settings.modo_app(),
            "organizacion": settings.ORGANIZACION, "mcp": mcp.activo()}
