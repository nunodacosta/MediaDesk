<#
    tools/gen_logo_flat.ps1
    -----------------------------------------------------------------------------
    Gera a geometria do logotipo "cristal em bruto" (muitos triangulos planos):

      brand\logo-flat.svg           (squircle, cantos transparentes)
      brand\logo-flat-maskable.svg  (fundo sangrado, glifo a 86%)
      brand\logo-flat-bands.json    (facetas para tools\gen_icons.ps1)

    O gradiente da primeira solucao (amarelo -> laranja -> rosa -> roxo -> azul)
    e desconstruido numa malha irregular de triangulos. As cores repetem-se por
    varias facetas como num cristal em bruto iluminado: o tom de cada faceta
    vem da posicao no eixo da luz (canto inferior esquerdo -> superior direito)
    mais um desvio proprio de cada triangulo. A passagem quente inclui o
    vermelho do YouTube (#FF0000). Tudo em cor plana, sem gradientes.

    Uso:
      powershell -ExecutionPolicy Bypass -File tools\gen_logo_flat.ps1
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$inv = [System.Globalization.CultureInfo]::InvariantCulture

# --- paleta: 10 tons, do amarelo ao azul --------------------------------
$palette = @(
    '#FEDA75', # amarelo
    '#FAB03E', # ambar
    '#F47B14', # laranja
    '#EF2A1F', # vermelho-laranja
    '#FF0000', # vermelho do YouTube
    '#E6003D', # vermelho-rosa
    '#D62976', # rosa
    '#B92C87', # rosa-magenta
    '#8134AF', # roxo
    '#515BD4'  # azul
)

# Limites em t (0 = canto inferior esquerdo, 1 = superior direito).
$bounds = @(0.08, 0.16, 0.24, 0.31, 0.38, 0.45, 0.52, 0.60, 0.72)

# --- malha irregular de triangulos ---------------------------------------
$cells = 6
$size = 64.0
$cell = $size / $cells
$sparkle = 0.13   # desvio de tom por faceta (em t)

function Hash01 {
    param([double]$a, [double]$b, [double]$c)
    $s = [Math]::Sin($a * 12.9898 + $b * 78.233 + $c * 37.719) * 43758.5453
    return $s - [Math]::Floor($s)
}

function Format-Num {
    param([double]$n)
    return $n.ToString('0.#', $inv)
}

# Escreve UTF-8 sem BOM: os SVG e o JSON ficam limpos para qualquer parser.
function Write-Utf8 {
    param([string]$Path, [string]$Text)
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false)))
}

# Vertices: interiores deslocados, bordas deslizam ao longo do proprio bordo
# para a malha continuar a cobrir tudo.
function Get-Vertex {
    param([int]$i, [int]$j)
    $x = $i * $cell
    $y = $j * $cell
    $onLeft = ($i -eq 0)
    $onRight = ($i -eq $cells)
    $onTop = ($j -eq 0)
    $onBottom = ($j -eq $cells)
    $r1 = (Hash01 $i $j 1) - 0.5
    $r2 = (Hash01 $i $j 2) - 0.5
    if (-not ($onLeft -or $onRight -or $onTop -or $onBottom)) {
        $x += $r1 * 0.62 * $cell
        $y += $r2 * 0.62 * $cell
    } elseif ($onLeft -or $onRight) {
        $y += $r1 * 0.70 * $cell
    } elseif ($onTop -or $onBottom) {
        $x += $r1 * 0.70 * $cell
    }
    return @([Math]::Round($x, 1), [Math]::Round($y, 1))
}

# t de um ponto no eixo da luz (0 no canto inferior esquerdo, 1 no oposto).
function Get-T {
    param([double]$x, [double]$y)
    return (($x - $y + 64.0) / 128.0)
}

function Get-ToneIndex {
    param([double]$t)
    $tt = [Math]::Min(0.999, [Math]::Max(0.0, $t))
    for ($k = 0; $k -lt $bounds.Count; $k++) {
        if ($tt -lt $bounds[$k]) { return $k }
    }
    return $palette.Count - 1
}

$facets = [System.Collections.Generic.List[object]]::new()
for ($j = 0; $j -lt $cells; $j++) {
    for ($i = 0; $i -lt $cells; $i++) {
        $a = Get-Vertex $i $j
        $b = Get-Vertex ($i + 1) $j
        $c = Get-Vertex ($i + 1) ($j + 1)
        $d = Get-Vertex $i ($j + 1)
        $tris = [System.Collections.Generic.List[object]]::new()
        if ((Hash01 $i $j 7) -gt 0.5) {
            $tris.Add(@($a, $b, $c))
            $tris.Add(@($a, $c, $d))
        } else {
            $tris.Add(@($a, $b, $d))
            $tris.Add(@($b, $c, $d))
        }
        $k = 0
        foreach ($tri in $tris) {
            $cx = ($tri[0][0] + $tri[1][0] + $tri[2][0]) / 3.0
            $cy = ($tri[0][1] + $tri[1][1] + $tri[2][1]) / 3.0
            # desvio proprio da faceta: cada triangulo reflecte a luz de forma
            # ligeiramente diferente, o que repete tons pela malha
            $jitterT = ((Hash01 $i $j (10 + $k)) - 0.5) * 2.0 * $sparkle
            $tone = Get-ToneIndex ((Get-T $cx $cy) + $jitterT)
            $k++
            $d2 = 'M{0} {1}L{2} {3}L{4} {5}Z' -f `
                (Format-Num $tri[0][0]), (Format-Num $tri[0][1]), `
                (Format-Num $tri[1][0]), (Format-Num $tri[1][1]), `
                (Format-Num $tri[2][0]), (Format-Num $tri[2][1])
            $facets.Add([pscustomobject]@{ color = $palette[$tone]; d = $d2 })
        }
    }
}

# Simbolo aprovado: triangulo de play do YouTube rodado a apontar para baixo,
# inteiramente branco, e bandeja solida com "DLP" vazado. A mascara recorta as
# letras na bandeja para o cristal aparecer atraves delas.
$glyph = @'
  <mask id="md-dlp" maskUnits="userSpaceOnUse" x="0" y="0" width="64" height="64">
    <rect x="15.6" y="43.3" width="32.8" height="9" rx="4.5" fill="#fff"/>
    <path d="M24.68 45.3H22.103V50.5H24.68A3.068 2.6 0 0 0 24.68 45.3" fill="none" stroke="#000" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round"/>
    <path d="M30.896 45.3V50.5H34.945" fill="none" stroke="#000" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round"/>
    <path d="M38.584 50.5V45.3H41.038A2.025 1.716 0 0 1 41.038 48.524H38.584" fill="none" stroke="#000" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round"/>
  </mask>
  <path d="M22.6 14H41.4Q43 14 42.166 15.365L32.834 30.635Q32 32 31.166 30.635L21.834 15.365Q21 14 22.6 14Z" transform="translate(0 1.6)" fill="#fff" stroke="#fff" stroke-width="1.4" stroke-linejoin="round"/>
  <g mask="url(#md-dlp)">
    <rect x="15.6" y="43.3" width="32.8" height="9" rx="4.5" fill="#fff"/>
  </g>
'@

$facetBlock = ($facets | ForEach-Object { '    <path d="{0}" fill="{1}"/>' -f $_.d, $_.color }) -join "`n"

$svg = @"
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="Media Desk">
  <defs>
    <clipPath id="md-squircle">
      <rect x="2" y="2" width="60" height="60" rx="16.5"/>
    </clipPath>
  </defs>
  <!-- Gerado por tools/gen_logo_flat.ps1: gradiente da primeira solucao
       desconstruido em $($facets.Count) triangulos planos, como um cristal em
       bruto iluminado. Inclui a evolucao para o vermelho do YouTube. -->
  <g clip-path="url(#md-squircle)">
$facetBlock
  </g>
$glyph
</svg>
"@
Write-Utf8 (Join-Path $root 'brand\logo-flat.svg') $svg

$maskable = @"
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="Media Desk">
  <!-- Gerado por tools/gen_logo_flat.ps1. Versao maskable: fundo sangrado e
       glifo dentro da zona segura. -->
$facetBlock
  <g transform="translate(32 32) scale(.86) translate(-32 -32)">
$glyph
  </g>
</svg>
"@
Write-Utf8 (Join-Path $root 'brand\logo-flat-maskable.svg') $maskable

# Os ficheiros de marca usados pela app sao copias da mesma geometria.
Write-Utf8 (Join-Path $root 'brand\logo.svg') $svg
Write-Utf8 (Join-Path $root 'brand\logo-maskable.svg') $maskable
Write-Utf8 (Join-Path $root 'favicon.svg') $svg

# JSON: cada faceta com a cor e os pontos do poligono (par x,y) para o GDI+.
$jsonFacets = $facets | ForEach-Object {
    $nums = [regex]::Matches($_.d, '-?\d+(\.\d+)?') | ForEach-Object { [double]::Parse($_.Value, $inv) }
    $pts = for ($p = 0; $p -lt $nums.Count; $p += 2) { , @($nums[$p], $nums[$p + 1]) }
    [pscustomobject]@{ color = $_.color; points = @($pts) }
}
$json = [pscustomobject]@{
    viewBox = 64
    facets  = @($jsonFacets)
} | ConvertTo-Json -Depth 6 -Compress
Write-Utf8 (Join-Path $root 'brand\logo-flat-bands.json') $json

$used = ($facets | Group-Object color | Measure-Object).Count
Write-Host ("[gen_logo_flat] {0} triangulos, {1} tons usados; SVG: {2:N0} bytes" -f `
        $facets.Count, $used, $svg.Length) -ForegroundColor Green
