#!/usr/bin/env bash
# Levanta los DOS sistemas en esta PC para probar el traspaso de ofertas:
#   Sistema de Cotización   http://127.0.0.1:8090  (API :8100)
#   Control de Proyecto     http://127.0.0.1:8080  (API :8000)
# Cada uno con su propia BD, SECRET_KEY y cuentas (ING-COT-003 §6).
#
# Busca el repositorio de Control de Proyecto en CONTROL_PROYECTO_DIR o, si
# no está definido, junto a este repositorio (../oriol-control-de-proyecto).
set -euo pipefail
AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAIZ="$(cd "$AQUI/../.." && pwd)"
CP="${CONTROL_PROYECTO_DIR:-$(cd "$RAIZ/.." && pwd)/oriol-control-de-proyecto}"

if [[ ! -x "$CP/Instalacion/desarrollo/levantar.sh" ]]; then
  echo "No encuentro Control de Proyecto en $CP." >&2
  echo "Clónalo al lado de este repositorio o define CONTROL_PROYECTO_DIR." >&2
  exit 1
fi

"$AQUI/levantar.sh"
"$CP/Instalacion/desarrollo/levantar.sh"
"$AQUI/estado.sh"
