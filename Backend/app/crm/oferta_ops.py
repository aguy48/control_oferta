"""Lógica de dominio de la oferta. El router valida, audita y serializa."""
from __future__ import annotations

import datetime as dt

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.identity import escenario_ops
from pathlib import Path

from app.kernel.models import (
    AjusteGeneral, AnexoOferta, Documento, InformeTecnico, Oferta, PartidaOferta,
    SeguimientoPaso, Tarea, Usuario, TRANSICIONES_OFERTA, now,
)
from app.kernel.schemas import OfertaCreate, OfertaUpdate, PartidaIn
from app.conexion_control_proyecto.traspaso import TraspasoInvalido, validar_para_traspaso

ROLES_LECTURA = ("admin", "analista", "auditor")
ROLES_ESCRITURA = ("admin", "analista")

# Estados en los que la oferta ya no se edita (el traspaso debe reflejar
# exactamente lo que se ganó).
ESTADOS_CERRADOS = ("ganada", "perdida", "anulada")
# Campos que siguen editables con la oferta ganada: no cambian el contenido
# económico del traspaso. El SBC destino es único de la instancia (Generales).
EDITABLES_CERRADA = {"notas", "cliente_contacto"}


def generar_codigo(db: Session, cuando: dt.datetime | None = None) -> str:
    """ORI-AAAA-MM-NNN, correlativo por mes."""
    cuando = cuando or now()
    prefijo = f"ORI-{cuando:%Y}-{cuando:%m}-"
    codigos = [c for (c,) in db.query(Oferta.codigo).filter(Oferta.codigo.like(prefijo + "%")).all()]
    mayor = 0
    for c in codigos:
        try:
            mayor = max(mayor, int(c.rsplit("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    return f"{prefijo}{mayor + 1:03d}"


def cargar_oferta(db: Session, oferta_id: str, usuario: Usuario, *, escritura: bool = False) -> Oferta:
    o = db.query(Oferta).filter(Oferta.id == oferta_id).first()
    if not o:
        raise HTTPException(404, "Oferta no encontrada")
    try:
        escenario_ops.exigir_proyecto_visible(usuario, o)
    except HTTPException:
        raise HTTPException(404, "Oferta no encontrada")
    if escritura:
        escenario_ops.exigir_escritura(usuario)
    return o


def listar_ofertas(db: Session, usuario: Usuario, estado: str | None = None) -> list[Oferta]:
    esc = escenario_ops.exigir_escenario(usuario)
    q = db.query(Oferta).filter(Oferta.escenario_id == esc.id)
    if estado:
        q = q.filter(Oferta.estado == estado)
    return q.order_by(Oferta.codigo.desc()).all()


def _normalizar_modalidad(o: Oferta) -> None:
    # La facturación solo aplica a ejecución (ING-COT-003 §4).
    if o.modalidad == "suministro":
        o.facturacion = None


def crear_oferta(db: Session, body: OfertaCreate, usuario: Usuario) -> Oferta:
    escenario_ops.exigir_escritura(usuario)
    esc = escenario_ops.exigir_escenario(usuario)
    data = body.model_dump()
    if data.get("margen_pct") is None:
        fila = db.query(AjusteGeneral).filter(AjusteGeneral.id == "default").first()
        data["margen_pct"] = float(fila.margen_pct) if fila and fila.margen_pct is not None else 25
    from app.conexion_control_proyecto import mcp
    dest_id, dest_nom = mcp.destino_instancia(db)
    if dest_id:
        data["mcp_destino_id"] = dest_id
        if dest_nom:
            data["sede_destino"] = dest_nom
    o = Oferta(
        codigo=generar_codigo(db),
        escenario_id=esc.id,
        analista_id=usuario.id,
        analista_nombre=usuario.nombre,
        creado_por=usuario.id,
        actualizado_por=usuario.id,
        **data,
    )
    _normalizar_modalidad(o)
    db.add(o)
    db.flush()
    return o


def actualizar_oferta(o: Oferta, body: OfertaUpdate, usuario: Usuario) -> list[str]:
    cambios = body.model_dump(exclude_unset=True)
    cambios.pop("mcp_destino_id", None)
    cambios.pop("sede_destino", None)
    if o.estado in ESTADOS_CERRADOS:
        bloqueados = set(cambios) - EDITABLES_CERRADA
        if bloqueados:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"La oferta está {o.estado}: solo se pueden cambiar "
                f"{', '.join(sorted(EDITABLES_CERRADA))}.",
            )
    for k, v in cambios.items():
        setattr(o, k, v)
    _normalizar_modalidad(o)
    o.actualizado_por = usuario.id
    return sorted(cambios)


def reemplazar_partidas(db: Session, o: Oferta, partidas: list[PartidaIn], usuario: Usuario) -> None:
    if o.estado in ESTADOS_CERRADOS:
        raise HTTPException(status.HTTP_409_CONFLICT, f"La oferta está {o.estado}: las partidas ya no se editan.")
    o.partidas.clear()
    db.flush()
    for i, p in enumerate(partidas):
        o.partidas.append(PartidaOferta(orden=i, **p.model_dump()))
    o.actualizado_por = usuario.id


def cambiar_estado(o: Oferta, nuevo: str, usuario: Usuario) -> str:
    """Aplica la transición. Devuelve el estado anterior. No hace commit."""
    actual = o.estado
    if nuevo == actual:
        raise HTTPException(status.HTTP_409_CONFLICT, f"La oferta ya está {actual}.")
    if nuevo not in TRANSICIONES_OFERTA.get(actual, ()):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"No se puede pasar de {actual} a {nuevo}.",
        )
    if nuevo == "ganada":
        # Punto de enganche con Control de Proyecto (§2): la oferta debe
        # quedar completa para generar el archivo de traspaso.
        try:
            validar_para_traspaso(o)
        except TraspasoInvalido as e:
            raise HTTPException(422, str(e))
        o.fecha_ganada = now()
    o.estado = nuevo
    o.actualizado_por = usuario.id
    return actual


def eliminar_oferta(db: Session, o: Oferta, usuario: Usuario) -> str:
    """Solo borrador: quita la oferta y sus anexos para poder empezar de nuevo."""
    if o.estado != "borrador":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Solo se puede eliminar un borrador. Esta oferta está {o.estado}.",
        )
    escenario_ops.exigir_escritura(usuario)
    codigo = o.codigo
    anexos = db.query(AnexoOferta).filter(AnexoOferta.oferta_id == o.id).all()
    ids_anexo = [a.id for a in anexos]
    q_inf = db.query(InformeTecnico).filter(InformeTecnico.oferta_id == o.id)
    if ids_anexo:
        q_inf = db.query(InformeTecnico).filter(
            (InformeTecnico.oferta_id == o.id) | (InformeTecnico.anexo_id.in_(ids_anexo))
        )
    for inf in q_inf.all():
        inf.oferta_id = None
        if inf.anexo_id in ids_anexo:
            inf.anexo_id = None
    for a in anexos:
        try:
            Path(a.ruta).unlink(missing_ok=True)
        except OSError:
            pass
        db.delete(a)
    for t in db.query(Tarea).filter(Tarea.oferta_id == o.id).all():
        t.oferta_id = None
    for d in db.query(Documento).filter(Documento.oferta_id == o.id).all():
        d.oferta_id = None
    db.query(SeguimientoPaso).filter(SeguimientoPaso.oferta_id == o.id).delete()
    from app.kernel.models import SerialVenta
    db.query(SerialVenta).filter(SerialVenta.oferta_id == o.id).delete()
    db.delete(o)
    db.flush()
    return codigo
