"""CRM: ofertas y fichas operativas (clientes, contactos, ciclo)."""


def montar(app):
    from app.crm.routers import (
        analisis, anexos, clientes, contactos, documentos, informes, ofertas, panel,
        productos, proveedores, reportes, seguimiento, tareas,
    )
    app.include_router(panel.router)
    app.include_router(ofertas.router)
    app.include_router(anexos.router)
    app.include_router(analisis.router)
    app.include_router(informes.router)
    app.include_router(reportes.router)
    app.include_router(clientes.router)
    app.include_router(productos.router)
    app.include_router(proveedores.router)
    app.include_router(contactos.router)
    app.include_router(tareas.router)
    app.include_router(documentos.router)
    app.include_router(seguimiento.router)
