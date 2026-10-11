<#
    tools/new_selfsigned_cert.ps1
    -----------------------------------------------------------------------------
    Cria um certificado de ASSINATURA DE CODIGO auto-assinado, para TESTAR o
    pipeline localmente. NAO remove o aviso do SmartScreen (so um certificado
    emitido por uma Autoridade de Certificacao reconhecida o faz). Ver ASSINATURA.md.

    Uso:
      powershell -ExecutionPolicy Bypass -File tools\new_selfsigned_cert.ps1
      powershell -ExecutionPolicy Bypass -File tools\new_selfsigned_cert.ps1 -Trust

    Resultado:
      - certificado de codigo de assinatura em Cert:\CurrentUser\My
      - ficheiro .pfx exportado (omissao: build\certs\mediadesk-teste.pfx)
      - imprime o thumbprint e as variaveis a definir antes do build

    Parametros:
      -Subject   nome do certificado (omissao: "CN=ALDACO (teste), O=ALDACO, C=PT")
      -Out       caminho do .pfx (omissao: build\certs\mediadesk-teste.pfx)
      -Password  password do .pfx (omissao: mediadesk)
      -Years     validade em anos (omissao: 3)
      -Trust     adiciona o certificado a Root e TrustedPublisher do utilizador
                 (para a assinatura ficar "Valid" nesta maquina)
#>
[CmdletBinding()]
param(
    [string]$Subject  = 'CN=ALDACO (teste), O=ALDACO, C=PT',
    [string]$Out      = '',
    [string]$Password = 'mediadesk',
    [int]$Years       = 3,
    [switch]$Trust
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $Out) { $Out = Join-Path $root 'build\certs\mediadesk-teste.pfx' }
$outDir = Split-Path -Parent $Out
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }

Write-Host "[cert] a criar certificado de assinatura de codigo..." -ForegroundColor Cyan
$cert = New-SelfSignedCertificate `
    -Type CodeSigningCert `
    -Subject $Subject `
    -CertStoreLocation 'Cert:\CurrentUser\My' `
    -KeyUsage DigitalSignature `
    -KeyExportPolicy Exportable `
    -KeyAlgorithm RSA -KeyLength 2048 -HashAlgorithm SHA256 `
    -NotAfter (Get-Date).AddYears($Years)

$pwd = ConvertTo-SecureString -String $Password -AsPlainText -Force
Export-PfxCertificate -Cert ("Cert:\CurrentUser\My\$($cert.Thumbprint)") -FilePath $Out -Password $pwd | Out-Null

if ($Trust) {
    foreach ($store in 'Root', 'TrustedPublisher') {
        try {
            $already = Get-ChildItem "Cert:\CurrentUser\$store" -ErrorAction SilentlyContinue |
                       Where-Object { $_.Thumbprint -eq $cert.Thumbprint }
            if (-not $already) {
                $s = New-Object System.Security.Cryptography.X509Certificates.X509Store $store, 'CurrentUser'
                $s.Open('ReadWrite'); $s.Add($cert); $s.Close()
                Write-Host "[cert] adicionado a CurrentUser\$store" -ForegroundColor Green
            }
        } catch {
            Write-Host "[cert] aviso: nao foi possivel adicionar a CurrentUser\$store ($($_.Exception.Message))" -ForegroundColor Yellow
        }
    }
}

Write-Host ""
Write-Host "[cert] criado com sucesso." -ForegroundColor Green
Write-Host "  Subject    : $($cert.Subject)"
Write-Host "  Thumbprint : $($cert.Thumbprint)"
Write-Host "  PFX        : $Out"
Write-Host "  Password   : $Password"
Write-Host ""
Write-Host "  Opcao A - usar o ficheiro .pfx no build:" -ForegroundColor Cyan
Write-Host "    `$env:MEDIADESK_PFX='$Out'"
Write-Host "    `$env:MEDIADESK_PFX_PASSWORD='$Password'"
Write-Host "    powershell -ExecutionPolicy Bypass -File build_portable.ps1"
Write-Host ""
Write-Host "  Opcao B - usar o certificado ja instalado no Windows:" -ForegroundColor Cyan
Write-Host "    `$env:MEDIADESK_THUMBPRINT='$($cert.Thumbprint)'"
Write-Host ""
Write-Host "  Nota: um certificado auto-assinado NAO remove o aviso do SmartScreen." -ForegroundColor Yellow
