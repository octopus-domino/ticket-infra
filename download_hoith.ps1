param([string]$DestDir = '.\data\imports')
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $DestDir | Out-Null
$publicKey = 'https://disk.yandex.ru/d/6rI165UaOpvG0A'
$query = [uri]::EscapeDataString($publicKey)
$api = 'https://cloud-api.yandex.net/v1/disk/public/resources'
$metadata = Invoke-RestMethod -Uri "${api}?public_key=$query" -TimeoutSec 60
$drive = Get-PSDrive -Name ([IO.Path]::GetPathRoot((Resolve-Path $DestDir)).TrimEnd('\').TrimEnd(':'))
if ($drive.Free -lt ([long]$metadata.size + 1GB)) { throw 'Insufficient free disk space.' }
$target = Join-Path $DestDir 'hoith.gpkg'
if ((Test-Path -LiteralPath $target) -and (Get-Item -LiteralPath $target).Length -eq $metadata.size) { Write-Host 'Existing file preserved.'; exit 0 }
$response = Invoke-RestMethod -Uri "${api}/download?public_key=$query" -TimeoutSec 60
if (-not $response.href -or ([uri]$response.href).Scheme -ne 'https') { throw 'No HTTPS download URL returned.' }
$partial = "$target.part"
Invoke-WebRequest -Uri $response.href -OutFile $partial -UseBasicParsing -TimeoutSec 7200
if ((Get-Item -LiteralPath $partial).Length -ne $metadata.size) { throw 'Incomplete download.' }
Move-Item -LiteralPath $partial -Destination $target -Force
Get-Item -LiteralPath $target | Select-Object Name,Length,FullName
