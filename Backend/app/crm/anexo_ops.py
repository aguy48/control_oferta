"""Anexos PDF de la oferta e informes técnicos de campo."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.crm import gemini_oferta, oferta_ops
from app.identity import escenario_ops
from app.kernel.config import settings
from app.kernel.models import (
    AjusteGeneral, AnexoOferta, InformeTecnico, Oferta, PartidaOferta, TIPOS_ANEXO, Usuario, now,
)
from app.kernel.schemas import InformeIn, PartidaIn

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _tipo_anexo(nombre: str | None, mime: str | None, tipo: str | None) -> str:
    if tipo in TIPOS_ANEXO and tipo not in ("otro",):
        return tipo
    kind = gemini_oferta.clasificar_fuente(nombre, mime, tipo)
    if kind == "audio":
        return "audio"
    if kind == "imagen":
        return "imagen"
    if kind == "whatsapp":
        return "whatsapp"
    return tipo if tipo in TIPOS_ANEXO else "otro"


def _slug(nombre: str) -> str:
    base = unicodedata.normalize("NFKD", nombre or "documento.pdf")
    base = "".join(ch for ch in base if not unicodedata.combining(ch))
    base = _SAFE.sub("-", base).strip("-.") or "documento.pdf"
    return base[:120]


def _dir_anexos(escenario_id: str, oferta_id: str | None) -> Path:
    raiz = Path(settings.STORAGE_DIR) / "anexos" / (escenario_id or "sin-escenario")
    if oferta_id:
        raiz = raiz / oferta_id
    raiz.mkdir(parents=True, exist_ok=True)
    return raiz


def margen_defecto(db: Session, oferta: Oferta | None = None) -> float:
    if oferta is not None and oferta.margen_pct is not None:
        return float(oferta.margen_pct)
    fila = db.query(AjusteGeneral).filter(AjusteGeneral.id == "default").first()
    if fila and fila.margen_pct is not None:
        return float(fila.margen_pct)
    return 25.0


def listar_anexos(db: Session, usuario: Usuario, oferta_id: str | None = None) -> list[AnexoOferta]:
    esc = escenario_ops.exigir_escenario(usuario)
    q = db.query(AnexoOferta).filter(AnexoOferta.escenario_id == esc.id)
    if oferta_id:
        q = q.filter(AnexoOferta.oferta_id == oferta_id)
    return q.order_by(AnexoOferta.creado_en.desc()).all()


def cargar_anexo(db: Session, anexo_id: str, usuario: Usuario) -> AnexoOferta:
    a = db.query(AnexoOferta).filter(AnexoOferta.id == anexo_id).first()
    if not a:
        raise HTTPException(404, "Anexo no encontrado")
    esc = escenario_ops.exigir_escenario(usuario)
    if a.escenario_id and a.escenario_id != esc.id:
        raise HTTPException(404, "Anexo no encontrado")
    return a


async def guardar_upload(
    db: Session,
    usuario: Usuario,
    archivo: UploadFile,
    tipo: str,
    oferta_id: str | None = None,
    ocr: bool = True,
) -> AnexoOferta:
    escenario_ops.exigir_escritura(usuario)
    esc = escenario_ops.exigir_escenario(usuario)
    tipo = _tipo_anexo(archivo.filename, archivo.content_type, tipo)
    if tipo not in TIPOS_ANEXO:
        raise HTTPException(422, f"Tipo de anexo no válido: {tipo}")
    o = None
    if oferta_id:
        o = oferta_ops.cargar_oferta(db, oferta_id, usuario, escritura=True)
    data = await archivo.read()
    if not data:
        raise HTTPException(422, "El archivo está vacío.")
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, "El archivo no puede superar 20 MB.")
    nombre = _slug(archivo.filename or "documento")
    dest = _dir_anexos(esc.id, o.id if o else None) / f"{now().strftime('%Y%m%d%H%M%S')}-{nombre}"
    dest.write_bytes(data)
    texto, extra = ("", None)
    if ocr:
        texto, extra = gemini_oferta.analizar_documento(
            data, db, tipo, nombre=archivo.filename, mime=archivo.content_type,
        )
    a = AnexoOferta(
        oferta_id=o.id if o else None,
        escenario_id=esc.id,
        tipo=tipo,
        nombre=nombre,
        mime=archivo.content_type or gemini_oferta.mime_adjunto(archivo.filename, archivo.content_type, tipo),
        ruta=str(dest),
        texto_ocr=texto or None,
        extraccion=extra,
        creado_por=usuario.usuario,
    )
    db.add(a)
    db.flush()
    return a


def ocr_anexo(db: Session, a: AnexoOferta, usuario: Usuario) -> AnexoOferta:
    escenario_ops.exigir_escritura(usuario)
    path = Path(a.ruta)
    if not path.is_file():
        raise HTTPException(404, "El archivo del anexo ya no está en disco.")
    texto, extra = gemini_oferta.analizar_documento(
        path.read_bytes(), db, a.tipo, nombre=a.nombre, mime=a.mime,
    )
    a.texto_ocr = texto or None
    a.extraccion = extra
    return a


def aplicar_extraccion_a_oferta(
    db: Session,
    o: Oferta,
    anexos: list[AnexoOferta],
    usuario: Usuario,
    margen_pct: float | None = None,
    reemplazar: bool = True,
) -> list[dict]:
    if o.estado in oferta_ops.ESTADOS_CERRADOS:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"La oferta está {o.estado}: las partidas ya no se editan.",
        )
    margen = float(margen_pct if margen_pct is not None else margen_defecto(db, o))
    o.margen_pct = margen
    crudas: list[dict] = []
    for a in anexos:
        extra = a.extraccion or {}
        for p in extra.get("partidas") or []:
            if isinstance(p, dict):
                crudas.append(p)
    if not crudas:
        extra0 = (anexos[0].extraccion if anexos else None) or {}
        if extra0.get("informe_tecnico") or extra0.get("resumen"):
            crudas = [{
                "descripcion": (extra0.get("resumen") or extra0.get("informe_tecnico") or "Alcance según análisis")[:400],
                "cantidad": 1, "precio_costo": 0, "unidad": "GLB",
            }]
    partidas = gemini_oferta.aplicar_margen(crudas, margen)
    if not partidas:
        raise HTTPException(422, "Las fuentes no tienen partidas. Analízalas de nuevo con Gemini.")
    body = [PartidaIn(
        disciplina=p["disciplina"], item=p["item"], descripcion=p["descripcion"],
        unidad=p["unidad"], cantidad=p["cantidad"], precio_unitario=p["precio_unitario"],
    ) for p in partidas]
    if reemplazar:
        oferta_ops.reemplazar_partidas(db, o, body, usuario)
    else:
        existentes = list(o.partidas)
        offset = len(existentes)
        for i, p in enumerate(body):
            o.partidas.append(PartidaOferta(orden=offset + i, **p.model_dump()))
        o.actualizado_por = usuario.id
    return partidas


def listar_informes(db: Session, usuario: Usuario) -> list[InformeTecnico]:
    esc = escenario_ops.exigir_escenario(usuario)
    return (
        db.query(InformeTecnico)
        .filter(InformeTecnico.escenario_id == esc.id)
        .order_by(InformeTecnico.creado_en.desc())
        .all()
    )


EXT_INFORME_OFFICE = {
    "doc", "docx", "odt", "rtf", "xls", "xlsx", "ods", "csv",
}


def es_archivo_office(nombre: str | None) -> bool:
    n = (nombre or "").rsplit(".", 1)
    return len(n) == 2 and n[-1].lower() in EXT_INFORME_OFFICE


def meta_anexo_informe(a: AnexoOferta | None) -> dict:
    if a is None:
        return {"anexo_id": None, "anexo_nombre": None, "archivo_office": False}
    return {
        "anexo_id": a.id,
        "anexo_nombre": a.nombre,
        "archivo_office": es_archivo_office(a.nombre),
    }


def anexos_de_informes(db: Session, informes: list[InformeTecnico]) -> dict[str, AnexoOferta]:
    ids = [i.anexo_id for i in informes if i.anexo_id]
    if not ids:
        return {}
    filas = db.query(AnexoOferta).filter(AnexoOferta.id.in_(ids)).all()
    return {a.id: a for a in filas}


def eliminar_informe(db: Session, inf: InformeTecnico, usuario: Usuario) -> None:
    escenario_ops.exigir_escritura(usuario)
    anexo_id = inf.anexo_id
    db.delete(inf)
    db.flush()
    if not anexo_id:
        return
    if db.query(InformeTecnico).filter(InformeTecnico.anexo_id == anexo_id).count():
        return
    a = db.query(AnexoOferta).filter(AnexoOferta.id == anexo_id).first()
    if a is None or a.tipo != "informe_tecnico" or not es_archivo_office(a.nombre):
        return
    path = Path(a.ruta) if a.ruta else None
    db.delete(a)
    if path is not None and path.is_file():
        path.unlink()


def cargar_informe(db: Session, informe_id: str, usuario: Usuario) -> InformeTecnico:
    inf = db.query(InformeTecnico).filter(InformeTecnico.id == informe_id).first()
    if not inf:
        raise HTTPException(404, "Informe técnico no encontrado")
    esc = escenario_ops.exigir_escenario(usuario)
    if inf.escenario_id and inf.escenario_id != esc.id:
        raise HTTPException(404, "Informe técnico no encontrado")
    return inf


def crear_informe(db: Session, body: InformeIn, usuario: Usuario) -> InformeTecnico:
    escenario_ops.exigir_escritura(usuario)
    esc = escenario_ops.exigir_escenario(usuario)
    inf = InformeTecnico(escenario_id=esc.id, creado_por=usuario.usuario, **body.model_dump())
    db.add(inf)
    db.flush()
    return inf


def informe_desde_anexo(db: Session, a: AnexoOferta, usuario: Usuario) -> InformeTecnico:
    escenario_ops.exigir_escritura(usuario)
    extra = a.extraccion or {}
    inf = InformeTecnico(
        escenario_id=a.escenario_id,
        codigo=None,
        titulo=(extra.get("titulo") or a.nombre.rsplit(".", 1)[0] or "Informe técnico")[:200],
        cliente_razon_social=extra.get("cliente") or None,
        cliente_rif=extra.get("rif") or None,
        resumen=(extra.get("informe_tecnico") or extra.get("resumen") or a.texto_ocr or "")[:20000] or None,
        anexo_id=a.id,
        oferta_id=a.oferta_id,
        creado_por=usuario.usuario,
    )
    db.add(inf)
    db.flush()
    return inf


def generar_oferta_desde_informe(
    db: Session,
    inf: InformeTecnico,
    usuario: Usuario,
    margen_pct: float | None = None,
    mcp_destino_id: str | None = None,
    sede_destino: str | None = None,
) -> Oferta:
    escenario_ops.exigir_escritura(usuario)
    extra = {}
    if inf.anexo_id:
        a = db.query(AnexoOferta).filter(AnexoOferta.id == inf.anexo_id).first()
        if a and a.extraccion:
            extra = a.extraccion
    margen = float(margen_pct if margen_pct is not None else margen_defecto(db))
    partidas = gemini_oferta.aplicar_margen(extra.get("partidas") or [], margen)
    from app.kernel.schemas import OfertaCreate
    o = oferta_ops.crear_oferta(db, OfertaCreate(
        titulo=inf.titulo[:200],
        cliente_razon_social=inf.cliente_razon_social or "Cliente por confirmar",
        cliente_rif=inf.cliente_rif,
        origen="tecnica",
        margen_pct=margen,
        mcp_destino_id=mcp_destino_id,
        sede_destino=sede_destino,
        notas="Generada desde informe técnico " + (inf.codigo or inf.id),
    ), usuario)
    if partidas:
        body = [PartidaIn(
            disciplina=p["disciplina"], item=p["item"], descripcion=p["descripcion"],
            unidad=p["unidad"], cantidad=p["cantidad"], precio_unitario=p["precio_unitario"],
        ) for p in partidas]
        oferta_ops.reemplazar_partidas(db, o, body, usuario)
    inf.oferta_id = o.id
    return o


def fuentes_de_anexos(anexos: list[AnexoOferta]) -> list[dict]:
    fuentes = []
    for a in anexos:
        path = Path(a.ruta)
        if path.is_file():
            fuentes.append({
                "data": path.read_bytes(), "nombre": a.nombre,
                "mime": a.mime, "tipo": a.tipo,
            })
    return fuentes


def analizar_anexos_juntos(db: Session, anexos: list[AnexoOferta]) -> tuple[str, dict]:
    texto, extra = gemini_oferta.analizar_fuentes(fuentes_de_anexos(anexos), db)
    if anexos:
        anexos[0].texto_ocr = (texto or anexos[0].texto_ocr or "")[:50000] or None
        anexos[0].extraccion = extra
    return texto, extra


def informe_desde_extraccion(
    db: Session, extra: dict, usuario: Usuario,
    anexo: AnexoOferta | None = None, oferta: Oferta | None = None,
) -> InformeTecnico:
    escenario_ops.exigir_escritura(usuario)
    esc = escenario_ops.exigir_escenario(usuario)
    inf = InformeTecnico(
        escenario_id=esc.id,
        titulo=(extra.get("titulo") or (anexo.nombre if anexo else None) or "Informe técnico")[:200],
        cliente_razon_social=extra.get("cliente") or (oferta.cliente_razon_social if oferta else None),
        cliente_rif=extra.get("rif") or (oferta.cliente_rif if oferta else None),
        resumen=(extra.get("informe_tecnico") or extra.get("resumen") or "")[:20000] or None,
        anexo_id=anexo.id if anexo else None,
        oferta_id=oferta.id if oferta else None,
        creado_por=usuario.usuario,
    )
    db.add(inf)
    db.flush()
    return inf


def generar_informe_y_oferta(
    db: Session,
    usuario: Usuario,
    anexos: list[AnexoOferta],
    *,
    oferta: Oferta | None = None,
    crear_informe: bool = True,
    crear_oferta: bool = True,
    margen_pct: float | None = None,
    mcp_destino_id: str | None = None,
    sede_destino: str | None = None,
    reanalizar: bool = True,
) -> tuple[dict, InformeTecnico | None, Oferta | None]:
    """Junta PDF + audio + WhatsApp, genera informe técnico y oferta."""
    escenario_ops.exigir_escritura(usuario)
    if not anexos:
        raise HTTPException(422, "Carga al menos un PDF, audio o chat de WhatsApp.")
    if reanalizar:
        _, extra = analizar_anexos_juntos(db, anexos)
    else:
        extra = (anexos[0].extraccion or {})
        if not extra.get("informe_tecnico") and not extra.get("partidas"):
            _, extra = analizar_anexos_juntos(db, anexos)
    inf = None
    if crear_informe:
        inf = informe_desde_extraccion(db, extra, usuario, anexo=anexos[0], oferta=oferta)
    o = oferta
    if crear_oferta:
        if o is None:
            from app.kernel.schemas import OfertaCreate
            o = oferta_ops.crear_oferta(db, OfertaCreate(
                titulo=(extra.get("titulo") or (inf.titulo if inf else "Oferta desde análisis"))[:200],
                cliente_razon_social=(
                    extra.get("cliente")
                    or (inf.cliente_razon_social if inf else None)
                    or "Cliente por confirmar"
                ),
                cliente_rif=extra.get("rif") or (inf.cliente_rif if inf else None),
                origen="tecnica",
                margen_pct=margen_pct if margen_pct is not None else margen_defecto(db),
                mcp_destino_id=mcp_destino_id,
                sede_destino=sede_destino,
                notas="Generada por Gemini desde PDF / audio / WhatsApp",
            ), usuario)
            for a in anexos:
                if a.oferta_id is None:
                    a.oferta_id = o.id
        aplicar_extraccion_a_oferta(db, o, anexos, usuario, margen_pct=margen_pct)
        if inf:
            inf.oferta_id = o.id
    return extra, inf, o
