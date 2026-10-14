# SignPath — assinatura de código gratuita para OSS (passo a passo)

O **SignPath** ([signpath.io](https://signpath.io) / [signpath.org](https://signpath.org))
oferece **certificado de assinatura OV + serviço de assinatura, gratuitos para
projetos open source**. É o único caminho gratuito para remover o aviso do
SmartScreen. A decisão de licença (GPL-3.0) e a análise estão em
[LICENCA.md](LICENCA.md); as opções locais/sem custo estão em
[ASSINATURA.md](ASSINATURA.md).

> Este documento assume o plano OSS gratuito. O certificado é emitido pela
> SignPath Foundation e **exige aprovação manual por release**.

## 1. Pré-requisitos (checklist)

| Requisito | Estado neste projeto |
|---|---|
| Licença aprovada pela OSI | ✅ **GPL-3.0** (`LICENSE`, `licenses/GPL-3.0.txt`) |
| Sem dupla-licença comercial / sem componentes proprietários | ⚠️ rever (WebView2/.NET são redistribuíveis, não proprietários do projeto) |
| Repositório **público**, mantido e **já lançado** | ✅ `github.com/nunodacosta/MediaDesk` + release `v3.6.0` |
| Builds verificáveis a partir do código | ✅ `build_portable.ps1` + `checksums.json` + `SHA256SUMS.txt` |
| Política de assinatura + privacidade no repositório | ✅ `CODE_SIGNING_POLICY.md` (exigido pela SignPath Foundation) |
| Metadados de versão nos executáveis (ProductName/ProductVersion) | ✅ `MediaDeskLauncher.csproj` (`Product`/`Version`) + Inno Setup |
| MFA (autenticação multifator) na conta | ❌ a ativar ao criar a conta |
| Candidatura ao plano OSS (repo + GPL-3.0 + release) | ❌ a submeter em <https://signpath.org/apply> |
| Aprovação manual por release | ℹ️ a contar com ela no fluxo |

O `config.json`, `cookies.txt`, `history.json`, `sessions.json` e `downloads\`
da raiz são **dados de desenvolvimento** e **não podem** entrar no repositório
público — o `.gitignore` na raiz já os exclui.

## 2. Como a assinatura interage com o auto-extraível

O auto-extraível `MediaDesk-Portable.exe` = *launcher* + payload anexado + um
**rodapé `MDPL`** de 32 bytes. O `signtool`/SignPath anexam a **tabela de
certificados ao FIM do ficheiro** — ou seja, **depois** do rodapé.

Por isso, o leitor do rodapé (`Program.cs`, `Payload.Prepare`) foi tornado
**tolerante**: procura o rodapé `MDPL` de trás para a frente (janela de 256 KB)
e valida a estrutura (`zipOffset + zipLength == posição do rodapé`), em vez de
exigir o rodapé exatamente nos últimos 32 bytes.

Consequência: **assinam-se os ficheiros já montados** (SFX, Setup, launcher).
Isto é exatamente o que o SignPath espera (submeter os executáveis finais).

> ❌ **Não** usar a abordagem "assinar o stub antes de anexar o payload": foi
> testada e a assinatura **desaparece** depois de anexar o overlay (o Windows
> deixa de a encontrar). A ordem correta é montar → assinar.

## 3. Fluxo por release (1 submissão)

```powershell
# --- Passo 0: build normal (SEM assinatura) ---------------------------------
powershell -ExecutionPolicy Bypass -File build_portable.ps1

# --- Passo 1: empacotar os ficheiros finais ---------------------------------
powershell -ExecutionPolicy Bypass -File tools\prep_signpath.ps1
#   -> build\signpath\signpath-<versao>-<build>.zip
#      (contem: MediaDesk-Portable.exe, MediaDesk-Setup.exe,
#               MediaDesk-Portable\YT-DLP-Media-Desk.exe)

# --- Passo 2: submeter / aprovar / descarregar ------------------------------
#   Interface do SignPath (ou API/CI): submeter o ZIP, aprovar o pedido,
#   descarregar o ZIP assinado.

# --- Passo 3: aplicar e publicar --------------------------------------------
powershell -ExecutionPolicy Bypass -File tools\apply_signed.ps1 -Source <zip assinado>
#   - substitui os 3 executaveis em dist\
#   - recria o dist\MediaDesk-Portable.zip (com o launcher assinado)
#   - regenera o dist\SHA256SUMS.txt
```

No fim, **publicar**: `MediaDesk-Portable.zip` (recomendado), o auto-extraível,
o Setup e o **`SHA256SUMS.txt`** (fora do ZIP, na página de release).

## 4. Preparar o repositório público (uma vez)

> **Estado:** já feito — repo **público** `github.com/nunodacosta/MediaDesk`,
> release `v3.6.0` publicada com os artefactos + `SHA256SUMS.txt`.

```powershell
git remote add origin https://github.com/nunodacosta/MediaDesk.git
git push -u origin main
```

- O `.gitignore` exclui os dados de desenvolvimento e as pastas de build.
- Confirmar que `LICENSE`, `licenses/GPL-3.0.txt` e o aviso ALDACO estão
  presentes (requisito OSI).
- Publicar uma **1.ª release** (com os artefactos + `SHA256SUMS.txt`) — o
  SignPath exige projetos **já lançados**.

### Conta e projeto no SignPath

1. Criar conta em <https://app.signpath.io> com **MFA** ativa.
2. Candidatar o projeto ao **plano OSS** (indicar o repositório público e a
   licença GPL-3.0). Aguardar aprovação.
3. **Certificado de assinatura:** **não** criar/importar certificado na página
   de certificados. No plano OSS, a **SignPath Foundation fornece o certificado**
   (a chave privada fica no HSM da SignPath); as opções *self-signed*, *CSR* e
   *import* servem para testes/compras próprias e não se aplicam.
4. Criar o **projeto** (ex.: slug `mediadesk`) e uma **signing policy**
   (ex.: `release-signing`) que use o certificado fornecido, com SHA-256 +
   *timestamp* RFC-3161.
5. Criar uma **artifact configuration**: um ZIP com os ficheiros a assinar
   (é exatamente o que o `prep_signpath.ps1` produz).
6. Por release: submeter o ZIP via interface (ou API/CI), aprovar e descarregar
   o ZIP assinado.

> Alternativa CI: o SignPath tem *GitHub Action / GitLab integration* para
> automatizar a submissão. Sem CI, a interface web (fluxo acima) é suficiente.

## 5. Verificar a assinatura

```powershell
# cada executavel deve dar Status = Valid
Get-AuthenticodeSignature dist\MediaDesk-Portable\YT-DLP-Media-Desk.exe | Format-List
Get-AuthenticodeSignature dist\MediaDesk-Setup.exe | Format-List
Get-AuthenticodeSignature dist\MediaDesk-Portable.exe | Format-List
```

O `SignerCertificate.Subject` deve corresponder à SignPath Foundation (é a
assinatura que o Windows reconhece). Ao extrair o ZIP/SFX, o
`verificar-integridade.ps1` continua a confirmar os 8 ficheiros da aplicação.

## 6. Testar o pipeline localmente (sem SignPath)

Antes de depender do serviço, pode validar toda a ordem com um certificado
**auto-assinado** (não remove o SmartScreen em terceiros — é só teste):

```powershell
powershell -File tools\new_selfsigned_cert.ps1 -Trust
$env:MEDIADESK_PFX = 'build\certs\mediadesk-teste.pfx'
$env:MEDIADESK_PFX_PASSWORD = 'mediadesk'
powershell -File build_portable.ps1
# confirme que o auto-extraivel continua a extrair e que:
Get-AuthenticodeSignature dist\MediaDesk-Portable.exe | Format-List
Get-AuthenticodeSignature dist\MediaDesk-Setup.exe | Format-List
```

O `Try-Sign` do build **não re-assina** ficheiros já assinados (guarda incluída),
pelo que nunca substitui uma assinatura do SignPath por engano.

## 7. Limitações a conhecer

- O **auto-extraível assinado** depende do leitor tolerante do rodapé — já
  implementado e testado. Se um dia alterar o formato do rodapé, repetir o teste.
- O certificado OSS exige **aprovação manual por release** — não é instantâneo.
- Um certificado auto-assinado **não** substitui a assinatura do SignPath para
  efeitos de SmartScreen/reputação.

## 8. Automatizar com CI (GitHub Actions)

O template está em [`.github/workflows/signpath.yml`](.github/workflows/signpath.yml).
Faz: `tools/prepare_runtime.ps1` (runtime) → `build_portable.ps1` →
`prep_signpath.ps1` → carrega a **pasta** `build\signpath\stage` (os `.exe` crus)
como artefacto do workflow → submete à SignPath
(`signpath/github-action-submit-signing-request@v3`, com o parâmetro `version`) →
`apply_signed.ps1` → publica a release (em tags `v*`).

> ⚠️ **Não carregar o nosso ZIP no CI.** O `actions/upload-artifact` já empacota
> o que lhe damos num ZIP. Se carregássemos `build\signpath\signpath-*.zip`,
> ficaria um ZIP **dentro** de outro ZIP e os `<pe-file>` da configuração nunca
> seriam encontrados (o pedido falharia). Por isso o CI carrega a **pasta** e a
> configuração tem o root `<zip-file>` com os `.exe` a **um nível**. Para
> submissão manual (secção 3) o ZIP continua a servir: a SignPath vê-o como um
> `<zip-file>` com os mesmos 3 `.exe` dentro.

Configurar uma vez no repositório:

- **Secret** `SIGNPATH_API_TOKEN` (token de submissor).
- **Variable** `SIGNPATH_ORGANIZATION_ID`.
- **Slugs** `SIGNPATH_PROJECT`, `SIGNPATH_POLICY`, `SIGNPATH_ARTIFACT_CONFIG`
  (ajustar aos definidos na SignPath).

**Comportamento do template:**

1. **Runtime automático** — `bin\` (Python, yt-dlp, FFmpeg, Deno) **não** está no
   repositório; o passo *Preparar runtime* repõe tudo a partir de fontes públicas
   com versões fixadas (`tools/prepare_runtime.ps1`: Python 3.10 embeddable,
   yt-dlp 2026.08.19, FFmpeg win64-gpl, deno 2.6.9). O Inno Setup é instalado
   via `choco install innosetup` para gerar o instalador.
2. **Robusto sem SignPath** — os passos da SignPath só correm quando o secret
   `SIGNPATH_API_TOKEN` existe. Sem ele, o workflow **publica a release não
   assinada** com o `SHA256SUMS.txt` gerado no build (estado atual do projeto).
3. **Artifact configuration com restrições de metadados** — está pronta em
   [`signpath/artifact-configuration.xml`](signpath/artifact-configuration.xml);
   criar na SignPath com o slug `mediadesk-release` (ou ajustar
   `SIGNPATH_ARTIFACT_CONFIG`). Impõe, por *file metadata restrictions*,
   `product-name="YT-DLP Media Desk"`, `product-version="${version}"` e
   `company-name="ALDACO"` nos 3 executáveis. O `version` é o parâmetro que o
   workflow lê de `version.json` (ver `MediaDeskLauncher.csproj`).

O trigger por tag (`push: tags: ['v*']`) está **ativo**: cada tag `v*` dispara
build + (quando configurado) assinatura + release.

### 8.1 Artifact configuration e o padding do Inno Setup

A configuração de artefacto versionada é
[`signpath/artifact-configuration.xml`](signpath/artifact-configuration.xml)
(slug `mediadesk-release`). O essencial:

- **Root `<zip-file>`** — o GitHub entrega sempre um ZIP de transporte; o root
  descreve esse ZIP e os `<pe-file>` ficam a **um nível**
  (`MediaDesk-Portable.exe`, `MediaDesk-Setup.exe`,
  `MediaDesk-Portable/YT-DLP-Media-Desk.exe`).
- **Um só nível de ZIP** — por isso o CI carrega a **pasta**, não o nosso ZIP.
- **Restrições de metadados** em cada `<pe-file>`:
  `product-name`, `product-version="${version}"` e `company-name`.

> ⚠️ **Padding do instalador (Inno Setup) — resolvido no fluxo.** O `.exe` do
> Inno Setup sai com os campos da *Version Info* preenchidos com **espaços**
> (largura fixa do stub — comportamento do Inno, sem diretiva para o desativar).
> Confirmado nos artefactos deste projeto:
>
> | Campo | Valor real | Largura no PE |
> |---|---|---|
> | `ProductName` | `YT-DLP Media Desk` | 60 (com espaços à direita) |
> | `ProductVersion` | `3.6.0` | 50 |
> | `FileVersion` | `3.6.0` | 20 |
> | `CompanyName` | `ALDACO` | 60 |
>
> As *file metadata restrictions* comparam o valor **exato**, logo o padding tem
> de sair antes de submeter. O
> [`tools/normalize_versioninfo.ps1`](tools/normalize_versioninfo.ps1) substitui
> os espaços à direita por NUL **no próprio ficheiro, sem alterar o tamanho nem
> a estrutura do PE** (nada se desloca; o payload do instalador fica intacto — ao
> contrário de reescrever o recurso com o Resource Hacker, que corrompe o
> instalador). É chamado automaticamente por `tools/prep_signpath.ps1` só na
> **cópia** que vai para assinatura; o `dist\MediaDesk-Setup.exe` original
> mantém-se como saiu do Inno.
>
> Os executáveis `.NET` (launcher e auto-extraível) **não** têm padding
> (`ProductName` com 17 chars), logo não precisam de normalização.
>
> Nota: não se restringe `file-version` (o Inno escreve `3.6.0`, o .NET escreve
> `3.6.0.0`) nem `original-filename` (herdado como `YT-DLP-Media-Desk.dll`). As
> restrições obrigatórias nos termos OSS são `product-name` e `product-version`,
> ambas cumpridas.

> O fluxo manual (secção 3) não precisa de CI e usa o mesmo `prep`/`apply`.

## 9. Ficheiros relevantes

| Ficheiro | Papel |
|---|---|
| `CODE_SIGNING_POLICY.md` | Política de assinatura + privacidade (exigida pela SignPath Foundation) |
| `signpath\artifact-configuration.xml` | Configuração de artefacto da SignPath (restrições de metadados) |
| `tools\prep_signpath.ps1` | Empacota os executáveis finais (pasta `stage\` + ZIP) para submeter |
| `tools\normalize_versioninfo.ps1` | Remove o padding dos metadados do instalador (na cópia para assinatura) |
| `tools\apply_signed.ps1` | Aplica o ZIP/pasta assinado, recria o ZIP da pasta, regenera hashes |
| `tools\prepare_runtime.ps1` | Repõe o runtime `bin\` (Python/yt-dlp/FFmpeg/Deno) a partir de fontes públicas (CI e reconstruções) |
| `tools\new_selfsigned_cert.ps1` | Certificado de teste (validar o pipeline localmente) |
| `.github\workflows\signpath.yml` | CI (GitHub Actions) de build + assinatura + release |
