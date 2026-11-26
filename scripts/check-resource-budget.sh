#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "${1:-}" == --compose ]]; then
  shift
  script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
  docker compose "$@" config --format json | python3 "$script_dir/check_resource_budget.py"
  exit
fi
echo 'Host memory (MiB):'
free -m
mapfile -t containers < <(docker ps -q)
if ((${#containers[@]})); then
  echo 'All running containers, including services outside the CoDoc compose project:'
  docker stats --no-stream "${containers[@]}"
  docker inspect --format '{{.Name}} memory_limit_bytes={{.HostConfig.Memory}} oom_killed={{.State.OOMKilled}}' "${containers[@]}"
fi
echo 'Also review the kernel journal for OOM events; a snapshot cannot prove peak memory safety.'
