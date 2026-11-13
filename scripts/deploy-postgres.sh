#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
command -v flock >/dev/null || { echo 'Install flock (util-linux) before deployment.'; exit 1; }
exec 9>"$ROOT/.codoc-deploy.lock"
flock -n 9 || { echo 'Another deployment or migration is running.'; exit 1; }
[[ -f .env && -f .postgres.env ]] || { echo 'Run the PostgreSQL migration first; preserve .env and .postgres.env.'; exit 1; }
set -a; source .env; source .postgres.env; set +a
: "${DATABASE_PASSWORD:?Set DATABASE_PASSWORD}"
export APP_SECRETS_ENCRYPTION_KEY="${APP_SECRETS_ENCRYPTION_KEY:-${JWT_SECRET:?Preserve JWT_SECRET}}"
export CLIENT_API_PUBLIC_URL="${CLIENT_API_PUBLIC_URL:-${APP_CLIENT_API_PUBLIC_URL:-${APP_FRONTEND_URL:?Preserve APP_FRONTEND_URL}/client-api}}"
docker network inspect codoc-client-api >/dev/null 2>&1 || docker network create codoc-client-api >/dev/null
COMPOSE=(docker compose --env-file .env -f ticket-infra/compose.api.yml -f ticket-infra/compose.postgres.yml)
# Validate interpolation before stopping services; --quiet never prints secrets.
"${COMPOSE[@]}" config --quiet
export CODOC_NGINX_APP_PORT="${CODOC_HTTP_PORT:-8090}"
bash "$ROOT/ticket-infra/scripts/check-deploy-config.sh"
source "$ROOT/ticket-infra/scripts/lib/low-memory-build.sh"
codoc_build_preflight
codoc_capture_running
backup="$ROOT/backups/postgres-deploy-$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$backup"
database_changed=false
app_ready=false
finish() {
  local status=$?; trap - EXIT
  if ! codoc_stop_builder; then echo 'Could not stop builder. CoDoc remains stopped; inspect Docker before restarting it.' >&2; exit 1; fi
  if ((status != 0)); then
    if [[ "$app_ready" == true ]]; then
      echo 'Application is healthy; external Nginx update failed. App remains running; inspect the Nginx rollback output.' >&2
    elif [[ "$database_changed" == false ]]; then
      "${COMPOSE[@]}" stop postgres >/dev/null 2>&1 || true
      codoc_restore_running
      echo "Update failed before schema changes. Previous containers restored. Backup: $backup" >&2
    else
      "${COMPOSE[@]}" stop app >/dev/null 2>&1 || true
      echo "Update failed after schema changes. App stays stopped; preserve $backup and follow POSTGRES-MIGRATION.md rollback instructions." >&2
    fi
  fi
  exit "$status"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
codoc_stop_apps
"${COMPOSE[@]}" up -d --wait postgres
"${COMPOSE[@]}" exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "$backup/database.dump"
cp -- .env "$backup/deploy.env"
cp -- .postgres.env "$backup/postgres.env"
old_app="$("${COMPOSE[@]}" ps -a -q app)"
if [[ -n "$old_app" ]]; then docker inspect --format '{{.Image}}' "$old_app" > "$backup/previous-image.txt"; fi
codoc_stop_stack
"${COMPOSE[@]}" stop postgres
if [[ "${CODOC_BUILD_ON_HOST:-true}" == true ]]; then
  codoc_prepare_builder
  codoc_build_image codoc-app runtime
else
  docker image inspect codoc-app >/dev/null
fi
codoc_stop_builder
"${COMPOSE[@]}" up -d --wait postgres
database_changed=true
"${COMPOSE[@]}" exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 --single-transaction -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < ticket-pdf/src/main/resources/db/upgrade-journeys.sql
"${COMPOSE[@]}" exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 --single-transaction -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < ticket-pdf/src/main/resources/db/upgrade-workflows.sql
for migration in journey-batch-owner journey-print-sources journey-albums workflow-visits poetry-sets; do
  "${COMPOSE[@]}" exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 --single-transaction -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "ticket-infra/scripts/$migration.sql"
done
codoc_start_postgres_app
app_ready=true
if [[ "${CODOC_UPDATE_EXTERNAL_NGINX:-false}" == true ]]; then
  sudo -n env CODOC_NGINX_APP_PORT="$CODOC_NGINX_APP_PORT" bash "$ROOT/ticket-infra/scripts/install-external-nginx.sh"
fi
echo "PostgreSQL deployment is healthy. Backup: $backup"
"${COMPOSE[@]}" ps
