#!/usr/bin/env bash
# Levanta en esta PC los TRES nodos del traspaso de ofertas por el MCP:
#   Sistema de Cotización          http://127.0.0.1:8090  (API :8100)
#   Control de Proyecto (SBC)      http://127.0.0.1:8080  (API :8000)
#   MASTER CONTROL PROJECT (MCP)   http://127.0.0.1:8081  (API :8001)
# Cada uno con su propia BD, SECRET_KEY y cuentas (ING-COT-003 §6).
# La primera vez, enlázalos con enrolar-mcp-local.sh.
#
# Busca Control de Proyecto en CONTROL_PROYECTO_DIR o junto a este repositorio.
set -euo pipefail
AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAIZ="$(cd "$AQUI/../.." && pwd)"
CP="${CONTROL_PROYECTO_DIR:-$(cd "$RAIZ/.." && pwd)/oriol-control-de-proyecto}"
DEV="$CP/Instalacion/desarrollo"

if [[ ! -x "$DEV/levantar.sh" ]]; then
  echo "No encuentro Control de Proyecto en $CP." >&2
  echo "Clónalo al lado de este repositorio o define CONTROL_PROYECTO_DIR." >&2
  exit 1
fi

arriba() { curl -fsS -o /dev/null "$1" 2>/dev/null; }

"$AQUI/levantar.sh"
# Los scripts de Control de Proyecto pueden terminar con error al calcular la
# IP de LAN (equipos sin el comando `ip`) aunque el servicio quede arriba.
"$DEV/levantar.sh" || arriba http://127.0.0.1:8000/health || { echo "Control de Proyecto no arrancó." >&2; exit 1; }
"$DEV/levantar-master.sh" || true
for _ in $(seq 1 40); do arriba http://127.0.0.1:8001/health && break; sleep 0.5; done
arriba http://127.0.0.1:8001/health || { echo "El MCP no arrancó (revisa $CP/.dev-run/master.log)." >&2; exit 1; }
"$AQUI/estado.sh"
