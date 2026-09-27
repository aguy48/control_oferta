#!/usr/bin/env bash
# Detiene el Sistema de Cotización de desarrollo (no borra datos).
# No toca Control de Proyecto (:8000/:8080) ni el MASTER (:8001/:8081).
set -euo pipefail
AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAIZ="$(cd "$AQUI/../.." && pwd)"
RUN="$RAIZ/.dev-run"
API_PORT="${COTIZACION_API_PORT:-8100}"
WEB_PORT="${COTIZACION_WEB_PORT:-8090}"

bajar() {
  local f="$1"
  if [[ -f "$f" ]]; then
    kill "$(cat "$f")" 2>/dev/null || true
    rm -f "$f"
  fi
}

bajar "$RUN/api.pid"
bajar "$RUN/web.pid"
# Por si quedaron procesos sin pidfile (patrón con [] para no coincidir consigo mismo).
pkill -f "[u]vicorn app.main:app --host .* --port ${API_PORT}" 2>/dev/null || true
pkill -f "[s]ervir-frontend.py --root .* --port ${WEB_PORT}" 2>/dev/null || true

echo "Sistema de Cotización (desarrollo) detenido."
