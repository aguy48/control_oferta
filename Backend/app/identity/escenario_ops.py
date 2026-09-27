"""
Escenarios de trabajo: periodo_contratacion + razón social
(p. ej. ORIOL CONSULTORES 2025-2026).

El administrador cierra un ciclo vencido; si lo deja consultable queda
histórico de solo lectura. La sesión elige un escenario tras autenticarse
(después del 2FA si aplica).
"""
from __future__ import annotations

import datetime as dt
import re

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.kernel.models import (
    ACCESOS_ESCENARIO, Escenario, Proyecto, Usuario, UsuarioEscenario,
    es_rol_noc_soc,
)


def nombre_escenario(esc: Escenario) -> str:
    return f"{(esc.razon_social or '').strip()} {(esc.periodo_contratacion or '').strip()}".strip()


def validar_fechas(
    fecha_inicio: dt.date | None,
    fecha_fin: dt.date | None,
    *,
    inicio_min: dt.date | None = None,
    fin_min: dt.date | None = None,
) -> None:
    """Inicio y cierre obligatorios; el cierre es posterior al inicio.
    Al editar no se aceptan fechas anteriores a las ya registradas."""
    if fecha_inicio is None or fecha_fin is None:
        raise HTTPException(
            400,
            "La fecha de inicio y la fecha de cierre son obligatorias.",
        )
    if fecha_fin <= fecha_inicio:
        raise HTTPException(
            400,
            "La fecha de cierre debe ser posterior a la fecha de inicio.",
        )
    if inicio_min is not None and fecha_inicio < inicio_min:
        raise HTTPException(
            400,
            "La fecha de inicio no puede ser anterior a la ya registrada.",
        )
    if fin_min is not None and fecha_fin < fin_min:
        raise HTTPException(
            400,
            "La fecha de cierre no puede ser anterior a la ya registrada.",
        )


def acceso_por_rol(rol: str) -> str:
    if rol == "auditor" or es_rol_noc_soc(rol):
        return "lectura"
    return "lectura_escritura"


def serializar(esc: Escenario, acceso: str) -> dict:
    efectivo = acceso_efectivo(esc, acceso)
    return {
        "id": esc.id,
        "nombre": nombre_escenario(esc),
        "razon_social": esc.razon_social,
        "periodo_contratacion": esc.periodo_contratacion,
        "fecha_inicio": esc.fecha_inicio,
        "fecha_fin": esc.fecha_fin,
        "estado": esc.estado,
        "consultable": bool(esc.consultable),
        "por_defecto": bool(getattr(esc, "por_defecto", False)),
        "acceso": efectivo,
        "solo_lectura": efectivo == "lectura" or esc.estado != "activo",
    }


def acceso_asignado(db: Session, usuario: Usuario, escenario_id: str) -> str | None:
    """Solo cuenta la asignación explícita. El administrador no entra a un
    escenario que no le hayan asignado (el CRUD /escenarios sigue listando todos)."""
    fila = db.query(UsuarioEscenario).filter(
        UsuarioEscenario.usuario_id == usuario.id,
        UsuarioEscenario.escenario_id == escenario_id,
    ).first()
    return fila.acceso if fila else None


def acceso_efectivo(esc: Escenario, acceso: str) -> str:
    if esc.estado != "activo":
        return "lectura"
    return acceso if acceso in ACCESOS_ESCENARIO else "lectura"


def visible_en_selector(esc: Escenario, usuario: Usuario) -> bool:
    if usuario.rol == "admin":
        return True
    if esc.estado == "activo":
        return True
    return bool(esc.consultable)


def disponibles(db: Session, usuario: Usuario) -> list[tuple[Escenario, str]]:
    """Tras autenticarse, cada usuario solo ve los escenarios que tiene asignados."""
    out: list[tuple[Escenario, str]] = []
    asig = (
        db.query(UsuarioEscenario)
        .filter(UsuarioEscenario.usuario_id == usuario.id)
        .all()
    )
    for a in asig:
        esc = a.escenario
        if esc is None or not visible_en_selector(esc, usuario):
            continue
        out.append((esc, a.acceso))
    out.sort(key=lambda t: (t[0].periodo_contratacion or "", t[0].razon_social or ""), reverse=True)
    return out


def puede_elegir(db: Session, usuario: Usuario, escenario_id: str) -> tuple[Escenario, str]:
    esc = db.query(Escenario).filter(Escenario.id == escenario_id).first()
    if not esc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Escenario no encontrado")
    acceso = acceso_asignado(db, usuario, escenario_id)
    if acceso is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "No tienes acceso a ese periodo de contratación. Pide al administrador que te lo asigne.",
        )
    if not visible_en_selector(esc, usuario):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Ese escenario está cerrado y el administrador no lo dejó consultable.",
        )
    return esc, acceso


def hidratar_sesion(db: Session, usuario: Usuario, escenario_id: str | None) -> None:
    usuario._escenario_id = None
    usuario._escenario_acceso = None
    usuario._escenario = None
    if not escenario_id:
        return
    try:
        esc, acceso = puede_elegir(db, usuario, escenario_id)
    except HTTPException:
        return
    usuario._escenario_id = esc.id
    usuario._escenario = esc
    usuario._escenario_acceso = acceso_efectivo(esc, acceso)


def exigir_escenario(usuario: Usuario) -> Escenario:
    esc = getattr(usuario, "_escenario", None)
    if esc is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Selecciona un escenario (periodo de contratación) para continuar.",
        )
    return esc


def exigir_escritura(usuario: Usuario) -> Escenario:
    esc = exigir_escenario(usuario)
    if esc.estado != "activo":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Este escenario está cerrado. Queda como histórico: solo consulta, "
            "salvo que el administrador lo reabra.",
        )
    if getattr(usuario, "_escenario_acceso", None) != "lectura_escritura":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Tu acceso a este escenario es de solo lectura.",
        )
    return esc


def exigir_proyecto_visible(usuario: Usuario, proyecto: Proyecto) -> None:
    esc = exigir_escenario(usuario)
    if proyecto.escenario_id and proyecto.escenario_id != esc.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proyecto no encontrado")
    if proyecto.escenario_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proyecto no encontrado")


def asignar(db: Session, usuario_id: str, escenario_id: str, acceso: str) -> None:
    if acceso not in ACCESOS_ESCENARIO:
        raise HTTPException(400, "acceso debe ser 'lectura' o 'lectura_escritura'")
    fila = db.query(UsuarioEscenario).filter(
        UsuarioEscenario.usuario_id == usuario_id,
        UsuarioEscenario.escenario_id == escenario_id,
    ).first()
    if fila:
        fila.acceso = acceso
    else:
        db.add(UsuarioEscenario(
            usuario_id=usuario_id, escenario_id=escenario_id, acceso=acceso,
        ))


def _escenario_tecnico_noc(db: Session) -> Escenario | None:
    """Escenario de trabajo del perfil NOC/SOC (razón social técnica), si existe."""
    filas = (
        db.query(Escenario)
        .filter(Escenario.estado == "activo")
        .order_by(Escenario.creado_en)
        .all()
    )
    for e in filas:
        clave = f"{e.razon_social or ''} {e.periodo_contratacion or ''}".upper()
        if "TECNICO_NOC_SOC" in clave or "NOC_SOC" in clave or "NOC/SOC" in clave:
            return e
    return None


def asignar_por_defecto(db: Session, usuario: Usuario) -> None:
    if db.query(UsuarioEscenario).filter(UsuarioEscenario.usuario_id == usuario.id).first():
        return
    if es_rol_noc_soc(usuario.rol):
        cand = _escenario_tecnico_noc(db)
        if cand is None:
            activos = db.query(Escenario).filter(Escenario.estado == "activo").all()
            if len(activos) == 1:
                cand = activos[0]
        if cand:
            asignar(db, usuario.id, cand.id, acceso_por_rol(usuario.rol))
            db.commit()
        return
    activos = db.query(Escenario).filter(Escenario.estado == "activo").all()
    if not activos:
        return
    # Admin sin asignación no puede elegir escenario (el selector queda vacío).
    if usuario.rol == "admin" or len(activos) == 1:
        for esc in activos:
            asignar(db, usuario.id, esc.id, acceso_por_rol(usuario.rol))
        db.commit()
        return


def preferido_noc(disponibles_serial: list[dict]) -> dict | None:
    """El técnico NOC/SOC no elige: entra al escenario técnico, o al único/primero."""
    if not disponibles_serial:
        return None
    for e in disponibles_serial:
        clave = f"{e.get('razon_social') or ''} {e.get('nombre') or ''}".upper()
        if "TECNICO_NOC_SOC" in clave or "NOC_SOC" in clave or "NOC/SOC" in clave:
            return e
    return disponibles_serial[0]


def preferido_sesion(disponibles_serial: list[dict]) -> dict | None:
    """Escenario de entrada: el marcado por defecto, ORIOL 2025-2026 o el primero activo."""
    if not disponibles_serial:
        return None
    marked = [e for e in disponibles_serial if e.get("por_defecto")]
    if marked:
        activos = [e for e in marked if e.get("estado") == "activo"]
        return activos[0] if activos else marked[0]
    for e in disponibles_serial:
        nom = f"{e.get('nombre') or ''} {e.get('razon_social') or ''} {e.get('periodo_contratacion') or ''}"
        if re.search(r"ORIOL CONSULTORES\s*2025-2026", nom, re.I):
            return e
    for e in disponibles_serial:
        nom = f"{e.get('nombre') or ''} {e.get('razon_social') or ''}"
        if re.search(r"ORIOL CONSULTORES", nom, re.I) and e.get("estado") == "activo":
            return e
    activos = [e for e in disponibles_serial if e.get("estado") == "activo"]
    return activos[0] if activos else disponibles_serial[0]


def marcar_por_defecto(db: Session, escenario_id: str) -> Escenario:
    esc = db.query(Escenario).filter(Escenario.id == escenario_id).first()
    if not esc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Escenario no encontrado")
    db.query(Escenario).filter(Escenario.id != esc.id).update({"por_defecto": False})
    esc.por_defecto = True
    return esc


def asegurar_marcado_por_defecto(db: Session) -> Escenario | None:
    """Si nadie está marcado, deja por defecto ORIOL CONSULTORES 2025-2026 o el activo más reciente."""
    if db.query(Escenario).filter(Escenario.por_defecto.is_(True)).first():
        return None
    filas = db.query(Escenario).order_by(Escenario.creado_en).all()
    if not filas:
        return None
    cand = None
    for e in filas:
        if e.estado == "activo" and re.search(
            r"ORIOL CONSULTORES", f"{e.razon_social or ''} {e.periodo_contratacion or ''}", re.I
        ) and "2025-2026" in (e.periodo_contratacion or ""):
            cand = e
            break
    if cand is None:
        for e in filas:
            if e.estado == "activo" and re.search(r"ORIOL CONSULTORES", e.razon_social or "", re.I):
                cand = e
                break
    if cand is None:
        cand = next((e for e in filas if e.estado == "activo"), filas[0])
    cand.por_defecto = True
    db.commit()
    return cand


def sembrar_inicial(db: Session) -> Escenario | None:
    """Crea ORIOL CONSULTORES 2025-2026 si no hay escenarios y enlaza lo existente."""
    if db.query(Escenario).count() > 0:
        e = db.query(Escenario).filter(Escenario.estado == "activo").order_by(
            Escenario.creado_en
        ).first()
        if e:
            for p in db.query(Proyecto).filter(Proyecto.escenario_id.is_(None)).all():
                p.escenario_id = e.id
            db.commit()
        return e
    e = Escenario(
        razon_social="ORIOL CONSULTORES",
        periodo_contratacion="2025-2026",
        fecha_inicio=dt.date(2025, 1, 1),
        fecha_fin=dt.date(2026, 12, 31),
        estado="activo",
        consultable=True,
        por_defecto=True,
    )
    db.add(e)
    db.flush()
    for u in db.query(Usuario).all():
        asignar(db, u.id, e.id, acceso_por_rol(u.rol))
    for p in db.query(Proyecto).filter(Proyecto.escenario_id.is_(None)).all():
        p.escenario_id = e.id
    db.commit()
    return e
