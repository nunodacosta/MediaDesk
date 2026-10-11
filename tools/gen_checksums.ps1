<#
    tools/gen_checksums.ps1
    -----------------------------------------------------------------------------
    Gera checksums.json (SHA-256) dos ficheiros da aplicacao. O servidor verifica
    estes hashes em segundo plano e a interface mostra o estado em "Acerca".

    Uso:
      powershell -ExecutionPolicy Bypass -File tools\gen_checksums.ps1
      powershell -ExecutionPolicy Bypass -File tools\gen_checksums.ps1 -IncludeEngines
#>
[CmdletBinding()]
param(
    [switch]$IncludeEngines
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

$lista = @(
    'server.py',
    'index.html',
    'sw.js',
    'version.json',
    'licenses.json',
    'manifest.webmanifest',
    'favicon.svg'
)
# O motor yt-dlp e pequeno e critico; ffmpeg/deno sao grandes (opcionais).
$lista += 'bin/yt-dlp.exe'
if ($IncludeEngines) { $lista += @('bin/ffmpeg.exe', 'bin/deno.exe') }

$files = [ordered]@{}
foreach ($rel in $lista) {
    $full = Join-Path $root ($rel -replace '/', '\')
    if (Test-Path $full) {
        $h = (Get-FileHash -Path $full -Algorithm SHA256).Hash.ToLower()
        $files[$rel] = $h
        Write-Host ("  {0,-26} {1}" -f $rel, $h.Substring(0,16) + '...') -ForegroundColor DarkGray
    } else {
        Write-Host "[gen_checksums] ausente: $rel" -ForegroundColor Yellow
    }
}

$manifest = [ordered]@{
    gerado    = (Get-Date).ToString('s')
    algoritmo = 'SHA-256'
    ficheiros = $files
}
$out = Join-Path $root 'checksums.json'
[System.IO.File]::WriteAllText($out, ($manifest | ConvertTo-Json -Depth 5), (New-Object System.Text.UTF8Encoding($false)))
Write-Host "[gen_checksums] $($files.Count) ficheiros -> checksums.json" -ForegroundColor Cyan
