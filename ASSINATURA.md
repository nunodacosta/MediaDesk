# Assinatura de código — decisão: sem custos (software livre)

**Decisão (2026):** o YT-DLP Media Desk é livre (com créditos aos autores) e, nesta
fase, **não se paga por certificado de assinatura**. Distribuir sem assinatura é
perfeitamente normal em software livre — o utilizador vê **um** aviso do
SmartScreen na primeira execução ("Mais informações → Executar mesmo assim").

Este documento explica o que o build já faz (sem custo), como reduzir o atrito e
quais os **únicos caminhos gratuitos** para vir a ter uma assinatura "confiável".

## 1. O que o build faz hoje (sem custo)

O pipeline de assinatura está **pronto** (ver secção 5), mas sem certificado o
build simplesmente emite um aviso e segue. O que é sempre produzido:

| Artefacto | Finalidade |
|---|---|
| `dist\MediaDesk-Portable.zip` | **Descarga recomendada** (geralmente menos avisos do que auto-extraíveis novos) |
| `dist\MediaDesk-Portable.exe` | Auto-extraível (tudo incluído) |
| `dist\MediaDesk-Setup.exe` | Instalador por utilizador |
| `dist\SHA256SUMS.txt` | Hashes SHA-256 de todos os artefactos de release |
| `verificar-integridade.ps1` | Utilitário para o utilizador confirmar a integridade |

### Verificação de integridade (custo zero, para distribuir junto)

O utilizador pode verificar o que descarregou:

```powershell
# junto dos artefactos (ZIP / auto-extraivel / instalador)
powershell -ExecutionPolicy Bypass -File verificar-integridade.ps1
```

Ficheiros com integridade **verificada** dão tanta confiança como uma assinatura,
desde que o `SHA256SUMS.txt` seja publicado num local que o utilizador confie
(ex.: página de descarga oficial / release do repositório), **não apenas dentro
do próprio ZIP**.

## 2. Realidade do SmartScreen (sem assinatura)

- O aviso aparece no **primeiro** ficheiro executável novo naquela máquina.
- Número de downloads/instalações sem incidentes constrói reputação ao longo do
  tempo.
- Distribuir a **pasta/ZIP portátil** costuma gerar menos bloqueios do que um
  auto-extraível novo (ficheiro menor e mais convencional).
- Se o Defender/AV marcar como falso positivo, submeter em:
  <https://www.microsoft.com/en-us/wdsi/filesubmission>

## 3. Caminhos gratuitos para uma assinatura "a sério"

Não existe certificado gratuito "trusted" para software com licença própria.
Existe **um** caminho gratuito, reservado a projetos **open source (OSI)**:

### SignPath Foundation (<https://signpath.org>)
- Certificado de assinatura nível OV + serviço de assinatura, **gratuito para OSS**.
- Condições: licença **aprovada pela OSI** (MIT, Apache-2.0, GPL-3.0…), sem
  dupla-licença comercial; **sem componentes proprietários**; repositório
  público, mantido e já lançado; builds verificáveis a partir do código;
  MFA nos acessos; aprovação manual por release.

A verificação de elegibilidade e o plano de mudança de licença estão em
[LICENCA.md](LICENCA.md) (a alteração de licença é uma decisão tua).

## 4. Certificado de teste (auto-assinado) — só para validar o pipeline

```powershell
powershell -ExecutionPolicy Bypass -File tools\new_selfsigned_cert.ps1 -Trust
$env:MEDIADESK_PFX = 'build\certs\mediadesk-teste.pfx'
$env:MEDIADESK_PFX_PASSWORD = 'mediadesk'
powershell -ExecutionPolicy Bypass -File build_portable.ps1
```

> Não remove o SmartScreen em máquinas de terceiros — serve apenas para testar
> o fluxo localmente. Para remover o certificado de teste, ver a secção própria
> deste script.

## 5. Pipeline pronto para um dia decidires assinar

Se um dia mudares de ideias (certificado próprio ou SignPath), o build já está
preparado — basta definir variáveis antes de correr:

| Variável | Para que serve |
|---|---|
| `MEDIADESK_PFX` / `MEDIADESK_PFX_PASSWORD` | ficheiro `.pfx` |
| `MEDIADESK_THUMBPRINT` + `MEDIADESK_CERT_STORE` | certificado no Windows (`CurrentUser`/`LocalMachine`) |
| `MEDIADESK_SUBJECT` | certificado por nome/CN |
| `MEDIADESK_TSA` / `MEDIADESK_NO_TIMESTAMP` | timestamp configurável |

O build assina (SHA-256 + timestamp RFC-3161) o launcher da pasta, o
auto-extraível e o instalador, e **verifica** cada um imprimindo o estado. Os
`SHA256SUMS.txt` são gerados no fim, já com os ficheiros assinados.

> **Assinatura gratuita (OSS):** o caminho sem custos para uma assinatura
> reconhecida pelo Windows é o **SignPath Foundation**. O fluxo completo
> (submeter o ZIP com os executáveis finais, aprovar, aplicar e regenerar
> hashes) está em [SIGNPATH.md](SIGNPATH.md). Nota técnica importante: assina-se
> sempre **depois de montar** o auto-extraível — o leitor do rodapé `MDPL` já
> tolera a assinatura anexada ao fim do ficheiro.
