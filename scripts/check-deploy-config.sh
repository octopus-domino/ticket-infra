#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
port="${CODOC_NGINX_APP_PORT:-8090}"
[[ "$port" =~ ^[0-9]{1,5}$ ]] && ((10#$port > 0 && 10#$port <= 65535)) || {
  echo 'Invalid application upstream port.' >&2; exit 1;
}
for name in APP_POETRY_POEMSHIP_URL APP_POETRY_POETREE_URL; do
  value="${!name:-}"
  # Fixed operator configuration, never a request parameter. Avoid credentials in URLs.
  [[ -z "$value" || "$value" =~ ^https://[a-zA-Z0-9.-]+(:[0-9]{1,5})?(/[a-zA-Z0-9._~/-]*)?$ ]] || {
    echo "Invalid HTTPS endpoint in $name (credentials/query strings are not allowed)." >&2; exit 1;
  }
done
for file in "$ROOT/deploy.sh" "$ROOT/scripts/deploy-postgres.sh" "$ROOT/scripts/install-external-nginx.sh"; do
  bash -n "$file"
done
[[ "${CODOC_UPDATE_EXTERNAL_NGINX:-false}" == true || "${CODOC_UPDATE_EXTERNAL_NGINX:-false}" == false ]] || {
  echo 'CODOC_UPDATE_EXTERNAL_NGINX must be true or false.' >&2; exit 1;
}
[[ "${CODOC_WALK_MCP_ENABLED:-false}" == true || "${CODOC_WALK_MCP_ENABLED:-false}" == false ]] || {
  echo 'CODOC_WALK_MCP_ENABLED must be true or false.' >&2; exit 1;
}
if [[ "${CODOC_UPDATE_EXTERNAL_NGINX:-false}" == true && $EUID != 0 ]]; then
  sudo -n true || { echo 'External Nginx update requires noninteractive sudo; no services were stopped.' >&2; exit 1; }
fi
echo 'Deployment configuration checked; no services were changed.'
