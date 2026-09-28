"""Filtro de escenario y roles de las fichas operativas."""
from fastapi import HTTPException

from app.crm.oferta_ops import ROLES_ESCRITURA, ROLES_LECTURA
from app.identity import escenario_ops
from app.kernel.models import _rif_norm

__all__ = ["ROLES_LECTURA", "ROLES_ESCRITURA", "escenario", "escritura", "rif_norm", "_rif_norm"]


def escenario(usuario):
    return escenario_ops.exigir_escenario(usuario)


def escritura(usuario):
    escenario_ops.exigir_escritura(usuario)


def rif_norm(valor: str | None) -> str | None:
    return _rif_norm(valor)


def aplicar(obj, body, campos: tuple[str, ...]) -> list[str]:
    cambios = []
    data = body.model_dump(exclude_unset=True)
    for campo in campos:
        if campo not in data:
            continue
        valor = data[campo]
        if getattr(obj, campo) != valor:
            setattr(obj, campo, valor)
            cambios.append(campo)
    return cambios


def o_404(obj, mensaje: str):
    if not obj:
        raise HTTPException(404, mensaje)
    return obj
