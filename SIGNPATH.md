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
| Repositório **público**, mantido e **já lançado** | ❌ criar repositório git + 1.ª release |
| Builds verificáveis a partir do código | ✅ `build_portable.ps1` + `checksums.json` + `SHA256SUMS.txt` |
| Política de assinatura + privacidade no repositório | ✅ `CODE_SIGNING_POLICY.md` (exigido pela SignPath Foundation) |
| Metadados de versão nos executáveis (ProductName/ProductVersion) | ✅ `MediaDeskLauncher.csproj` (`Product`/`Version`) + Inno Setup |
| MFA (autenticação multifator) na conta | ❌ a ativar ao criar a conta |
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

> **Estado:** já feito — `git init` + 1.º commit em `main`. Falta criar o
> repositório no GitHub e fazer `push`.

```powershell
# criar o repositório VAZIO em https://github.com/new  (nome: MediaDesk, Public)
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
3. Criar o **projeto** e uma **signing policy** (ex.: `release`) com SHA-256 +
   *timestamp* RFC-3161.
4. Criar uma **artifact configuration**: um ZIP com os ficheiros a assinar
   (é exatamente o que o `prep_signpath.ps1` produz).
5. Por release: submeter o ZIP via interface (ou API/CI), aprovar e descarregar
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
Faz: `build_portable.ps1` → `prep_signpath.ps1` → carrega o ZIP como artefacto
do workflow → submete à SignPath (`signpath/github-action-submit-signing-request@v3`)
→ `apply_signed.ps1` → publica a release (em tags `v*`).

Configurar uma vez no repositório:

- **Secret** `SIGNPATH_API_TOKEN` (token de submissor).
- **Variable** `SIGNPATH_ORGANIZATION_ID`.
- **Slugs** `SIGNPATH_PROJECT`, `SIGNPATH_POLICY`, `SIGNPATH_ARTIFACT_CONFIG`
  (ajustar aos definidos na SignPath).

**Dois requisitos que o template assume:**

1. **Runtime presente** — `bin\` (Python, yt-dlp, FFmpeg, Deno, ~520 MB) e
   `ffmpeg\` **não** estão no repositório. No CI, use um *runner self-hosted*
   com o runtime, ou descarregue-o (de um release anterior / cache) antes do
   build. O workflow falha com mensagem clara se faltar.
2. **Artifact configuration com restrições de metadados** — na SignPath, a
   configuração do artefacto deve impor, por *file metadata restrictions*:
   `ProductName = "YT-DLP Media Desk"` e `ProductVersion = <versão do build>`
   (já definidos nos executáveis; ver `MediaDeskLauncher.csproj`).

> O fluxo manual (secção 3) não precisa de CI e usa o mesmo `prep`/`apply`.

## 9. Ficheiros relevantes

| Ficheiro | Papel |
|---|---|
| `CODE_SIGNING_POLICY.md` | Política de assinatura + privacidade (exigida pela SignPath Foundation) |
| `tools\prep_signpath.ps1` | Empacota os executáveis finais num ZIP para submeter |
| `tools\apply_signed.ps1` | Aplica o ZIP/pasta assinado, recria o ZIP da pasta, regenera hashes |
| `tools\new_selfsigned_cert.ps1` | Certificado de teste (validar o pipeline localmente) |
| `.github\workflows\signpath.yml` | CI (GitHub Actions) de build + assinatura + release |
