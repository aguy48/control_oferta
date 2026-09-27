#!/usr/bin/env bash
# Levanta el Sistema de Cotización en DESARROLLO en esta máquina
# (API :8100 + HTML :8090) y abre el navegador. Si ya corre, solo abre la app.
# Mismo esquema que Control de Proyecto (Instalacion/desarrollo/levantar.sh),
# en otros puertos para que ambos convivan en la misma PC.
set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAIZ="$(cd "$AQUI/../.." && pwd)"
BACKEND="$RAIZ/Backend"
FRONTEND="$RAIZ/Frontend"
RUN="$RAIZ/.dev-run"
LOG="$RUN/desarrollo.log"
PID_API="$RUN/api.pid"
PID_WEB="$RUN/web.pid"
BIND="${COTIZACION_DEV_BIND:-0.0.0.0}"
API_PORT="${COTIZACION_API_PORT:-8100}"
WEB_PORT="${COTIZACION_WEB_PORT:-8090}"
URL="http://127.0.0.1:${WEB_PORT}/sistema_cotizacion.html"
ADMIN_CLAVE_INICIAL="CambiaEstoYa.1"

ip_lan() {
  ip -4 -br addr 2>/dev/null | awk '
    $1 == "lo" { next }
    $1 ~ /^(proton|wg|tun|tailscale|docker|br-|veth|virbr)/ { next }
    { for (i = 3; i <= NF; i++) if ($i ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+\//) { split($i, c, "/"); print c[1]; exit } }'
}

mkdir -p "$RUN" "$BACKEND/data"

aviso() {
  echo "$*"
  if command -v notify-send >/dev/null 2>&1; then
    notify-send -a "Sistema de Cotización" "Sistema de Cotización" "$*" || true
  fi
}

responde() { curl -fsS -o /dev/null "$1" 2>/dev/null; }

vivo() {
  local pidfile="$1" url="$2"
  if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then return 0; fi
  responde "$url"
}

abrir() {
  [[ "${COTIZACION_NO_ABRIR:-}" == "1" ]] && return 0
  if command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 || true
  elif command -v gio >/dev/null 2>&1; then gio open "$URL" >/dev/null 2>&1 || true
  elif command -v open >/dev/null 2>&1; then open "$URL" >/dev/null 2>&1 || true
  fi
}

entorno_python() {
  local venv="$BACKEND/.venv"
  if [[ ! -x "$venv/bin/python" ]]; then
    if command -v uv >/dev/null 2>&1; then
      uv venv "$venv" >>"$LOG" 2>&1
    elif ! python3 -m venv "$venv" >>"$LOG" 2>&1; then
      echo "No se pudo crear el entorno Python (instala python3-venv o uv)." >&2
      exit 1
    fi
  fi
  # Reinstala solo si cambió requirements.txt.
  local marca="$venv/.requirements.sha"
  local actual; actual="$(sha256sum "$BACKEND/requirements.txt" | cut -d' ' -f1)"
  if [[ ! -f "$marca" ]] || [[ "$(cat "$marca")" != "$actual" ]]; then
    aviso "Instalando dependencias del backend (primera vez)…"
    if command -v uv >/dev/null 2>&1; then
      uv pip install --python "$venv/bin/python" -r "$BACKEND/requirements.txt" >>"$LOG" 2>&1
    else
      "$venv/bin/pip" install -q -r "$BACKEND/requirements.txt" >>"$LOG" 2>&1
    fi
    echo "$actual" >"$marca"
  fi
}

if vivo "$PID_API" "http://127.0.0.1:${API_PORT}/health" && vivo "$PID_WEB" "$URL"; then
  aviso "Ya estaba en marcha. Abriendo $URL"
  abrir
  exit 0
fi

entorno_python

if [[ ! -f "$BACKEND/.env" ]]; then
  # BD y SECRET_KEY PROPIAS de esta instancia (ING-COT-003 §6): no se copian
  # de Control de Proyecto.
  umask 077
  cp "$BACKEND/.env.example" "$BACKEND/.env"
  SK="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
  sed -i \
    -e "s|^DATABASE_URL=.*|DATABASE_URL=sqlite:///./sistema_cotizacion.db|" \
    -e "s|^SECRET_KEY=.*|SECRET_KEY=${SK}|" \
    -e "s|^CORS_ORIGINS=.*|CORS_ORIGINS=*|" \
    -e "s|^INITIAL_ADMIN_USER=.*|INITIAL_ADMIN_USER=admin|" \
    -e "s|^INITIAL_ADMIN_PASSWORD=.*|INITIAL_ADMIN_PASSWORD=${ADMIN_CLAVE_INICIAL}|" \
    "$BACKEND/.env"
  aviso "Se creó Backend/.env de desarrollo (admin / ${ADMIN_CLAVE_INICIAL}). Se pide cambiarla al entrar."
fi

if ! vivo "$PID_API" "http://127.0.0.1:${API_PORT}/health"; then
  cd "$BACKEND"
  nohup "$BACKEND/.venv/bin/uvicorn" app.main:app --host "$BIND" --port "$API_PORT" \
    --env-file "$BACKEND/.env" >>"$LOG" 2>&1 &
  echo $! >"$PID_API"
fi

if ! vivo "$PID_WEB" "$URL"; then
  nohup python3 "$AQUI/servir-frontend.py" \
    --root "$FRONTEND" --bind "$BIND" --port "$WEB_PORT" --api-port "$API_PORT" \
    --index sistema_cotizacion.html --config "$AQUI/config.js" \
    >>"$LOG" 2>&1 &
  echo $! >"$PID_WEB"
fi

VERSION="$(cat "$RAIZ/VERSION" 2>/dev/null || echo "?")"
for _ in $(seq 1 60); do
  if responde "http://127.0.0.1:${API_PORT}/health" && responde "$URL"; then
    LAN="$(ip_lan || true)"
    MSG="Sistema de Cotización v${VERSION} listo: $URL"
    [[ -n "$LAN" ]] && MSG="$MSG  |  LAN: http://${LAN}:${WEB_PORT}/sistema_cotizacion.html"
    aviso "$MSG"
    abrir
    exit 0
  fi
  sleep 0.5
done

aviso "Arranque incompleto. Revisa $LOG"
exit 1
