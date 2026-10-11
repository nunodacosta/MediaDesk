<#
    tools/prepare_runtime.ps1
    -----------------------------------------------------------------------------
    Repoe o runtime em bin\ a partir de fontes publicas com versoes fixadas.
    Usado no CI (GitHub Actions) e util para reconstrucoes na maquina.

      bin\python\python.exe  <- Python 3.10 embeddable (python.org)
      bin\yt-dlp.exe         <- yt-dlp (GitHub releases, versao fixada)
      bin\ffmpeg.exe         <- FFmpeg win64-gpl (BtbN FFmpeg-Builds)
      bin\deno.exe           <- Deno (GitHub releases, versao fixada)

    O ficheiro ._pth do Python e ajustado para ativar `import site` (igual ao
    runtime local, que tem pacotes em Lib\site-packages). O server.py usa apenas
    a biblioteca standard, pelo que nao sao instalados pacotes adicionais.

    Parametros:
      -PythonVersion <3.10.11>   versao do Python embeddable
      -YtDlpVersion  <2026.08.19>  versao (tag) do yt-dlp
      -DenoVersion   <2.6.9>      versao do Deno
      -SkipDownloads reutilizar o que ja existe em bin\ (nao descarrega nada)
      -Destination   <raiz>\bin   onde colocar o runtime (para testes)

    Exemplos:
      powershell -ExecutionPolicy Bypass -File tools\prepare_runtime.ps1
      powershell -ExecutionPolicy Bypass -File tools\prepare_runtime.ps1 -SkipDownloads
#>
[CmdletBinding()]
param(
    [string]$PythonVersion = '3.10.11',
    [string]$YtDlpVersion  = '2026.08.19',
    [string]$DenoVersion   = '2.6.9',
    [switch]$SkipDownloads,
    [string]$Destination = ''
)
$ErrorActionPreference = 'Stop'
$root = if ($PSScriptRoot) { Split-Path -Parent $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $Destination) { $Destination = Join-Path $root 'bin' }
$bin = $Destination
$dl  = Join-Path $env:TEMP 'mediadesk_runtime'
New-Item -ItemType Directory -Path $bin -Force | Out-Null
New-Item -ItemType Directory -Path $dl  -Force | Out-Null

function Info($m) { Write-Host "[runtime] $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "[ OK ]   $m" -ForegroundColor Green }

function Assert-Zip($f) {
    # Valida que o ficheiro e um ZIP completo e com conteudo (evita reutilizar
    # downloads truncados deixados por execucoes anteriores).
    Add-Type -AssemblyName System.IO.Compression.FileSystem | Out-Null
    try {
        $z = [System.IO.Compression.ZipFile]::OpenRead($f)
        $n = $z.Entries.Count
        $z.Dispose()
        if ($n -lt 1) { throw 'zip vazio' }
    } catch {
        Remove-Item $f -Force -ErrorAction SilentlyContinue
        throw "ZIP invalido/corrompido: $f"
    }
}

function Get-Dl($url, $dst, [switch]$AsZip) {
    if (Test-Path $dst) {
        if ($AsZip) { Assert-Zip $dst }
        Write-Host "  (cache/ja existe) $([System.IO.Path]::GetFileName($dst))"
        return
    }
    Write-Host "  a descarregar: $url"
    # Descarrega para .part e so renomeia apos sucesso: um ficheiro truncado
    # nunca e tratado como completo. -C - retoma downloads parciais e
    # --retry-all-errors repete erros transitorios (18, 56, tempo limite, ...).
    $part = "$dst.part"
    & curl.exe -sSL -f --retry 5 --retry-all-errors --retry-delay 2 -C - -o $part $url
    if ($LASTEXITCODE -ne 0) {
        Remove-Item $part -Force -ErrorAction SilentlyContinue
        throw "Falha ao descarregar: $url (curl $LASTEXITCODE)"
    }
    if (-not (Test-Path $part) -or (Get-Item $part).Length -lt 1024) {
        Remove-Item $part -Force -ErrorAction SilentlyContinue
        throw "Descarregamento invalido (vazio/parcial): $url"
    }
    Move-Item $part $dst -Force
    if ($AsZip) { Assert-Zip $dst }
}

function Extract-Zip($zip, $dir) {
    if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }
    Expand-Archive -Path $zip -DestinationPath $dir -Force
}

function Refresh-IfStale($target) {
    # true se temos de (re)preparar o componente
    if (-not (Test-Path $target)) { return $true }
    if ($SkipDownloads) {
        Ok "ja presente e -SkipDownloads: $([System.IO.Path]::GetFileName($target))"
        return $false
    }
    return $true
}

# --- Python embeddable --------------------------------------------------------
$pyDir = Join-Path $bin 'python'
$pyExe = Join-Path $pyDir 'python.exe'
if (Refresh-IfStale $pyExe) {
    Info "Python $PythonVersion embeddable (python.org)..."
    $pyZip = Join-Path $dl 'python-embed.zip'
    Get-Dl "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" $pyZip -AsZip
    if (Test-Path $pyDir) { Remove-Item $pyDir -Recurse -Force }
    New-Item -ItemType Directory -Path $pyDir -Force | Out-Null
    Expand-Archive -Path $pyZip -DestinationPath $pyDir -Force
    $mj, $mn = ($PythonVersion -split '\.')[0], ($PythonVersion -split '\.')[1]
    $pthFile = Join-Path $pyDir ("python{0}{1}._pth" -f $mj, $mn)
    if (Test-Path $pthFile) {
        $txt = Get-Content $pthFile -Raw
        $new = [regex]::Replace($txt, '(?m)^[ \t]*#[ \t]*import site[ \t]*\r?$', 'import site')
        if ($new -ne $txt) {
            [System.IO.File]::WriteAllText($pthFile, $new, (New-Object System.Text.UTF8Encoding($false)))
            Write-Host "  ._pth: 'import site' ativado"
        }
    } else {
        Write-Host "  aviso: $([System.IO.Path]::GetFileName($pthFile)) nao encontrado"
    }
}
$v = (& $pyExe --version 2>&1) -join ' '
if ($LASTEXITCODE -ne 0) { throw 'Python nao executa.' }
Ok "python: $v"
& $pyExe -c "import ssl, sqlite3, unicodedata, urllib.request; print('stdlib ok')" 2>&1 | Out-String | Write-Host

# --- yt-dlp -------------------------------------------------------------------
$yt = Join-Path $bin 'yt-dlp.exe'
if (Refresh-IfStale $yt) {
    Info "yt-dlp $YtDlpVersion (GitHub releases)..."
    Get-Dl "https://github.com/yt-dlp/yt-dlp/releases/download/$YtDlpVersion/yt-dlp.exe" $yt
}
$yv = (& $yt --version 2>&1) -join ' '
if ($LASTEXITCODE -ne 0) { throw 'yt-dlp nao executa.' }
Ok "yt-dlp: $yv"

# --- FFmpeg -------------------------------------------------------------------
$ff = Join-Path $bin 'ffmpeg.exe'
if (Refresh-IfStale $ff) {
    Info 'FFmpeg win64-gpl (BtbN FFmpeg-Builds, master)...'
    $ffZip = Join-Path $dl 'ffmpeg.zip'
    Get-Dl 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip' $ffZip -AsZip
    $ffDir = Join-Path $dl 'ffmpeg'
    Extract-Zip $ffZip $ffDir
    $exe = Get-ChildItem $ffDir -Recurse -Filter ffmpeg.exe | Select-Object -First 1
    if (-not $exe) { throw 'ffmpeg.exe nao encontrado na extraccao do zip.' }
    Copy-Item $exe.FullName $ff -Force
}
$fv = ((& $ff -version 2>&1) | Select-Object -First 1) -join ' '
if ($LASTEXITCODE -ne 0) { throw 'ffmpeg nao executa.' }
Ok "ffmpeg: $fv"

# --- Deno ---------------------------------------------------------------------
$de = Join-Path $bin 'deno.exe'
if (Refresh-IfStale $de) {
    Info "Deno $DenoVersion (GitHub releases)..."
    $dZip = Join-Path $dl 'deno.zip'
    Get-Dl "https://github.com/denoland/deno/releases/download/v$DenoVersion/deno-x86_64-pc-windows-msvc.zip" $dZip -AsZip
    $dDir = Join-Path $dl 'deno'
    Extract-Zip $dZip $dDir
    if (-not (Test-Path (Join-Path $dDir 'deno.exe'))) { throw 'deno.exe nao encontrado na extraccao do zip.' }
    Copy-Item (Join-Path $dDir 'deno.exe') $de -Force
}
$dv = ((& $de --version 2>&1) | Select-Object -First 1) -join ' '
if ($LASTEXITCODE -ne 0) { throw 'deno nao executa.' }
Ok "deno: $dv"

Write-Host ""
Ok "Runtime pronto em: $bin"