"""Identidad: login, 2FA, usuarios, escenarios de trabajo."""


def montar(app):
    from app.identity.routers import auth, usuarios, escenarios
    app.include_router(auth.router)
    app.include_router(usuarios.router)
    app.include_router(escenarios.router)
