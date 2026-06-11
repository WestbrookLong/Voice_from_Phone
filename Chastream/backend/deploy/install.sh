#!/usr/bin/env bash
set -euo pipefail

DEPLOY_PATH="${1:-/home/ubuntu/projects/chastream-mobile}"
BACKEND_PATH="$DEPLOY_PATH/backend"
SHARED_PATH="$DEPLOY_PATH/shared"

mkdir -p "$SHARED_PATH" "$SHARED_PATH/data"

if [[ ! -f "$SHARED_PATH/.env" ]]; then
  cp "$BACKEND_PATH/.env.example" "$SHARED_PATH/.env"
  chmod 600 "$SHARED_PATH/.env"
  echo "Created $SHARED_PATH/.env. Configure secrets before starting the service."
fi

sudo apt-get update
sudo apt-get install -y python3-venv python3-dev build-essential ffmpeg libsndfile1 libportaudio2

python3 -m venv "$BACKEND_PATH/.venv"
"$BACKEND_PATH/.venv/bin/pip" install --upgrade pip wheel
"$BACKEND_PATH/.venv/bin/pip" install -r "$BACKEND_PATH/requirements-api.txt"
"$BACKEND_PATH/.venv/bin/pip" install -r "$BACKEND_PATH/requirements-worker.txt"

SERVICE_TMP="$(mktemp)"
sed "s|__DEPLOY_PATH__|$DEPLOY_PATH|g" \
  "$BACKEND_PATH/deploy/chastream-mobile.service" > "$SERVICE_TMP"
sudo install -m 0644 "$SERVICE_TMP" /etc/systemd/system/chastream-mobile.service
rm -f "$SERVICE_TMP"

sudo install -m 0644 \
  "$BACKEND_PATH/deploy/nginx-location.conf" \
  /etc/nginx/snippets/chastream-location.conf

NGINX_SITE="/etc/nginx/sites-available/moneyage-backend"
if ! sudo grep -q "snippets/chastream-location.conf" "$NGINX_SITE"; then
  sudo cp "$NGINX_SITE" "$NGINX_SITE.bak.$(date +%Y%m%d%H%M%S)"
  SITE_TMP="$(mktemp)"
  python3 - "$NGINX_SITE" "$SITE_TMP" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_text(encoding="utf-8")
needle = "    location / {\n"
if needle not in source:
    raise SystemExit("Unable to locate the default Nginx location block.")
updated = source.replace(
    needle,
    "    include /etc/nginx/snippets/chastream-location.conf;\n\n" + needle,
    1,
)
Path(sys.argv[2]).write_text(updated, encoding="utf-8")
PY
  sudo install -m 0644 "$SITE_TMP" "$NGINX_SITE"
  rm -f "$SITE_TMP"
fi

sudo nginx -t
sudo systemctl daemon-reload
sudo systemctl enable chastream-mobile.service
sudo systemctl reload nginx

echo "Installation complete. Configure $SHARED_PATH/.env, then start the service."
