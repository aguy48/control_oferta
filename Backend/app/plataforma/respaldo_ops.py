"""Respaldos de esta instancia (datos SQLite/Postgres + ZIP de aplicación)."""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session

from app.kernel.config import APP_VERSION, settings
from app.kernel.db import engine

TIPOS = ("datos", "aplicacion")
_NOMBRE_OK = re.compile(r"^(datos|aplicacion)_(\d{8})_(\d{6})\.[A-Za-z0-9._]+$")
FRASE_RESTAURAR = "restaurar cotizacion"
_EXCLUIR_STORAGE = {"respaldos", "restauraciones", "logs"}
_EXCLUIR_DIRS = {
    ".venv", "venv", "__pycache__", ".pytest_cache", "data", "logs",
    ".git", "node_modules", ".mypy_cache",
}
_EXCLUIR_NOMBRES = {".env", ".env.local", ".env.production"}
_EXCLUIR_SUFIJOS = {".db", ".pyc", ".pyo", ".sqlite", ".sqlite3"}


def carpeta_respaldos() -> Path:
    p = Path(settings.STORAGE_DIR) / "respaldos"
    p.mkdir(parents=True, exist_ok=True)
    return p


def raiz_aplicacion() -> Path:
    return Path(__file__).resolve().parents[3]


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _fmt_bytes(n: int) -> str:
    x = float(n)
    for u in ("B", "KB", "MB", "GB"):
        if x < 1024 or u == "GB":
            return f"{x:.1f} {u}" if u != "B" else f"{int(x)} B"
        x /= 1024
    return f"{n} B"


def _iso_mtime(path: Path) -> str:
    ts = path.stat().st_mtime
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _info_archivo(path: Path) -> dict | None:
    if not path.is_file():
        return None
    nombre = path.name
    tipo = "datos" if nombre.startswith("datos_") else (
        "aplicacion" if nombre.startswith("aplicacion_") else "otro"
    )
    tam = path.stat().st_size
    return {
        "nombre": nombre,
        "tipo": tipo,
        "tamano_bytes": tam,
        "tamano": _fmt_bytes(tam),
        "creado_en": _iso_mtime(path),
        "ruta": f"respaldos/{nombre}",
    }


def listar() -> dict:
    carpeta = carpeta_respaldos()
    archivos = []
    for p in carpeta.iterdir():
        if not p.is_file() or not _NOMBRE_OK.match(p.name):
            continue
        info = _info_archivo(p)
        if info:
            archivos.append(info)
    archivos.sort(key=lambda a: a["creado_en"], reverse=True)
    return {
        "carpeta": "respaldos",
        "ultimo_datos": next((a for a in archivos if a["tipo"] == "datos"), None),
        "ultimo_aplicacion": next((a for a in archivos if a["tipo"] == "aplicacion"), None),
        "archivos": archivos[:40],
        "frase_restaurar": FRASE_RESTAURAR,
        "nota_restauracion": (
            "Datos: ZIP con el SQL y las carpetas de esta instancia (anexos, fichas). "
            "Aplicación: HTML + código Backend, sin .env ni venv. "
            f"Para restaurar datos escriba exactamente: {FRASE_RESTAURAR}"
        ),
    }


def ruta_segura(nombre: str) -> Path | None:
    if not nombre or not _NOMBRE_OK.match(nombre):
        return None
    base = carpeta_respaldos().resolve()
    path = (base / os.path.basename(nombre)).resolve()
    try:
        path.relative_to(base)
    except ValueError:
        return None
    return path if path.is_file() else None


def _ruta_sqlite() -> Path | None:
    u = make_url(settings.DATABASE_URL)
    if u.get_backend_name() != "sqlite":
        return None
    raw = u.database or ""
    if not raw or raw == ":memory:":
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _backup_sqlite(destino: Path) -> None:
    src_path = _ruta_sqlite()
    raw = engine.raw_connection()
    try:
        dbapi = getattr(raw, "driver_connection", None) or raw
        if src_path is not None and src_path.is_file():
            src = sqlite3.connect(str(src_path))
            try:
                dst = sqlite3.connect(str(destino))
                try:
                    src.backup(dst)
                finally:
                    dst.close()
            finally:
                src.close()
            return
        dst = sqlite3.connect(str(destino))
        try:
            dbapi.backup(dst)
        finally:
            dst.close()
    finally:
        raw.close()


def _omitir_dir(nombre: str) -> bool:
    return nombre in _EXCLUIR_DIRS or nombre.endswith(".egg-info")


def _omitir_archivo(path: Path) -> bool:
    if path.name in _EXCLUIR_NOMBRES or path.name.startswith(".env"):
        return True
    return path.suffix.lower() in _EXCLUIR_SUFIJOS


def _agregar_storage(zf: zipfile.ZipFile, manifest: dict) -> int:
    base = Path(settings.STORAGE_DIR)
    if not base.is_dir():
        return 0
    n = 0
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        rel_parts = p.relative_to(base).parts
        if rel_parts and rel_parts[0] in _EXCLUIR_STORAGE:
            continue
        if _omitir_archivo(p):
            continue
        arc = Path("storage") / p.relative_to(base)
        zf.write(p, arc.as_posix())
        manifest["archivos"].append(arc.as_posix())
        n += 1
    return n


def generar_datos(db: Session) -> dict:
    del db
    stamp = _stamp()
    motor = engine.dialect.name
    destino = carpeta_respaldos() / f"datos_{stamp}.zip"
    manifest = {
        "version_app": APP_VERSION,
        "creado_en": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "contenido": "SQL + carpetas de STORAGE_DIR (sin respaldos anidados ni .env).",
        "motor": motor,
        "archivos": [],
        "n_archivos_storage": 0,
    }
    with tempfile.TemporaryDirectory(prefix="cot-respaldo-") as td:
        tmp = Path(td)
        if motor == "sqlite":
            sql_path = tmp / "datos.sqlite"
            _backup_sqlite(sql_path)
        else:
            raise RuntimeError(f"Motor {motor} no soportado aún para respaldo de datos.")
        with zipfile.ZipFile(destino, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(sql_path, f"sql/{sql_path.name}")
            manifest["archivos"].append(f"sql/{sql_path.name}")
            manifest["n_archivos_storage"] = _agregar_storage(zf, manifest)
            zf.writestr("MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    info = _info_archivo(destino)
    if not info:
        raise RuntimeError("El archivo de respaldo no se creó.")
    info["n_archivos"] = manifest["n_archivos_storage"]
    return info


def _agregar_arbol(zf: zipfile.ZipFile, manifest: dict, base: Path, rel_dir: str) -> None:
    src = base / rel_dir
    if not src.is_dir():
        return
    for p in sorted(src.rglob("*")):
        if not p.is_file():
            continue
        if any(_omitir_dir(part) for part in p.relative_to(src).parts):
            continue
        if _omitir_archivo(p):
            continue
        rel = p.relative_to(base).as_posix()
        zf.write(p, rel)
        manifest["archivos"].append(rel)


def generar_aplicacion() -> dict:
    base = raiz_aplicacion()
    stamp = _stamp()
    destino = carpeta_respaldos() / f"aplicacion_{stamp}.zip"
    manifest = {
        "version_app": APP_VERSION,
        "creado_en": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "contenido": "Frontend + Backend/app (sin .env, venv ni bases).",
        "archivos": [],
    }
    with zipfile.ZipFile(destino, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        html = base / "Frontend" / "sistema_cotizacion.html"
        if html.is_file():
            zf.write(html, "Frontend/sistema_cotizacion.html")
            manifest["archivos"].append("Frontend/sistema_cotizacion.html")
        for carpeta in ("Frontend/js", "Frontend/css", "Frontend/assets", "Backend/app"):
            _agregar_arbol(zf, manifest, base, carpeta)
        for rel in ("VERSION", "README.md", "Backend/requirements.txt", "Backend/.env.example"):
            p = base / rel
            if p.is_file():
                zf.write(p, rel)
                manifest["archivos"].append(rel)
        zf.writestr("MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    info = _info_archivo(destino)
    if not info:
        raise RuntimeError("El ZIP de aplicación no se creó.")
    return info


def generar(db: Session, tipo: str) -> dict:
    tipo = (tipo or "").strip().lower()
    if tipo not in TIPOS:
        raise ValueError("tipo debe ser 'datos' o 'aplicacion'")
    if tipo == "datos":
        return generar_datos(db)
    return generar_aplicacion()


def validar_confirmacion(frase: str, entendido: bool) -> None:
    if not entendido:
        raise ValueError("Marque que entiende que se sustituyen los datos actuales.")
    if (frase or "").strip().lower() != FRASE_RESTAURAR:
        raise ValueError(f"Escriba exactamente: {FRASE_RESTAURAR}")


def restaurar_datos(path: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="cot-restaura-") as td:
        dest = Path(td)
        with zipfile.ZipFile(path) as zf:
            zf.extractall(dest)
        sql = next((p for p in (dest / "sql").glob("datos.*") if p.is_file()), None)
        if sql is None:
            raise RuntimeError("El ZIP no trae sql/datos.sqlite")
        storage_src = dest / "storage"
        n_arch = 0
        if storage_src.is_dir():
            storage_dst = Path(settings.STORAGE_DIR)
            storage_dst.mkdir(parents=True, exist_ok=True)
            for p in storage_src.rglob("*"):
                if not p.is_file():
                    continue
                rel = p.relative_to(storage_src)
                if rel.parts and rel.parts[0] in _EXCLUIR_STORAGE:
                    continue
                out = storage_dst / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, out)
                n_arch += 1
        db_path = _ruta_sqlite()
        if db_path is None:
            raise RuntimeError("Solo se restaura SQLite en esta instancia.")
        engine.dispose()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sql, db_path)
    return {"tipo": "datos", "n_archivos": n_arch, "sql": str(db_path)}
