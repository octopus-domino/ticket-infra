#!/usr/bin/env bash
# Publish the checked-out Ostrovok adapter on the existing Compose service.
set -Eeuo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
git diff --quiet HEAD -- mcp/ostrovok/server.py
container="$(docker ps -q --filter label=com.docker.compose.project=codoc --filter label=com.docker.compose.service=ostrovok-mcp)"
[[ -n "$container" && "$container" != *$'\n'* ]] || { echo 'Expected one running Ostrovok service.' >&2; exit 1; }
work="$(mktemp -d)"
target=/srv/mcp/server.py
docker cp "$container:$target" "$work/previous.py"
docker exec -i "$container" python -c 'import ast,sys; ast.parse(sys.stdin.buffer.read())' < mcp/ostrovok/server.py
rollback() {
    status=$?
    trap - EXIT
    if ((status != 0)); then
        docker cp "$work/previous.py" "$container:$target" && docker restart "$container" >/dev/null || true
    fi
    rm -f -- "$work/previous.py"
    rmdir -- "$work"
    exit "$status"
}
trap rollback EXIT
docker cp mcp/ostrovok/server.py "$container:$target"
docker restart "$container" >/dev/null
for ((attempt=0; attempt<20; attempt++)); do
    if docker exec "$container" wget -q -T 2 -O /dev/null http://127.0.0.1:8192/health; then
        docker commit "$container" codoc-ostrovok-mcp:latest >/dev/null
        bash "$root/scripts/lib/post-deploy-docker-cleanup.sh"
        echo "Ostrovok adapter published in $container"
        exit 0
    fi
    sleep 1
done
echo 'Ostrovok health check failed.' >&2
exit 1
