<#
    tools/gen_pad.ps1
    -----------------------------------------------------------------------------
    Gera o ficheiro PAD (Portable Application Description) a partir de version.json.

    Serve para o Softpedia (e outros diretorios que aceitam PAD) publicarem
    automaticamente novas versoes: submete-se o URL do PAD UMA vez e o diretorio
    passa a monitorizar esse ficheiro, publicando cada nova versao sem intervencao.

    Fonte unica de verdade: version.json (versao e data).
    Saida por omissao: pad\mediadesk.xml

    IMPORTANTE (qual e o PAD "verdadeiro"):
      Os ficheiros publicados sao construidos pela CI (GitHub Actions), e nao
      pela build local - sao parecidos mas nao identicos. Por isso o PAD que
      interessa e o que a CI gera no fim da build e que viaja DENTRO da release
      (asset "mediadesk.xml"). O URL estavel a submeter ao Softpedia UMA vez e:
        https://github.com/nunodacosta/MediaDesk/releases/latest/download/mediadesk.xml
      A copia em pad\mediadesk.xml no repositorio serve apenas para consulta e
      como reserva (o seu tamanho pode diferir do asset publicado).

    O tamanho indicado no PAD e o do instalador (dist\MediaDesk-Setup.exe), lido
    no fim da build. Prioridade: -SizeBytes > dist\... > -FallbackSizeBytes.

    Uso:
      powershell -ExecutionPolicy Bypass -File tools\gen_pad.ps1
      powershell -ExecutionPolicy Bypass -File tools\gen_pad.ps1 -SizeBytes 154032663
#>
[CmdletBinding()]
param(
    [string]$OutPath,
    [long]$SizeBytes = 0,
    [long]$FallbackSizeBytes = 0
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

$verPath = Join-Path $root 'version.json'
if (-not (Test-Path $verPath)) { throw "version.json nao encontrado em $root" }
$vj = Get-Content $verPath -Raw -Encoding UTF8 | ConvertFrom-Json
$version = [string]$vj.version
$date = [string]$vj.date
if (-not $OutPath) { $OutPath = Join-Path $root 'pad\mediadesk.xml' }

# --- data -> mes / dia / ano (sem zeros a esquerda) --------------------------
$parts = ($date -split '-')
if ($parts.Count -lt 3) { throw "version.json: data em formato inesperado ($date)" }
$year = $parts[0]
$month = ([int]$parts[1]).ToString()
$day = ([int]$parts[2]).ToString()

# --- tamanho do instalador ---------------------------------------------------
# Prioridade: -SizeBytes (explicito) > dist\MediaDesk-Setup.exe > -FallbackSizeBytes
# Nota: em PowerShell os nomes nao distinguem maiusculas, por isso a variavel
# local NAO pode chamar-se $sizeBytes (colidiria com o parametro $SizeBytes).
$instSizeBytes = 0
$setup = Join-Path $root 'dist\MediaDesk-Setup.exe'
if ($SizeBytes -gt 0) { $instSizeBytes = $SizeBytes }
elseif (Test-Path $setup) { $instSizeBytes = (Get-Item $setup).Length }
elseif ($FallbackSizeBytes -gt 0) { $instSizeBytes = $FallbackSizeBytes }
$sizeK = 0
$sizeMB = '0'
if ($instSizeBytes -gt 0) {
    $sizeK = [int][math]::Round($instSizeBytes / 1024)
    $sizeMB = ([math]::Round($instSizeBytes / 1048576, 2)).ToString([System.Globalization.CultureInfo]::InvariantCulture)
}

$base = 'https://github.com/nunodacosta/MediaDesk'
$raw  = 'https://raw.githubusercontent.com/nunodacosta/MediaDesk/main'
$dl   = "$base/releases/download/v$version"

# --- descricoes (sem < > e sem acentos, para maxima compatibilidade) ---------
$desc45 = 'Download and organise video and audio'
$desc80 = 'Local Windows interface for yt-dlp that organises downloads into drawers'
$desc250 = 'YT-DLP Media Desk is a local desktop interface for yt-dlp on Windows. It downloads video or audio, then organises everything: the media library indexes your downloads folder, and files go into colour-coded drawers that are real subfolders.'
$desc450 = 'YT-DLP Media Desk is a local desktop interface for yt-dlp on Windows. Paste a link, choose the format and quality, and download video or audio. What sets it apart is what happens next: a media library scans and indexes your downloads folder so it can be browsed and searched inside the app, and files are organised into drawers - real subfolders on disk, each with its own colour, that a file can be moved between from its own menu.'
$desc2000 = @'
YT-DLP Media Desk is a local desktop interface for yt-dlp, for Windows 10 and 11. Everything runs on the user's machine: no account, no telemetry, no paid tier.

Downloading is straightforward: paste a link, choose the format and quality, and the file lands in your downloads folder.

The difference is what happens after the download. A media library scans the downloads folder and indexes what it finds, so your media can be browsed, searched and filtered from inside the app - no need to open Explorer and hunt through folders. Files are then organised into drawers: real subfolders on disk, each with its own colour, shown as a grid in the sidebar with a per-type filter. Every file shows which drawer it belongs to, and can be moved between drawers of the same type - or out to an external folder - from the file's own menu. The activity view keeps the complete download history and shows which drawer each file went to.

The interface is available in five languages (Portuguese, English, Spanish, French and German), with light and dark themes and several colour palettes.

It is distributed as a portable zip, a self-extracting executable and a standard installer, each published with SHA-256 hashes so downloads can be verified. Free and open source software, licensed under the GNU GPL v3.0.
'@

# --- validacao dos limites de caracteres dos descritores ---------------------
$limits = @(
    @('Char_Desc_45',   $desc45,   45),
    @('Char_Desc_80',   $desc80,   80),
    @('Char_Desc_250',  $desc250,  250),
    @('Char_Desc_450',  $desc450,  450),
    @('Char_Desc_2000', $desc2000, 2000)
)
foreach ($l in $limits) {
    if ([string]$l[1] -match '[<>]') { throw "$($l[0]) contem < ou > (invalido em PAD)" }
    if ([string]$l[1].Length -gt $l[2]) {
        throw "$($l[0]) tem $([string]$l[1].Length) caracteres (maximo $($l[2]))"
    }
}

$template = @'
<?xml version="1.0" encoding="utf-8" ?>
<XML_DIZ_INFO>
  <MASTER_PAD_VERSION_INFO>
    <MASTER_PAD_VERSION>3.11</MASTER_PAD_VERSION>
    <MASTER_PAD_EDITOR>tools/gen_pad.ps1 (MediaDesk)</MASTER_PAD_EDITOR>
    <MASTER_PAD_INFO>Portable Application Description, or PAD for short, is a data set that is used by software authors to disseminate information to anyone interested in their software products.</MASTER_PAD_INFO>
  </MASTER_PAD_VERSION_INFO>
  <Company_Info>
    <Company_Name>ALDACO</Company_Name>
    <Company_WebSite_URL>__BASE__</Company_WebSite_URL>
    <Contact_Info>
      <Author_First_Name>Nuno</Author_First_Name>
      <Author_Last_Name>Duraes</Author_Last_Name>
      <Author_Email>nuno.costaduraes@outlook.pt</Author_Email>
      <Contact_First_Name>Nuno</Contact_First_Name>
      <Contact_Last_Name>Duraes</Contact_Last_Name>
      <Contact_Email>nuno.costaduraes@outlook.pt</Contact_Email>
    </Contact_Info>
    <Support_Info>
      <General_Email>nuno.costaduraes@outlook.pt</General_Email>
      <Support_Email>nuno.costaduraes@outlook.pt</Support_Email>
      <Sales_Email>nuno.costaduraes@outlook.pt</Sales_Email>
      <Fax_Phone>NA</Fax_Phone>
    </Support_Info>
  </Company_Info>
  <Program_Info>
    <Program_Name>YT-DLP Media Desk</Program_Name>
    <Program_Version>__VERSION__</Program_Version>
    <Program_Release_Month>__MONTH__</Program_Release_Month>
    <Program_Release_Day>__DAY__</Program_Release_Day>
    <Program_Release_Year>__YEAR__</Program_Release_Year>
    <Program_Cost_Dollars>0</Program_Cost_Dollars>
    <Program_Cost_Other_Code />
    <Program_Cost_Other>0</Program_Cost_Other>
    <Program_Type>Freeware</Program_Type>
    <Program_Release_Status>New Release</Program_Release_Status>
    <Program_Install_Support>Install and Uninstall</Program_Install_Support>
    <Program_OS_Support>Windows 11, Windows 10</Program_OS_Support>
    <Program_Language>English, Portuguese, Spanish, French, German</Program_Language>
    <File_Info>
      <Filename_Versioned>MediaDesk-Setup.exe</Filename_Versioned>
      <Filename_Generic>MediaDesk-Setup.exe</Filename_Generic>
      <Filename_Long>MediaDesk-Setup.exe</Filename_Long>
      <File_Size_Bytes>__SIZEBYTES__</File_Size_Bytes>
      <File_Size_K>__SIZEK__</File_Size_K>
      <File_Size_MB>__SIZEMB__</File_Size_MB>
    </File_Info>
    <Expire_Info>
      <Has_Expire_Info>N</Has_Expire_Info>
      <Expire_Based_On>Days</Expire_Based_On>
    </Expire_Info>
    <Program_Change_Info>Version __VERSION__ (__DATE__). See the release page for the full changelog.</Program_Change_Info>
    <Program_Specific_Category>Video Downloaders</Program_Specific_Category>
    <Program_Categories>Multimedia, Internet</Program_Categories>
    <Program_System_Requirements>Windows 10 or Windows 11 (64-bit). No external dependencies: everything needed is bundled.</Program_System_Requirements>
    <Includes_JAVA_VM>N</Includes_JAVA_VM>
    <Includes_VB_Runtime>N</Includes_VB_Runtime>
    <Includes_DirectX>N</Includes_DirectX>
  </Program_Info>
  <Program_Descriptions>
    <English>
      <Keywords>yt-dlp, video downloader, youtube downloader, media library, download manager, portable, open source, windows</Keywords>
      <Char_Desc_45>__DESC45__</Char_Desc_45>
      <Char_Desc_80>__DESC80__</Char_Desc_80>
      <Char_Desc_250>__DESC250__</Char_Desc_250>
      <Char_Desc_450>__DESC450__</Char_Desc_450>
      <Char_Desc_2000>__DESC2000__</Char_Desc_2000>
    </English>
  </Program_Descriptions>
  <Web_Info>
    <Application_URLs>
      <Application_Info_URL>__BASE__</Application_Info_URL>
      <Application_Order_URL />
      <Application_Screenshot_URL>__RAW__/docs/screenshots/mediateca.png</Application_Screenshot_URL>
      <Application_Icon_URL>__RAW__/icons/icon-32.png</Application_Icon_URL>
      <Application_XML_File_URL>__BASE__/releases/latest/download/mediadesk.xml</Application_XML_File_URL>
    </Application_URLs>
    <Download_URLs>
      <Primary_Download_URL>__DL__/MediaDesk-Setup.exe</Primary_Download_URL>
      <Secondary_Download_URL>__DL__/MediaDesk-Portable.zip</Secondary_Download_URL>
      <Additional_Download_URL_1>__BASE__/releases/latest</Additional_Download_URL_1>
    </Download_URLs>
  </Web_Info>
  <Permissions>
    <Distribution_Permissions>Free and open source software, licensed under the GNU General Public License v3.0. You may copy and distribute verbatim copies of the binaries exactly as published on the project repository, in their unmodified form. The complete corresponding source code is available at __BASE__</Distribution_Permissions>
    <EULA>YT-DLP Media Desk is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License v3.0 for more details: https://www.gnu.org/licenses/gpl-3.0.html</EULA>
  </Permissions>
</XML_DIZ_INFO>
'@

$xml = $template
$xml = $xml.Replace('__BASE__', $base)
$xml = $xml.Replace('__RAW__', $raw)
$xml = $xml.Replace('__DL__', $dl)
$xml = $xml.Replace('__VERSION__', $version)
$xml = $xml.Replace('__DATE__', $date)
$xml = $xml.Replace('__MONTH__', $month)
$xml = $xml.Replace('__DAY__', $day)
$xml = $xml.Replace('__YEAR__', $year)
$xml = $xml.Replace('__SIZEBYTES__', $instSizeBytes.ToString())
$xml = $xml.Replace('__SIZEK__', $sizeK.ToString())
$xml = $xml.Replace('__SIZEMB__', $sizeMB)
$xml = $xml.Replace('__DESC45__', $desc45)
$xml = $xml.Replace('__DESC80__', $desc80)
$xml = $xml.Replace('__DESC250__', $desc250)
$xml = $xml.Replace('__DESC450__', $desc450)
$xml = $xml.Replace('__DESC2000__', $desc2000.Trim())

if ($xml -match '__[A-Z0-9]+__') { throw "Placeholder nao substituido: $($Matches[0])" }

$outDir = Split-Path -Parent $OutPath
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
[System.IO.File]::WriteAllText($OutPath, $xml, (New-Object System.Text.UTF8Encoding($false)))

Write-Host "[gen_pad] escrito: $OutPath" -ForegroundColor Green
Write-Host "[gen_pad] versao $version, instalador $instSizeBytes bytes ($sizeMB MB)" -ForegroundColor Cyan
