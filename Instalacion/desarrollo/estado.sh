#!/usr/bin/env bash
# Estado del Sistema de Cotización y, si está levantado, de Control de Proyecto.
set -uo pipefail
API_PORT="${COTIZACION_API_PORT:-8100}"
WEB_PORT="${COTIZACION_WEB_PORT:-8090}"
LAN="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i <= NF; i++) if ($i == "src") { print $(i + 1); exit }}')"

api() { curl -fsS "$1" 2>/dev/null || echo "no responde"; }
html() { local c; c="$(curl -s -o /dev/null -w '%{http_code}' "$1" 2>/dev/null)"; [[ "$c" == "200" ]] && echo 200 || echo "no responde"; }

echo "Cotización API :${API_PORT}            $(api "http://127.0.0.1:${API_PORT}/health")"
echo "Cotización HTML :${WEB_PORT}           $(html "http://127.0.0.1:${WEB_PORT}/sistema_cotizacion.html")"
echo "Control de Proyecto API :8000   $(api http://127.0.0.1:8000/health)"
echo "Control de Proyecto HTML :8080  $(html http://127.0.0.1:8080/control_de_proyecto_app.html)"
[[ -n "$LAN" ]] && echo "LAN Cotización  http://${LAN}:${WEB_PORT}/sistema_cotizacion.html"
exit 0
