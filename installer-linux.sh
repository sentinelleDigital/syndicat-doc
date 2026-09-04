#!/usr/bin/env bash
# Pose une icône « Assistant Syndical » dans le menu et sur le bureau.
# À lancer une seule fois :  ./installer-linux.sh
# Le chemin est détecté automatiquement : le dossier peut être n'importe où.
set -e
DOSSIER="$(cd "$(dirname "$0")" && pwd)"
CIBLE="$HOME/.local/share/applications/assistant-syndical.desktop"
mkdir -p "$(dirname "$CIBLE")"

cat > "$CIBLE" <<EOF
[Desktop Entry]
Type=Application
Name=Assistant Syndical
Comment=Assistant documentaire syndical — CCN 3029 + Code du travail
Exec=$DOSSIER/lancer.sh
Path=$DOSSIER
Icon=text-x-generic
Terminal=true
Categories=Office;Utility;
EOF

chmod +x "$CIBLE" "$DOSSIER/lancer.sh"
BUREAU="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Bureau")"
if [ -d "$BUREAU" ]; then
  cp "$CIBLE" "$BUREAU/Assistant Syndical.desktop"
  chmod +x "$BUREAU/Assistant Syndical.desktop"
  # GNOME exige que le lanceur soit marqué « de confiance »
  gio set "$BUREAU/Assistant Syndical.desktop" metadata::trusted true 2>/dev/null || true
  echo "  Icône posée sur le bureau : $BUREAU"
fi
echo "  Icône ajoutée au menu des applications."
echo "  L'outil peut aussi se lancer par : $DOSSIER/lancer.sh"
