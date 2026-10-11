<#
    verificar-integridade.ps1
    -----------------------------------------------------------------------------
    Verifica a integridade (SHA-256) dos ficheiros do YT-DLP Media Desk.

    Funciona em dois modos (automático):
      1) Junto dos artefactos de release (pasta dist\): verifica os ficheiros
         listados no SHA256SUMS.txt (ZIP, auto-extraivel, instalador, launcher).
      2) Dentro da pasta portatil (MediaDesk-Portable\): verifica os ficheiros
         da aplicacao contra o checksums.json.

    Uso:
      powershell -ExecutionPolicy Bypass -File verificar-integridade.ps1

    Devolve 0 se tudo for valido; 1 se algum ficheiro falhar.
#>
$ErrorActionPreference = 'Stop'
$dir = $PSScriptRoot
if (-not $dir) { $dir = Split-Path -Parent $MyInvocation.MyCommand.Path }
Set-Location $dir

$falhas  = 0
$ok      = 0

function Test-Uma($rel, $esperado) {
    $full = Join-Path $dir $rel
    if (-not (Test-Path $full)) {
        Write-Host ("  [EM FALTA] {0}" -f $rel) -ForegroundColor DarkYellow
        $script:falhas++
        return
    }
    $real = (Get-FileHash $full -Algorithm SHA256).Hash.ToLower()
    if ($real -eq $esperado.ToLower()) {
        Write-Host ("  [OK]      {0}" -f $rel) -ForegroundColor Green
        $script:ok++
    } else {
        Write-Host ("  [FALHOU]  {0}" -f $rel) -ForegroundColor Red
        Write-Host ("            esperado: {0}" -f $esperado)
        Write-Host ("            obtido  : {0}" -f $real)
        $script:falhas++
    }
}

if (Test-Path (Join-Path $dir 'SHA256SUMS.txt')) {
    Write-Host "A verificar artefactos de release (SHA256SUMS.txt)..." -ForegroundColor Cyan
    $linhas = Get-Content (Join-Path $dir 'SHA256SUMS.txt') -Encoding UTF8 |
              Where-Object { $_ -and -not $_.StartsWith('#') }
    foreach ($l in $linhas) {
        $partes = $l -split '  ', 2
        if ($partes.Count -lt 2) { continue }
        Test-Uma $partes[1].Trim() $partes[0].Trim()
    }
} elseif (Test-Path (Join-Path $dir 'checksums.json')) {
    Write-Host "A verificar os ficheiros da aplicacao (checksums.json)..." -ForegroundColor Cyan
    $cj = Get-Content (Join-Path $dir 'checksums.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($k in $cj.ficheiros.PSObject.Properties.Name) {
        Test-Uma ($k -replace '/', '\') $cj.ficheiros.$k
    }
} else {
    Write-Host "Nenhum SHA256SUMS.txt nem checksums.json encontrado nesta pasta." -ForegroundColor Yellow
    Write-Host "Coloque este script junto dos artefactos de release ou dentro da pasta portatil."
    exit 2
}

Write-Host ""
if ($falhas -eq 0) {
    Write-Host ("Integridade OK: {0} ficheiro(s) validos." -f $ok) -ForegroundColor Green
    exit 0
} else {
    Write-Host ("Integridade COM PROBLEMAS: {0} falha(s), {1} ok." -f $falhas, $ok) -ForegroundColor Red
    exit 1
}