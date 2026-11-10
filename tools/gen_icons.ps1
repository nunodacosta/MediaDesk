<#
    tools/gen_icons.ps1
    -----------------------------------------------------------------------------
    Gera os icones do Media Desk a partir da geometria do logotipo:

      icons\icon-32.png, icon-192.png, icon-512.png
      icons\icon-maskable-512.png   (fundo sangrado + glifo na zona segura)
      app.ico                       (16, 24, 32, 48, 64, 128 e 256)

    O desenho e feito com System.Drawing (GDI+) a 4x e reduzido com
    interpolacao de alta qualidade, por isso o resultado e nitido em todos os
    tamanhos. Nao depende de rasterizadores SVG externos: o script e a fonte de
    verdade, tal como brand\logo.svg.

    Uso:
      powershell -ExecutionPolicy Bypass -File tools\gen_icons.ps1
#>
[CmdletBinding()]
param(
    [string]$Root
)

if (-not $Root) { $Root = Split-Path -Parent $PSScriptRoot }
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$iconsDir = Join-Path $Root 'icons'
$icoPath = Join-Path $Root 'app.ico'
New-Item -ItemType Directory -Force -Path $iconsDir | Out-Null

# --- Facetas do logotipo ---------------------------------------------------
# A geometria vem de brand\logo-flat-bands.json, gerado por
# tools\gen_logo_flat.ps1: a mesma malha de triangulos que o SVG, para o icone
# desenhado e o SVG nunca divergirem.
$geometryPath = Join-Path $Root 'brand\logo-flat-bands.json'
if (-not (Test-Path $geometryPath)) {
    throw "Falta $geometryPath - correr tools\gen_logo_flat.ps1 primeiro."
}
$geometry = Get-Content $geometryPath -Raw | ConvertFrom-Json
$facetShapes = foreach ($facet in $geometry.facets) {
    $hex = $facet.color.TrimStart('#')
    $col = [System.Drawing.Color]::FromArgb(
        255,
        [Convert]::ToInt32($hex.Substring(0, 2), 16),
        [Convert]::ToInt32($hex.Substring(2, 2), 16),
        [Convert]::ToInt32($hex.Substring(4, 2), 16))
    $pts = [System.Drawing.PointF[]]($facet.points | ForEach-Object {
            [System.Drawing.PointF]::new([single]($_[0]), [single]($_[1]))
        })
    [pscustomobject]@{ Brush = (New-Object System.Drawing.SolidBrush($col)); Points = $pts }
}

function New-RoundedPath {
    param([single]$X, [single]$Y, [single]$W, [single]$H, [single]$R)
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $d = [Math]::Min($R * 2, [Math]::Min($W, $H))
    if ($d -le 0) {
        $path.AddRectangle((New-Object System.Drawing.RectangleF($X, $Y, $W, $H)))
        return $path
    }
    $path.AddArc($X, $Y, $d, $d, 180, 90)
    $path.AddArc($X + $W - $d, $Y, $d, $d, 270, 90)
    $path.AddArc($X + $W - $d, $Y + $H - $d, $d, $d, 0, 90)
    $path.AddArc($X, $Y + $H - $d, $d, $d, 90, 90)
    $path.CloseFigure()
    return $path
}

function Add-Facets {
    param([System.Drawing.Graphics]$G)
    foreach ($shape in $facetShapes) {
        $G.FillPolygon($shape.Brush, $shape.Points)
    }
}

# Acrescenta um arco de elipse ao caminho, aproximado por curvas de Bezier
# (segmentos de <= 90 graus). Angulos em graus, sentido horario no ecra.
function Add-EllipseArc {
    param(
        [System.Drawing.Drawing2D.GraphicsPath]$Path,
        [double]$Cx, [double]$Cy, [double]$Rx, [double]$Ry,
        [double]$StartDeg, [double]$EndDeg
    )
    $a = $StartDeg * [Math]::PI / 180
    $b = $EndDeg * [Math]::PI / 180
    $segments = [int][Math]::Max(1, [Math]::Ceiling([Math]::Abs($b - $a) / ([Math]::PI / 2)))
    $step = ($b - $a) / $segments
    $t = $a
    for ($i = 0; $i -lt $segments; $i++) {
        $u = $t + $step
        $k = 4.0 / 3.0 * [Math]::Tan($step / 4.0)
        $p0x = $Cx + $Rx * [Math]::Cos($t); $p0y = $Cy + $Ry * [Math]::Sin($t)
        $p3x = $Cx + $Rx * [Math]::Cos($u); $p3y = $Cy + $Ry * [Math]::Sin($u)
        $c1x = $p0x - $k * $Rx * [Math]::Sin($t); $c1y = $p0y + $k * $Ry * [Math]::Cos($t)
        $c2x = $p3x + $k * $Rx * [Math]::Sin($u); $c2y = $p3y - $k * $Ry * [Math]::Cos($u)
        $Path.AddBezier(
            [single]$p0x, [single]$p0y, [single]$c1x, [single]$c1y,
            [single]$c2x, [single]$c2y, [single]$p3x, [single]$p3y)
        $t = $u
    }
}

# Desenha o glifo: triangulo de play (virado para baixo) sobre uma bandeja
# solida com "DLP" vazado. As letras sao subtraidas da bandeja como regiao,
# por isso o cristal aparece atraves delas.
function Add-Glyph {
    param([System.Drawing.Graphics]$G)

    # SourceOver no glifo: nas bordas o branco mistura-se com o cristal em vez
    # de o substituir (SourceCopy deixava halos translucidos nas letras).
    $previousMode = $G.CompositingMode
    $G.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceOver
    $white = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::White)

    # Seta: triangulo do play do YouTube rodado a apontar para baixo.
    # Quadraticas do SVG convertidas em cubicas (controlos a 2/3 do caminho).
    $arrow = New-Object System.Drawing.Drawing2D.GraphicsPath
    $arrow.AddLine([single]22.6, [single]15.6, [single]41.4, [single]15.6)
    $arrow.AddBezier(
        [single]41.4, [single]15.6,
        [single]42.4667, [single]15.6, [single]42.722, [single]16.055, [single]42.166, [single]16.965)
    $arrow.AddLine([single]42.166, [single]16.965, [single]32.834, [single]32.235)
    $arrow.AddBezier(
        [single]32.834, [single]32.235,
        [single]32.278, [single]33.145, [single]31.722, [single]33.145, [single]31.166, [single]32.235)
    $arrow.AddLine([single]31.166, [single]32.235, [single]21.834, [single]16.965)
    $arrow.AddBezier(
        [single]21.834, [single]16.965,
        [single]21.278, [single]16.055, [single]22.044, [single]15.6, [single]22.6, [single]15.6)
    $arrow.CloseFigure()
    $arrowPen = New-Object System.Drawing.Pen([System.Drawing.Color]::White, [single]1.4)
    $arrowPen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round
    $G.FillPath($white, $arrow)
    $G.DrawPath($arrowPen, $arrow)

    # Letras DLP (monolineares, mesmas coordenadas do SVG).
    $dPath = New-Object System.Drawing.Drawing2D.GraphicsPath
    $dPath.AddLine([single]24.68, [single]45.3, [single]22.103, [single]45.3)
    $dPath.AddLine([single]22.103, [single]45.3, [single]22.103, [single]50.5)
    $dPath.AddLine([single]22.103, [single]50.5, [single]24.68, [single]50.5)
    Add-EllipseArc -Path $dPath -Cx 24.68 -Cy 47.9 -Rx 3.068 -Ry 2.6 -StartDeg 90 -EndDeg -90
    $dPath.CloseFigure()

    $lPath = New-Object System.Drawing.Drawing2D.GraphicsPath
    $lPath.AddLine([single]30.896, [single]45.3, [single]30.896, [single]50.5)
    $lPath.AddLine([single]30.896, [single]50.5, [single]34.945, [single]50.5)

    $pHalf = (48.524 - 45.3) / 2.0
    $pCy = 46.912
    $pCx = 41.038 - 2.025 * [Math]::Sqrt(1.0 - [Math]::Pow($pHalf / 1.716, 2))
    $pStart = [Math]::Atan2((45.3 - $pCy) / 1.716, (41.038 - $pCx) / 2.025) * 180 / [Math]::PI
    $pEnd = [Math]::Atan2((48.524 - $pCy) / 1.716, (41.038 - $pCx) / 2.025) * 180 / [Math]::PI
    $pPath = New-Object System.Drawing.Drawing2D.GraphicsPath
    $pPath.AddLine([single]38.584, [single]50.5, [single]38.584, [single]45.3)
    $pPath.AddLine([single]38.584, [single]45.3, [single]41.038, [single]45.3)
    Add-EllipseArc -Path $pPath -Cx $pCx -Cy $pCy -Rx 2.025 -Ry 1.716 -StartDeg $pStart -EndDeg $pEnd
    $pPath.AddLine([single]41.038, [single]48.524, [single]38.584, [single]48.524)

    # Contorno do traco das letras (espessura 1.35, extremidades redondas).
    # Cada letra e widened em separado e unida como regiao: nas juncoes em T
    # (ex.: pe da letra P) os contornos sobrepoem-se, e uma uniao com Winding
    # preenche a sobreposicao em vez de a cancelar (como faria o modo Alternate).
    $letterPen = New-Object System.Drawing.Pen([System.Drawing.Color]::White, [single]1.35)
    $letterPen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $letterPen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
    $letterPen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round
    $holes = New-Object System.Drawing.Region
    $holes.MakeEmpty()
    foreach ($src in @($dPath, $lPath, $pPath)) {
        $outline = New-Object System.Drawing.Drawing2D.GraphicsPath
        $outline.FillMode = [System.Drawing.Drawing2D.FillMode]::Winding
        $outline.AddPath($src, $false)
        $outline.Widen($letterPen)
        $holes.Union($outline)
        $outline.Dispose()
    }

    $tray = New-RoundedPath 15.6 43.3 32.8 9 4.5
    $trayRegion = New-Object System.Drawing.Region($tray)
    $trayRegion.Exclude($holes)
    $G.FillRegion($white, $trayRegion)

    $trayRegion.Dispose(); $tray.Dispose(); $holes.Dispose(); $letterPen.Dispose()
    $pPath.Dispose(); $lPath.Dispose(); $dPath.Dispose()
    $arrowPen.Dispose(); $arrow.Dispose(); $white.Dispose()
    $G.CompositingMode = $previousMode
}

function New-LogoBitmap {
    param([int]$Size, [bool]$Maskable)

    $supersample = 4
    $big = $Size * $supersample
    $source = New-Object System.Drawing.Bitmap(
        $big, $big, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [System.Drawing.Graphics]::FromImage($source)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $g.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
    $g.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceCopy
    $g.Clear([System.Drawing.Color]::Transparent)
    $g.ScaleTransform($big / 64.0, $big / 64.0)

    if ($Maskable) {
        Add-Facets -G $g
    }
    else {
        $squircle = New-RoundedPath 2 2 60 60 16.5
        $g.SetClip($squircle, [System.Drawing.Drawing2D.CombineMode]::Replace)
        Add-Facets -G $g
        $g.ResetClip()
        $squircle.Dispose()
    }

    if ($Maskable) {
        # Zona segura: o glifo fica a 86% para caber no recorte circular.
        $g.TranslateTransform([single]32, [single]32)
        $g.ScaleTransform([single]0.86, [single]0.86)
        $g.TranslateTransform([single]-32, [single]-32)
    }
    Add-Glyph -G $g


    $output = New-Object System.Drawing.Bitmap(
        $Size, $Size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $outG = [System.Drawing.Graphics]::FromImage($output)
    $outG.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceCopy
    $outG.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $outG.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $outG.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $outG.DrawImage($source, (New-Object System.Drawing.Rectangle(0, 0, $Size, $Size)))
    $outG.Dispose()
    $g.Dispose()
    $source.Dispose()
    return $output
}

# --- PNGs ------------------------------------------------------------------
$pngTargets = @(
    @{ Name = 'icon-32.png';           Size = 32;  Maskable = $false },
    @{ Name = 'icon-192.png';          Size = 192; Maskable = $false },
    @{ Name = 'icon-512.png';          Size = 512; Maskable = $false },
    @{ Name = 'icon-maskable-512.png'; Size = 512; Maskable = $true  }
)

foreach ($target in $pngTargets) {
    $bmp = New-LogoBitmap -Size $target.Size -Maskable $target.Maskable
    $path = Join-Path $iconsDir $target.Name
    $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
    Write-Host ("[gen_icons] {0,-24} {1}x{1}" -f $target.Name, $target.Size) -ForegroundColor Green
}

# --- ICO (frames BMP 32 bpp, compativel com rc.exe/Explorer/Inno Setup) ----
function Get-IcoFrameBytes {
    param([System.Drawing.Bitmap]$Image)

    $w = $Image.Width
    $h = $Image.Height
    $rect = New-Object System.Drawing.Rectangle(0, 0, $w, $h)
    $locked = $Image.LockBits(
        $rect,
        [System.Drawing.Imaging.ImageLockMode]::ReadOnly,
        [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $stride = $locked.Stride
    $pixels = New-Object byte[] ($stride * $h)
    [System.Runtime.InteropServices.Marshal]::Copy($locked.Scan0, $pixels, 0, $pixels.Length)
    $Image.UnlockBits($locked)

    # DIB do ICO: linhas de baixo para cima, BGRA, seguidas da mascara AND.
    $xor = New-Object byte[] ($w * $h * 4)
    for ($y = 0; $y -lt $h; $y++) {
        $src = ($h - 1 - $y) * $stride
        [Array]::Copy($pixels, $src, $xor, $y * $w * 4, $w * 4)
    }
    $maskStride = [int]([Math]::Floor(($w + 31) / 32) * 4)
    $mask = New-Object byte[] ($maskStride * $h)

    $stream = New-Object System.IO.MemoryStream
    $writer = New-Object System.IO.BinaryWriter($stream)
    $writer.Write([UInt32]40)                 # biSize
    $writer.Write([Int32]$w)                  # biWidth
    $writer.Write([Int32]($h * 2))            # biHeight (XOR + AND)
    $writer.Write([UInt16]1)                  # biPlanes
    $writer.Write([UInt16]32)                 # biBitCount
    $writer.Write([UInt32]0)                  # biCompression (BI_RGB)
    $writer.Write([UInt32]($w * $h * 4))      # biSizeImage
    $writer.Write([Int32]0)
    $writer.Write([Int32]0)
    $writer.Write([UInt32]0)
    $writer.Write([UInt32]0)
    $writer.Write($xor)
    $writer.Write($mask)
    $writer.Flush()
    $bytes = $stream.ToArray()
    $writer.Dispose()
    $stream.Dispose()
    return ,$bytes
}

$icoSizes = @(16, 24, 32, 48, 64, 128, 256)
$frames = New-Object 'System.Collections.Generic.List[byte[]]'
foreach ($size in $icoSizes) {
    $bmp = New-LogoBitmap -Size $size -Maskable $false
    $frames.Add((Get-IcoFrameBytes -Image $bmp))
    $bmp.Dispose()
}

$file = [System.IO.File]::Create($icoPath)
$ico = New-Object System.IO.BinaryWriter($file)
$ico.Write([UInt16]0)                 # reserved
$ico.Write([UInt16]1)                 # type = icon
$ico.Write([UInt16]$frames.Count)
$offset = 6 + (16 * $frames.Count)
for ($i = 0; $i -lt $frames.Count; $i++) {
    $dim = if ($icoSizes[$i] -ge 256) { 0 } else { $icoSizes[$i] }
    $ico.Write([Byte]$dim)
    $ico.Write([Byte]$dim)
    $ico.Write([Byte]0)               # color count
    $ico.Write([Byte]0)               # reserved
    $ico.Write([UInt16]1)             # planes
    $ico.Write([UInt16]32)            # bit count
    $ico.Write([UInt32]$frames[$i].Length)
    $ico.Write([UInt32]$offset)
    $offset += $frames[$i].Length
}
foreach ($frame in $frames) { $ico.Write($frame) }
$ico.Flush()
$ico.Dispose()
$file.Dispose()
Write-Host ("[gen_icons] app.ico                  {0} frames ({1} KB)" -f $frames.Count, [Math]::Round((Get-Item $icoPath).Length / 1KB)) -ForegroundColor Green

# --- Verificacao rapida -----------------------------------------------------
$probe = [System.Drawing.Bitmap]::FromFile((Join-Path $iconsDir 'icon-512.png'))
$corner = $probe.GetPixel(1, 1)
$arrow = $probe.GetPixel([int](32 / 64 * 512), [int](18 / 64 * 512))
$tray = $probe.GetPixel([int](17.5 / 64 * 512), [int](48 / 64 * 512))
$hole = $probe.GetPixel([int](22.1 / 64 * 512), [int](48 / 64 * 512))
$probe.Dispose()
if ($corner.A -ne 0) { throw "icon-512.png: canto devia ser transparente (alpha=$($corner.A))." }
if ($arrow.R -lt 245 -or $arrow.G -lt 245 -or $arrow.B -lt 245 -or $arrow.A -lt 245) {
    throw "icon-512.png: a seta devia ser branca (obtido $($arrow.R),$($arrow.G),$($arrow.B),$($arrow.A))."
}
if ($tray.R -lt 245 -or $tray.G -lt 245 -or $tray.B -lt 245 -or $tray.A -lt 245) {
    throw "icon-512.png: a bandeja devia ser branca (obtido $($tray.R),$($tray.G),$($tray.B),$($tray.A))."
}
if ($hole.A -lt 250 -or ($hole.R -gt 240 -and $hole.G -gt 240 -and $hole.B -gt 240)) {
    throw "icon-512.png: o 'DLP' devia ser vazado, com o cristal visivel (obtido $($hole.R),$($hole.G),$($hole.B),$($hole.A))."
}

$probe = [System.Drawing.Bitmap]::FromFile((Join-Path $iconsDir 'icon-maskable-512.png'))
$corner = $probe.GetPixel(1, 1)
$probe.Dispose()
if ($corner.A -ne 255) { throw "icon-maskable-512.png: o fundo devia ser opaco (alpha=$($corner.A))." }

$checkIcon = New-Object System.Drawing.Icon($icoPath)
$checkIcon.Dispose()
Write-Host '[gen_icons] verificacao OK (transparencia, glifo branco, maskable e ICO)' -ForegroundColor Green
