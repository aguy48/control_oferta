#!/usr/bin/env bash
# Trae de Control de Proyecto los módulos que el Sistema de Cotización
# reutiliza TAL CUAL (ING-COT-003 §6), para no divergir de su identidad.
#
# Uso: Backend/herramientas/sincronizar_identity.sh /ruta/a/oriol-control-de-proyecto
#
# Después de sincronizar, corre las pruebas (pytest) antes de hacer commit.
set -euo pipefail

CP="${1:?Indica la ruta del repositorio oriol-control-de-proyecto}"
ORIGEN="$CP/Backend/app"
DESTINO="$(cd "$(dirname "$0")/../app" && pwd)"

# Copias exactas.
TAL_CUAL=(
  identity/__init__.py
  identity/escenario_ops.py
  identity/routers/auth.py
  identity/routers/escenarios.py
  identity/routers/usuarios.py
  kernel/db.py
  kernel/deps.py
  plataforma/seguridad_ops.py
  plataforma/geoip_ops.py
)
for f in "${TAL_CUAL[@]}"; do
  cp "$ORIGEN/$f" "$DESTINO/$f"
  echo "copiado   $f"
done

# Copia con un ajuste: emisor TOTP propio ("Oriol COT") para que la app
# autenticadora distinga esta instancia de Control de Proyecto.
cp "$ORIGEN/kernel/security.py" "$DESTINO/kernel/security.py"
python3 - "$DESTINO/kernel/security.py" <<'PY'
import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
old = '    return f"Oriol CP - {ip}"'
new = ('    # ADAPTADO (Sistema de Cotización): emisor propio para que la app\n'
       '    # autenticadora distinga esta instancia de Control de Proyecto.\n'
       '    return f"Oriol COT - {ip}"')
if old not in s:
    sys.exit("security.py cambió en Control de Proyecto: revisa totp_issuer() a mano")
open(p, "w", encoding="utf-8").write(s.replace(old, new))
PY
echo "adaptado  kernel/security.py (emisor TOTP)"

cat <<'TXT'

Revisar a mano si Control de Proyecto cambió (NO se copian solos):
  kernel/models.py   tablas Usuario, RefreshToken, BitacoraEvento, Escenario,
                     UsuarioEscenario, BloqueoIp, AjustesSeguridad
  kernel/schemas.py  bloques Auth, Usuarios y Escenarios
  kernel/config.py   variables que leen los módulos copiados
  plataforma/telegram_ops.py, plataforma/modulos_ops.py,
  colaboracion/mailer.py  (adaptadores: misma interfaz, sin el servicio)
TXT
