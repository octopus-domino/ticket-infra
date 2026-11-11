#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/ticket-infra/scripts/lib/low-memory-build.sh"
command -v flock >/dev/null || { echo 'Install flock (util-linux).' >&2; exit 1; }
exec 9>"$ROOT/.codoc-deploy.lock"
flock -n 9 || { echo 'Another deployment is running.' >&2; exit 1; }
codoc_build_preflight
codoc_capture_running
finish() {
  local status=$?; trap - EXIT
  if ! codoc_stop_builder; then echo 'Could not stop builder. CoDoc remains stopped to avoid memory overlap.' >&2; exit 1; fi
  codoc_restore_running
  exit "$status"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
echo 'Stopping CoDoc during the local build; the previous containers will be restarted afterwards.'
codoc_stop_stack
codoc_prepare_builder
codoc_build_image "${CODOC_IMAGE:-codoc-app}" "${CODOC_BUILD_TARGET:-runtime}" "$@"
