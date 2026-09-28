"""Plataforma: seguridad, generales, asistente y Telegram."""


def montar(app):
    from app.plataforma.routers import (
        auditoria, generales, asistente, telegram, onlyoffice, eventos, respaldos,
    )
    app.include_router(auditoria.router)
    app.include_router(eventos.router)
    app.include_router(respaldos.router)
    app.include_router(generales.router)
    app.include_router(asistente.router)
    app.include_router(telegram.router)
    app.include_router(onlyoffice.router)
