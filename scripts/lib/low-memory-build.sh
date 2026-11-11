#!/usr/bin/env bash
# Shared by build and deployment entrypoints. The caller owns its ERR/EXIT traps.

codoc_build_preflight() {
  [[ "${CODOC_BUILD_ON_HOST:-true}" == true || "${CODOC_BUILD_ON_HOST:-true}" == false ]] || { echo 'CODOC_BUILD_ON_HOST must be true or false.' >&2; return 1; }
  docker info >/dev/null
  local total
  total="$(docker info --format '{{.MemTotal}}')"
  [[ "$total" =~ ^[0-9]+$ && "$total" -ge 3758096384 ]] || { echo 'The Docker host needs at least 3.5 GiB total memory for this 4 GB profile.' >&2; return 1; }
  docker buildx version >/dev/null || { echo 'Install Docker Buildx before stopping the application.' >&2; return 1; }
  command -v flock >/dev/null || { echo 'Install flock (util-linux).' >&2; return 1; }
  CODOC_BUILDER=codoc-lowmem-v1
  CODOC_RUNNING_IDS=()
  exec 8>"$ROOT/.codoc-build.lock"
  flock -n 8 || { echo 'Another CoDoc build is running.' >&2; return 1; }
}

codoc_capture_running() {
  local project id found all=''
  CODOC_RUNNING_IDS=()
  # Stop only this installation, never every container on the host.
  for project in codoc codoc-gateway; do
    found="$(docker ps -q --filter "label=com.docker.compose.project=$project")" || return
    all+="$found"$'\n'
  done
  found="$(docker ps -q --filter 'name=^/ticket-app$')" || return
  all+="$found"
  while IFS= read -r id; do
    [[ -n "$id" ]] && CODOC_RUNNING_IDS+=("$id")
  done < <(printf '%s\n' "$all" | sort -u)
}

codoc_stop_apps() {
  local id service name
  for id in "${CODOC_RUNNING_IDS[@]}"; do
    service="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$id")"
    name="$(docker inspect --format '{{.Name}}' "$id")"
    if [[ "$service" == app || "$name" == /ticket-app ]]; then
      docker stop --time 60 "$id" >/dev/null
    fi
  done
}

codoc_stop_stack() {
  codoc_stop_apps
  local id running
  for id in "${CODOC_RUNNING_IDS[@]}"; do
    running="$(docker inspect --format '{{.State.Running}}' "$id")"
    if [[ "$running" == true ]]; then docker stop --time 60 "$id" >/dev/null; fi
  done
  # The cached builder must not keep memory while the application is running.
  codoc_stop_builder
}

codoc_restore_supporting() {
  local id service name phase
  # Restore databases/Redis before their clients. Starting an already running container is safe.
  for phase in storage clients; do
  for id in "${CODOC_RUNNING_IDS[@]}"; do
    service="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$id" 2>/dev/null)" || continue
    name="$(docker inspect --format '{{.Name}}' "$id" 2>/dev/null)" || continue
    if [[ "$service" == app || "$name" == /ticket-app ]]; then continue; fi
    if [[ "$phase" == storage && "$service" != postgres && "$service" != redis ]]; then continue; fi
    if [[ "$phase" == clients && ( "$service" == postgres || "$service" == redis ) ]]; then continue; fi
    docker start "$id" >/dev/null || true
  done
  done
}

codoc_restore_running() {
  codoc_restore_supporting
  local id service name
  for id in "${CODOC_RUNNING_IDS[@]}"; do
    service="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$id" 2>/dev/null)" || continue
    name="$(docker inspect --format '{{.Name}}' "$id" 2>/dev/null)" || continue
    if [[ "$service" == app || "$name" == /ticket-app ]]; then docker start "$id" >/dev/null || true; fi
  done
}

codoc_start_postgres_app() {
  local legacy_gateway
  legacy_gateway="$(docker ps -a -q --filter label=com.docker.compose.project=codoc-gateway --filter label=com.docker.compose.service=gateway)"
  if [[ -n "$legacy_gateway" ]]; then
    # Retain the existing gateway's Redis volume and client API keys.
    "${COMPOSE[@]}" up -d --no-build --wait --wait-timeout 300 app
    codoc_restore_supporting
  else
    "${COMPOSE[@]}" up -d --no-build --wait --wait-timeout 300 app gateway
  fi
}

codoc_check_build_memory() {
  local meminfo="${CODOC_MEMINFO_FILE:-/proc/meminfo}" available
  if [[ ! -r "$meminfo" ]]; then
    echo 'Cannot read host MemAvailable. Use these build scripts on the Linux Docker host.' >&2
    return 1
  fi
  available="$(awk '/^MemAvailable:/ {print int($2/1024)}' "$meminfo")"
  if [[ ! "$available" =~ ^[0-9]+$ || "$available" -lt 2816 ]]; then
    echo "At least 2816 MiB MemAvailable is needed before starting the 2304 MiB builder (available: ${available:-unknown})." >&2
    echo 'Stop other heavy workloads and retry. CoDoc has not changed any database schema.' >&2
    return 1
  fi
}

codoc_prepare_builder() {
  codoc_check_build_memory
  if ! docker buildx inspect "$CODOC_BUILDER" >/dev/null 2>&1; then
    docker buildx create --name "$CODOC_BUILDER" --driver docker-container \
      --driver-opt memory=2304m --driver-opt memory-swap=2304m \
      --driver-opt cpu-period=100000 --driver-opt cpu-quota=200000 \
      --config "$ROOT/ticket-infra/buildkitd-low-memory.toml" >/dev/null
  fi
  CODOC_BUILDER_PAUSED=false
  docker buildx inspect "$CODOC_BUILDER" --bootstrap >/dev/null
  local limits
  limits="$(docker inspect --format '{{.HostConfig.Memory}}:{{.HostConfig.MemorySwap}}:{{.HostConfig.CpuPeriod}}:{{.HostConfig.CpuQuota}}' "buildx_buildkit_${CODOC_BUILDER}0")"
  if [[ "$limits" != 2415919104:2415919104:100000:200000 ]]; then
    echo "Unexpected limits on $CODOC_BUILDER. Recreate only this builder with docker buildx rm --keep-state $CODOC_BUILDER and retry." >&2
    return 1
  fi
}

codoc_build_image() {
  local image="$1" target="$2"; shift 2
  docker buildx build --builder "$CODOC_BUILDER" --load --progress=plain \
    --platform linux/amd64 --file "$ROOT/ticket-infra/Dockerfile" \
    --target "$target" --tag "$image" "$@" "$ROOT"
}

codoc_stop_builder() {
  if [[ "${CODOC_BUILDER_PAUSED:-false}" == true ]]; then return 0; fi
  local name="${CODOC_BUILDER:-codoc-lowmem-v1}" container running
  container="$(docker ps -a -q --filter "name=^/buildx_buildkit_${name}0$")" || return 1
  if [[ -n "$container" ]]; then
    docker buildx stop "$name" >/dev/null || return 1
    running="$(docker inspect --format '{{.State.Running}}' "$container")" || return 1
    [[ "$running" == false ]] || { echo 'Builder is still running; application must remain stopped.' >&2; return 1; }
  fi
  CODOC_BUILDER_PAUSED=true
}
