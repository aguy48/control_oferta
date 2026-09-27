"""Conexión Oferta Ganada → Control de Proyecto por archivo (ING-COT-003)."""


def montar(app):
    from app.conexion_control_proyecto import router
    app.include_router(router.router)
