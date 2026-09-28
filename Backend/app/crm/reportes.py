"""HTML imprimible de oferta comercial e informe técnico (papel membretado ORIOL)."""
from __future__ import annotations

import html
from datetime import datetime

from app.kernel.models import AjusteGeneral, InformeTecnico, Oferta


def _e(v) -> str:
    return html.escape("" if v is None else str(v))


def _dinero(n, moneda: str = "USD") -> str:
    return f"{moneda} {float(n or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _css() -> str:
    return """
    :root{--morado:#662483;--naranja:#F18A00;--ink:#231122;--muted:#5a4a58;}
    *{box-sizing:border-box}
    body{margin:0;padding:24px;font:13px/1.45 "Segoe UI",Calibri,Arial,sans-serif;color:var(--ink)}
    header{display:flex;justify-content:space-between;align-items:flex-start;
      border-bottom:4px solid var(--naranja);padding-bottom:12px;margin-bottom:18px}
    h1{margin:0;font-size:18px;color:var(--morado);letter-spacing:.04em;text-transform:uppercase}
    .meta{font-size:12px;color:var(--muted);text-align:right}
    .chip{display:inline-block;background:#F1E8F5;color:var(--morado);border-radius:999px;padding:2px 10px;font-weight:700;font-size:11px}
    table{width:100%;border-collapse:collapse;margin:12px 0}
    th{background:var(--morado);color:#fff;text-align:left;padding:6px 8px;font-size:12px}
    td{border-top:1px solid #e7e2e6;padding:6px 8px;vertical-align:top}
    td.num,th.num{text-align:right;white-space:nowrap}
    tfoot td{font-weight:700;background:#FDEEDD}
    .bloque{margin:14px 0}
    .muted{color:var(--muted)}
    footer{margin-top:28px;border-top:1px solid #e7e2e6;padding-top:8px;font-size:11px;color:var(--muted)}
    @media print{body{padding:8mm} .no-print{display:none}}
    """


def _empresa(az: AjusteGeneral | None) -> tuple[str, str]:
    razon = (az.razon_social if az and az.razon_social else "ORIOL Consultores C.A.")
    pie = " · ".join(x for x in [
        az.rif if az else None,
        az.telefono if az else None,
        az.email if az else None,
        az.direccion if az else None,
    ] if x)
    return razon, pie


def html_oferta(o: Oferta, az: AjusteGeneral | None = None) -> str:
    razon, pie = _empresa(az)
    iva = round((o.total_precio or 0) * (o.iva_pct or 0) / 100, 2)
    total = round((o.total_precio or 0) + iva, 2)
    filas = ""
    for p in o.partidas:
        filas += (
            f"<tr><td>{_e(p.disciplina)}</td><td>{_e(p.item)}</td>"
            f"<td>{_e(p.descripcion)}</td><td>{_e(p.unidad)}</td>"
            f"<td class='num'>{p.cantidad:g}</td>"
            f"<td class='num'>{_dinero(p.precio_unitario, o.moneda)}</td>"
            f"<td class='num'>{_dinero(p.precio_total, o.moneda)}</td></tr>"
        )
    if not filas:
        filas = "<tr><td colspan='7' class='muted'>Sin partidas.</td></tr>"
    origen = "Informe técnico + oferta comercial" if o.origen == "tecnica" else "Oferta comercial"
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>{_e(o.codigo)} — {_e(o.titulo)}</title><style>{_css()}</style></head>
<body>
<header>
  <div>
    <h1>{_e(razon)}</h1>
    <div class="muted">Sistema de Cotización · {_e(origen)}</div>
  </div>
  <div class="meta">
    <div><strong>{_e(o.codigo)}</strong></div>
    <div>{datetime.now():%d/%m/%Y}</div>
    <div class="chip">Margen {float(o.margen_pct or 0):g}%</div>
  </div>
</header>
<div class="bloque">
  <strong>Cliente:</strong> {_e(o.cliente_razon_social)}
  {_e(' · RIF ' + o.cliente_rif) if o.cliente_rif else ''}<br>
  <strong>Asunto:</strong> {_e(o.titulo)}<br>
  {f'<strong>SBC destino:</strong> {_e(o.sede_destino)}<br>' if o.sede_destino else ''}
</div>
{f'<p>{_e(o.notas)}</p>' if o.notas else ''}
<table>
  <thead><tr><th>Disciplina</th><th>Ítem</th><th>Descripción</th><th>Und.</th>
    <th class="num">Cant.</th><th class="num">P. unitario</th><th class="num">Total</th></tr></thead>
  <tbody>{filas}</tbody>
  <tfoot>
    <tr><td colspan="6">Subtotal</td><td class="num">{_dinero(o.total_precio, o.moneda)}</td></tr>
    <tr><td colspan="6">IVA {o.iva_pct}%</td><td class="num">{_dinero(iva, o.moneda)}</td></tr>
    <tr><td colspan="6">Total</td><td class="num">{_dinero(total, o.moneda)}</td></tr>
  </tfoot>
</table>
<p class="muted">Los precios de venta incluyen el margen comercial de {float(o.margen_pct or 0):g}%
sobre el costo de proveedor cuando la partida nació de una factura u oferta cargada.</p>
<footer>{_e(pie or razon)}</footer>
<p class="no-print"><button onclick="window.print()">Imprimir / PDF</button></p>
</body></html>"""


def html_informe(inf: InformeTecnico, az: AjusteGeneral | None = None, texto: str | None = None) -> str:
    razon, pie = _empresa(az)
    cuerpo = texto or inf.resumen or "Sin cuerpo de informe."
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>{_e(inf.codigo or inf.titulo)}</title><style>{_css()}
.prosa{{white-space:pre-wrap;border:1px solid #e7e2e6;padding:14px;border-radius:8px}}
</style></head>
<body>
<header>
  <div>
    <h1>{_e(razon)}</h1>
    <div class="muted">Informe técnico de campo / levantamiento</div>
  </div>
  <div class="meta">
    <div><strong>{_e(inf.codigo or 'SIN-CÓDIGO')}</strong></div>
    <div>{(inf.creado_en or datetime.now()):%d/%m/%Y}</div>
  </div>
</header>
<div class="bloque">
  <strong>Título:</strong> {_e(inf.titulo)}<br>
  {f'<strong>Cliente:</strong> {_e(inf.cliente_razon_social)}' if inf.cliente_razon_social else ''}
  {_e(' · RIF ' + inf.cliente_rif) if inf.cliente_rif else ''}
</div>
<div class="prosa">{_e(cuerpo)}</div>
<footer>Este informe técnico deriva en una oferta comercial independiente.
{_e(pie or razon)}</footer>
<p class="no-print"><button onclick="window.print()">Imprimir / PDF</button></p>
</body></html>"""
