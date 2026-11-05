#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

# Run from anywhere: the three repositories and the existing .env live in ROOT.
ROOT="${CODOC_DEPLOY_SNAPSHOT_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)}"
# git pull may replace this very file. Execute an immutable copy outside the repos.
if [[ -z "${CODOC_DEPLOY_SNAPSHOT_ROOT:-}" ]]; then
  snapshot="$(mktemp "${TMPDIR:-/tmp}/codoc-deploy.XXXXXX")"
  trap 'rm -f -- "$snapshot"' EXIT
  cp -- "${BASH_SOURCE[0]}" "$snapshot"
  export CODOC_DEPLOY_SNAPSHOT_ROOT="$ROOT"
  bash "$snapshot" "$@"
  exit 0
fi
cd "$ROOT"
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
for command in docker git curl flock realpath tar; do command -v "$command" >/dev/null || fail "Missing command: $command"; done
exec 9>"$ROOT/.codoc-deploy.lock"
flock -n 9 || fail 'Another deployment is running.'
[[ -f .env ]] || fail "Create $ROOT/.env first; see ticket-infra/deploy.env.example"
set -a
# This is the same trusted shell-format .env used by the previous deployment script.
source .env
set +a
: "${GOOGLE_CLIENT_ID:?GOOGLE_CLIENT_ID is empty}"
: "${GOOGLE_CLIENT_SECRET:?GOOGLE_CLIENT_SECRET is empty}"
: "${JWT_SECRET:?JWT_SECRET is empty}"
[[ ${#JWT_SECRET} -ge 32 ]] || fail 'JWT_SECRET must have at least 32 characters; preserve the existing production value.'
export APP_FRONTEND_URL="${APP_FRONTEND_URL:-https://www.codoc.site}"
[[ "$APP_FRONTEND_URL" =~ ^https://[^/]+$ ]] || fail 'APP_FRONTEND_URL must be an HTTPS origin without trailing slash.'
# Existing encrypted credentials used JWT_SECRET as their fallback: do not rotate it here.
export APP_SECRETS_ENCRYPTION_KEY="${APP_SECRETS_ENCRYPTION_KEY:-$JWT_SECRET}"
export APP_CONNECTORS_ALLOWED_ORIGINS="${APP_CONNECTORS_ALLOWED_ORIGINS:-}"
export APP_RECOGNITION_OLLAMA_ENABLED=false
export JAVA_TOOL_OPTIONS="${JAVA_TOOL_OPTIONS:--Xms128m -Xmx1536m -XX:ActiveProcessorCount=2}"
export SPRING_PROFILES_ACTIVE=prod
export SPRING_JPA_HIBERNATE_DDL_AUTO=validate
export DOCKER_BUILDKIT=1
DEPLOY_CLIENT_API="${DEPLOY_CLIENT_API:-true}"
SKIP_GIT_PULL="${SKIP_GIT_PULL:-false}"
NO_CACHE="${NO_CACHE:-false}"
FIRST_INSTALL="${FIRST_INSTALL:-false}"
READY_ATTEMPTS="${READY_ATTEMPTS:-90}"
[[ "$READY_ATTEMPTS" =~ ^[1-9][0-9]{0,2}$ ]] || fail 'READY_ATTEMPTS must be a positive integer of at most three digits.'
for option in DEPLOY_CLIENT_API SKIP_GIT_PULL NO_CACHE FIRST_INSTALL; do
  [[ "${!option}" == true || "${!option}" == false ]] || fail "$option must be true or false"
done
DATA_DIR="$(realpath -m -- "${DATA_DIR:-$HOME/ticket-data}")"
BACKUP_DIR="$(realpath -m -- "${BACKUP_DIR:-$HOME/ticket-backups}")"
[[ "$DATA_DIR" != / && "$DATA_DIR" != "$ROOT" && "$DATA_DIR" != "$HOME" ]] || fail 'Choose a dedicated DATA_DIR.'
[[ "$BACKUP_DIR/" != "$DATA_DIR/"* ]] || fail 'BACKUP_DIR must be outside DATA_DIR.'
docker info >/dev/null
if docker container inspect ticket-app >/dev/null 2>&1; then
  mounted_type="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/app/data"}}{{.Type}}{{end}}{{end}}' ticket-app)"
  mounted_source="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/app/data"}}{{.Source}}{{end}}{{end}}' ticket-app)"
  [[ "$mounted_type" == bind && "$(realpath -m -- "$mounted_source")" == "$DATA_DIR" ]] || fail "Existing ticket-app uses different storage ($mounted_type: $mounted_source). Set DATA_DIR correctly; no container was stopped."
fi
if [[ ! -f "$DATA_DIR/ticket-db.mv.db" && "$FIRST_INSTALL" != true ]]; then
  fail 'Existing H2 database not found. Check DATA_DIR; only a genuinely new installation may use FIRST_INSTALL=true.'
fi
if [[ "$FIRST_INSTALL" == true && -f "$DATA_DIR/ticket-db.mv.db" ]]; then fail 'FIRST_INSTALL cannot be used with an existing database.'; fi

if [[ "$DEPLOY_CLIENT_API" == true ]]; then
  : "${TYK_ADMIN_SECRET:?Set a stable TYK_ADMIN_SECRET in .env}"
  : "${REDIS_PASSWORD:?Set a stable REDIS_PASSWORD in .env}"
  [[ ${#TYK_ADMIN_SECRET} -ge 32 && ${#REDIS_PASSWORD} -ge 32 ]] || fail 'Tyk and Redis secrets must have at least 32 characters.'
  export TYK_ADMIN_SECRET REDIS_PASSWORD
  export APP_CLIENT_API_TYK_URL=http://gateway:8081
  export APP_CLIENT_API_TYK_SECRET="$TYK_ADMIN_SECRET"
  export APP_CLIENT_API_PUBLIC_URL="${APP_CLIENT_API_PUBLIC_URL:-$APP_FRONTEND_URL/client-api}"
  docker compose version >/dev/null
else
  export APP_CLIENT_API_TYK_URL='' APP_CLIENT_API_TYK_SECRET='' APP_CLIENT_API_PUBLIC_URL=''
fi

for repo in ticket-editor ticket-pdf ticket-infra; do
  [[ -d "$repo" ]] || fail "Missing repository: $repo"
  if [[ "$SKIP_GIT_PULL" != true ]]; then
    [[ -z "$(git -C "$repo" status --porcelain)" ]] || fail "$repo has local changes. Commit/copy them deliberately or use SKIP_GIT_PULL=true for an uploaded source snapshot."
    printf '\nUpdating %s\n' "$repo"
    git -C "$repo" pull --ff-only
  fi
done
# Use the just-updated infrastructure file; all services share the existing bind-mounted app.
gateway=(docker compose --project-name codoc-gateway --env-file /dev/null -f "$ROOT/ticket-infra/compose.gateway.yml")
if [[ "$DEPLOY_CLIENT_API" == true ]]; then "${gateway[@]}" config --quiet; fi
stamp="$(date -u +%Y%m%dT%H%M%SZ)-$$"
image="ticket-fullstack:$stamp"
build=(docker build --platform linux/amd64 --progress plain -f ticket-infra/Dockerfile -t "$image" .)
if [[ "$NO_CACHE" == true ]]; then build+=(--no-cache); fi
printf '\nBuilding %s; the current app stays online during the build.\n' "$image"
"${build[@]}"
docker network inspect codoc-client-api >/dev/null 2>&1 || docker network create codoc-client-api >/dev/null
if [[ "$DEPLOY_CLIENT_API" == true ]]; then "${gateway[@]}" up -d --wait --wait-timeout 180; fi

mkdir -p -- "$DATA_DIR" "$BACKUP_DIR"
backup="$BACKUP_DIR/$stamp"
mkdir -m 700 -- "$backup"
previous=''
stopped=false
replaced=false
on_error() {
  local status=$?
  trap - ERR
  printf '\nDeployment failed (exit %s). Backup: %s\n' "$status" "$backup" >&2
  if [[ "$replaced" == true ]]; then
    docker logs --tail 80 ticket-app >&2 || true
    docker stop --time 60 ticket-app >/dev/null 2>&1 || true
    printf 'The failed new app is stopped. Previous container: %s. Do not start it against a migrated DB blindly; see rollback instructions.\n' "${previous:-none}" >&2
  elif [[ "$stopped" == true ]]; then
    docker start ticket-app >/dev/null || true
  fi
  exit "$status"
}
trap on_error ERR
if docker container inspect ticket-app >/dev/null 2>&1; then
  docker inspect -f '{{.Image}}' ticket-app > "$backup/previous-image.txt"
  docker stop --time 60 ticket-app >/dev/null
  stopped=true
fi
# Back up only after Java has stopped. Never delete an H2 lock file on a live database.
docker run --rm --network none --entrypoint /bin/sh \
  --mount "type=bind,src=$DATA_DIR,dst=/source,readonly" \
  --mount "type=bind,src=$backup,dst=/backup" "$image" \
  -ec 'tar -czf /backup/data.tgz -C /source .; chmod 600 /backup/data.tgz'
cp -- .env "$backup/deploy.env"
chmod 600 "$backup/deploy.env"
for repo in ticket-editor ticket-pdf ticket-infra; do
  if git -C "$repo" rev-parse HEAD >/dev/null 2>&1; then printf '%s %s\n' "$repo" "$(git -C "$repo" rev-parse HEAD)"; fi
done > "$backup/revisions.txt"
if [[ "$stopped" == true ]]; then
  previous="ticket-app-previous-$stamp"
  docker rename ticket-app "$previous"
fi
replaced=true

env_args=()
while IFS= read -r variable; do
  case "$variable" in APP_*|SMTP_*|EMAIL_*|GOOGLE_CLIENT_ID|GOOGLE_CLIENT_SECRET|JWT_SECRET|JAVA_TOOL_OPTIONS|SPRING_PROFILES_ACTIVE|SPRING_JPA_HIBERNATE_DDL_AUTO) env_args+=(--env "$variable");; esac
done < <(compgen -e)
launch() {
  docker run -d --name ticket-app --restart unless-stopped \
    --network codoc-client-api --network-alias app \
    --cpus 2 --memory 2304m --memory-swap 3072m \
    --log-driver json-file --log-opt max-size=20m --log-opt max-file=3 \
    -p 127.0.0.1:8080:80 \
    --mount "type=bind,src=$DATA_DIR,dst=/app/data" \
    "${env_args[@]}" "$image" >/dev/null
}
ready() {
  local attempt
  for ((attempt=1; attempt<=READY_ATTEMPTS; attempt++)); do
    if docker exec ticket-app curl -fsS --max-time 3 http://127.0.0.1:8080/api/guest/recognition/capabilities >/dev/null 2>&1 \
      && curl -fsS --max-time 3 http://127.0.0.1:8080/ >/dev/null 2>&1; then return 0; fi
    sleep 2
  done
  return 1
}
if [[ "$FIRST_INSTALL" == true ]]; then
  export SPRING_JPA_HIBERNATE_DDL_AUTO=update
  launch
  ready
  docker stop --time 60 ticket-app >/dev/null
  docker rm ticket-app >/dev/null
  export SPRING_JPA_HIBERNATE_DDL_AUTO=validate
fi
launch
ready
languages="$(docker exec ticket-app tesseract --list-langs 2>&1)"
printf '%s\n' "$languages" | tee "$backup/ocr-languages.txt"
if [[ $'\n'"$languages"$'\n' != *$'\neng\n'* || $'\n'"$languages"$'\n' != *$'\nrus\n'* ]]; then
  printf 'Tesseract must include both eng and rus.\n' >&2
  false
fi
docker image tag "$image" ticket-fullstack:latest
printf '\nLocal app is ready. Image: %s\nBackup: %s\nPrevious container: %s\n' "$image" "$backup" "${previous:-none}"
trap - ERR

# TLS is terminated by the external Nginx. Fail visibly without rolling back a healthy local app.
if ! curl -fsS --max-time 30 "$APP_FRONTEND_URL/api/guest/recognition/capabilities"; then
  printf '\nLocal app is ready, but the public HTTPS check failed. Check external Nginx/DNS/TLS.\n' >&2
  exit 2
fi
printf '\nHTTPS preflight (Origin has no trailing slash):\n'
curl -fsS --max-time 30 -X OPTIONS \
  -H "Origin: $APP_FRONTEND_URL" -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: content-type' -D - -o /dev/null \
  "$APP_FRONTEND_URL/api/auth/refresh"
if [[ "$DEPLOY_CLIENT_API" == true ]]; then
  code="$(curl -sS --max-time 30 -o /dev/null -w '%{http_code}' "$APP_CLIENT_API_PUBLIC_URL/recognition/capabilities")"
  [[ "$code" == 401 || "$code" == 403 ]] || fail "Client API without a key returned $code (expected 401/403). Check Nginx /client-api/ and Tyk."
fi
printf '\nDeployment complete. Keep the stopped previous container and backup until acceptance.\n'
