#!/usr/bin/env bash
set -Eeuo pipefail
# Exercises the real dispatcher in an isolated directory. Never calls Docker or touches live data.
INFRA="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
test_root="$(mktemp -d "${TMPDIR:-/tmp}/codoc-entrypoint.XXXXXX")"
trap 'rm -rf -- "$test_root"' EXIT
mkdir -p "$test_root/bin" "$test_root/ticket-infra/scripts" "$test_root/ticket-editor" "$test_root/ticket-pdf"
cp "$INFRA/deploy.sh" "$test_root/ticket-infra/deploy.sh"
for command in docker curl git; do
  printf '#!/usr/bin/env bash\nexit 0\n' > "$test_root/bin/$command"
  chmod +x "$test_root/bin/$command"
done
printf 'SKIP_GIT_PULL=true\n' > "$test_root/.env"
touch "$test_root/.postgres.env"
cat > "$test_root/ticket-infra/scripts/deploy-postgres.sh" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
[[ "${CODOC_DEPLOY_LOCK_HELD:-}" == true ]]
[[ "${CODOC_UPDATE_EXTERNAL_NGINX:-}" == true ]]
[[ "${1:-}" == --entrypoint-test ]]
flock -n 9
printf 'PostgreSQL dispatcher and inherited lock passed.\n'
touch "${CODOC_DEPLOY_SNAPSHOT_ROOT}/passed"
SH
PATH="$test_root/bin:$PATH" bash "$test_root/ticket-infra/deploy.sh" --entrypoint-test
[[ -f "$test_root/passed" ]]
bash -n "$INFRA/deploy.sh"
bash -n "$INFRA/scripts/deploy-postgres.sh"
