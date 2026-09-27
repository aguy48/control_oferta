#!/usr/bin/env bash
# Instala el ícono del Sistema de Cotización en el escritorio y en el menú de
# aplicaciones (GNOME/KDE). Mismo esquema que Control de Proyecto: el lanzador
# real vive en ~/.local/bin (sin espacios en la ruta, que GNOME rechaza).
# El ícono es el logo oficial de ORIOL (Frontend/assets/logo-oriol.png), sin alterar.
set -euo pipefail
AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAIZ="$(cd "$AQUI/../.." && pwd)"
ICONO_ORIG="$RAIZ/Frontend/assets/logo-oriol.png"
EXEC="$AQUI/levantar.sh"
DESKTOP_NOMBRE="sistema-cotizacion-dev.desktop"
LANZADOR="$HOME/.local/bin/sistema-cotizacion-dev"
ICONO_NOMBRE="sistema-cotizacion-dev"
ICONO_DEST="$HOME/.local/share/icons/hicolor/256x256/apps/${ICONO_NOMBRE}.png"

chmod +x "$AQUI/levantar.sh" "$AQUI/detener.sh" "$AQUI/estado.sh" "$AQUI/instalar-icono.sh" \
  "$AQUI/levantar-con-control-proyecto.sh"

ESCRITORIO="${XDG_DESKTOP_DIR:-}"
if [[ -z "$ESCRITORIO" ]] && [[ -f "$HOME/.config/user-dirs.dirs" ]]; then
  # shellcheck disable=SC1090
  . "$HOME/.config/user-dirs.dirs"
  ESCRITORIO="${XDG_DESKTOP_DIR:-}"
fi
ESCRITORIO="${ESCRITORIO:-$HOME/Escritorio}"
[[ -d "$ESCRITORIO" ]] || ESCRITORIO="$HOME/Desktop"
mkdir -p "$ESCRITORIO" "$HOME/.local/share/applications" "$(dirname "$LANZADOR")" "$(dirname "$ICONO_DEST")"

cat >"$LANZADOR" <<EOF2
#!/usr/bin/env bash
exec $(printf '%q' "$EXEC") "\$@"
EOF2
chmod +x "$LANZADOR"
cp "$ICONO_ORIG" "$ICONO_DEST"

escribir() {
  cat >"$1" <<EOF2
[Desktop Entry]
Version=1.0
Type=Application
Name=Sistema de Cotización (desarrollo)
Comment=Levanta backend :8100 y frontend :8090 en esta máquina
Exec=$LANZADOR
Icon=$ICONO_NOMBRE
Terminal=false
Categories=Development;
StartupNotify=true
EOF2
  chmod +x "$1"
}

DEST_ESCRITORIO="$ESCRITORIO/$DESKTOP_NOMBRE"
escribir "$DEST_ESCRITORIO"
escribir "$HOME/.local/share/applications/$DESKTOP_NOMBRE"

if command -v gio >/dev/null 2>&1; then
  gio set -t string "$DEST_ESCRITORIO" metadata::trusted true 2>/dev/null \
    || gio set "$DEST_ESCRITORIO" metadata::trusted true 2>/dev/null || true
fi
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo "Ícono instalado en: $DEST_ESCRITORIO"
echo "Lanzador: $LANZADOR"
echo "Doble clic para levantar el Sistema de Cotización. Para parar: $AQUI/detener.sh"
