#!/usr/bin/env bash
set -Eeuo pipefail
echo 'Host memory (MiB):'
free -m
mapfile -t containers < <(docker ps -q)
if ((${#containers[@]})); then
  echo 'All running containers, including services outside the CoDoc compose project:'
  docker stats --no-stream "${containers[@]}"
  docker inspect --format '{{.Name}} memory_limit_bytes={{.HostConfig.Memory}} oom_killed={{.State.OOMKilled}}' "${containers[@]}"
fi
echo 'Also review the kernel journal for OOM events; a snapshot cannot prove peak memory safety.'
