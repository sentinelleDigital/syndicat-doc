#!/usr/bin/env bash
# Assistant Syndical — Linux et macOS.
# Double-clic sur l'icône du bureau, ou : ./lancer.sh
# Toute la logique est dans demarrer.py ; ce fichier ne fait que l'atteindre.
cd "$(dirname "$0")"

for PY in python3 python; do
  if command -v "$PY" >/dev/null 2>&1; then
    exec "$PY" demarrer.py "$@"
  fi
done

echo
echo "  Python n'est pas installé sur cet ordinateur."
echo "  L'assistant en a besoin. Installation :"
echo
echo "    Debian, Ubuntu, Mint :  sudo apt install python3"
echo "    Fedora               :  sudo dnf install python3"
echo "    macOS                :  brew install python"
echo
read -r -p "  Appuyer sur Entrée pour fermer. " _
exit 1
