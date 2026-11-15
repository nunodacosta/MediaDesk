<#
    tools/gen_winget.ps1
    -----------------------------------------------------------------------------
    Gera os manifestos do winget (Windows Package Manager) para a versao atual.

    Saida (estrutura identica a do repositorio microsoft/winget-pkgs):
      winget\manifests\a\ALDACO\YTDLPMediaDesk\<versao>\
        ALDACO.YTDLPMediaDesk.yaml                    (version)
        ALDACO.YTDLPMediaDesk.installer.yaml          (installer)
        ALDACO.YTDLPMediaDesk.locale.en-US.yaml       (locale)

    Fonte de verdade: version.json (versao e data) e o SHA-256 do instalador.
    O SHA-256 vem, por prioridade:
      1) -Sha256 <hex>
      2) dist\SHA256SUMS.txt  (linha do Media.Desk.Setup.exe, gerada no build)

    O URL aponta para o asset versionado da release no GitHub, que e imutavel.

    Uso (depois de publicar a release):
      powershell -ExecutionPolicy Bypass -File tools\gen_winget.ps1 `
          -Sha256 C8860C0A5C0858A8D27E15F29E1BB74B35B40F69BA8A814E87FE3C618C92252F
#>
[CmdletBinding()]
param(
    [string]$Sha256 = '',
    [string]$InstallerUrl = '',
    [string]$ReleaseDate = '',
    [string]$OutRoot = ''
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

$vj = Get-Content (Join-Path $root 'version.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$version = [string]$vj.version
$date = [string]$vj.date

if (-not $ReleaseDate) { $ReleaseDate = $date }
if (-not $InstallerUrl) {
    $InstallerUrl = "https://github.com/nunodacosta/MediaDesk/releases/download/v$version/Media.Desk.Setup.exe"
}
if (-not $Sha256) {
    $sums = Join-Path $root 'dist\SHA256SUMS.txt'
    if (-not (Test-Path $sums)) { throw 'Indica -Sha256 ou gera dist\SHA256SUMS.txt primeiro.' }
    $line = Get-Content $sums -Encoding UTF8 |
        Where-Object { $_ -match '^\s*[0-9a-fA-F]{64}\s+Media\.Desk\.Setup\.exe\s*$' } |
        Select-Object -First 1
    if (-not $line) { throw 'SHA256SUMS.txt nao contem uma linha para Media.Desk.Setup.exe.' }
    $Sha256 = ($line -split '\s+')[0]
}
$Sha256 = $Sha256.Trim().ToUpperInvariant()
if ($Sha256 -notmatch '^[0-9A-F]{64}$') { throw "SHA-256 invalido: $Sha256" }

# --- Identidade do pacote (nao mudar sem atualizar o repositorio winget-pkgs) --
$id        = 'ALDACO.YTDLPMediaDesk'
$publisher = 'ALDACO'
$pkgName   = 'YT-DLP Media Desk'
# ProductCode do Inno Setup: {AppId}_is1 (ver installer/mediadesk.iss).
$productCode = '{B7F3E2A1-9C4D-4E7B-8A2F-5D1C6E9B0A34}_is1'
$manifestVersion = '1.6.0'

$short = 'Local Windows interface for yt-dlp: download video or audio and organise it into a searchable media library with colour-coded drawers.'
$description = @'
YT-DLP Media Desk is a local desktop interface for yt-dlp on Windows 10 and 11. Paste a link, choose the format and quality, and download video or audio. What sets it apart is what happens next: a media library scans and indexes your downloads folder so it can be browsed and searched inside the app, and files are organised into drawers - real subfolders on disk, each with its own colour, that a file can be moved between from its own menu. The interface is available in five languages, with light and dark themes and several colour palettes.

Everything runs on the user's machine: no account, no telemetry, no paid tier. Free and open source software under the GNU GPL v3.0.
'@

if (-not $OutRoot) { $OutRoot = Join-Path $root 'winget\manifests' }
$outDir = Join-Path $OutRoot "a\$publisher\$($id.Split('.')[1])\$version"
New-Item -ItemType Directory -Path $outDir -Force | Out-Null

$versionYaml = @"
# yaml-language-server: `$schema=https://aka.ms/winget-manifest.version.$manifestVersion.schema.json
PackageIdentifier: $id
PackageVersion: $version
DefaultLocale: en-US
ManifestType: version
ManifestVersion: $manifestVersion
"@

$installerYaml = @"
# yaml-language-server: `$schema=https://aka.ms/winget-manifest.installer.$manifestVersion.schema.json
PackageIdentifier: $id
PackageVersion: $version
InstallerType: inno
Scope: user
UpgradeBehavior: install
ReleaseDate: $ReleaseDate
Installers:
  - Architecture: x64
    InstallerUrl: $InstallerUrl
    InstallerSha256: $Sha256
    ProductCode: '$productCode'
    AppsAndFeaturesEntries:
      - DisplayName: $pkgName $version
        Publisher: $publisher
        DisplayVersion: $version
        ProductCode: '$productCode'
        InstallerType: inno
ManifestType: installer
ManifestVersion: $manifestVersion
"@

$shortYaml = $short.Replace("'", "''")

$localeYaml = @"
# yaml-language-server: `$schema=https://aka.ms/winget-manifest.defaultLocale.$manifestVersion.schema.json
PackageIdentifier: $id
PackageVersion: $version
PackageLocale: en-US
Publisher: $publisher
PublisherUrl: https://github.com/nunodacosta/MediaDesk
PublisherSupportUrl: https://github.com/nunodacosta/MediaDesk/issues
Author: $publisher
PackageName: $pkgName
PackageUrl: https://github.com/nunodacosta/MediaDesk
License: GPL-3.0-or-later
LicenseUrl: https://github.com/nunodacosta/MediaDesk/blob/main/LICENSE
Copyright: Copyright (c) $publisher
ShortDescription: '$shortYaml'
Description: |-
$((($description.Trim() -split "`n") | ForEach-Object { if ($_.Trim().Length -eq 0) { '' } else { "  $($_.TrimEnd())" } }) -join "`n")
Moniker: mediadesk
Tags:
  - youtube
  - downloader
  - yt-dlp
  - video
  - audio
  - media
  - ffmpeg
ReleaseNotesUrl: https://github.com/nunodacosta/MediaDesk/releases/tag/v$version
# O locale predefinido usa "defaultLocale"; "locale" so para locales adicionais.
ManifestType: defaultLocale
ManifestVersion: $manifestVersion
"@

$enc = New-Object System.Text.UTF8Encoding($false)
function Write-Yaml($name, $text) {
    $path = Join-Path $outDir $name
    $normalized = ($text.TrimEnd() -replace "`r`n", "`n") + "`n"
    [System.IO.File]::WriteAllText($path, $normalized, $enc)
    Write-Host "[gen_winget] escrito: $path" -ForegroundColor Green
}

Write-Yaml "$id.yaml" $versionYaml
Write-Yaml "$id.installer.yaml" $installerYaml
Write-Yaml "$id.locale.en-US.yaml" $localeYaml

Write-Host "[gen_winget] versao $version, SHA-256 $($Sha256.Substring(0,16))..." -ForegroundColor Cyan
Write-Host "[gen_winget] validar:  winget validate --manifest `"$outDir`"" -ForegroundColor Cyan
