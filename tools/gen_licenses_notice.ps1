<#
    tools/gen_licenses_notice.ps1
    -----------------------------------------------------------------------------
    Gera, a partir dos BINARIOS efetivamente empacotados, os avisos de licenca e a
    oferta de codigo-fonte correspondente (GPL-3.0, secao 6):

      licenses/FFmpeg-NOTICE.txt    aviso do FFmpeg + revisao exata + oferta
      licenses/SOURCE-OFFER.txt     mapa de codigo-fonte/licenca de TODOS os
                                    componentes de terceiros redistribuidos

    Objetivo: garantir que a revisao indicada na oferta corresponde EXATAMENTE ao
    binario distribuido (evita divergencias entre o pin do runtime e o que sai).

    Uso:
      powershell -ExecutionPolicy Bypass -File tools\gen_licenses_notice.ps1
      powershell -ExecutionPolicy Bypass -File tools\gen_licenses_notice.ps1 -OutDir licences
#>
[CmdletBinding()]
param(
    [string]$OutDir,
    [string]$BinDir,
    [string]$ProjectUrl = 'https://github.com/nunodacosta/MediaDesk'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $OutDir) { $OutDir = Join-Path $root 'licenses' }
if (-not $BinDir) { $BinDir = Join-Path $root 'bin' }
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Run-Capture([string]$exe, [string[]]$cmdArgs) {
    if (-not (Test-Path $exe)) { return $null }
    try { return (& $exe @cmdArgs 2>&1 | Out-String).Trim() } catch { return $null }
}

# --- Deteta versoes dos binarios empacotados ---------------------------------
$ffExe     = Join-Path $BinDir 'ffmpeg.exe'
$ytExe     = Join-Path $BinDir 'yt-dlp.exe'
$denoExe   = Join-Path $BinDir 'deno.exe'
$pyExe     = Join-Path $BinDir 'python\python.exe'

$ffRaw  = Run-Capture $ffExe @('-version')
$ffLine = if ($ffRaw) { ($ffRaw -split "`r?`n")[0].Trim() } else { '(binario ausente)' }
$ffConf = ''
if ($ffRaw) {
    $cl = ($ffRaw -split "`r?`n") | Where-Object { $_ -match '^\s*configuration:' } | Select-Object -First 1
    if ($cl) { $ffConf = ($cl -replace '^\s*configuration:\s*', '').Trim() }
}
$ffVer  = if ($ffLine -match 'ffmpeg version\s+(\S+)') { $Matches[1] } else { 'desconhecida' }

# Revisao (hash do commit) a partir do nome da versao.
$ffHash = ''
$m = [regex]::Match($ffVer, '(?i)(?:-g|git-)([0-9a-f]{7,40})')
if ($m.Success) { $ffHash = $m.Groups[1].Value }

# Origem do build.
$ffOrigin = 'desconhecida'
if ($ffVer -match '^N-\d+-g[0-9a-f]+')            { $ffOrigin = 'BtbN/FFmpeg-Builds' }
elseif ($ffVer -match '^\d{4}-\d{2}-\d{2}-git-')  { $ffOrigin = 'gyan.dev' }

# Licenca segundo os flags efetivos de configuracao.
$hasGpl = $ffConf -match '--enable-gpl(\s|$)'
$hasV3  = $ffConf -match '--enable-version3(\s|$)'
if     ($hasGpl -and $hasV3) { $ffLic = 'GPL-3.0-or-later';  $ffLicFile = 'GPL-3.0.txt' }
elseif ($hasGpl)             { $ffLic = 'GPL-2.0-or-later';  $ffLicFile = 'GPL-2.0.txt' }
elseif ($hasV3)              { $ffLic = 'LGPL-3.0-or-later'; $ffLicFile = 'LGPL-3.0.txt' }
else                         { $ffLic = 'LGPL-2.1-or-later'; $ffLicFile = 'LGPL-2.1.txt' }
if (-not (Test-Path (Join-Path $OutDir $ffLicFile))) {
    if (Test-Path (Join-Path $root ("licenses\$ffLicFile"))) { $ffLicFile = $ffLicFile } else { $ffLicFile = $ffLicFile + ' (ver pasta licenses)' }
}

$flags = @()
foreach ($f in '--enable-gpl', '--enable-version3', '--enable-nonfree') {
    if ($ffConf -match ([regex]::Escape($f) + '(\s|$)')) { $flags += $f }
}
$ffFlags = if ($flags.Count) { $flags -join ' ' } else { '(sem flags GPL visiveis)' }

$ytVer   = Run-Capture $ytExe @('--version')
if ($ytVer) { $ytVer = ($ytVer -split "`r?`n")[0].Trim() } else { $ytVer = '(ausente)' }
$denoVer = Run-Capture $denoExe @('--version')
if ($denoVer) { $denoVer = ($denoVer -split "`r?`n")[0].Trim() } else { $denoVer = '(ausente)' }
$pyVer   = Run-Capture $pyExe @('--version')
if ($pyVer) { $pyVer = ($pyVer -split "`r?`n")[0].Trim() } else { $pyVer = '(ausente)' }

$stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm')

# --- licenses/FFmpeg-NOTICE.txt ----------------------------------------------
$hashLine = if ($ffHash) { $ffHash } else { '(nao detetada)' }
$commitUrl = if ($ffHash) { "https://github.com/FFmpeg/FFmpeg/commit/$ffHash" } else { 'https://github.com/FFmpeg/FFmpeg' }

$ffNotice = @"
FFmpeg - AVISO DE LICENCA E OFERTA DO CODIGO-FONTE CORRESPONDENTE
=================================================================
FFmpeg - LICENSE NOTICE AND CORRESPONDING SOURCE OFFER

Componente / Component ........: FFmpeg
Versao distribuida / Version ..: $ffVer
Licenca / License .............: $ffLic
Texto integral / Full text ....: licenses/$ffLicFile
Flags relevantes / Flags ......: $ffFlags
Origem do build / Build origin : $ffOrigin

------------------------------------------------------------------------------
CODIGO-FONTE CORRESPONDENTE / CORRESPONDING SOURCE
------------------------------------------------------------------------------
Revisao exata do FFmpeg / Exact FFmpeg revision:
    $hashLine
    $commitUrl
Arvore upstream / Upstream source tree:
    https://github.com/FFmpeg/FFmpeg
Scripts de build e patches / Build scripts and patches:
    https://github.com/BtbN/FFmpeg-Builds
    https://www.gyan.dev/ffmpeg/builds/
Documentacao / Documentation:
    https://ffmpeg.org/

------------------------------------------------------------------------------
OFERTA ESCRITA / WRITTEN OFFER (GPL-3.0, secao/section 6(b))
------------------------------------------------------------------------------
O codigo-fonte correspondente acima indicado, bem como os scripts de build,
patches e configuracao usados para produzir este binario, sao/serao fornecidos
a qualquer terceiro, a pedido, durante pelo menos tres (3) anos a contar da data
de distribuicao, sem qualquer custo. Pedidos / Requests:
    https://github.com/nunodacosta/MediaDesk

The Corresponding Source identified above, together with the build scripts,
patches and configuration used to produce this binary, will be provided to any
third party, on request, for at least three (3) years from the date of
distribution, at no charge. Requests:
    https://github.com/nunodacosta/MediaDesk

Nota / Note: o FFmpeg e distribuido como programa independente (agregado) com o
YT-DLP Media Desk. O YT-DLP Media Desk e, por sua vez, software livre sob
GPL-3.0; o respetivo codigo-fonte esta em:
    https://github.com/nunodacosta/MediaDesk

Ficheiro gerado automaticamente por tools/gen_licenses_notice.ps1 a partir do
binario empacotado, para que a revisao indicada corresponda exatamente ao que e
distribuido. Data / Date: $stamp
"@
[System.IO.File]::WriteAllText((Join-Path $OutDir 'FFmpeg-NOTICE.txt'), $ffNotice, $utf8)

# --- licenses/SOURCE-OFFER.txt -----------------------------------------------
$sourceOffer = @"
YT-DLP Media Desk - CODIGO-FONTE E LICENCAS DOS COMPONENTES
===========================================================
YT-DLP Media Desk - SOURCE AND LICENSES OF THE COMPONENTS

Este documento identifica, para cada componente de terceiros redistribuido,
a licenca aplicavel, o texto integral (pasta licenses/) e onde obter o codigo-
fonte correspondente. Gerado automaticamente a partir dos binarios empacotados.
Data / Date: $stamp

1) Aplicacao (codigo proprio) / Application (own code)
   Licenca .....: GNU GPL-3.0 (texto: licenses/GPL-3.0.txt; aviso: licenses/ALDACO-IP-NOTICE.txt)
   Codigo-fonte : $ProjectUrl

2) FFmpeg
   Versao ......: $ffVer
   Licenca .....: $ffLic (texto: licenses/$ffLicFile)
   Codigo-fonte : $commitUrl
                  https://github.com/BtbN/FFmpeg-Builds
   Detalhe .....: licenses/FFmpeg-NOTICE.txt (inclui a oferta escrita)

3) yt-dlp
   Versao ......: $ytVer
   Licenca .....: Unlicense (dominio publico) - texto: licenses/yt-dlp-UNLICENSE.txt
   Codigo-fonte : https://github.com/yt-dlp/yt-dlp

4) Python (embebido) / Embedded Python
   Versao ......: $pyVer
   Licenca .....: PSF-2.0 - texto: licenses/Python-PSF-LICENSE.txt
   Codigo-fonte : https://www.python.org/downloads/source/

5) Deno
   Versao ......: $denoVer
   Licenca .....: MIT - texto: licenses/Deno-MIT-LICENSE.txt
   Codigo-fonte : https://github.com/denoland/deno

6) .NET (runtime do launcher) / .NET runtime
   Licenca .....: MIT - texto: licenses/.NET-MIT-LICENSE.txt
   Codigo-fonte : https://github.com/dotnet/runtime

7) Microsoft Edge WebView2 Runtime
   Licenca .....: Microsoft (redistribuivel) - texto: licenses/WebView2-NOTICE.txt
   Informacao ..: https://developer.microsoft.com/microsoft-edge/webview2/

Componentes permissivos (Unlicense/MIT/PSF): basta a inclusao do aviso e do
texto da licenca, que acompanham esta distribuicao. Componentes GPL (FFmpeg):
adicionalmente, e disponibilizada a oferta do codigo-fonte correspondente
(ver licenses/FFmpeg-NOTICE.txt).
"@
[System.IO.File]::WriteAllText((Join-Path $OutDir 'SOURCE-OFFER.txt'), $sourceOffer, $utf8)

Write-Host "[gen_licenses_notice] FFmpeg $ffVer ($ffLic) -> $OutDir" -ForegroundColor Cyan
Write-Host "[gen_licenses_notice]   FFmpeg-NOTICE.txt + SOURCE-OFFER.txt" -ForegroundColor Cyan
