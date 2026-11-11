#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
command -v flock >/dev/null || { echo 'Install flock (util-linux) before migration.'; exit 1; }
exec 9>"$ROOT/.codoc-deploy.lock"
flock -n 9 || { echo 'Another deployment or migration is running.'; exit 1; }
[[ ${1:-} == --migrate ]] || { echo 'Usage: ticket-infra/scripts/migrate-postgres.sh --migrate'; exit 2; }
[[ -f .env ]] || { echo 'Missing deployment .env'; exit 1; }
[[ ! -f .postgres.env ]] || { echo 'This installation already uses PostgreSQL. Use scripts/deploy-postgres.sh.'; exit 1; }
set -a; source .env; set +a
h2_file="${H2_FILE_NAME:-ticket-db.mv.db}"
[[ "$h2_file" =~ ^[a-zA-Z0-9._-]+\.mv\.db$ ]] || { echo 'H2_FILE_NAME must be a database basename ending in .mv.db.'; exit 1; }
export H2_MIGRATION_URL="${H2_MIGRATION_URL:-jdbc:h2:file:/legacy/${h2_file%.mv.db};IFEXISTS=TRUE;ACCESS_MODE_DATA=r;FILE_LOCK=NO}"
if docker container inspect ticket-app >/dev/null 2>&1; then
  existing_mount="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/app/data"}}{{.Source}}{{end}}{{end}}' ticket-app)"
  mount_type="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/app/data"}}{{.Type}}{{end}}{{end}}' ticket-app)"
  [[ "$mount_type" == bind && -n "$existing_mount" && -f "$existing_mount/$h2_file" ]] || { echo 'The existing ticket-app storage must be reviewed before migration.'; exit 1; }
  export CODOC_APP_STORAGE="$existing_mount"
  export CODOC_HTTP_PORT=8080
fi
: "${DATABASE_PASSWORD:?Set a new PostgreSQL password in .env; preserve existing JWT_SECRET and encryption key}"
export APP_SECRETS_ENCRYPTION_KEY="${APP_SECRETS_ENCRYPTION_KEY:-${JWT_SECRET:?Preserve JWT_SECRET}}"
export CLIENT_API_PUBLIC_URL="${CLIENT_API_PUBLIC_URL:-${APP_CLIENT_API_PUBLIC_URL:-${APP_FRONTEND_URL:?Preserve APP_FRONTEND_URL}/client-api}}"
docker network inspect codoc-client-api >/dev/null 2>&1 || docker network create codoc-client-api >/dev/null
COMPOSE=(docker compose --env-file .env -f ticket-infra/compose.api.yml -f ticket-infra/compose.postgres.yml)
stamp="$(date -u +%Y%m%dT%H%M%SZ)-$$"
backup="$ROOT/backups/postgres-$stamp"
mkdir -p "$backup"
old_image=''
old_container="$(docker compose --env-file .env -f ticket-infra/compose.api.yml ps -a -q app)"
if [[ -z "$old_container" ]] && docker container inspect ticket-app >/dev/null 2>&1; then old_container=ticket-app; fi
if [[ -n "$old_container" ]]; then
  old_image="$(docker inspect --format '{{.Image}}' "$old_container")"
  docker tag "$old_image" "codoc-before-postgres:$stamp"
  printf 'services:\n  app:\n    image: codoc-before-postgres:%s\n' "$stamp" > "$backup/rollback.yml"
fi
source "$ROOT/ticket-infra/scripts/lib/low-memory-build.sh"
codoc_build_preflight
codoc_capture_running
bootstrap=''
migration_started=false
cleanup_bootstrap() {
  if [[ -n "$bootstrap" ]]; then docker rm -f "$bootstrap" >/dev/null 2>&1 || true; fi
}
finish() {
  local status=$?; trap - EXIT; cleanup_bootstrap
  if ! codoc_stop_builder; then echo 'Could not stop builder. CoDoc remains stopped; inspect Docker before restarting it.' >&2; exit 1; fi
  if ((status != 0)); then
    if [[ "$migration_started" == false ]]; then
      "${COMPOSE[@]}" stop postgres >/dev/null 2>&1 || true
      codoc_restore_running
      echo "Migration stopped before data import. Previous containers restored. H2 backup: $backup" >&2
    else
      "${COMPOSE[@]}" stop app >/dev/null 2>&1 || true
      echo "Migration needs review. Application remains stopped to avoid writes to two databases. Backup: $backup" >&2
    fi
  fi
  exit "$status"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
codoc_stop_stack
# Create the H2 backup BEFORE building and without requiring a newly built image.
if [[ -n "$old_container" ]]; then
  docker run --rm --network none --memory 128m --memory-swap 128m --cpus 0.5 \
    --entrypoint sh --volumes-from "$old_container:ro" -e "H2_FILE_NAME=$h2_file" -v "$backup:/backups" "$old_image" \
    -c 'test -f "/app/data/$H2_FILE_NAME" && umask 077 && tar -C /app/data -czf /backups/h2-data.tar.gz .'
else
  storage="${CODOC_APP_STORAGE:-codoc_app-data}"
  if [[ "$storage" == /* ]]; then source_mount="type=bind,src=$storage,dst=/source,readonly";
  else docker volume inspect "$storage" >/dev/null; source_mount="type=volume,src=$storage,dst=/source,readonly"; fi
  docker run --rm --network none --memory 128m --memory-swap 128m --cpus 0.5 \
    --mount "$source_mount" -e "H2_FILE_NAME=$h2_file" -v "$backup:/backups" busybox:1.37 \
    sh -c 'test -f "/source/$H2_FILE_NAME" && umask 077 && tar -C /source -czf /backups/h2-data.tar.gz .'
fi
cp -- .env "$backup/deploy.env"
if [[ -n "${CODOC_APP_STORAGE:-}" ]]; then
  printf 'CODOC_APP_STORAGE=%q\n' "$CODOC_APP_STORAGE" > "$backup/storage.env"
fi
printf 'CODOC_APP_STORAGE=%q\nCODOC_HTTP_PORT=%q\nSPRING_PROFILES_ACTIVE=prod,postgres\n' "${CODOC_APP_STORAGE:-app-data}" "${CODOC_HTTP_PORT:-8090}" > "$backup/postgres.env.pending"
if [[ "${CODOC_BUILD_ON_HOST:-true}" == true ]]; then
  codoc_prepare_builder
  codoc_build_image codoc-app runtime
  codoc_build_image codoc-migration migration
else
  docker image inspect codoc-app >/dev/null
  docker image inspect codoc-migration >/dev/null
fi
codoc_stop_builder
"${COMPOSE[@]}" up -d --wait postgres
bootstrap="codoc-pg-bootstrap-$stamp-$$"
"${COMPOSE[@]}" run -d --no-deps --name "$bootstrap" \
  -e SPRING_JPA_HIBERNATE_DDL_AUTO=update \
  -e 'JAVA_TOOL_OPTIONS=-Xms64m -Xmx512m -XX:MaxDirectMemorySize=64m -XX:ActiveProcessorCount=2' app >/dev/null
ready=false
for attempt in $(seq 1 90); do
  status="$(docker exec "$bootstrap" sh -c 'curl -s --max-time 3 -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/actuator/health' 2>/dev/null || true)"
  if [[ "$status" == 200 || "$status" == 401 ]]; then ready=true; break; fi
  sleep 2
done
if [[ "$ready" != true ]]; then docker logs --tail 80 "$bootstrap"; echo "Schema initialization failed. H2 backup: $backup"; exit 1; fi
cleanup_bootstrap
bootstrap=''
migration_started=true
"${COMPOSE[@]}" run --rm migration | tee "$backup/migration.log"
"${COMPOSE[@]}" exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 --single-transaction -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < ticket-pdf/src/main/resources/db/upgrade-workflows.sql
"${COMPOSE[@]}" exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "$backup/postgres-after.dump"
mv -- "$backup/postgres.env.pending" "$ROOT/.postgres.env"
codoc_start_postgres_app
printf 'Migration finished. Backups and rollback configuration: %s\n' "$backup"
printf 'Use scripts/deploy-postgres.sh for future updates; do not restart the old H2 app.\n'
