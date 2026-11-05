param(
    [string]$Tag = 'ticket-editor:stabilized',
    [string[]]$BuildArguments = @()
)

$ErrorActionPreference = 'Stop'
Get-Command docker -ErrorAction Stop | Out-Null
$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$dockerfilePath = Join-Path $PSScriptRoot 'Dockerfile'
$previousBuildKit = $env:DOCKER_BUILDKIT
$buildExitCode = 1

try {
    $env:DOCKER_BUILDKIT = '1'
    $dockerArguments = @('build', '--progress=plain', '--file', $dockerfilePath, '--tag', $Tag) +
        $BuildArguments + @($workspaceRoot)
    & docker @dockerArguments
    $buildExitCode = $LASTEXITCODE
} finally {
    $env:DOCKER_BUILDKIT = $previousBuildKit
}

exit $buildExitCode
