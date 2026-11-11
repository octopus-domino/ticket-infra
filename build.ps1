param(
    [string]$Tag = 'codoc-app',
    [string[]]$BuildArguments = @()
)

$ErrorActionPreference = 'Stop'
Get-Command docker -ErrorAction Stop | Out-Null
$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$builderName = 'codoc-lowmem-v1'
$managedIds = @()
$deployLock = $null
$buildLock = $null
$buildExitCode = 1
function Invoke-Docker {
    & docker @args
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed (exit $LASTEXITCODE)." }
}
function Invoke-DockerOptional {
    $ErrorActionPreference = 'Continue'
    & docker @args 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}
function Get-ServiceLabel([string]$ContainerId) {
    $labels = Invoke-Docker inspect --format '{{json .Config.Labels}}' $ContainerId | ConvertFrom-Json
    return $labels.'com.docker.compose.service'
}
function Stop-LowMemoryBuilder {
    $containers = @(Invoke-Docker ps -a -q --filter "name=^/buildx_buildkit_${builderName}0$")
    if ($containers.Count -gt 0) {
        Invoke-Docker buildx stop $builderName | Out-Null
        if ((Invoke-Docker inspect --format '{{.State.Running}}' $containers[0]) -ne 'false') {
            throw 'Builder is still running. The application must remain stopped.'
        }
    }
}
try {
    $deployLock = [IO.File]::Open((Join-Path $workspaceRoot '.codoc-deploy.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    $buildLock = [IO.File]::Open((Join-Path $workspaceRoot '.codoc-build.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    Invoke-Docker buildx version | Out-Null
    $dockerMemory = [long](Invoke-Docker info --format '{{.MemTotal}}')
    if ($dockerMemory -lt 3758096384) { throw 'The Docker host needs at least 3.5 GiB total memory.' }
    foreach ($project in @('codoc', 'codoc-gateway')) {
        $managedIds += @(Invoke-Docker ps -q --filter "label=com.docker.compose.project=$project")
    }
    $managedIds += @(Invoke-Docker ps -q --filter 'name=^/ticket-app$')
    $managedIds = @($managedIds | Where-Object { $_ } | Sort-Object -Unique)
    # Stop Java before databases, retaining exactly the containers that were running.
    foreach ($id in $managedIds) {
        $service = Get-ServiceLabel $id
        $name = Invoke-Docker inspect --format '{{.Name}}' $id
        if ($service -eq 'app' -or $name -eq '/ticket-app') { Invoke-Docker stop --time 60 $id | Out-Null }
    }
    foreach ($id in $managedIds) {
        if ((Invoke-Docker inspect --format '{{.State.Running}}' $id) -eq 'true') { Invoke-Docker stop --time 60 $id | Out-Null }
    }
    Stop-LowMemoryBuilder
    # Read the daemon host's memory, not the Windows client's RAM or a remote client's RAM.
    $available = [int](Invoke-Docker run --rm --memory 32m --memory-swap 32m --network none busybox:1.37 sh -c 'awk ''/^MemAvailable:/ {print int($2/1024)}'' /proc/meminfo')
    if ($available -lt 2816) { throw "At least 2816 MiB MemAvailable is needed (available: $available)." }
    if (-not (Invoke-DockerOptional buildx inspect $builderName)) {
        Invoke-Docker buildx create --name $builderName --driver docker-container `
            --driver-opt memory=2304m --driver-opt memory-swap=2304m `
            --driver-opt cpu-period=100000 --driver-opt cpu-quota=200000 `
            --config (Join-Path $PSScriptRoot 'buildkitd-low-memory.toml') | Out-Null
    }
    Invoke-Docker buildx inspect $builderName --bootstrap | Out-Null
    $limits = Invoke-Docker inspect --format '{{.HostConfig.Memory}}:{{.HostConfig.MemorySwap}}:{{.HostConfig.CpuPeriod}}:{{.HostConfig.CpuQuota}}' "buildx_buildkit_${builderName}0"
    if ($limits -ne '2415919104:2415919104:100000:200000') { throw 'Unexpected builder limits. Recreate codoc-lowmem-v1 with --keep-state and retry.' }
    $dockerArguments = @('buildx', 'build', '--builder', $builderName, '--load', '--progress=plain',
        '--platform', 'linux/amd64', '--file', (Join-Path $PSScriptRoot 'Dockerfile'), '--target', 'runtime', '--tag', $Tag) + $BuildArguments + @($workspaceRoot)
    Invoke-Docker @dockerArguments
    $buildExitCode = 0
} catch {
    Write-Warning $_.Exception.Message
} finally {
    if ($null -ne $buildLock) {
        $restoreAllowed = $true
        try { Stop-LowMemoryBuilder } catch { Write-Warning 'Could not stop builder. CoDoc remains stopped to avoid memory overlap.'; $restoreAllowed=$false; $buildExitCode=1 }
        if ($restoreAllowed) {
        foreach ($phase in @('storage', 'supporting', 'app')) {
            foreach ($id in $managedIds) {
                try {
                    $service = Get-ServiceLabel $id
                    $name = Invoke-Docker inspect --format '{{.Name}}' $id
                    $isApp = $service -eq 'app' -or $name -eq '/ticket-app'
                    $isStorage = $service -in @('postgres', 'redis')
                    if (($phase -eq 'storage' -and $isStorage) -or
                        ($phase -eq 'supporting' -and -not $isStorage -and -not $isApp) -or
                        ($phase -eq 'app' -and $isApp)) { Invoke-Docker start $id | Out-Null }
                } catch { Write-Warning "Could not restore container $id"; $buildExitCode = 1 }
            }
        }
        }
        $buildLock.Dispose()
    }
    if ($null -ne $deployLock) { $deployLock.Dispose() }
}

exit $buildExitCode
