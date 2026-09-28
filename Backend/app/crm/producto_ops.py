"""Catálogo de productos/servicios, historial de cotización y seriales de venta."""
from __future__ import annotations

import math
import re

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.crm import acceso
from app.kernel.models import (
    Oferta, PartidaOferta, ProductoServicio, SerialVenta, Usuario, now,
)

CAMPOS = (
    "tipo", "codigo", "nombre", "descripcion", "unidad", "disciplina",
    "precio_ref", "requiere_serial", "garantia_semanas", "tiempo_entrega_semanas",
    "activo",
)


def n_seriales(cantidad: float) -> int:
    if (cantidad or 0) <= 0:
        return 0
    return max(1, int(math.ceil(float(cantidad))))


def _n_cotizaciones(db: Session, producto_id: str, escenario_id: str | None) -> int:
    q = (
        db.query(func.count(PartidaOferta.id))
        .join(Oferta, Oferta.id == PartidaOferta.oferta_id)
        .filter(PartidaOferta.producto_id == producto_id, Oferta.estado != "anulada")
    )
    if escenario_id:
        q = q.filter(Oferta.escenario_id == escenario_id)
    return int(q.scalar() or 0)


def _out(db: Session, p: ProductoServicio):
    from app.kernel.schemas import ProductoOut
    return ProductoOut(
        id=p.id, tipo=p.tipo, codigo=p.codigo, nombre=p.nombre,
        descripcion=p.descripcion, unidad=p.unidad, disciplina=p.disciplina,
        precio_ref=p.precio_ref, requiere_serial=bool(p.requiere_serial),
        garantia_semanas=p.garantia_semanas,
        tiempo_entrega_semanas=p.tiempo_entrega_semanas, activo=p.activo,
        n_cotizaciones=_n_cotizaciones(db, p.id, p.escenario_id),
        creado_en=p.creado_en,
    )


def cargar(db: Session, producto_id: str, usuario: Usuario) -> ProductoServicio:
    esc = acceso.escenario(usuario)
    p = db.query(ProductoServicio).filter(
        ProductoServicio.id == producto_id, ProductoServicio.escenario_id == esc.id,
    ).first()
    return acceso.o_404(p, "Producto o servicio no encontrado")


def generar_codigo(db: Session, escenario_id: str, tipo: str) -> str:
    pref = "SRV-" if tipo == "servicio" else "PRD-"
    codigos = [
        c for (c,) in db.query(ProductoServicio.codigo).filter(
            ProductoServicio.escenario_id == escenario_id,
            ProductoServicio.codigo.like(pref + "%"),
        ).all()
    ]
    mayor = 0
    for c in codigos:
        m = re.search(r"(\d+)$", c or "")
        if m:
            mayor = max(mayor, int(m.group(1)))
    return f"{pref}{mayor + 1:03d}"


def listar(db: Session, usuario: Usuario, q: str | None = None,
           tipo: str | None = None, activos: bool = True) -> list:
    esc = acceso.escenario(usuario)
    qry = db.query(ProductoServicio).filter(ProductoServicio.escenario_id == esc.id)
    if activos:
        qry = qry.filter(ProductoServicio.activo.is_(True))
    if tipo in ("producto", "servicio"):
        qry = qry.filter(ProductoServicio.tipo == tipo)
    if q:
        like = f"%{q.strip()}%"
        qry = qry.filter(
            (ProductoServicio.nombre.ilike(like))
            | (ProductoServicio.codigo.ilike(like))
            | (ProductoServicio.descripcion.ilike(like))
        )
    filas = qry.order_by(ProductoServicio.nombre).limit(80).all()
    return [_out(db, p) for p in filas]


def crear(db: Session, body, usuario: Usuario):
    acceso.escritura(usuario)
    esc = acceso.escenario(usuario)
    data = body.model_dump()
    codigo = (data.get("codigo") or "").strip().upper() or generar_codigo(db, esc.id, data.get("tipo") or "producto")
    data["codigo"] = codigo
    if db.query(ProductoServicio).filter(
        ProductoServicio.escenario_id == esc.id, ProductoServicio.codigo == codigo,
    ).first():
        raise HTTPException(409, f"Ya existe un ítem con código {codigo}.")
    if data.get("tipo") == "servicio":
        data["requiere_serial"] = bool(data.get("requiere_serial"))
    p = ProductoServicio(escenario_id=esc.id, creado_por=usuario.id, **data)
    db.add(p)
    db.flush()
    return _out(db, p)


def actualizar(db: Session, p: ProductoServicio, body) -> list[str]:
    if body.codigo:
        codigo = body.codigo.strip().upper()
        otro = db.query(ProductoServicio).filter(
            ProductoServicio.escenario_id == p.escenario_id,
            ProductoServicio.codigo == codigo,
            ProductoServicio.id != p.id,
        ).first()
        if otro:
            raise HTTPException(409, f"Ya existe un ítem con código {codigo}.")
        body.codigo = codigo
    cambios = acceso.aplicar(p, body, CAMPOS)
    p.actualizado_en = now()
    return cambios


def cotizaciones(db: Session, p: ProductoServicio) -> list[dict]:
    filas = (
        db.query(PartidaOferta, Oferta)
        .join(Oferta, Oferta.id == PartidaOferta.oferta_id)
        .filter(PartidaOferta.producto_id == p.id, Oferta.escenario_id == p.escenario_id)
        .order_by(Oferta.creado_en.desc())
        .all()
    )
    out = []
    for partida, oferta in filas:
        out.append({
            "oferta_id": oferta.id,
            "codigo": oferta.codigo,
            "cliente": oferta.cliente_razon_social,
            "fecha": oferta.creado_en,
            "estado": oferta.estado,
            "cantidad": partida.cantidad,
            "precio_unitario": partida.precio_unitario,
            "monto": partida.precio_total,
            "moneda": oferta.moneda,
        })
    return out


def top_cotizados(db: Session, usuario: Usuario, limite: int = 10) -> list[dict]:
    esc = acceso.escenario(usuario)
    filas = (
        db.query(
            ProductoServicio.id,
            ProductoServicio.tipo,
            ProductoServicio.codigo,
            ProductoServicio.nombre,
            func.count(PartidaOferta.id).label("n"),
            func.coalesce(func.sum(PartidaOferta.cantidad), 0).label("cant"),
            func.coalesce(func.sum(PartidaOferta.cantidad * PartidaOferta.precio_unitario), 0).label("monto"),
        )
        .join(PartidaOferta, PartidaOferta.producto_id == ProductoServicio.id)
        .join(Oferta, Oferta.id == PartidaOferta.oferta_id)
        .filter(
            ProductoServicio.escenario_id == esc.id,
            Oferta.escenario_id == esc.id,
            Oferta.estado != "anulada",
        )
        .group_by(
            ProductoServicio.id, ProductoServicio.tipo,
            ProductoServicio.codigo, ProductoServicio.nombre,
        )
        .order_by(func.count(PartidaOferta.id).desc(), func.sum(PartidaOferta.cantidad).desc())
        .limit(max(1, min(limite, 20)))
        .all()
    )
    return [
        {
            "id": pid, "tipo": tipo, "codigo": codigo, "nombre": nombre,
            "n_cotizaciones": int(n), "cantidad": float(cant), "monto": round(float(monto), 2),
        }
        for pid, tipo, codigo, nombre, n, cant, monto in filas
    ]


def seriales_requeridos(db: Session, o: Oferta) -> list[dict]:
    partidas = (
        db.query(PartidaOferta)
        .options(joinedload(PartidaOferta.producto))
        .filter(PartidaOferta.oferta_id == o.id)
        .order_by(PartidaOferta.orden)
        .all()
    )
    out = []
    for p in partidas:
        prod = p.producto
        if not prod or not prod.requiere_serial:
            continue
        n = n_seriales(p.cantidad)
        ya = [
            s.serial for s in db.query(SerialVenta).filter(SerialVenta.partida_id == p.id).all()
        ]
        out.append({
            "partida_id": p.id,
            "producto_id": prod.id,
            "item": p.item,
            "descripcion": p.descripcion,
            "cantidad": p.cantidad,
            "n_seriales": n,
            "garantia_semanas": prod.garantia_semanas,
            "seriales": ya,
        })
    return out


def registrar_seriales(db: Session, o: Oferta, seriales: list, usuario: Usuario) -> None:
    pendientes = {r["partida_id"]: r for r in seriales_requeridos(db, o)}
    if not pendientes:
        return
    por_partida: dict[str, list[str]] = {}
    for s in seriales or []:
        pid = s.partida_id if hasattr(s, "partida_id") else s.get("partida_id")
        val = (s.serial if hasattr(s, "serial") else s.get("serial") or "").strip().upper()
        if not pid or not val:
            continue
        por_partida.setdefault(pid, []).append(val)
    faltan = []
    vistos = set()
    for pid, req in pendientes.items():
        vals = por_partida.get(pid) or list(req.get("seriales") or [])
        if len(vals) != req["n_seriales"]:
            faltan.append(f"{req['descripcion']} ({req['n_seriales']} seriales)")
            continue
        if len(set(vals)) != len(vals):
            raise HTTPException(409, f"Hay seriales repetidos en «{req['descripcion']}».")
        for ser in vals:
            clave = (pid, ser)
            if clave in vistos:
                raise HTTPException(409, f"Serial duplicado: {ser}")
            vistos.add(clave)
    if faltan:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "codigo": "seriales_requeridos",
                "mensaje": "Al ganar la venta hay que capturar el serial de cada unidad.",
                "partidas": list(pendientes.values()),
                "faltan": faltan,
            },
        )
    db.query(SerialVenta).filter(SerialVenta.oferta_id == o.id).delete()
    for pid, req in pendientes.items():
        vals = por_partida.get(pid) or []
        for ser in vals:
            db.add(SerialVenta(
                oferta_id=o.id, partida_id=pid, producto_id=req["producto_id"],
                serial=ser, creado_por=usuario.id,
            ))
    db.flush()
