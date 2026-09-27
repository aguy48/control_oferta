"""CRM: ofertas y su ciclo comercial (borrador → … → ganada)."""


def montar(app):
    from app.crm.routers import ofertas
    app.include_router(ofertas.router)
