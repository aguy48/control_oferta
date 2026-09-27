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

from app import identity, crm, conexion_control_proyecto
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
    """create_all no agrega columnas a tablas existentes: se añaden aquí las
    columnas nuevas de ofertas (traspaso por MCP) en bases ya creadas."""
    nuevas = {
        "mcp_destino_id": "VARCHAR", "mcp_traspaso_id": "VARCHAR", "mcp_version": "INTEGER",
        "mcp_estado": "VARCHAR", "mcp_detalle": "TEXT", "mcp_actualizado_en": "TIMESTAMP",
    }
    existentes = {c["name"] for c in inspect(engine).get_columns("ofertas")}
    with engine.begin() as con:
        for col, tipo in nuevas.items():
            if col not in existentes:
                con.execute(text(f"ALTER TABLE ofertas ADD COLUMN {col} {tipo}"))
                logger.info("Columna ofertas.%s agregada.", col)


async def _ciclo_mcp():
    """Latido al MCP y lectura de acuses cada MCP_POLL_SECONDS."""
    from app.conexion_control_proyecto import mcp
    while True:
        await asyncio.to_thread(mcp.ciclo_periodico, SessionLocal)
        await asyncio.sleep(max(15, settings.MCP_POLL_SECONDS))


@asynccontextmanager
async def lifespan(app: FastAPI):
    _inicializar_datos()
    tarea = None
    if settings.mcp_configurado():
        tarea = asyncio.create_task(_ciclo_mcp())
        logger.info("Traspaso por MCP activo: %s", settings.MCP_URL)
    else:
        logger.info("MCP no configurado: el traspaso queda por descarga manual.")
    logger.info("Backend del Sistema de Cotización iniciado.")
    yield
    if tarea:
        tarea.cancel()


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
conexion_control_proyecto.montar(app)


@app.get("/health")
def health():
    return {"status": "ok", "version": APP_VERSION, "modo": settings.modo_app(),
            "organizacion": settings.ORGANIZACION, "mcp": settings.mcp_configurado()}
