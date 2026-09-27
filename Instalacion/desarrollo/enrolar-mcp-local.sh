#!/usr/bin/env bash
# Enrola en el MCP LOCAL (MASTER CONTROL PROJECT :8001) los dos nodos que
# participan en el traspaso de ofertas, SOLO para desarrollo:
#   - "sbc-local-dev"        (rol sbc_app)    = Control de Proyecto :8000
#   - "cotizacion-local-dev" (rol cotizacion) = Sistema de Cotización :8100
# Usa las mismas funciones del paso 28 (sbc_ops.crear_nodo / rotar_token /
# activar_desde_sede) desde el .venv de Control de Proyecto, así que no pide
# la sesión 2FA del administrador. En producción el alta se hace en el paso 28.
#
# Requiere los tres servicios levantados (levantar-con-control-proyecto.sh).
# Es idempotente: si los nodos existen, les rota el token y vuelve a enlazar.
set -euo pipefail
AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAIZ="$(cd "$AQUI/../.." && pwd)"
CP="${CONTROL_PROYECTO_DIR:-$(cd "$RAIZ/.." && pwd)/oriol-control-de-proyecto}"
MCP_URL_LOCAL="${MCP_URL_LOCAL:-http://127.0.0.1:8001}"
PY="$CP/Backend/.venv/bin/python"

[[ -x "$PY" ]] || { echo "Falta $PY: levanta antes Control de Proyecto." >&2; exit 1; }
[[ -f "$CP/Backend/.env.master" ]] || { echo "Falta Backend/.env.master: levanta antes el MCP (levantar-master.sh)." >&2; exit 1; }
curl -fsS "$MCP_URL_LOCAL/health" >/dev/null || { echo "El MCP no responde en $MCP_URL_LOCAL." >&2; exit 1; }

# 1) En la BD del MCP: sitio y nodos, con token nuevo.
TOKENS="$(cd "$CP/Backend" && ENVF=.env.master "$PY" - <<'PY'
import json, os
for linea in open(os.environ["ENVF"], encoding="utf-8"):
    linea = linea.strip()
    if linea and not linea.startswith("#") and "=" in linea:
        k, _, v = linea.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))
from app.kernel.db import SessionLocal, Base, engine
from app.kernel.models import NodoSbc, Sitio
from app.plataforma import sbc_ops
Base.metadata.create_all(bind=engine)
db = SessionLocal()
sitio = db.query(Sitio).filter(Sitio.codigo == "local-dev").first()
if not sitio:
    sitio_id = sbc_ops.crear_sitio(db, "local-dev", "Desarrollo local", "Esta PC", None, False, "enrolar-mcp-local")["id"]
else:
    sitio_id = sitio.id
out = {}
for clave, nombre, rol in (("sbc", "sbc-local-dev", "sbc_app"), ("cot", "cotizacion-local-dev", "cotizacion")):
    n = db.query(NodoSbc).filter(NodoSbc.nombre == nombre, NodoSbc.sitio_id == sitio_id).first()
    fila = sbc_ops.rotar_token(db, n.id, "enrolar-mcp-local") if n else \
        sbc_ops.crear_nodo(db, sitio_id, nombre, rol, "Desarrollo local", None, "enrolar-mcp-local")
    out[clave] = {"id": fila["id"], "token": fila["token_alta"]}
print(json.dumps(out))
PY
)"
SBC_TOKEN="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["sbc"]["token"])' "$TOKENS")"
COT_TOKEN="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["cot"]["token"])' "$TOKENS")"

# 2) Control de Proyecto :8000 se enlaza al MCP (paso 28 → Este nodo).
(cd "$CP/Backend" && ENVF=.env MCP="$MCP_URL_LOCAL" TOK="$SBC_TOKEN" "$PY" - <<'PY'
import os
for linea in open(os.environ["ENVF"], encoding="utf-8"):
    linea = linea.strip()
    if linea and not linea.startswith("#") and "=" in linea:
        k, _, v = linea.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))
from app.kernel.db import SessionLocal
from app.plataforma import sbc_ops
db = SessionLocal()
out = sbc_ops.activar_desde_sede(db, os.environ["MCP"], os.environ["TOK"])
print("SBC enlazado al MCP:", out.get("enrolado"), out.get("nodo_nombre") or "")
PY
)

# 3) El Sistema de Cotización usa su token de nodo (Backend/.env) y se reinicia.
ENVC="$RAIZ/Backend/.env"
[[ -f "$ENVC" ]] || { echo "Falta $ENVC: levanta antes el Sistema de Cotización." >&2; exit 1; }
python3 - "$ENVC" "$MCP_URL_LOCAL" "$COT_TOKEN" <<'PY'
import sys
ruta, url, tok = sys.argv[1:]
valores = {"MCP_URL": url, "MCP_TOKEN": tok, "MCP_POLL_SECONDS": "15"}
lineas, vistos = [], set()
for linea in open(ruta, encoding="utf-8").read().splitlines():
    k = linea.split("=", 1)[0].strip()
    if k in valores:
        lineas.append(f"{k}={valores[k]}"); vistos.add(k)
    else:
        lineas.append(linea)
lineas += [f"{k}={v}" for k, v in valores.items() if k not in vistos]
open(ruta, "w", encoding="utf-8").write("\n".join(lineas) + "\n")
PY
"$AQUI/detener.sh" >/dev/null
COTIZACION_NO_ABRIR=1 "$AQUI/levantar.sh" >/dev/null
curl -fsS http://127.0.0.1:${COTIZACION_API_PORT:-8100}/health; echo
echo "Listo: Cotización → MCP ($MCP_URL_LOCAL) → sbc-local-dev (Control de Proyecto :8000)."
