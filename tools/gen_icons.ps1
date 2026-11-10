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

# Desenha o glifo (seta para uma bandeja) em coordenadas 0..64.
# Sem triangulo de play: o simbolo representa transferir media para a mesa.
function Add-Glyph {
    param([System.Drawing.Graphics]$G)

    $white = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::White)
    $shaft = New-RoundedPath 28.25 9 7.5 17 3.75
    $G.FillPath($white, $shaft)

    $head = New-Object System.Drawing.Drawing2D.GraphicsPath
    $head.AddPolygon([System.Drawing.PointF[]]@(
        [System.Drawing.PointF]::new([single]20.8, [single]23.2),
        [System.Drawing.PointF]::new([single]43.2, [single]23.2),
        [System.Drawing.PointF]::new([single]32.0, [single]37.4)
    ))
    $headPen = New-Object System.Drawing.Pen([System.Drawing.Color]::White, [single]1.8)
    $headPen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round
    $G.FillPath($white, $head)
    $G.DrawPath($headPen, $head)

    $trayPen = New-Object System.Drawing.Pen([System.Drawing.Color]::White, [single]6.5)
    $trayPen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $trayPen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
    $tray = New-Object System.Drawing.Drawing2D.GraphicsPath
    $tray.AddLine([single]17, [single]43, [single]17, [single]44.5)
    $tray.AddArc([single]17, [single]37.5, [single]14, [single]14, [single]180, [single]-90)
    $tray.AddLine([single]24, [single]51.5, [single]40, [single]51.5)
    $tray.AddArc([single]33, [single]37.5, [single]14, [single]14, [single]90, [single]-90)
    $tray.AddLine([single]47, [single]44.5, [single]47, [single]43)
    $G.DrawPath($trayPen, $tray)

    $tray.Dispose(); $trayPen.Dispose()
    $head.Dispose(); $headPen.Dispose()
    $shaft.Dispose(); $white.Dispose()
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
$shaft = $probe.GetPixel([int](32 / 64 * 512), [int](18 / 64 * 512))
$probe.Dispose()
if ($corner.A -ne 0) { throw "icon-512.png: canto devia ser transparente (alpha=$($corner.A))." }
if ($shaft.R -lt 245 -or $shaft.G -lt 245 -or $shaft.B -lt 245 -or $shaft.A -lt 245) {
    throw "icon-512.png: a seta devia ser branca (obtido $($shaft.R),$($shaft.G),$($shaft.B),$($shaft.A))."
}

$probe = [System.Drawing.Bitmap]::FromFile((Join-Path $iconsDir 'icon-maskable-512.png'))
$corner = $probe.GetPixel(1, 1)
$probe.Dispose()
if ($corner.A -ne 255) { throw "icon-maskable-512.png: o fundo devia ser opaco (alpha=$($corner.A))." }

$checkIcon = New-Object System.Drawing.Icon($icoPath)
$checkIcon.Dispose()
Write-Host '[gen_icons] verificacao OK (transparencia, glifo branco, maskable e ICO)' -ForegroundColor Green
