#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
workspace_dir="$(dirname -- "$script_dir")"

# Cache mounts are a BuildKit feature. A Dockerfile cannot enable the builder itself.
export DOCKER_BUILDKIT=1

exec docker build \
  --progress=plain \
  --file "$script_dir/Dockerfile" \
  --tag "${CODOC_IMAGE:-ticket-editor:stabilized}" \
  "$@" \
  "$workspace_dir"
