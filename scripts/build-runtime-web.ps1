param(
    [Parameter(Mandatory = $true)][string]$ProjectRoot,
    [Parameter(Mandatory = $true)][ValidateSet('editor', 'private-journey')][string]$Component,
    [Parameter(Mandatory = $true)][string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
$project = (Resolve-Path -LiteralPath $ProjectRoot).Path
$output = [IO.Path]::GetFullPath($OutputDirectory)
$values = @{
    VITE_CODOC_API_URL = '/'; VITE_PUBLIC_SOURCES_BASE_URL = '';
    VITE_API_BASE = '/'; VITE_BACKEND_URL = '/'; VITE_BASE_URL = '/';
    VITE_EXPORT_API = '/api/export'; VITE_BUILD_SOURCEMAP = 'false'
}
$previous = @{}
foreach ($name in $values.Keys) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    [Environment]::SetEnvironmentVariable($name, $values[$name], 'Process')
}

Push-Location -LiteralPath $project
try {
    if ($Component -eq 'private-journey') {
        & npx tsc --noEmit
        if ($LASTEXITCODE -ne 0) { throw 'TypeScript check failed' }
        & npx vite build --base=/private-journey/ --outDir $output
        if ($LASTEXITCODE -ne 0) { throw 'Private journey build failed' }
    } else {
        & npm run build
        if ($LASTEXITCODE -ne 0) { throw 'Editor build failed' }
        $built = Join-Path $project 'dist'
        if ($output -ne $built) {
            [IO.Directory]::CreateDirectory($output) | Out-Null
            Get-ChildItem -LiteralPath $built -Force | Copy-Item -Destination $output -Recurse -Force
        }
    }
} finally {
    Pop-Location
    foreach ($name in $previous.Keys) { [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process') }
}
