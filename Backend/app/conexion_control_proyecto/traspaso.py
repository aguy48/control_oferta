"""
Archivo de traspaso Oferta Ganada → Control de Proyecto (ING-COT-003 §5,
formato FOR-COT-002).

El archivo ES un "respaldo de oferta" RESPALDO_OFERTA_CONTROL_PROYECTO_V1,
el mismo que Control de Proyecto ya importa desde el formulario de Contrato
(js/control_de_proyecto_app.js: leerDatosOfertaDesdeArchivo /
aplicarOfertaAContrato) y guarda en proyecto.master. Así la versión actual de
Control de Proyecto lo lee sin cambios. Lo propio del Sistema de Cotización
viaja en el bloque adicional "origen", que Control de Proyecto ignora hasta
que se le enseñe a leerlo.

En Control de Proyecto la valuación se desagrega por FRENTE (valuaciones[]
.frente_label, cuya lista sale de master.frentes[]). Por eso la granularidad
de la oferta (§4) se traduce en cuántos frentes lleva el archivo:

  ejecucion + detallada → un frente por disciplina
  ejecucion + resumida  → un único frente "GLOBAL"
  suministro            → un único frente "SUMINISTRO"
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json

from app.kernel.models import Oferta, PartidaOferta

FORMATO = "RESPALDO_OFERTA_CONTROL_PROYECTO_V1"
FORMATO_ORIGEN = "FOR-COT-002"
VERSION_ORIGEN = 1
SISTEMA_ORIGEN = "sistema_cotizacion_oriol"

FRENTE_RESUMIDO = "GLOBAL"
FRENTE_SUMINISTRO = "SUMINISTRO"

# Tipo de orden que el formulario de Contrato de Control de Proyecto ofrece.
TIPO_ORDEN_SUGERIDO = {"suministro": "orden_compra", "ejecucion": "contrato_obra"}


class TraspasoInvalido(ValueError):
    """La oferta no cumple lo necesario para generar el traspaso."""


def _r2(x: float) -> float:
    return round(float(x or 0), 2)


def _etiqueta_disciplina(p: PartidaOferta) -> str:
    return (p.disciplina or "GENERAL").strip().upper()


def validar_para_traspaso(oferta: Oferta) -> None:
    """Reglas mínimas para que Control de Proyecto pueda armar el contrato.

    Se aplican al pasar la oferta a "ganada" y otra vez al generar el
    archivo, por si la oferta se modificó por fuera de la API.
    """
    errores = []
    if oferta.modalidad not in TIPO_ORDEN_SUGERIDO:
        errores.append("Falta la modalidad (suministro o ejecucion).")
    if oferta.modalidad == "ejecucion" and oferta.facturacion not in ("resumida", "detallada"):
        errores.append("Una oferta de ejecución necesita la facturación (resumida o detallada).")
    if not (oferta.cliente_rif or "").strip():
        errores.append("Falta el RIF del cliente: Control de Proyecto identifica al cliente por RIF.")
    if not oferta.partidas:
        errores.append("La oferta no tiene partidas.")
    if any((p.cantidad or 0) <= 0 for p in oferta.partidas):
        errores.append("Todas las partidas deben tener cantidad mayor que cero.")
    if oferta.modalidad == "ejecucion" and oferta.facturacion == "detallada":
        # Control de Proyecto cruza el avance físico por número de partida
        # dentro de cada frente: no puede repetirse en la misma disciplina.
        vistos = set()
        for p in oferta.partidas:
            clave = (_etiqueta_disciplina(p), p.item.strip())
            if clave in vistos:
                errores.append(f"Partida repetida '{p.item}' en la disciplina '{clave[0]}'.")
            vistos.add(clave)
    if errores:
        raise TraspasoInvalido(" ".join(errores))


def _frente_de(oferta: Oferta, p: PartidaOferta) -> str:
    if oferta.modalidad == "suministro":
        return FRENTE_SUMINISTRO
    if oferta.facturacion == "resumida":
        return FRENTE_RESUMIDO
    return _etiqueta_disciplina(p)


def _construir_frentes(oferta: Oferta) -> list[dict]:
    # Con un solo frente, los números de partida de distintas disciplinas
    # podrían repetirse: se renumeran 1..N y se conserva el original.
    renumerar = oferta.modalidad == "suministro" or oferta.facturacion == "resumida"
    frentes: dict[str, dict] = {}
    for n, p in enumerate(sorted(oferta.partidas, key=lambda x: x.orden), start=1):
        label = _frente_de(oferta, p)
        f = frentes.setdefault(label, {"frente_label": label, "subtotal_precio": 0.0, "items": []})
        it = {
            "item": str(n) if renumerar else p.item.strip(),
            "descripcion": p.descripcion,
            "unidad": p.unidad,
            "cantidad": p.cantidad,
            "precio_unitario": _r2(p.precio_unitario),
            "precio_total": p.precio_total,
        }
        if renumerar:
            it["item_oferta"] = p.item.strip()
            it["disciplina"] = _etiqueta_disciplina(p)
        f["items"].append(it)
    for f in frentes.values():
        f["subtotal_precio"] = _r2(sum(it["precio_total"] for it in f["items"]))
    return list(frentes.values())


def _construir_cronograma(oferta: Oferta) -> list[dict]:
    """Una actividad por disciplina (insumo del cronograma, no 1 a 1 — §3)."""
    grupos: dict[tuple[str, str], list[int]] = {}
    for p in sorted(oferta.partidas, key=lambda x: x.orden):
        if not p.duracion_semanas:
            continue
        inicio = p.semana_inicio or 1
        fin = inicio + p.duracion_semanas - 1
        clave = (_frente_de(oferta, p), _etiqueta_disciplina(p))
        g = grupos.setdefault(clave, [inicio, fin])
        g[0], g[1] = min(g[0], inicio), max(g[1], fin)
    crono = []
    for (frente, disciplina), (inicio, fin) in grupos.items():
        actividad = "ENTREGA DE SUMINISTRO" if oferta.modalidad == "suministro" else disciplina
        crono.append({
            "actividad": actividad,
            "frente_label": frente,
            "fase": disciplina,
            "semana_inicio": inicio,
            "semana_fin": fin,
            "duracion_semanas": fin - inicio + 1,
        })
    return crono


def huella(frentes: list[dict], resumen: dict) -> str:
    """SHA-256 del contenido económico: detecta si dos archivos del mismo
    código de oferta traen datos distintos."""
    canon = json.dumps({"frentes": frentes, "resumen": resumen}, sort_keys=True,
                       ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def construir_traspaso(oferta: Oferta, *, generado: dt.datetime | None = None) -> dict:
    validar_para_traspaso(oferta)
    generado = generado or dt.datetime.utcnow()
    frentes = _construir_frentes(oferta)
    cronograma = _construir_cronograma(oferta)
    total = _r2(sum(f["subtotal_precio"] for f in frentes))
    iva = _r2(total * (oferta.iva_pct or 0) / 100)
    resumen = {"total_precio": total, "iva_monto": iva, "total_general": _r2(total + iva)}
    semanas = oferta.semanas_totales or max((c["semana_fin"] for c in cronograma), default=None)
    return {
        "formato": FORMATO,
        "generado": generado.replace(microsecond=0).isoformat() + "Z",
        "nombre": oferta.titulo,
        "meta": {
            "titulo": oferta.titulo,
            "iva_pct": oferta.iva_pct,
            "moneda": oferta.moneda,
            "semanas_totales": semanas,
            "n_items": sum(len(f["items"]) for f in frentes),
        },
        "resumen": resumen,
        "frentes": frentes,
        "cronograma": cronograma,
        "origen": {
            "sistema": SISTEMA_ORIGEN,
            "formato": FORMATO_ORIGEN,
            "version": VERSION_ORIGEN,
            "codigo_oferta": oferta.codigo,
            "cliente": {
                "razon_social": oferta.cliente_razon_social,
                "rif": oferta.cliente_rif,
                "tipo": oferta.cliente_tipo,
                "contacto": oferta.cliente_contacto,
            },
            "modalidad": oferta.modalidad,
            "facturacion": oferta.facturacion if oferta.modalidad == "ejecucion" else None,
            "tipo_orden_sugerido": TIPO_ORDEN_SUGERIDO[oferta.modalidad],
            "analista": oferta.analista_nombre,
            "fecha_ganada": oferta.fecha_ganada.replace(microsecond=0).isoformat() + "Z"
            if oferta.fecha_ganada else None,
            "sede_destino": oferta.sede_destino,
            "huella_sha256": huella(frentes, resumen),
        },
    }


def nombre_archivo(oferta: Oferta) -> str:
    """El código de oferta en el nombre da trazabilidad e idempotencia (§5)."""
    return f"{oferta.codigo}_traspaso_control_proyecto.json"
