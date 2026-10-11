<#
    tools/apply_signed.ps1
    -----------------------------------------------------------------------------
    Aplica um ZIP (ou PASTA) ASSINADO devolvido pelo SignPath: extrai os
    executaveis e coloca-os nos lugares certos do projeto, recria o ZIP da pasta
    portatil e regenera o dist\SHA256SUMS.txt. Ver SIGNPATH.md.

    Uso:
      powershell -File tools\apply_signed.ps1 -Source <zip assinado>
      powershell -File tools\apply_signed.ps1 -Source <pasta assinada>
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Source
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root 'dist'

function Info($m) { Write-Host "[INFO]  $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "[ OK ]  $m" -ForegroundColor Green }
function Warn($m) { Write-Host "[AVISO] $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "[ERRO]  $m" -ForegroundColor Red; exit 1 }

if (-not (Test-Path $Source)) { Die "ZIP/pasta assinado nao encontrado: $Source" }

# Caminhos esperados (relativos a dist)
$relativos = @(
    'MediaDesk-Portable.exe',
    'MediaDesk-Setup.exe',
    'MediaDesk-Portable\YT-DLP-Media-Desk.exe'
)

$extraiu = $false
if (Test-Path $Source -PathType Container) {
    # A GitHub Action do SignPath entrega uma PASTA com os ficheiros assinados.
    $stage = (Resolve-Path $Source).Path
    Info "A usar a pasta de artefactos assinados: $stage"
} else {
    $stage = Join-Path $root 'build\signpath\unpack'
    if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
    New-Item -ItemType Directory -Path $stage -Force | Out-Null
    Info "A extrair $Source ..."
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    try {
        [System.IO.Compression.ZipFile]::ExtractToDirectory($Source, $stage)
    } catch {
        Die "Falha ao extrair o ZIP: $($_.Exception.Message)"
    }
    $extraiu = $true
}

# Localiza cada ficheiro pela sua folha (tolerante a estrutura do ZIP)
foreach ($r in $relativos) {
    $folha = Split-Path -Leaf $r
    $encontrado = Get-ChildItem $stage -Recurse -File -Filter $folha | Select-Object -First 1
    if (-not $encontrado) { Die "'$folha' nao encontrado dentro do ZIP assinado." }

    $sig = $null
    try { $sig = Get-AuthenticodeSignature $encontrado.FullName } catch { }
    if ($sig -and $sig.Status -ne 'NotSigned') {
        Ok ("assinado [{0}]  {1}" -f $sig.Status, $folha)
    } else {
        Warn "O ficheiro '$folha' NAO parece estar assinado."
    }

    $destino = Join-Path $dist $r
    New-Item -ItemType Directory -Path (Split-Path -Parent $destino) -Force | Out-Null
    Copy-Item $encontrado.FullName $destino -Force
    Ok "colocado: dist\$r"
}

if ($extraiu) { Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue }

# Recria o ZIP da pasta portatil (para incluir o launcher assinado)
$outFolder = Join-Path $dist 'MediaDesk-Portable'
$folderZip = Join-Path $dist 'MediaDesk-Portable.zip'
if (Test-Path $outFolder) {
    Info "A recriar o ZIP da pasta portatil (com o launcher assinado)..."
    if (Test-Path $folderZip) { Remove-Item $folderZip -Force }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory($outFolder, $folderZip, [System.IO.Compression.CompressionLevel]::Optimal, $true)
    Ok ("ZIP recriado: $folderZip  (" + ("{0:N0} MB" -f ((Get-Item $folderZip).Length / 1MB)) + ")")
} else {
    Warn "Pasta portatil nao encontrada; ZIP nao foi recriado."
}

# Regenera hashes de release
Info "A regenerar os hashes de release (SHA256SUMS.txt)..."
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'tools\gen_release_hashes.ps1')

Write-Host ""
Write-Host "Verificar as assinaturas:" -ForegroundColor Cyan
Write-Host "  Get-AuthenticodeSignature dist\MediaDesk-Portable.exe | Format-List"
Write-Host "  Get-AuthenticodeSignature dist\MediaDesk-Setup.exe | Format-List"
Write-Host "  Get-AuthenticodeSignature dist\MediaDesk-Portable\YT-DLP-Media-Desk.exe | Format-List"
Write-Host ""
