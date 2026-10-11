<#
    tools/prep_signpath.ps1
    -----------------------------------------------------------------------------
    Prepara o artefacto (ZIP) para submeter ao SignPath (assinatura OSS gratuita).

    O SignPath assina os executaveis DENTRO do ZIP e devolve o ZIP assinado com a
    mesma estrutura. Este script so empacota - nao altera nada no projeto.

    Inclui os 3 ficheiros finais que o utilizador executara/instalara:
      - MediaDesk-Portable.exe                  (auto-extraivel)
      - MediaDesk-Setup.exe                     (instalador)
      - MediaDesk-Portable\YT-DLP-Media-Desk.exe (launcher da pasta)

    IMPORTANTE: assinam-se os ficheiros JA MONTADOS. O leitor do rodape "MDPL"
    do auto-extraivel tolera a assinatura anexada ao fim (Program.cs,
    Payload.Prepare), por isso a ordem assinar-depois-de-montar e a correta.
    NAO tentar "assinar o stub antes de anexar": a assinatura perde-se ao anexar
    o overlay.

    Fluxo (ver SIGNPATH.md):
      1) powershell -File tools\prep_signpath.ps1
      2) submeter o ZIP no SignPath, aprovar e descarregar o ZIP assinado
      3) powershell -File tools\apply_signed.ps1 -Source <zip assinado>

    Uso:
      powershell -ExecutionPolicy Bypass -File tools\prep_signpath.ps1
#>
[CmdletBinding()]
param(
    [string]$OutDir = ''
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root 'dist'
if (-not $OutDir) { $OutDir = Join-Path $root 'build\signpath' }

function Info($m) { Write-Host "[INFO]  $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "[ OK ]  $m" -ForegroundColor Green }
function Warn($m) { Write-Host "[AVISO] $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "[ERRO]  $m" -ForegroundColor Red; exit 1 }

# Lista de ficheiros (caminhos relativos a dist; a estrutura e preservada)
$relativos = @(
    'MediaDesk-Portable.exe',
    'MediaDesk-Setup.exe',
    'MediaDesk-Portable\YT-DLP-Media-Desk.exe'
)

$verFile = Join-Path $root 'version.json'
if (-not (Test-Path $verFile)) { Die "version.json nao encontrado." }
$ver = Get-Content $verFile -Raw | ConvertFrom-Json

$faltam = @()
foreach ($r in $relativos) { if (-not (Test-Path (Join-Path $dist $r))) { $faltam += $r } }
if ($faltam.Count) {
    Die ("Ficheiros em falta em dist\:`n      - " + ($faltam -join "`n      - ") + "`n      Corre primeiro: build_portable.ps1")
}

New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
$zipName = "signpath-$($ver.version)-$($ver.build).zip"
$zipOut = Join-Path $OutDir $zipName
$stage = Join-Path $OutDir 'stage'

if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage -Force | Out-Null

foreach ($r in $relativos) {
    $src = Join-Path $dist $r
    $dst = Join-Path $stage $r
    New-Item -ItemType Directory -Path (Split-Path -Parent $dst) -Force | Out-Null
    Copy-Item $src $dst -Force
    try {
        $sig = Get-AuthenticodeSignature $src
        $estado = if ($sig -and $sig.Status -ne 'NotSigned') { "JA ASSINADO [$($sig.Status)]" } else { 'sem assinatura' }
    } catch { $estado = '?' }
    Info ("{0,-42} {1,8}  {2}" -f $r, ("{0:N0} MB" -f ((Get-Item $src).Length / 1MB)), $estado)
}

if (Test-Path $zipOut) { Remove-Item $zipOut -Force }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($stage, $zipOut, [System.IO.Compression.CompressionLevel]::Optimal, $false)
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
Ok ("ZIP para o SignPath: $zipOut  (" + ("{0:N0} MB" -f ((Get-Item $zipOut).Length / 1MB)) + ")")
Write-Host ""
Write-Host "Proximos passos (ver SIGNPATH.md):" -ForegroundColor Cyan
Write-Host "  1. Submeter o ZIP no SignPath (pedido de assinatura OSS)."
Write-Host "  2. Aprovar e descarregar o ZIP assinado."
Write-Host "  3. Aplicar e regenerar hashes:"
Write-Host "       powershell -File tools\apply_signed.ps1 -Source <zip assinado>"
Write-Host ""
