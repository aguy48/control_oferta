"""
Escenarios de trabajo = catálogo del SBC destino (Generales).

El MCP los recibe en el latido del nodo y los expone en
GET /nodos-sbc/traspasos/destinos[].escenarios. Esta instancia los
espeja en su propia tabla `escenarios` (identity/) para el login y
el tenancy de las ofertas. No se inventan periodos locales cuando
ya hay un SBC elegido.
"""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy.orm import Session

from app.identity import escenario_ops
from app.kernel.models import Escenario, Usuario

logger = logging.getLogger("sistema_cotizacion")


def alta_local_permitida(db: Session) -> bool:
    from app.conexion_control_proyecto import mcp
    dest, _sede = mcp.destino_instancia(db)
    return not dest


def _fecha(valor) -> dt.date | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, dt.date) and not isinstance(valor, dt.datetime):
        return valor
    if isinstance(valor, dt.datetime):
        return valor.date()
    texto = str(valor).strip()[:10]
    try:
        return dt.date.fromisoformat(texto)
    except ValueError:
        return None


def _clave(razon: str, periodo: str) -> tuple[str, str]:
    return (razon or "").strip(), (periodo or "").strip()


def sincronizar(db: Session) -> dict:
    """Copia (upsert) los escenarios del SBC fijado en Generales."""
    from app.conexion_control_proyecto import mcp
    dest_id, sede = mcp.destino_instancia(db)
    if not dest_id:
        return {
            "ok": False, "motivo": "sin_destino", "sede": None,
            "creados": 0, "actualizados": 0, "escenarios": [],
        }
    try:
        destinos = mcp.destinos()
    except mcp.McpError as e:
        return {
            "ok": False, "motivo": str(e), "sede": sede,
            "creados": 0, "actualizados": 0, "escenarios": [],
        }
    nodo = next((d for d in destinos if d.get("id") == dest_id), None)
    if nodo is None:
        return {
            "ok": False, "motivo": "destino_no_listado", "sede": sede,
            "creados": 0, "actualizados": 0, "escenarios": [],
        }
    sede = nodo.get("nombre") or sede
    remotos = [
        r for r in (nodo.get("escenarios") or [])
        if isinstance(r, dict) and _clave(r.get("razon_social"), r.get("periodo_contratacion"))[0]
        and _clave(r.get("razon_social"), r.get("periodo_contratacion"))[1]
    ]
    if not remotos:
        return {
            "ok": True, "motivo": "sbc_sin_escenarios", "sede": sede,
            "creados": 0, "actualizados": 0, "escenarios": [],
        }

    locales = db.query(Escenario).all()
    por_id = {e.id: e for e in locales}
    por_clave = {_clave(e.razon_social, e.periodo_contratacion): e for e in locales}
    usuarios = db.query(Usuario).all()
    creados = 0
    actualizados = 0
    ids_remotos = set()

    for raw in remotos:
        razon, periodo = _clave(raw.get("razon_social"), raw.get("periodo_contratacion"))
        rid = (raw.get("id") or "").strip() or None
        esc = por_clave.get((razon, periodo))
        if esc is None and rid and rid in por_id:
            cand = por_id[rid]
            if _clave(cand.razon_social, cand.periodo_contratacion) == (razon, periodo):
                esc = cand
        if esc is None:
            kwargs = dict(
                razon_social=razon,
                periodo_contratacion=periodo,
                fecha_inicio=_fecha(raw.get("fecha_inicio")),
                fecha_fin=_fecha(raw.get("fecha_fin")),
                estado=(raw.get("estado") or "activo").strip() or "activo",
                consultable=bool(raw.get("consultable", True)),
                por_defecto=False,
            )
            if rid and rid not in por_id:
                kwargs["id"] = rid
            esc = Escenario(**kwargs)
            db.add(esc)
            db.flush()
            for u in usuarios:
                escenario_ops.asignar(db, u.id, esc.id, escenario_ops.acceso_por_rol(u.rol))
            por_id[esc.id] = esc
            por_clave[(razon, periodo)] = esc
            creados += 1
        else:
            esc.razon_social = razon
            esc.periodo_contratacion = periodo
            ini, fin = _fecha(raw.get("fecha_inicio")), _fecha(raw.get("fecha_fin"))
            if ini is not None:
                esc.fecha_inicio = ini
            if fin is not None:
                esc.fecha_fin = fin
            if raw.get("estado") in ("activo", "cerrado"):
                esc.estado = raw["estado"]
            if "consultable" in raw:
                esc.consultable = bool(raw.get("consultable"))
            actualizados += 1
        ids_remotos.add(esc.id)
        if raw.get("por_defecto") is True:
            escenario_ops.marcar_por_defecto(db, esc.id)

    db.commit()
    escenario_ops.asegurar_marcado_por_defecto(db)
    filas = db.query(Escenario).order_by(
        Escenario.periodo_contratacion.desc(), Escenario.razon_social
    ).all()
    return {
        "ok": True,
        "motivo": None,
        "sede": sede,
        "creados": creados,
        "actualizados": actualizados,
        "escenarios": [
            {
                "id": e.id,
                "nombre": escenario_ops.nombre_escenario(e),
                "razon_social": e.razon_social,
                "periodo_contratacion": e.periodo_contratacion,
                "del_sbc": e.id in ids_remotos,
            }
            for e in filas
        ],
    }
