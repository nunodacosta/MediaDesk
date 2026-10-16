<#
    tools/sync_version.ps1
    -----------------------------------------------------------------------------
    Fonte unica de verdade: version.json
    Gera/atualiza:
      - index.html ......... bloco entre // VERSION:BEGIN e // VERSION:END
      - server.py .......... linha APP_VERSION
      - MediaDeskLauncher.csproj ... <Version>/<FileVersion>/<InformationalVersion>
      - installer/mediadesk.iss .... #define AppVersion

    Uso:
      powershell -ExecutionPolicy Bypass -File tools\sync_version.ps1
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

$verPath = Join-Path $root 'version.json'
if (-not (Test-Path $verPath)) { throw "version.json nao encontrado em $root" }
$vj = Get-Content $verPath -Raw -Encoding UTF8 | ConvertFrom-Json
$version = [string]$vj.version
$date = [string]$vj.date
$build = [int]$vj.build
Write-Host "[sync_version] versao $version ($date, build $build)" -ForegroundColor Cyan

# ============================ index.html ====================================
$idxPath = Join-Path $root 'index.html'
$html = [System.IO.File]::ReadAllText($idxPath, [System.Text.Encoding]::UTF8)

$entries = New-Object System.Collections.Generic.List[string]
foreach ($h in $vj.history) {
    $e = New-Object System.Collections.Generic.List[string]
    $e.Add('                {')
    $e.Add("                    version: `"$($h.version)`",")
    $e.Add("                    date: `"$($h.date)`",")
    $hasGroups = ($h.PSObject.Properties.Name -contains 'groups') -and ($null -ne $h.groups)
    if ($hasGroups) {
        $e.Add('                    groups: {')
        foreach ($g in $h.groups.PSObject.Properties) {
            $items = ($g.Value | ForEach-Object { "`"$_`"" }) -join ', '
            $e.Add("                        `"$($g.Name)`": [$items],")
        }
        $e.Add('                    }')
    } else {
        $items = ($h.changes | ForEach-Object { "`"$_`"" }) -join ', '
        $e.Add("                    changes: [$items]")
    }
    $e.Add('                }')
    $entries.Add(($e -join "`r`n"))
}
$historyJs = ($entries -join ",`r`n")

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add('// VERSION:BEGIN - gerado por tools/sync_version.ps1; nao editar a mao.')
$lines.Add("            const APP_VERSION = `"$version`";")
$lines.Add("            const APP_VERSION_DATE = `"$date`";")
$lines.Add("            const APP_BUILD = $build;")
$lines.Add('            const VERSION_HISTORY = [')
$lines.Add($historyJs)
$lines.Add('            ];')
$lines.Add('            const CURRENT_VERSION_CHANGES = VERSION_HISTORY[0].groups')
$lines.Add('                ? Object.values(VERSION_HISTORY[0].groups).flat()')
$lines.Add('                : VERSION_HISTORY[0].changes;')
$lines.Add('            // VERSION:END')
$block = ($lines -join "`r`n")

$begin = '// VERSION:BEGIN'
$end = '// VERSION:END'
$bi = $html.IndexOf($begin)
$ei = $html.IndexOf($end)
if ($bi -lt 0 -or $ei -lt 0) { throw 'Marcadores VERSION nao encontrados em index.html' }
$eiEnd = $ei + $end.Length
$html = $html.Substring(0, $bi) + $block + $html.Substring($eiEnd)
[System.IO.File]::WriteAllText($idxPath, $html, (New-Object System.Text.UTF8Encoding($false)))
Write-Host '[sync_version] index.html atualizado' -ForegroundColor Green

# ============================ server.py =====================================
$srvPath = Join-Path $root 'server.py'
if (Test-Path $srvPath) {
    $srv = [System.IO.File]::ReadAllText($srvPath, [System.Text.Encoding]::UTF8)
    $new = [regex]::Replace($srv, '(?m)^APP_VERSION\s*=\s*"[^"]*".*$', "APP_VERSION = `"$version`"  # gerado por tools/sync_version.ps1")
    if ($new -ne $srv) {
        [System.IO.File]::WriteAllText($srvPath, $new, (New-Object System.Text.UTF8Encoding($false)))
        Write-Host '[sync_version] server.py atualizado' -ForegroundColor Green
    } else {
        Write-Host '[sync_version] server.py: linha APP_VERSION ja correta' -ForegroundColor Yellow
    }
}

# ============================ csproj ========================================
$csPath = Join-Path $root 'MediaDeskLauncher.csproj'
if (Test-Path $csPath) {
    $cs = [System.IO.File]::ReadAllText($csPath, [System.Text.Encoding]::UTF8)
    $cs = [regex]::Replace($cs, '<Version>[^<]*</Version>', "<Version>$version</Version>")
    $cs = [regex]::Replace($cs, '<FileVersion>[^<]*</FileVersion>', "<FileVersion>$version.0</FileVersion>")
    $cs = [regex]::Replace($cs, '<InformationalVersion>[^<]*</InformationalVersion>', "<InformationalVersion>$version</InformationalVersion>")
    [System.IO.File]::WriteAllText($csPath, $cs, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host '[sync_version] csproj atualizado' -ForegroundColor Green
}

# ============================ installer .iss ================================
$issPath = Join-Path $root 'installer\mediadesk.iss'
if (Test-Path $issPath) {
    # O .iss tem acentos nas mensagens personalizadas (Espanol/Francais/Deutsch),
    # por isso e gravado em UTF-8. Detetamos se o ficheiro original tem BOM e
    # preservamo-lo: o Inno Setup 6 so garante a leitura correta de UTF-8 quando
    # existe BOM.
    $issBytes = [System.IO.File]::ReadAllBytes($issPath)
    $issHasBom = ($issBytes.Length -ge 3 -and $issBytes[0] -eq 0xEF -and $issBytes[1] -eq 0xBB -and $issBytes[2] -eq 0xBF)
    $iss = [System.Text.Encoding]::UTF8.GetString($issBytes)
    if ($issHasBom) { $iss = $iss.TrimStart([char]0xFEFF) }
    $newIss = [regex]::Replace($iss, '(?m)^(#define AppVersion\s*)"[^"]*"', "`$1`"$version`"")
    if ($newIss -ne $iss) {
        [System.IO.File]::WriteAllText($issPath, $newIss, (New-Object System.Text.UTF8Encoding($issHasBom)))
        Write-Host '[sync_version] installer\mediadesk.iss atualizado' -ForegroundColor Green
    } else {
        Write-Host '[sync_version] installer\mediadesk.iss: AppVersion ja correta' -ForegroundColor Yellow
    }
}

# ============================ README.md =====================================
# Mantem a versao visivel na pagina inicial do repositorio (os termos da
# SignPath Foundation exigem que a home page / pagina de download corresponda
# a release publicada). Preserva o BOM se existir.
$readmePath = Join-Path $root 'README.md'
if (Test-Path $readmePath) {
    $rmBytes = [System.IO.File]::ReadAllBytes($readmePath)
    $rmHasBom = ($rmBytes.Length -ge 3 -and $rmBytes[0] -eq 0xEF -and $rmBytes[1] -eq 0xBB -and $rmBytes[2] -eq 0xBF)
    $rm = [System.Text.Encoding]::UTF8.GetString($rmBytes)
    if ($rmHasBom) { $rm = $rm.TrimStart([char]0xFEFF) }
    # \u00e3 evita depender da codificacao do proprio script (Windows PowerShell
    # le .ps1 sem BOM como ANSI); casa tanto "Versao" como "Versao" com til.
    # Usa ${1} (e nao $1) porque a versao comeca por digito: "$1$version"
    # seria lido pelo .NET como o grupo inexistente "$13" e ficaria literal.
    $newRm = [regex]::Replace($rm, '(?m)^(- \*\*Vers\u00e3o:\*\* ).*$', "`${1}$version")
    if ($newRm -ne $rm) {
        [System.IO.File]::WriteAllText($readmePath, $newRm, (New-Object System.Text.UTF8Encoding($rmHasBom)))
        Write-Host '[sync_version] README.md atualizado' -ForegroundColor Green
    } else {
        Write-Host '[sync_version] README.md: versao ja correta' -ForegroundColor Yellow
    }
}

Write-Host "[sync_version] concluido: $version" -ForegroundColor Cyan
