"""OnlyOffice Document Server: abrir y guardar anexos Word, Excel, PowerPoint y PDF."""
from __future__ import annotations

import hashlib
import io
import ipaddress
import re
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.kernel.config import settings
from app.kernel.models import AjusteGeneral, AnexoOferta, Usuario, now

EXT_WORD = {"doc", "docx", "odt", "rtf", "txt"}
EXT_CELL = {"xls", "xlsx", "ods", "csv"}
EXT_SLIDE = {"ppt", "pptx", "odp"}
EXT_PDF = {"pdf"}
EXT_OFFICE = EXT_WORD | EXT_CELL | EXT_SLIDE | EXT_PDF

ROLES_LECTURA = ("admin", "analista", "auditor")
ROLES_EDICION = ("admin", "analista")

_TIPOS_NUEVO = {
    "word": ("docx", "Documento.docx"),
    "cell": ("xlsx", "Hoja.xlsx"),
    "slide": ("pptx", "Presentacion.pptx"),
}


def _url_limpia(raw: str | None) -> str:
    u = (raw or "").strip().rstrip("/")
    if not u:
        return ""
    if not (u.startswith("http://") or u.startswith("https://")):
        raise ValueError("La URL debe empezar por http:// o https://")
    return u[:400]


def _es_ip_privada(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False


def url_para_document_server(ds: str, api: str) -> str:
    """URL que el contenedor OnlyOffice usa para leer y guardar el archivo.

    Si Document Server y la API están en la misma IP LAN, Docker no suele
    alcanzar esa IP (hairpin NAT). Se reescribe a host.docker.internal.
    """
    if not api or not ds:
        return api
    try:
        p_api = urlparse(api)
        p_ds = urlparse(ds)
    except Exception:
        return api
    host_api = (p_api.hostname or "").lower()
    host_ds = (p_ds.hostname or "").lower()
    if not host_api:
        return api
    if host_api in {"localhost", "127.0.0.1", "::1", "host.docker.internal"}:
        return api
    if host_api != host_ds:
        return api
    if not _es_ip_privada(host_api):
        return api
    netloc = "host.docker.internal"
    if p_api.port:
        netloc += f":{p_api.port}"
    return urlunparse((p_api.scheme or "http", netloc, p_api.path or "", "", "", "")).rstrip("/")


def _az(db: Session | None) -> AjusteGeneral | None:
    if db is None:
        return None
    return db.query(AjusteGeneral).filter(AjusteGeneral.id == "default").first()


def _asegurar(db: Session) -> AjusteGeneral:
    fila = _az(db)
    if fila is None:
        fila = AjusteGeneral(id="default", razon_social="ORIOL Consultores C.A.")
        db.add(fila)
        db.flush()
    return fila


def jwt_secret(db: Session | None = None) -> str:
    az = _az(db)
    enc = getattr(az, "onlyoffice_jwt_secret_enc", None) if az is not None else None
    if enc:
        from app.kernel import crypto_secrets
        try:
            val = crypto_secrets.descifrar(enc)
            if val:
                return val
        except Exception:
            pass
    return (settings.ONLYOFFICE_JWT_SECRET or "").strip()


def ds_url(db: Session | None = None) -> str:
    az = _az(db)
    if az is not None:
        u = (getattr(az, "onlyoffice_url", None) or "").strip().rstrip("/")
        if u:
            return u
    return (settings.ONLYOFFICE_URL or "").strip().rstrip("/")


def app_url(db: Session | None = None, fallback: str = "") -> str:
    az = _az(db)
    if az is not None:
        u = (getattr(az, "onlyoffice_app_url", None) or "").strip().rstrip("/")
        if u:
            return u
    env = (settings.ONLYOFFICE_APP_URL or "").strip().rstrip("/")
    if env:
        return env
    return (fallback or "").rstrip("/")


def publico(az: AjusteGeneral | None = None) -> dict:
    tiene_db_url = bool(az is not None and (getattr(az, "onlyoffice_url", None) or "").strip())
    tiene_db_sec = bool(az is not None and getattr(az, "onlyoffice_jwt_secret_enc", None))
    env_url = bool((settings.ONLYOFFICE_URL or "").strip())
    env_sec = bool((settings.ONLYOFFICE_JWT_SECRET or "").strip())
    if tiene_db_url:
        url_final = str(az.onlyoffice_url).strip().rstrip("/")
    else:
        url_final = (settings.ONLYOFFICE_URL or "").strip().rstrip("/")
    app = ""
    if az is not None:
        app = (getattr(az, "onlyoffice_app_url", None) or "").strip().rstrip("/")
    if not app:
        app = (settings.ONLYOFFICE_APP_URL or "").strip().rstrip("/")
    return {
        "configurado": bool(url_final),
        "fuente": "generales" if tiene_db_url else ("entorno" if env_url else "ninguna"),
        "url": url_final or None,
        "app_url": app or None,
        "tiene_jwt": tiene_db_sec or env_sec,
        "ds_script": (url_final + "/web-apps/apps/api/documents/api.js") if url_final else None,
    }


def estado(db: Session | None = None) -> dict:
    cfg = publico(_az(db) if db is not None else None)
    return {
        "habilitado": bool(cfg.get("configurado")),
        "ds_url": cfg.get("url"),
        "ds_script": cfg.get("ds_script"),
        "tiene_jwt": bool(cfg.get("tiene_jwt")),
        "fuente": cfg.get("fuente"),
    }


def guardar(db: Session, datos: dict, *, actor=None) -> dict:
    from app.kernel import crypto_secrets
    az = _asegurar(db)
    if "onlyoffice_url" in datos and datos["onlyoffice_url"] is not None:
        az.onlyoffice_url = _url_limpia(datos["onlyoffice_url"]) or None
    if "onlyoffice_app_url" in datos and datos["onlyoffice_app_url"] is not None:
        az.onlyoffice_app_url = _url_limpia(datos["onlyoffice_app_url"]) or None
    secreto = datos.get("onlyoffice_jwt_secret")
    if datos.get("onlyoffice_quitar_jwt"):
        az.onlyoffice_jwt_secret_enc = None
    elif secreto is not None and str(secreto).strip():
        az.onlyoffice_jwt_secret_enc = crypto_secrets.cifrar(str(secreto).strip()[:200])
    az.actualizado_en = now()
    az.actualizado_por = actor.usuario if actor is not None else None
    db.add(az)
    db.commit()
    db.refresh(az)
    return publico(az)


def _firmar(payload: dict, secret: str) -> str:
    tok = jwt.encode(payload, secret, algorithm="HS256")
    return tok if isinstance(tok, str) else tok.decode("ascii")


def _verificar(token: str, secret: str) -> dict:
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except JWTError as e:
        raise ValueError("Token de OnlyOffice inválido o caducado") from e


def _clave_firma(db: Session | None = None) -> str:
    return jwt_secret(db) or settings.SECRET_KEY


def token_archivo(origen: str, ident: str, uid: str, db: Session | None = None) -> str:
    exp = int((datetime.now(timezone.utc) + timedelta(hours=12)).timestamp())
    return _firmar(
        {"origen": origen, "id": ident, "uid": uid, "exp": exp},
        _clave_firma(db),
    )


def leer_token_archivo(token: str, db: Session | None = None) -> dict:
    return _verificar(token, _clave_firma(db))


def extension_de(nombre: str) -> str:
    n = (nombre or "").rsplit(".", 1)
    return (n[-1].lower() if len(n) == 2 else "")


def document_type(ext: str) -> str:
    e = (ext or "").lower()
    if e in EXT_CELL:
        return "cell"
    if e in EXT_SLIDE:
        return "slide"
    if e in EXT_PDF:
        return "pdf"
    return "word"


def mime_de(nombre: str) -> str:
    ext = extension_de(nombre)
    return {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "doc": "application/msword",
        "odt": "application/vnd.oasis.opendocument.text",
        "rtf": "application/rtf",
        "txt": "text/plain",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xls": "application/vnd.ms-excel",
        "ods": "application/vnd.oasis.opendocument.spreadsheet",
        "csv": "text/csv",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "ppt": "application/vnd.ms-powerpoint",
        "odp": "application/vnd.oasis.opendocument.presentation",
        "pdf": "application/pdf",
    }.get(ext, "application/octet-stream")


def puede_editar(usuario: Usuario, origen: str, ext: str) -> bool:
    if (ext or "").lower() in EXT_PDF:
        return False
    if usuario.rol == "auditor":
        return False
    return usuario.rol in ROLES_EDICION


def _clave_doc(origen: str, ident: str, path: Path) -> str:
    st = path.stat()
    ident_s = hashlib.sha1(str(ident).encode("utf-8")).hexdigest()[:16]
    raw = f"{origen}-{ident_s}-{int(st.st_mtime)}-{st.st_size}"
    return re.sub(r"[^A-Za-z0-9._-]", "-", raw)[:120]


def resolver(db: Session, origen: str, ident: str) -> dict:
    origen = (origen or "").strip().lower()
    ident = (ident or "").strip()
    if not ident:
        raise FileNotFoundError("Falta el identificador del archivo")
    if origen != "anexo":
        raise ValueError("Origen no válido (anexo)")
    doc = db.query(AnexoOferta).filter(AnexoOferta.id == ident).first()
    if not doc:
        raise FileNotFoundError("Anexo no encontrado")
    path = Path(doc.ruta) if doc.ruta else None
    if path is None or not path.is_file():
        raise FileNotFoundError("Este anexo no tiene un archivo en disco")
    nombre = doc.nombre or path.name
    return {
        "origen": origen, "id": ident, "path": path,
        "nombre": nombre, "key": _clave_doc(origen, ident, path),
        "anexo": doc,
    }


def escribir(db: Session, origen: str, ident: str, data: bytes) -> None:
    rec = resolver(db, origen, ident)
    rec["path"].write_bytes(data)
    doc = rec.get("anexo")
    if doc is not None:
        db.add(doc)
        db.commit()


def config_editor(
    db: Session,
    *,
    origen: str,
    ident: str,
    usuario: Usuario,
    modo: str,
    base_api: str,
) -> dict:
    from app.crm import anexo_ops
    url = ds_url(db)
    if not url:
        raise RuntimeError("OnlyOffice no está configurado. En Generales indica la URL del Document Server.")
    anexo_ops.cargar_anexo(db, ident, usuario)
    rec = resolver(db, origen, ident)
    ext = extension_de(rec["nombre"])
    if ext not in EXT_OFFICE:
        raise ValueError("Este tipo de archivo no se abre en OnlyOffice.")
    api = app_url(db, fallback=base_api)
    if not api:
        raise ValueError("Falta la URL de la API para OnlyOffice (la que usa el Document Server).")
    tok = token_archivo(origen, ident, usuario.id, db)
    api_ds = url_para_document_server(url, api)
    file_url = f"{api_ds}/onlyoffice/archivo/{tok}"
    cb_url = f"{api_ds}/onlyoffice/callback?t={tok}"
    editar = (modo or "edit").lower() != "view" and puede_editar(usuario, origen, ext)
    document = {
        "fileType": ext,
        "key": rec["key"],
        "title": rec["nombre"],
        "url": file_url,
        "permissions": {
            "edit": editar,
            "comment": True,
            "download": True,
            "print": True,
            "review": editar,
        },
    }
    editor_config = {
        "callbackUrl": cb_url,
        "mode": "edit" if editar else "view",
        "lang": "es",
        "user": {"id": usuario.id, "name": usuario.nombre or usuario.usuario},
        "customization": {
            "autosave": True,
            "forcesave": True,
            "compactHeader": True,
            "hideRightMenu": False,
        },
    }
    tipo_doc = document_type(ext)
    cfg = {
        "documentType": tipo_doc,
        "document": document,
        "editorConfig": editor_config,
        "type": "desktop",
        "width": "100%",
        "height": "100%",
    }
    secret = jwt_secret(db)
    if secret:
        ahora = int(datetime.now(timezone.utc).timestamp())
        cfg["token"] = _firmar(
            {
                "document": document,
                "documentType": tipo_doc,
                "editorConfig": editor_config,
                "type": "desktop",
                "iat": ahora,
                "exp": ahora + 12 * 3600,
            },
            secret,
        )
    cfg["ds_url"] = url
    cfg["ds_script"] = url + "/web-apps/apps/api/documents/api.js"
    cfg["titulo"] = rec["nombre"]
    cfg["modo"] = editor_config["mode"]
    return cfg


def _bajar(url: str, secret: str = "") -> bytes:
    req = urllib.request.Request(url, method="GET")
    if secret:
        tok = _firmar({"payload": {"url": url}}, secret)
        req.add_header("Authorization", "Bearer " + tok)
    with urllib.request.urlopen(req, timeout=90) as resp:  # nosec B310 — URL del Document Server
        return resp.read()


def procesar_callback(db: Session, body: dict, token_q: str | None, auth_header: str | None) -> dict:
    secret = jwt_secret(db)
    payload = dict(body or {})
    tok = None
    if auth_header and auth_header.lower().startswith("bearer "):
        tok = auth_header.split(" ", 1)[1].strip()
    tok = tok or payload.get("token")
    if secret and tok:
        try:
            decoded = _verificar(tok, secret)
            if isinstance(decoded, dict):
                inner = decoded.get("payload") if isinstance(decoded.get("payload"), dict) else decoded
                payload = {**payload, **inner}
        except ValueError:
            if not token_q:
                raise
    status = int(payload.get("status") or 0)
    if status in (1, 4):
        return {"error": 0}
    if status not in (2, 6, 7):
        return {"error": 0}
    url = (payload.get("url") or "").strip()
    if not url:
        return {"error": 0}
    rec_tok = leer_token_archivo(token_q, db) if token_q else None
    if rec_tok is None:
        return {"error": 1}
    data = _bajar(url, secret)
    if not data:
        return {"error": 1}
    escribir(db, rec_tok["origen"], rec_tok["id"], data)
    return {"error": 0}


def _zip_xml(parts: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in parts.items():
            zf.writestr(name, content.encode("utf-8"))
    return buf.getvalue()


def plantilla_docx() -> bytes:
    return _zip_xml({
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>"
        ),
        "word/_rels/document.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
        ),
        "word/document.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t></w:t></w:r></w:p></w:body></w:document>"
        ),
    })


def plantilla_xlsx() -> bytes:
    return _zip_xml({
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            "</Relationships>"
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            "<sheets><sheet name=\"Hoja1\" sheetId=\"1\" r:id=\"rId1\"/></sheets></workbook>"
        ),
        "xl/worksheets/sheet1.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<sheetData/></worksheet>"
        ),
        "xl/styles.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<fonts count=\"1\"><font><sz val=\"11\"/><name val=\"Calibri\"/></font></fonts>"
            "<fills count=\"1\"><fill><patternFill patternType=\"none\"/></fill></fills>"
            "<borders count=\"1\"><border/></borders>"
            "<cellStyleXfs count=\"1\"><xf/></cellStyleXfs>"
            "<cellXfs count=\"1\"><xf/></cellXfs>"
            "</styleSheet>"
        ),
    })


def plantilla_pptx() -> bytes:
    ns_a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    ns_r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    ns_p = "http://schemas.openxmlformats.org/presentationml/2006/main"
    return _zip_xml({
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/ppt/presentation.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
            '<Override PartName="/ppt/slides/slide1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
            '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
            '<Override PartName="/ppt/slideMasters/slideMaster1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
            '<Override PartName="/ppt/theme/theme1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>'
            "</Relationships>"
        ),
        "ppt/_rels/presentation.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>'
            "</Relationships>"
        ),
        "ppt/presentation.xml": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<p:presentation xmlns:a="{ns_a}" xmlns:r="{ns_r}" xmlns:p="{ns_p}">'
            f"<p:sldMasterIdLst><p:sldMasterId id=\"2147483648\" r:id=\"rId1\"/></p:sldMasterIdLst>"
            f"<p:sldIdLst><p:sldId id=\"256\" r:id=\"rId2\"/></p:sldIdLst>"
            f"<p:sldSz cx=\"9144000\" cy=\"6858000\"/>"
            f"<p:notesSz cx=\"6858000\" cy=\"9144000\"/></p:presentation>"
        ),
        "ppt/slides/_rels/slide1.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
            "</Relationships>"
        ),
        "ppt/slides/slide1.xml": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<p:sld xmlns:a="{ns_a}" xmlns:r="{ns_r}" xmlns:p="{ns_p}">'
            f"<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id=\"1\" name=\"\"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>"
            f"<p:grpSpPr><a:xfrm><a:off x=\"0\" y=\"0\"/><a:ext cx=\"0\" cy=\"0\"/>"
            f"<a:chOff x=\"0\" y=\"0\"/><a:chExt cx=\"0\" cy=\"0\"/></a:xfrm></p:grpSpPr>"
            f"</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>"
        ),
        "ppt/slideLayouts/_rels/slideLayout1.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>'
            "</Relationships>"
        ),
        "ppt/slideLayouts/slideLayout1.xml": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<p:sldLayout xmlns:a="{ns_a}" xmlns:r="{ns_r}" xmlns:p="{ns_p}" type="blank">'
            f"<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id=\"1\" name=\"\"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>"
            f"<p:grpSpPr><a:xfrm><a:off x=\"0\" y=\"0\"/><a:ext cx=\"0\" cy=\"0\"/>"
            f"<a:chOff x=\"0\" y=\"0\"/><a:chExt cx=\"0\" cy=\"0\"/></a:xfrm></p:grpSpPr>"
            f"</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>"
        ),
        "ppt/slideMasters/_rels/slideMaster1.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>'
            "</Relationships>"
        ),
        "ppt/slideMasters/slideMaster1.xml": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<p:sldMaster xmlns:a="{ns_a}" xmlns:r="{ns_r}" xmlns:p="{ns_p}">'
            f"<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id=\"1\" name=\"\"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>"
            f"<p:grpSpPr><a:xfrm><a:off x=\"0\" y=\"0\"/><a:ext cx=\"0\" cy=\"0\"/>"
            f"<a:chOff x=\"0\" y=\"0\"/><a:chExt cx=\"0\" cy=\"0\"/></a:xfrm></p:grpSpPr>"
            f"</p:spTree></p:cSld>"
            f"<p:clrMap bg1=\"lt1\" tx1=\"dk1\" bg2=\"lt2\" tx2=\"dk2\" accent1=\"accent1\" "
            f"accent2=\"accent2\" accent3=\"accent3\" accent4=\"accent4\" accent5=\"accent5\" "
            f"accent6=\"accent6\" hlink=\"hlink\" folHlink=\"folHlink\"/>"
            f"<p:sldLayoutIdLst><p:sldLayoutId id=\"2147483649\" r:id=\"rId1\"/></p:sldLayoutIdLst>"
            f"</p:sldMaster>"
        ),
        "ppt/theme/theme1.xml": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<a:theme xmlns:a="{ns_a}" name="Office">'
            f"<a:themeElements><a:clrScheme name=\"Office\">"
            f"<a:dk1><a:sysClr val=\"windowText\" lastClr=\"000000\"/></a:dk1>"
            f"<a:lt1><a:sysClr val=\"window\" lastClr=\"FFFFFF\"/></a:lt1>"
            f"<a:dk2><a:srgbClr val=\"1F497D\"/></a:dk2>"
            f"<a:lt2><a:srgbClr val=\"EEECE1\"/></a:lt2>"
            f"<a:accent1><a:srgbClr val=\"4F81BD\"/></a:accent1>"
            f"<a:accent2><a:srgbClr val=\"C0504D\"/></a:accent2>"
            f"<a:accent3><a:srgbClr val=\"9BBB59\"/></a:accent3>"
            f"<a:accent4><a:srgbClr val=\"8064A2\"/></a:accent4>"
            f"<a:accent5><a:srgbClr val=\"4BACC6\"/></a:accent5>"
            f"<a:accent6><a:srgbClr val=\"F79646\"/></a:accent6>"
            f"<a:hlink><a:srgbClr val=\"0000FF\"/></a:hlink>"
            f"<a:folHlink><a:srgbClr val=\"800080\"/></a:folHlink>"
            f"</a:clrScheme>"
            f"<a:fontScheme name=\"Office\"><a:majorFont><a:latin typeface=\"Calibri\"/><a:ea typeface=\"\"/><a:cs typeface=\"\"/></a:majorFont>"
            f"<a:minorFont><a:latin typeface=\"Calibri\"/><a:ea typeface=\"\"/><a:cs typeface=\"\"/></a:minorFont></a:fontScheme>"
            f"<a:fmtScheme name=\"Office\"><a:fillStyleLst><a:solidFill><a:schemeClr val=\"phClr\"/></a:solidFill>"
            f"<a:solidFill><a:schemeClr val=\"phClr\"/></a:solidFill><a:solidFill><a:schemeClr val=\"phClr\"/></a:solidFill></a:fillStyleLst>"
            f"<a:lnStyleLst><a:ln w=\"9525\"><a:solidFill><a:schemeClr val=\"phClr\"/></a:solidFill></a:ln>"
            f"<a:ln w=\"25400\"><a:solidFill><a:schemeClr val=\"phClr\"/></a:solidFill></a:ln>"
            f"<a:ln w=\"38100\"><a:solidFill><a:schemeClr val=\"phClr\"/></a:solidFill></a:ln></a:lnStyleLst>"
            f"<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle>"
            f"<a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>"
            f"<a:bgFillStyleLst><a:solidFill><a:schemeClr val=\"phClr\"/></a:solidFill>"
            f"<a:solidFill><a:schemeClr val=\"phClr\"/></a:solidFill><a:solidFill><a:schemeClr val=\"phClr\"/></a:solidFill></a:bgFillStyleLst>"
            f"</a:fmtScheme></a:themeElements></a:theme>"
        ),
    })


def bytes_plantilla(tipo: str) -> tuple[str, str, bytes]:
    clave = (tipo or "").strip().lower()
    if clave not in _TIPOS_NUEVO:
        raise ValueError("Tipo nuevo debe ser word, cell o slide")
    ext, nombre = _TIPOS_NUEVO[clave]
    if ext == "docx":
        data = plantilla_docx()
    elif ext == "xlsx":
        data = plantilla_xlsx()
    else:
        data = plantilla_pptx()
    return ext, nombre, data


def crear_nuevo(
    db: Session,
    *,
    oferta_id: str | None,
    tipo: str,
    usuario: Usuario,
    nombre: str | None = None,
) -> AnexoOferta:
    from app.crm import anexo_ops, oferta_ops
    from app.identity import escenario_ops

    escenario_ops.exigir_escritura(usuario)
    esc = escenario_ops.exigir_escenario(usuario)
    o = None
    if oferta_id:
        o = oferta_ops.cargar_oferta(db, oferta_id, usuario, escritura=True)
    ext, nombre_def, data = bytes_plantilla(tipo)
    nom = (nombre or "").strip() or nombre_def
    if not nom.lower().endswith("." + ext):
        nom = nom + "." + ext
    dest = anexo_ops._dir_anexos(esc.id, o.id if o else None) / f"{now().strftime('%Y%m%d%H%M%S')}-{anexo_ops._slug(nom)}"
    dest.write_bytes(data)
    tipo_anexo = "oferta_comercial" if ext == "docx" else "otro"
    a = AnexoOferta(
        oferta_id=o.id if o else None,
        escenario_id=esc.id,
        tipo=tipo_anexo,
        nombre=nom,
        mime=mime_de(nom),
        ruta=str(dest),
        creado_por=usuario.usuario,
    )
    db.add(a)
    db.flush()
    db.commit()
    db.refresh(a)
    return a
