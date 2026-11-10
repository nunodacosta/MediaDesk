<#
    build_portable.ps1
    -----------------------------------------------------------------------------
    Cria a versao portatil do YT-DLP Media Desk:
      dist\Media Desk Portable\      -> pasta pronta a executar (sem instalacao)
      dist\Media Desk.exe            -> executavel auto-extraivel (tudo incluido)
      dist\Media Desk Setup.exe      -> instalador (Inno Setup)
      dist\Media Desk.zip            -> ZIP da pasta portatil

    Sem dependencias externas: Python, yt-dlp, FFmpeg e Deno viajam no pacote.

    Assinatura de codigo (opcional). Escolhe UMA destas fontes de certificado:
      MEDIADESK_PFX             -> caminho para um ficheiro .pfx
      MEDIADESK_PFX_PASSWORD    -> password do .pfx (se aplicavel)
      MEDIADESK_THUMBPRINT      -> thumbprint de um certificado no Windows
      MEDIADESK_CERT_STORE      -> CurrentUser (omissao) ou LocalMachine
      MEDIADESK_SUBJECT         -> nome (CN) de um certificado no Windows
    Extras:
      MEDIADESK_TSA             -> servidor de timestamp (omissao: DigiCert)
      MEDIADESK_NO_TIMESTAMP=1  -> assinar sem timestamp
    Sem certificado, o pacote e criado na mesma (nao assinado) e imprime-se um
    aviso. Guia completo em ASSINATURA.md.

    Por omissao cria-se tambem o ZIP da pasta portatil (dist\Media Desk.zip),
    que e a descarga recomendada (gera menos avisos do SmartScreen do que um
    auto-extraivel novo). No fim gera-se dist\SHA256SUMS.txt com os hashes de
    release. Usa -NoZip para omitir o ZIP.

    Exemplos:
      powershell -ExecutionPolicy Bypass -File build_portable.ps1
      $env:MEDIADESK_PFX="C:\certs\mediadesk.pfx"; $env:MEDIADESK_PFX_PASSWORD="segredo"; .\build_portable.ps1
      $env:MEDIADESK_THUMBPRINT="AB12..."; $env:MEDIADESK_CERT_STORE="LocalMachine"; .\build_portable.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipPublish,   # reutiliza o launcher ja publicado
    [switch]$SkipSfx,       # cria apenas a pasta portatil (sem auto-extraivel)
    [switch]$NoZip,         # nao cria o ZIP da pasta portatil (por omissao cria)
    [switch]$SkipVersion,   # nao corre sync_version/gen_checksums
    [switch]$SkipInstaller, # nao tenta gerar o instalador (Inno Setup)
    [switch]$KeepBuild      # mantem os ficheiros temporarios de build
)

$ErrorActionPreference = 'Stop'
$root = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
Set-Location $root

function Info($m) { Write-Host "[INFO]  $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "[ OK ]  $m" -ForegroundColor Green }
function Warn($m) { Write-Host "[AVISO] $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "[ERRO]  $m" -ForegroundColor Red; exit 1 }
function Human($b) {
    if ($b -ge 1GB) { "{0:N2} GB" -f ($b / 1GB) }
    elseif ($b -ge 1MB) { "{0:N0} MB" -f ($b / 1MB) }
    else { "{0:N0} KB" -f ($b / 1KB) }
}
function Remove-Tree($path, [int]$Tries = 3) {
    # Remove-Item -Recurse falha em discos USB quando o antivirus/indexador
    # mantem uma pasta aberta por instantes ("O diretorio nao esta vazio").
    # Nao e um erro do build: tenta-se algumas vezes e, como ultimo recurso,
    # esvazia-se a arvore com robocopy /MIR a partir de uma pasta vazia.
    if (-not (Test-Path $path)) { return }
    for ($i = 1; $i -le $Tries; $i++) {
        Remove-Item $path -Recurse -Force -ErrorAction SilentlyContinue
        if (-not (Test-Path $path)) { return }
        Start-Sleep -Milliseconds (400 * $i)
    }
    $empty = Join-Path ([System.IO.Path]::GetTempPath()) ("md-empty-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $empty -Force | Out-Null
    try {
        & robocopy $empty $path /MIR /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
    } finally {
        Remove-Item $empty -Recurse -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $path -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path $path) { Warn "Nao foi possivel remover por completo: $path" }
}

function Copy-Tree($src, $dst, [int]$Tries = 5) {
    # O disco F: (KINGSTON) tem falhas I/O intermitentes. O robocopy copia por
    # blocos, repete cada ficheiro falhado (sem recomecar a arvore toda como o
    # Copy-Item fazia) e ignora os que ja estao iguais, o que torna o build
    # muito mais rapido e resistente em discos USB lentos.
    New-Item -ItemType Directory -Path $dst -Force | Out-Null
    & robocopy $src $dst /E /COPY:DAT /R:$Tries /W:1 /MT:8 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy falhou (codigo $LASTEXITCODE) ao copiar '$src' -> '$dst'." }
}

# -- Assinatura de codigo (opcional) -----------------------------------------
# Definidas cedo para serem usadas na assinatura dos ficheiros finais (passo 7).
function Test-SignConfigured {
    return [bool]($env:MEDIADESK_PFX -or $env:MEDIADESK_THUMBPRINT -or $env:MEDIADESK_SUBJECT)
}

function Resolve-SignTool {
    $st = (Get-Command signtool -ErrorAction SilentlyContinue).Source
    if (-not $st) {
        $cand = Get-ChildItem 'C:\Program Files (x86)\Windows Kits\10\bin' -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -match '\\x64\\' } | Sort-Object FullName -Descending | Select-Object -First 1
        if ($cand) { $st = $cand.FullName }
    }
    return $st
}

function Try-Sign($path) {
    if (-not (Test-Path $path)) { return }
    if (-not (Test-SignConfigured)) { Warn "Sem assinatura (define MEDIADESK_PFX / MEDIADESK_THUMBPRINT / MEDIADESK_SUBJECT): $path"; return }
    # Ja assinado (ex.: launcher devolvido pelo SignPath)? Preservar a assinatura.
    $existing = $null
    try { $existing = Get-AuthenticodeSignature $path } catch { }
    if ($existing -and $existing.Status -ne 'NotSigned') {
        Ok ("Ja assinado, a manter: $path  [{0}]" -f $existing.Status); return
    }
    $signtool = Resolve-SignTool
    if (-not $signtool) { Warn "signtool.exe nao encontrado (instala o Windows SDK)."; return }

    $a = @('sign', '/fd', 'SHA256')
    if ($env:MEDIADESK_PFX) {
        $a += @('/f', $env:MEDIADESK_PFX)
        if ($env:MEDIADESK_PFX_PASSWORD) { $a += @('/p', $env:MEDIADESK_PFX_PASSWORD) }
    } elseif ($env:MEDIADESK_THUMBPRINT) {
        $a += @('/sha1', $env:MEDIADESK_THUMBPRINT)
        if ($env:MEDIADESK_CERT_STORE -and ($env:MEDIADESK_CERT_STORE -ieq 'LocalMachine')) { $a += '/sm' }
    } elseif ($env:MEDIADESK_SUBJECT) {
        $a += @('/n', $env:MEDIADESK_SUBJECT)
    }

    if (-not $env:MEDIADESK_NO_TIMESTAMP) {
        $tsa = if ($env:MEDIADESK_TSA) { $env:MEDIADESK_TSA } else { 'http://timestamp.digicert.com' }
        $a += @('/tr', $tsa, '/td', 'SHA256')
    }
    $a += $path

    & $signtool @a
    if ($LASTEXITCODE -eq 0) {
        $sig = Get-AuthenticodeSignature $path
        Ok ("Assinado: $path  [{0}]" -f $sig.Status)
    } else {
        Warn "Falha ao assinar: $path"
    }
}

$dist        = Join-Path $root 'dist'
$outFolder   = Join-Path $dist 'Media Desk Portable'
$folderZip   = Join-Path $dist 'Media Desk.zip'
$build       = Join-Path $root 'build\portable'
$payloadDir  = Join-Path $build 'payload'
$zipPath     = Join-Path $build 'payload.zip'
$publishDir  = Join-Path $build 'launcher'
$sfxPath     = Join-Path $dist 'Media Desk.exe'
$installerExe = Join-Path $dist 'Media Desk Setup.exe'
$launcherExe = 'Media Desk.exe'
$makeZip = -not $NoZip
$releaseSums = Join-Path $dist 'SHA256SUMS.txt'

Write-Host ""
Write-Host "===============================================" -ForegroundColor Magenta
Write-Host " YT-DLP Media Desk - Pacote portatil" -ForegroundColor Magenta
Write-Host "===============================================" -ForegroundColor Magenta

# --- 0. Validacoes -----------------------------------------------------------
foreach ($f in @('activity_service.py', 'bin\python\python.exe', 'bin\yt-dlp.exe', 'bin\ffmpeg.exe')) {
    if (-not (Test-Path (Join-Path $root $f))) { Die "Dependencia em falta: $f" }
}
if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) { Die "dotnet (SDK 8.0+) nao encontrado no PATH." }
New-Item -ItemType Directory -Path $dist -Force | Out-Null
New-Item -ItemType Directory -Path $build -Force | Out-Null
if (Test-Path $sfxPath) { try { Remove-Item $sfxPath -Force } catch { Die "Nao foi possivel substituir $sfxPath (pode estar em execucao)." } }

# Remove artefactos com os nomes antigos (MediaDesk-*) para que dist\ contenha
# apenas a release atual e nao duas nomenclaturas misturadas.
foreach ($legacy in @(
    (Join-Path $dist 'MediaDesk-Portable'),
    (Join-Path $dist 'MediaDesk-Portable.zip'),
    (Join-Path $dist 'MediaDesk-Portable.exe'),
    (Join-Path $dist 'MediaDesk-Setup.exe'),
    (Join-Path $dist 'Media Desk Portable.exe')
)) {
    if (Test-Path $legacy) {
        try { Remove-Tree $legacy }
        catch { Warn "Nao foi possivel remover o artefacto antigo: $legacy" }
    }
}

# --- 0.b Versao + checksums (fonte unica) ------------------------------------
if (-not $SkipVersion) {
    Info "A sincronizar a versao (version.json -> index.html/server.py/csproj)..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'tools\sync_version.ps1')
    if ($LASTEXITCODE -ne 0) { Die "sync_version.ps1 falhou." }
    Info "A gerar checksums SHA-256..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'tools\gen_checksums.ps1')
    if ($LASTEXITCODE -ne 0) { Die "gen_checksums.ps1 falhou." }
}

# --- 1. Publicar o launcher --------------------------------------------------
$launcher = Join-Path $publishDir $launcherExe
if (-not $SkipPublish) {
    Info "A publicar o launcher (self-contained, single-file)..."
    if (Test-Path $publishDir) { Remove-Tree $publishDir }
    & dotnet publish (Join-Path $root 'MediaDeskLauncher.csproj') -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:DebugType=none -o $publishDir -v q -nologo
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $launcher)) { Die "dotnet publish falhou." }
}
if (-not (Test-Path $launcher)) { Die "Launcher nao encontrado: $launcher" }
Ok ("Launcher publicado (" + (Human (Get-Item $launcher).Length) + ")")

# --- 2. Staging do payload (sem o launcher) ----------------------------------
Info "A preparar os ficheiros da aplicacao..."
if (Test-Path $payloadDir) { Remove-Tree $payloadDir }
New-Item -ItemType Directory -Path $payloadDir -Force | Out-Null

foreach ($f in 'server.py', 'activity_service.py', 'index.html', 'manifest.webmanifest', 'sw.js', 'favicon.svg') {
    $src = Join-Path $root $f
    if (Test-Path $src) { Copy-Item $src (Join-Path $payloadDir $f) -Force } else { Warn "Interface em falta: $f" }
}
foreach ($f in 'version.json', 'licenses.json', 'checksums.json', 'app.ico', 'verificar-integridade.ps1') {
    $src = Join-Path $root $f
    if (Test-Path $src) { Copy-Item $src (Join-Path $payloadDir $f) -Force } else { Warn "Ficheiro em falta: $f" }
}
if (Test-Path (Join-Path $root 'icons')) {
    Copy-Tree (Join-Path $root 'icons') (Join-Path $payloadDir 'icons')
}
if (Test-Path (Join-Path $root 'licenses')) {
    Copy-Tree (Join-Path $root 'licenses') (Join-Path $payloadDir 'licenses')
}

# Avisos de licenca + oferta de codigo-fonte (GPL), gerados a partir dos
# binarios empacotados para que a revisao indicada corresponda ao que sai.
$noticeScript = Join-Path $root 'tools\gen_licenses_notice.ps1'
if (Test-Path $noticeScript) {
    Info "A gerar avisos de licenca (FFmpeg/source offer)..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File $noticeScript -OutDir (Join-Path $payloadDir 'licenses')
    if ($LASTEXITCODE -ne 0) { Die "tools\gen_licenses_notice.ps1 falhou (avisos de licenca nao gerados)." }
} else {
    Warn "tools\gen_licenses_notice.ps1 em falta - avisos de licenca nao gerados."
}

$payloadBin = Join-Path $payloadDir 'bin'
New-Item -ItemType Directory -Path $payloadBin -Force | Out-Null
Copy-Tree (Join-Path $root 'bin\python') (Join-Path $payloadBin 'python')
foreach ($b in 'yt-dlp.exe', 'ffmpeg.exe', 'deno.exe') {
    $src = Join-Path $root "bin\$b"
    if (Test-Path $src) { Copy-Item $src (Join-Path $payloadBin $b) -Force } else { Warn "Ferramenta em falta: bin\$b" }
}

# As definicoes sao inicializadas e cifradas por DPAPI no primeiro arranque.
# Nao incluir config.enc no pacote: a cifra e especifica da conta Windows.

# LEIA-ME
$leia = @'
YT-DLP Media Desk - Versao portatil
====================================

Esta pasta e autonoma: NAO precisa de instalar nada (Python, yt-dlp, FFmpeg e
Deno viajam aqui dentro). Pode ser copiada para um pendrive, disco externo ou
cartao de memoria e executada em qualquer PC Windows x64.

COMO USAR
  1. Execute "Media Desk.exe".
  2. Os downloads ficam na pasta "downloads".
  3. Ao fechar a janela, o servidor interno e encerrado automaticamente.

NOTAS
  - Ajuste legendas, cookies e PO Token em "Configuracao".
  - Se mover a pasta, mantenha todos os ficheiros juntos.
  - As definicoes sao cifradas por DPAPI e vinculadas a esta conta Windows.
    Nao e possivel transferir o ficheiro cifrado para outro PC ou utilizador.

VERIFICAR A INTEGRIDADE (opcional)
  - Para confirmar que os ficheiros sao originais, execute:
        powershell -ExecutionPolicy Bypass -File verificar-integridade.ps1
  - Se descarregou o ZIP ou o auto-extraivel, confira o SHA-256 com o ficheiro
    "SHA256SUMS.txt" publicado junto da descarga.
'@
Set-Content (Join-Path $payloadDir 'LEIA-ME.txt') -Value $leia -Encoding UTF8

# --- 3. Pasta portatil -------------------------------------------------------
Info "A montar a pasta portatil..."
if (Test-Path $outFolder) { Remove-Tree $outFolder }
New-Item -ItemType Directory -Path $outFolder -Force | Out-Null
Copy-Item $launcher (Join-Path $outFolder $launcherExe) -Force
Copy-Tree $payloadDir $outFolder
Ok "Pasta portatil criada: $outFolder"

if (-not $SkipSfx) {
    # --- 4. Zip do payload ---------------------------------------------------
    Info "A comprimir o payload (pode demorar alguns minutos)..."
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory($payloadDir, $zipPath, [System.IO.Compression.CompressionLevel]::Optimal, $false)
    Ok ("Payload comprimido (" + (Human (Get-Item $zipPath).Length) + ")")

    # --- 5. Executavel auto-extraivel ---------------------------------------
    Info "A criar o executavel auto-extraivel..."
    $launcherLen = (Get-Item $launcher).Length
    $zipLen = (Get-Item $zipPath).Length
    $version = [DateTime]::UtcNow.Ticks

    Copy-Item $launcher $sfxPath -Force
    $fs = [System.IO.File]::Open($sfxPath, [System.IO.FileMode]::Append, [System.IO.FileAccess]::Write)
    try {
        $zfs = [System.IO.File]::OpenRead($zipPath)
        try { $zfs.CopyTo($fs) } finally { $zfs.Dispose() }
        # Rodape (32 bytes): zipOffset(8) zipLength(8) version(8) reservado(4) magic "MDPL"(4)
        $footer = New-Object byte[] 32
        [BitConverter]::GetBytes([Int64]$launcherLen).CopyTo($footer, 0)
        [BitConverter]::GetBytes([Int64]$zipLen).CopyTo($footer, 8)
        [BitConverter]::GetBytes([Int64]$version).CopyTo($footer, 16)
        [System.Text.Encoding]::ASCII.GetBytes('MDPL').CopyTo($footer, 28)
        $fs.Write($footer, 0, 32)
    } finally { $fs.Dispose() }
    Ok ("Auto-extraivel criado: $sfxPath  (" + (Human (Get-Item $sfxPath).Length) + ")")
}

# --- 7. Assinatura de codigo (opcional) --------------------------------------
# Assinam-se os ficheiros FINAIS: o launcher da pasta portatil e o auto-extraivel
# (e, no passo 7.b, o instalador). O signtool anexa a tabela de certificados ao
# FIM do ficheiro; no auto-extraivel isso deixa o rodape "MDPL" antes da
# assinatura. O leitor do rodape tolera essa assinatura anexada (ver
# Program.cs, Payload.Prepare), por isso a ordem assinar-depois-de-montar e a
# correta. (O metodo de "assinar o stub antes de anexar" NAO funciona: a
# assinatura deixa de ser encontrada depois de anexar o overlay.)
Try-Sign (Join-Path $outFolder $launcherExe)
if (-not $SkipSfx) { Try-Sign $sfxPath }

# --- 7.b Instalador (Inno Setup, opcional) -----------------------------------
if (-not $SkipInstaller) {
    $iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
    if (-not $iscc) {
        foreach ($cand in @(
            'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
            'C:\Program Files\Inno Setup 6\ISCC.exe',
            (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
        )) { if (Test-Path $cand) { $iscc = $cand; break } }
    }
    if ($iscc) {
        Info "A gerar o instalador (Inno Setup)..."
        $iss = Join-Path $root 'installer\mediadesk.iss'
        & $iscc $iss
        if ($LASTEXITCODE -eq 0 -and (Test-Path $installerExe)) {
            Ok ("Instalador criado: $installerExe  (" + (Human (Get-Item $installerExe).Length) + ")")
            Try-Sign $installerExe
        } else { Warn "Inno Setup falhou ao compilar o instalador." }
    } else {
        Warn "Inno Setup (ISCC.exe) nao encontrado; instalador nao gerado."
        Write-Host "      Instala o Inno Setup 6: https://jrsoftware.org/isdl.php"
    }
}

# --- 7.c ZIP da pasta portatil (omissao; apos assinar) -----------------------
if ($makeZip) {
    Info "A comprimir a pasta portatil (ZIP)..."
    if (Test-Path $folderZip) { Remove-Item $folderZip -Force }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory($outFolder, $folderZip, [System.IO.Compression.CompressionLevel]::Optimal, $true)
    Ok ("ZIP criado (" + (Human (Get-Item $folderZip).Length) + "): $folderZip")
}

# --- 7.d Hashes de release + utilitario de verificacao ------------------------
Info "A gerar SHA256SUMS.txt (hashes de release)..."
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'tools\gen_release_hashes.ps1')
if ($LASTEXITCODE -ne 0) { Warn "gen_release_hashes.ps1 falhou; verifica os hashes manualmente." }
Copy-Item (Join-Path $root 'verificar-integridade.ps1') (Join-Path $dist 'verificar-integridade.ps1') -Force
# --- 7.e Ficheiro PAD (Softpedia e outros diretorios) ------------------------
Info "A gerar o ficheiro PAD (pad\mediadesk.xml)..."
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'tools\gen_pad.ps1')
if ($LASTEXITCODE -ne 0) { Warn "gen_pad.ps1 falhou; o PAD nao foi atualizado." }

# --- 8. Limpeza --------------------------------------------------------------
if (-not $KeepBuild) {
    Remove-Tree $payloadDir
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force -ErrorAction SilentlyContinue }
}

# --- 9. Resumo ---------------------------------------------------------------
Write-Host ""
Write-Host "Concluido." -ForegroundColor Green
Write-Host ""
Write-Host "  Pasta portatil : $outFolder"
if (-not $SkipSfx) { Write-Host "  Auto-extraivel : $sfxPath" }
if ($makeZip) { Write-Host "  Zip da pasta   : $folderZip" }
Write-Host ""
if (-not $SkipSfx -and (Test-Path $sfxPath)) {
    Write-Host "  SHA256 (auto-extraivel):"
    Write-Host "    " ((Get-FileHash $sfxPath -Algorithm SHA256).Hash)
    Write-Host ""
}
if ($makeZip -and (Test-Path $folderZip)) {
    Write-Host "  SHA256 (ZIP da pasta):"
    Write-Host "    " ((Get-FileHash $folderZip -Algorithm SHA256).Hash)
    Write-Host ""
}
if (Test-Path $releaseSums) {
    Write-Host "  Hashes de release: $releaseSums"
    Write-Host "  Verificar        : verificar-integridade.ps1 (na pasta portatil ou junto dos artefactos)"
    Write-Host ""
}
if (-not (Test-SignConfigured)) {
    Warn "Pacote NAO assinado. O SmartScreen pode avisar na 1. execucao."
    Write-Host "      Opcoes: (1) assinar com MEDIADESK_PFX / MEDIADESK_THUMBPRINT / MEDIADESK_SUBJECT;"
    Write-Host "              (2) distribuir a pasta/ZIP portatil (o Windows bloqueia menos"
    Write-Host "                  do que auto-extraiveis novos)."
    Write-Host "      Guia: ASSINATURA.md (obter/criar certificado, testar, opcoes)."
    Write-Host "      Se aparecer aviso do Defender, envia o ficheiro como falso positivo em:"
    Write-Host "      https://www.microsoft.com/en-us/wdsi/filesubmission"
} else {
    Ok "Assinatura aplicada."
}
Write-Host ""
