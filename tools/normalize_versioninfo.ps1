<#
    tools/normalize_versioninfo.ps1
    -----------------------------------------------------------------------------
    Remove o preenchimento de espacos (padding) dos campos da Version Info de um
    executavel gerado pelo Inno Setup.

    Porque: o stub do Inno Setup reserva largura fixa para cada campo da
    Version Info e preenche o resto com espacos (comportamento do proprio Inno,
    sem diretiva para o desativar). Por exemplo, ProductName fica
    "YT-DLP Media Desk" seguido de 43 espacos. A SignPath exige restricoes de
    metadados EXATAS (product-name/product-version), logo os espacos tem de sair.

    Como: substitui apenas os espacos a direita de cada valor textual por NUL,
    no proprio ficheiro e SEM alterar o tamanho nem a estrutura do PE. Como nada
    se desloca, o payload do instalador e o resto do ficheiro ficam intactos
    (ao contrario de reescrever o recurso com o Resource Hacker, que corrompe).

    Este passo corre so na copia preparada para o SignPath (tools/prep_signpath.ps1).

    Uso:
      powershell -ExecutionPolicy Bypass -File tools\normalize_versioninfo.ps1 -Path dist\MediaDesk-Setup.exe
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Path
)

$ErrorActionPreference = 'Stop'

function Ok($m)   { Write-Host "[ OK ]  $m" -ForegroundColor Green }
function Warn($m) { Write-Host "[AVISO] $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "[ERRO]  $m" -ForegroundColor Red; exit 1 }

if (-not (Test-Path $Path)) { Die "Ficheiro nao encontrado: $Path" }
$full  = (Resolve-Path $Path).Path
$bytes = [System.IO.File]::ReadAllBytes($full)
$origLen = $bytes.Length

# 1. Localizar o bloco VS_VERSIONINFO (chave "VS_VERSION_INFO" em UTF-16LE).
$needle = [System.Text.Encoding]::Unicode.GetBytes('VS_VERSION_INFO')
$idx = -1
for ($i = 0; $i -le $bytes.Length - $needle.Length; $i++) {
    $match = $true
    for ($j = 0; $j -lt $needle.Length; $j++) {
        if ($bytes[$i + $j] -ne $needle[$j]) { $match = $false; break }
    }
    if ($match) { $idx = $i; break }
}
if ($idx -lt 0) { Die "Version Info nao encontrada em $Path." }

# wLength(2) + wValueLength(2) + wType(2) precedem a chave
$blockStart = $idx - 6
if ($blockStart -lt 0) { Die "Bloco de versao invalido em $Path." }

$script:stripped = 0

function Get-StrEnd([int]$o) {
    # Le a string UTF-16LE ate ao NUL e devolve a posicao imediatamente apos o NUL.
    while ($o -lt $bytes.Length - 1 -and [BitConverter]::ToUInt16($bytes, $o) -ne 0) { $o += 2 }
    return ($o + 2)
}

function Walk([int]$b) {
    if ($b + 6 -gt $bytes.Length) { return }
    $wLength      = [BitConverter]::ToUInt16($bytes, $b)
    $wValueLength = [BitConverter]::ToUInt16($bytes, $b + 2)
    $wType        = [BitConverter]::ToUInt16($bytes, $b + 4)
    if ($wLength -le 0) { return }

    $pos = Get-StrEnd ($b + 6)          # fim da chave
    $pos = ($pos + 3) -band (-bnot 3)   # alinha a 4 bytes

    # Nota: o Inno escreve wType=1 tambem nos nos contentores (StringFileInfo,
    # StringTable), por isso nao se decide pelo wType. Um no com wValueLength>0
    # tem um valor; o no raiz tem valor binario (VS_FIXEDFILEINFO) E filhos.
    if ($wValueLength -gt 0) {
        if ($wType -eq 1) {
            # Valor textual (campo da Version Info): tira os espacos a direita
            # (substitui por NUL), sem mudar o tamanho. Strings nao tem filhos.
            $valStart = $pos
            $valEnd = $valStart
            while ($valEnd -lt $bytes.Length - 1 -and [BitConverter]::ToUInt16($bytes, $valEnd) -ne 0) { $valEnd += 2 }
            $trim = $valEnd
            while ($trim -gt $valStart -and [BitConverter]::ToUInt16($bytes, $trim - 2) -eq 0x20) { $trim -= 2 }
            if ($trim -lt $valEnd) {
                for ($i = $trim; $i -lt $valEnd; $i += 2) { $bytes[$i] = 0; $bytes[$i + 1] = 0 }
                $script:stripped++
            }
            return
        }
        # Valor binario: salta-o e continua para os possiveis filhos.
        $pos += $wValueLength
        $pos = ($pos + 3) -band (-bnot 3)
    }

    # Percorre os blocos filhos (contentores e o no raiz). O wLength de um bloco
    # NAO inclui o padding de alinhamento que se segue, por isso alinha-se o
    # cursor a 4 bytes antes do bloco seguinte.
    $end = $b + $wLength
    while ($pos + 2 -le $bytes.Length -and $pos -lt $end) {
        $childLen = [BitConverter]::ToUInt16($bytes, $pos)
        if ($childLen -le 0) { break }
        Walk $pos
        $pos += $childLen
        $pos = ($pos + 3) -band (-bnot 3)
    }
}

Walk $blockStart

if ($script:stripped -eq 0) {
    Warn "Nenhum campo tinha padding (ja estava exato): $Path"
    exit 0
}

[System.IO.File]::WriteAllBytes($full, $bytes)

if ($bytes.Length -ne $origLen) { Die "Tamanho mudou (nao devia): $origLen -> $($bytes.Length)" }
Ok ("Padding removido de $($script:stripped) campos (tamanho inalterado): $Path")
