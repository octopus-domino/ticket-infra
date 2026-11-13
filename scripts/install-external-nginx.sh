#!/usr/bin/env bash
# Called explicitly during deployment; never downloads certificates or changes enabled sites.
set -Eeuo pipefail
umask 077
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
bash "$ROOT/scripts/check-deploy-config.sh"
[[ $EUID == 0 ]] || { echo 'Run this script with sudo; pass CODOC_NGINX_APP_PORT explicitly.' >&2; exit 1; }
port="${CODOC_NGINX_APP_PORT:-8090}"
target=/etc/nginx/sites-available/codoc
[[ -f "$target" && ! -L "$target" ]] || { echo 'Expected an existing regular codoc Nginx configuration.' >&2; exit 1; }
nginx -t
backup="${target}.backup-$(date -u +%Y%m%dT%H%M%SZ)-$$"
cp -p -- "$target" "$backup"
candidate="$(mktemp /etc/nginx/sites-available/.codoc.XXXXXX)"
changed=false
finish() {
  status=$?; trap - EXIT
  rm -f -- "$candidate"
  if ((status != 0)) && [[ "$changed" == true ]]; then
    cp -p -- "$backup" "$target"
    if nginx -t; then systemctl reload nginx || true; fi
    echo "Nginx update failed; restored $backup" >&2
  fi
  exit "$status"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
sed "s@http://127.0.0.1:8090;@http://127.0.0.1:${port};@g" "$ROOT/nginx.external.conf" > "$candidate"
chmod 644 "$candidate"
changed=true
mv -- "$candidate" "$target"
nginx -t
systemctl reload nginx
echo "External Nginx updated for upstream port $port. Backup: $backup"
