#!/usr/bin/env bash
set -euo pipefail

DEPLOY_PATH="${1:-/home/ubuntu/projects/chastream-mobile}"
BACKEND_PATH="$DEPLOY_PATH/backend"

python3 -m venv "$BACKEND_PATH/.venv"
"$BACKEND_PATH/.venv/bin/pip" install --upgrade pip wheel
"$BACKEND_PATH/.venv/bin/pip" install -r "$BACKEND_PATH/requirements-api.txt"

if [[ "${INSTALL_HEAVY_WORKER:-0}" == "1" ]]; then
  "$BACKEND_PATH/.venv/bin/pip" install -r "$BACKEND_PATH/requirements-worker.txt"
fi

sudo systemctl restart chastream-mobile.service
sleep 3
curl --fail --silent http://127.0.0.1:8010/health
echo
