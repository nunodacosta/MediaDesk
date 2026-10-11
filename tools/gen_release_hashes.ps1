<#
    tools/gen_release_hashes.ps1
    -----------------------------------------------------------------------------
    Gera dist\SHA256SUMS.txt com os hashes SHA-256 dos artefactos de release:
      - MediaDesk-Portable.zip   (descarga recomendada)
      - MediaDesk-Portable.exe   (auto-extraivel)
      - MediaDesk-Setup.exe      (instalador)
      - MediaDesk-Portable\YT-DLP-Media-Desk.exe (launcher da pasta)

    Deve ser corrido no FIM do build (a assinatura altera os ficheiros).
    Formato compativel com "sha256sum -c":  <hash>  <nome>

    Uso:
      powershell -ExecutionPolicy Bypass -File tools\gen_release_hashes.ps1
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root 'dist'

$candidatos = @(
    'MediaDesk-Portable.zip',
    'MediaDesk-Portable.exe',
    'MediaDesk-Setup.exe'
) | ForEach-Object { Join-Path $dist $_ }

$pastaLauncher = Join-Path $dist 'MediaDesk-Portable\YT-DLP-Media-Desk.exe'
if (Test-Path $pastaLauncher) { $candidatos += $pastaLauncher }

$count = 0
$sb = New-Object System.Text.StringBuilder
$header = @"
# YT-DLP Media Desk - SHA-256 dos artefactos de release
# Gerado: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K')
# Verificar:  powershell -ExecutionPolicy Bypass -File verificar-integridade.ps1
#
"@
[void]$sb.AppendLine($header.TrimEnd())
foreach ($p in $candidatos) {
    if (-not (Test-Path $p)) { continue }
    $h = (Get-FileHash $p -Algorithm SHA256).Hash.ToLower()
    $name = $p.Substring($dist.Length + 1)
    [void]$sb.AppendLine("$h  $name")
    Write-Host ("  {0,-30} {1}..." -f $name, $h.Substring(0, 16)) -ForegroundColor DarkGray
    $count++
}

if ($count -eq 0) { throw "Nenhum artefacto de release encontrado em $dist" }

$out = Join-Path $dist 'SHA256SUMS.txt'
[System.IO.File]::WriteAllText($out, $sb.ToString(), (New-Object System.Text.UTF8Encoding($false)))
Write-Host "[gen_release_hashes] $count artefactos -> $out" -ForegroundColor Cyan