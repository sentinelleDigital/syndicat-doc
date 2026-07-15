#!/usr/bin/env bash
# Lance OpenCode en chargeant d'abord les secrets de .env.
# OpenCode ne lit pas .env tout seul → ce wrapper l'injecte dans l'environnement.
#
# Usage :
#   ./run.sh            → ouvre OpenCode (interactif)
#   ./run.sh run "..."  → exécute une requête unique
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  echo "ERREUR : .env manquant. Fais : cp .env.example .env  puis remplis-le." >&2
  exit 1
fi

set -a
source .env
set +a

exec opencode "$@"
