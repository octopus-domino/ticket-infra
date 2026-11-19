param(
    [Parameter(Mandatory = $true)][string]$ProjectRoot,
    [Parameter(Mandatory = $true)][string]$ApiBase,
    [Parameter(Mandatory = $true)][string]$JavaHome,
    [Parameter(Mandatory = $true)][string]$AndroidHome,
    [Parameter(Mandatory = $true)][string]$OutputFile
)

$ErrorActionPreference = 'Stop'
$project = (Resolve-Path -LiteralPath $ProjectRoot).Path
$destination = [IO.Path]::GetFullPath($OutputFile)
$variableNames = @('VITE_CODOC_API_URL', 'VITE_PUBLIC_SOURCES_BASE_URL', 'JAVA_HOME', 'ANDROID_HOME')
$previousValues = @{}
foreach ($name in $variableNames) { $previousValues[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }

function Invoke-Checked([scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "Build command failed with exit code $LASTEXITCODE" }
}

Push-Location -LiteralPath $project
try {
    $env:VITE_CODOC_API_URL = $ApiBase.TrimEnd('/')
    $env:VITE_PUBLIC_SOURCES_BASE_URL = ''
    $env:JAVA_HOME = (Resolve-Path -LiteralPath $JavaHome).Path
    $env:ANDROID_HOME = (Resolve-Path -LiteralPath $AndroidHome).Path
    Invoke-Checked { npm test }
    Invoke-Checked { npm run build }
    Invoke-Checked { npx cap sync android }
    Push-Location -LiteralPath (Join-Path $project 'android')
    try { Invoke-Checked { .\gradlew.bat testDebugUnitTest assembleDebug } }
    finally { Pop-Location }
    $apk = Join-Path $project 'android/app/build/outputs/apk/debug/app-debug.apk'
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destination)) | Out-Null
    Copy-Item -LiteralPath $apk -Destination $destination
    Get-FileHash -LiteralPath $destination -Algorithm SHA256
} finally {
    Pop-Location
    foreach ($name in $variableNames) { [Environment]::SetEnvironmentVariable($name, $previousValues[$name], 'Process') }
}
