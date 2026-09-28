"""Análisis multimodal (PDF, audio, WhatsApp, imagen) → informe + partidas.

Con clave Gemini se envían los adjuntos al modelo. Sin clave se extrae
texto (PDF / chat exportado) y se arma un borrador heurístico.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import zipfile
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from sqlalchemy.orm import Session

from app.kernel.config import settings
from app.kernel.crypto_secrets import descifrar
from app.kernel.models import AjusteGeneral, TIPOS_ANEXO

logger = logging.getLogger("sistema_cotizacion")

TIPOS_DOC = TIPOS_ANEXO

AUDIO_EXT = (".mp3", ".wav", ".m4a", ".ogg", ".opus", ".aac", ".flac", ".amr", ".webm")
IMAGEN_EXT = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif")
MIME_AUDIO = {
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
    ".ogg": "audio/ogg", ".opus": "audio/opus", ".aac": "audio/aac",
    ".flac": "audio/flac", ".amr": "audio/amr", ".webm": "audio/webm",
}
MIME_IMAGEN = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".heic": "image/heic", ".gif": "image/gif",
}

SYSTEM_PROMPT = """Eres analista técnico-comercial de ORIOL Consultores C.A.
Recibes una o varias fuentes de un mismo trabajo:
- PDF (factura u oferta de proveedor, RIF, informe de campo NS-ORI, oferta comercial).
- Audio de visita, nota de voz o reunión (transcribe y extrae el alcance).
- Chat de WhatsApp exportado o captura (pedido del cliente, cantidades, equipos, plazos).
- Fotos de tableros, equipos o capturas.

Redacta el análisis como lo haría ORIOL: informe técnico de levantamiento
y, a partir de él, las partidas de la oferta comercial.
Devuelve SOLO JSON válido:
{
  "tipo_documento": "factura_proveedor|oferta_proveedor|informe_tecnico|oferta_comercial|rif|audio|whatsapp|imagen|otro",
  "titulo": "título corto del trabajo",
  "cliente": "",
  "proveedor": "",
  "rif": "",
  "resumen": "párrafo breve del alcance",
  "informe_tecnico": "informe completo en prosa (antecedentes, hallazgos, alcance recomendado, observaciones)",
  "partidas": [
    {
      "disciplina": "GENERAL",
      "item": "1",
      "descripcion": "texto de la línea",
      "unidad": "UND",
      "cantidad": 1,
      "precio_costo": 0
    }
  ]
}
precio_costo es el precio del proveedor (sin margen de ORIOL).
Si no hay precios (audio, WhatsApp, informe de campo), deja precio_costo en 0
y describe las actividades o equipos que se deben cotizar.
No inventes equipos, cantidades ni precios que no estén en las fuentes.
Si el audio o el chat son ambiguos, dilo en el informe y cotiza solo lo explícito."""


def clave_gemini(db: Session | None = None) -> str:
    env = (settings.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY") or "").strip()
    if env:
        return env
    if db is None:
        return ""
    fila = db.query(AjusteGeneral).filter(AjusteGeneral.id == "default").first()
    if not fila:
        return ""
    return (descifrar(fila.gemini_api_key_enc) or "").strip()


def modelo_gemini(db: Session | None = None) -> str:
    if db is not None:
        fila = db.query(AjusteGeneral).filter(AjusteGeneral.id == "default").first()
        if fila and (fila.gemini_model or "").strip():
            return fila.gemini_model.strip()
    return settings.GEMINI_MODEL or "gemini-2.5-flash"


def _ext(nombre: str) -> str:
    return "." + (nombre or "").rsplit(".", 1)[-1].lower() if "." in (nombre or "") else ""


def clasificar_fuente(nombre: str | None, mime: str | None, tipo: str | None = None) -> str:
    """Cómo se lee el archivo: pdf | audio | imagen | whatsapp | texto | binario."""
    n = (nombre or "").lower()
    m = (mime or "").lower()
    if tipo == "audio" or m.startswith("audio/") or _ext(n) in AUDIO_EXT:
        return "audio"
    if tipo == "imagen" or m.startswith("image/") or _ext(n) in IMAGEN_EXT:
        return "imagen"
    if tipo == "whatsapp" or "whatsapp" in n or n.endswith("_chat.txt"):
        return "whatsapp"
    if n.endswith(".zip") or m in ("application/zip", "application/x-zip-compressed"):
        return "whatsapp"
    if n.endswith(".txt") or m.startswith("text/"):
        return "whatsapp" if tipo in (None, "whatsapp", "otro") else "texto"
    if n.endswith(".pdf") or m == "application/pdf":
        return "pdf"
    return "binario"


def mime_adjunto(nombre: str | None, mime: str | None, kind: str) -> str:
    if mime and "/" in mime and not mime.endswith("octet-stream"):
        return mime
    ext = _ext(nombre or "")
    if kind == "audio":
        return MIME_AUDIO.get(ext, "audio/mpeg")
    if kind == "imagen":
        return MIME_IMAGEN.get(ext, "image/jpeg")
    if kind == "pdf":
        return "application/pdf"
    return mime or "application/octet-stream"


def decode_texto(data: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def extraer_whatsapp(data: bytes, nombre: str | None = None) -> str:
    """Texto de un .txt o de un .zip de WhatsApp (archivo _chat.txt)."""
    if not data:
        return ""
    if data[:2] == b"PK" or (nombre or "").lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                nombres = zf.namelist()
                chat = next((n for n in nombres if n.lower().endswith("_chat.txt")), None)
                if chat is None:
                    chat = next((n for n in nombres if n.lower().endswith(".txt")), None)
                if chat is None:
                    return ""
                return decode_texto(zf.read(chat))
        except zipfile.BadZipFile:
            return ""
    return decode_texto(data)


def texto_pdf(data: bytes, max_paginas: int = 40) -> str:
    if not data:
        return ""
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception:
        return ""
    partes = []
    for page in reader.pages[:max_paginas]:
        try:
            partes.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(partes).strip()


def aplicar_margen(partidas: list[dict], margen_pct: float | None) -> list[dict]:
    """precio_venta = precio_costo × (1 + margen/100)."""
    factor = 1 + (float(margen_pct or 0) / 100.0)
    out = []
    for i, p in enumerate(partidas or []):
        if not isinstance(p, dict):
            continue
        costo = float(p.get("precio_costo") or 0)
        desc = str(p.get("descripcion") or "Partida").strip() or "Partida"
        out.append({
            "disciplina": (str(p.get("disciplina") or "GENERAL").strip() or "GENERAL")[:120],
            "item": str(p.get("item") or (i + 1))[:40],
            "descripcion": desc[:4000],
            "unidad": (str(p.get("unidad") or "UND").strip() or "UND")[:20],
            "cantidad": float(p.get("cantidad") or 1),
            "precio_unitario": round(costo * factor, 2),
            "precio_costo": round(costo, 2),
        })
    return out


_RE_RIF = re.compile(r"\b([VEJPGCvejpgc]-?\d{6,9}-?\d)\b")
_RE_LINEA = re.compile(
    r"^(?P<item>\d{1,3})[.\-\)\s]+(?P<desc>.+?)\s+"
    r"(?P<cant>\d+(?:[.,]\d+)?)\s+"
    r"(?P<und>[A-Za-zÁÉÍÓÚÑáéíóúñ]{1,8})\s+"
    r"(?P<precio>\d+(?:[.,]\d{1,4})?)\s*$"
)
_RE_WA = re.compile(
    r"^(?:\[)?\d{1,2}[/-]\d{1,2}[/-]\d{2,4}[,\s]+\d{1,2}:\d{2}(?::\d{2})?"
    r"(?:\s*[ap]\.?\s*m\.?)?(?:\])?\s*-?\s*([^:]{1,80}):\s*(.+)$",
    re.IGNORECASE,
)
_RE_NUM_VE = r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+,\d+|\d+"
_RE_ES_NUM_VE = re.compile(rf"^(?:{_RE_NUM_VE})$")
_UNIDS_VE = (
    "bobina", "global", "horas", "hora", "hrs", "hr", "und.", "und",
    "pto", "glb.", "glb", "pzas", "pza", "juego", "kit", "lote",
    "kg", "ml", "jg", "gl", "h", "m",
)
_RE_PARTIDA_OFERTA = re.compile(
    rf"^Partida\s+(?P<item>\d+)\s+[–\-]\s+(?P<desc>.+?)\s+"
    rf"(?P<venta>{_RE_NUM_VE})\s+(?P<costo>{_RE_NUM_VE})",
    re.IGNORECASE,
)
_RE_DISC_RESUMEN = re.compile(
    rf"^(?P<item>\d{{1,2}})\s+(?P<desc>.+?)\s+Partidas?\s+\d"
    rf".*?(?P<venta>{_RE_NUM_VE})\s+(?P<costo>{_RE_NUM_VE})",
    re.IGNORECASE,
)
_RE_SALTA = re.compile(
    r"^(TOTAL|SUBTOTAL|IVA|Control:|N°|Notas|POR PARTIDA|SUPUESTOS|Descuento|Documento interno)",
    re.IGNORECASE,
)


def _num_ve(s: str) -> float:
    raw = (s or "").strip()
    if not raw:
        return 0.0
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", raw) or ("." in raw and "," in raw):
        return float(raw.replace(".", "").replace(",", "."))
    if "," in raw:
        return float(raw.replace(",", "."))
    return float(raw)


def _partidas_lineas_simples(blob: str) -> list[dict]:
    partidas = []
    for linea in blob.splitlines():
        linea = re.sub(r"\s+", " ", linea).strip()
        mm = _RE_LINEA.match(linea)
        if not mm:
            continue
        partidas.append({
            "disciplina": "GENERAL",
            "item": mm.group("item"),
            "descripcion": mm.group("desc").strip()[:4000],
            "unidad": mm.group("und")[:20],
            "cantidad": _num_ve(mm.group("cant")),
            "precio_costo": _num_ve(mm.group("precio")),
        })
    return partidas


def _unidad_ve(token: str) -> tuple[str, str] | None:
    raw = (token or "").strip()
    baja = raw.lower().rstrip(".")
    for u in _UNIDS_VE:
        clave = u.rstrip(".")
        if baja == clave:
            return u.rstrip("."), ""
        if len(clave) >= 3 and baja.endswith(clave) and len(baja) > len(clave):
            return clave, raw[: len(raw) - len(clave)]
    return None


def _detalle_desde_derecha(linea: str) -> dict | None:
    """Lee cantidad + unidad + 3–5 importes VE desde el final de la fila."""
    toks = linea.split()
    if len(toks) < 5:
        return None
    nums: list[str] = []
    i = len(toks) - 1
    while i >= 0 and _RE_ES_NUM_VE.match(toks[i]) and len(nums) < 5:
        nums.append(toks[i])
        i -= 1
    nums.reverse()
    if len(nums) < 3 or i < 1:
        return None
    if not _RE_ES_NUM_VE.match(toks[i]):
        return None
    cant = _num_ve(toks[i])
    und_info = _unidad_ve(toks[i - 1])
    if not und_info:
        return None
    und, prefijo = und_info
    desc_toks = toks[: i - 1]
    if prefijo:
        desc_toks.append(prefijo)
    desc = " ".join(desc_toks).strip()
    item = ""
    im = re.match(r"^(\d{1,2}\.\d+)\s+(.*)$", desc)
    if im:
        item, desc = im.group(1), im.group(2).strip()
    valores = [_num_ve(n) for n in nums]
    costo = valores[2] if len(valores) >= 3 else valores[0]
    if not desc:
        return None
    return {
        "item": item,
        "descripcion": desc,
        "unidad": und,
        "cantidad": cant,
        "precio_costo": costo,
    }


def _partidas_tabla_ve(blob: str) -> list[dict]:
    """Tablas VE (20.177,88) de costos por disciplina / ítem / partida comercial."""
    detalle: list[dict] = []
    ofertas: list[dict] = []
    disciplinas: list[dict] = []
    disc = "GENERAL"
    for cruda in blob.splitlines():
        linea = re.sub(r"\s+", " ", cruda).strip()
        if not linea or _RE_SALTA.match(linea):
            continue
        cab = re.search(r"(?:Tienda|Proyecto)\s+[^–\-]+[–\-]\s+(.+)$", linea, re.IGNORECASE)
        if cab and "cimas" not in cab.group(1).lower() and "resumen" not in cab.group(1).lower():
            disc = cab.group(1).strip()[:120]
            continue
        md = _detalle_desde_derecha(linea)
        if md:
            detalle.append({
                "disciplina": disc,
                "item": (md["item"] or str(len(detalle) + 1))[:40],
                "descripcion": md["descripcion"][:4000],
                "unidad": md["unidad"][:20],
                "cantidad": md["cantidad"],
                "precio_costo": md["precio_costo"],
            })
            continue
        mp = _RE_PARTIDA_OFERTA.match(linea)
        if mp:
            ofertas.append({
                "disciplina": "GENERAL",
                "item": f"P{mp.group('item')}",
                "descripcion": mp.group("desc").strip()[:4000],
                "unidad": "GLB",
                "cantidad": 1,
                "precio_costo": _num_ve(mp.group("costo")),
            })
            continue
        mr = _RE_DISC_RESUMEN.match(linea)
        if mr:
            disciplinas.append({
                "disciplina": mr.group("desc").strip()[:120],
                "item": mr.group("item"),
                "descripcion": mr.group("desc").strip()[:4000],
                "unidad": "GLB",
                "cantidad": 1,
                "precio_costo": _num_ve(mr.group("costo")),
            })
    if detalle:
        return detalle
    if ofertas:
        return ofertas
    return disciplinas


def _titulo_y_cliente(blob: str) -> tuple[str, str]:
    titulo = ""
    cliente = ""
    for linea in blob.splitlines():
        l = linea.strip()
        if not l:
            continue
        if not titulo and re.search(r"tienda|proyecto|oferta\s+ORI", l, re.I) and len(l) >= 20:
            titulo = l[:200]
        m = re.search(r"–\s*([A-ZÁÉÍÓÚÑ0-9][A-Za-záéíóúñ0-9 .,&-]{1,40})\s+Proyecto", l)
        if m:
            cliente = m.group(1).strip()
        elif "CIMAS" in l.upper() and not cliente:
            cliente = "CIMAS"
    return titulo, cliente


def extraer_heuristicas(texto: str, tipo_sugerido: str | None = None) -> dict:
    """Borrador sin Gemini: RIF, líneas de partida y, si es chat, el hilo."""
    blob = texto or ""
    rif = ""
    m = _RE_RIF.search(blob)
    if m:
        rif = m.group(1).upper()
    partidas = _partidas_lineas_simples(blob) or _partidas_tabla_ve(blob)
    mensajes = []
    for linea in blob.splitlines():
        wm = _RE_WA.match(linea.strip())
        if wm:
            mensajes.append(f"{wm.group(1).strip()}: {wm.group(2).strip()}")
    tipo = tipo_sugerido if tipo_sugerido in TIPOS_DOC else "otro"
    baja = blob.lower()
    if tipo == "otro":
        if mensajes or "whatsapp" in baja:
            tipo = "whatsapp"
        elif "informe" in baja or "levantamiento" in baja or "ns-ori" in baja:
            tipo = "informe_tecnico"
        elif "factura" in baja:
            tipo = "factura_proveedor"
        elif "oferta" in baja:
            tipo = "oferta_proveedor"
        elif "rif" in baja or "registro de informacion fiscal" in baja:
            tipo = "rif"
    titulo_doc, cliente = _titulo_y_cliente(blob)
    resumen = ""
    if mensajes:
        resumen = " · ".join(mensajes[:4])[:400]
    elif titulo_doc:
        resumen = titulo_doc[:400]
    else:
        for linea in blob.splitlines():
            linea = linea.strip()
            if len(linea) >= 40:
                resumen = linea[:400]
                break
    informe = _informe_heuristico(blob, resumen, mensajes, tipo)
    return {
        "tipo_documento": tipo,
        "titulo": (titulo_doc or (mensajes[0] if mensajes else "") or resumen or "Análisis de fuentes")[:80],
        "cliente": cliente,
        "proveedor": "",
        "rif": rif,
        "resumen": resumen,
        "informe_tecnico": informe,
        "partidas": partidas,
        "motor": "heuristicas",
    }


def _informe_heuristico(texto: str, resumen: str, mensajes: list[str], tipo: str) -> str:
    cuerpo = "\n".join(f"- {m}" for m in mensajes[:40]) if mensajes else (texto or "")[:3500]
    return (
        "INFORME TÉCNICO (borrador sin Gemini)\n\n"
        f"Fuente: {tipo}\n"
        f"Resumen: {resumen or '—'}\n\n"
        "Antecedentes / contenido extraído:\n"
        f"{cuerpo}\n\n"
        "Con clave Gemini en Generales se transcribe audio, se lee el PDF "
        "y se redacta el informe y las partidas de la oferta."
    )


def _extraer_json(texto: str) -> dict:
    raw = (texto or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    ini, fin = raw.find("{"), raw.rfind("}")
    if ini < 0 or fin <= ini:
        raise ValueError("Gemini no devolvió JSON.")
    data = json.loads(raw[ini:fin + 1])
    if not isinstance(data, dict):
        raise ValueError("Gemini no devolvió un objeto.")
    return data


def _normalizar(extra: dict, tipo_sugerido: str | None = None) -> dict:
    extra = dict(extra or {})
    tipo = extra.get("tipo_documento")
    if tipo not in TIPOS_DOC:
        extra["tipo_documento"] = tipo_sugerido if tipo_sugerido in TIPOS_DOC else "otro"
    extra.setdefault("titulo", extra.get("resumen") or "Análisis de fuentes")
    extra.setdefault("cliente", extra.get("cliente_razon_social") or "")
    extra.setdefault("proveedor", "")
    extra.setdefault("rif", "")
    extra.setdefault("resumen", "")
    extra.setdefault("informe_tecnico", extra.get("resumen") or "")
    if not isinstance(extra.get("partidas"), list):
        extra["partidas"] = []
    extra["titulo"] = str(extra["titulo"] or "Análisis de fuentes")[:200]
    extra["informe_tecnico"] = str(extra["informe_tecnico"] or "")[:20000]
    return extra


def llamar_gemini(texto: str, adjuntos: list[tuple[bytes, str]], clave: str, modelo: str) -> dict:
    partes: list[dict[str, Any]] = [{
        "text": (
            "Analiza las fuentes (PDF, audio, WhatsApp o imagen) y genera "
            "el informe técnico y las partidas de la oferta.\n\n"
            + (texto or "(sin texto extraído; usa los adjuntos)")
        ),
    }]
    for data, mime in adjuntos:
        if not data:
            continue
        partes.append({
            "inline_data": {
                "mime_type": mime or "application/octet-stream",
                "data": base64.b64encode(data).decode("ascii"),
            }
        })
    cuerpo = json.dumps({
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": partes}],
        "generationConfig": {"temperature": 0.15},
    }).encode("utf-8")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{modelo}:generateContent?key={urllib.parse.quote(clave)}"
    )
    req = urllib.request.Request(
        url, data=cuerpo, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detalle = e.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"Gemini HTTP {e.code}: {detalle}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"No se pudo contactar a Gemini: {e.reason}") from e
    cands = payload.get("candidates") or []
    if not cands:
        raise RuntimeError("Gemini no devolvió candidatos.")
    parts = (((cands[0] or {}).get("content") or {}).get("parts")) or []
    texto_final = "".join(p.get("text") or "" for p in parts if isinstance(p, dict))
    data = _extraer_json(texto_final)
    data["motor"] = "gemini"
    return data


def preparar_fuente(data: bytes, nombre: str | None = None,
                    mime: str | None = None, tipo: str | None = None) -> dict:
    kind = clasificar_fuente(nombre, mime, tipo)
    texto = ""
    adjunto = None
    if kind == "pdf":
        texto = texto_pdf(data)
        adjunto = (data, mime_adjunto(nombre, mime, "pdf"))
    elif kind == "audio":
        texto = f"[Audio adjunto: {nombre or 'nota de voz'}]"
        adjunto = (data, mime_adjunto(nombre, mime, "audio"))
    elif kind == "imagen":
        texto = f"[Imagen adjunta: {nombre or 'captura'}]"
        adjunto = (data, mime_adjunto(nombre, mime, "imagen"))
    elif kind in ("whatsapp", "texto"):
        texto = extraer_whatsapp(data, nombre)
    return {"kind": kind, "texto": texto, "adjunto": adjunto, "nombre": nombre or ""}


def analizar_fuentes(
    fuentes: list[dict],
    db: Session | None = None,
    tipo_sugerido: str | None = None,
) -> tuple[str, dict]:
    """Varias fuentes (PDF + audio + WhatsApp) en un solo análisis."""
    preparados = []
    for f in fuentes or []:
        if not f.get("data"):
            continue
        preparados.append(preparar_fuente(
            f["data"], f.get("nombre"), f.get("mime"), f.get("tipo") or tipo_sugerido,
        ))
    textos = []
    adjuntos: list[tuple[bytes, str]] = []
    for p in preparados:
        if p["texto"]:
            etiqueta = p["nombre"] or p["kind"]
            textos.append(f"--- {etiqueta} ---\n{p['texto']}")
        if p["adjunto"]:
            adjuntos.append(p["adjunto"])
    texto = "\n\n".join(textos).strip()
    clave = clave_gemini(db)
    if clave and (adjuntos or texto):
        try:
            extra = llamar_gemini(texto, adjuntos, clave, modelo_gemini(db))
            return texto, _normalizar(extra, tipo_sugerido)
        except Exception:
            logger.exception("Gemini falló; se usa extracción heurística")
    if not texto and any(p["kind"] == "audio" for p in preparados):
        extra = extraer_heuristicas("", tipo_sugerido or "audio")
        extra["resumen"] = "Se necesita la clave de Gemini en Generales para transcribir el audio."
        extra["informe_tecnico"] = extra["resumen"]
        extra["tipo_documento"] = "audio"
        return texto, extra
    return texto, _normalizar(extraer_heuristicas(texto, tipo_sugerido), tipo_sugerido)


def analizar_documento(
    data: bytes,
    db: Session | None = None,
    tipo_sugerido: str | None = None,
    nombre: str | None = None,
    mime: str | None = None,
) -> tuple[str, dict]:
    """Una sola fuente. Devuelve (texto_ocr, extraccion)."""
    return analizar_fuentes(
        [{"data": data, "nombre": nombre, "mime": mime, "tipo": tipo_sugerido}],
        db, tipo_sugerido,
    )
