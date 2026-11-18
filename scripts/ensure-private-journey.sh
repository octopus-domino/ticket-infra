#!/usr/bin/env bash
# Prepare the fourth source repository before any running service is stopped.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
target="$ROOT/private_jorney"
if [[ ! -d "$target" ]]; then
  if [[ "${SKIP_GIT_PULL:-false}" == true ]]; then
    echo 'Missing private_jorney source snapshot beside ticket-editor.' >&2; exit 1
  fi
  git clone https://github.com/octopus-domino/private-jorney.git "$target"
fi
[[ -f "$target/package-lock.json" ]] || {
  echo 'private_jorney does not contain the application source.' >&2; exit 1;
}
