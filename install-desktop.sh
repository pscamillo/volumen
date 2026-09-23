#!/usr/bin/env bash
# install-desktop.sh — put Volumen in the Linux application menu.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
D="$HOME/.local/share/applications"
mkdir -p "$D"
cat >"$D/volumen.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Volumen
Comment=Open, flatten, cut and judge Herculaneum scroll surfaces
Exec=$HERE/volumen.sh
Icon=$HERE/assets/volumen-icon.svg
Terminal=false
Categories=Science;Education;
EOF
chmod +x "$HERE/volumen.sh"
command -v update-desktop-database >/dev/null && update-desktop-database "$D" 2>/dev/null
echo "Installed: $D/volumen.desktop"
