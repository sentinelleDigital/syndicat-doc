#!/usr/bin/env bash
# Lance l'interface web de l'Assistant Syndical.
# Double-clic (ou : ./lancer.sh). Le navigateur s'ouvre tout seul.
cd "$(dirname "$0")"
exec python3 serveur.py
