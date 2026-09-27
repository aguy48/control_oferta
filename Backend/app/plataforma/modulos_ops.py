"""
ADAPTADOR (Sistema de Cotización).

En Control de Proyecto este módulo aplica la política de acceso que el
MASTER SOC/NOC fija sobre cada SBC. El Sistema de Cotización es una
instancia propia fuera de esa red (ING-COT-003 §6): settings.es_sbc() es
siempre falso y kernel/deps.py nunca llega a llamarlo. Se deja la misma
interfaz, permisiva, por si se copia una versión futura de deps.py.
"""


def usuario_permitido(usuario: str) -> bool:
    return True


def aplicacion_permitida() -> bool:
    return True
