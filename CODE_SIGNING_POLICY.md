# Política de assinatura de código (Code Signing Policy)

> **Summary (EN):** Release executables of **YT-DLP Media Desk** are signed via
> the **SignPath Foundation** (free code-signing for open-source projects).
> **Free code signing provided by [SignPath.io](https://about.signpath.io),
> certificate by [SignPath Foundation](https://signpath.org).**
> The project is licensed under **GPL-3.0** and its source is public. Integrity
> can always be verified with the published SHA-256 sums. This program does not
> transfer any information to other networked systems unless specifically
> requested by the user.

## 1. Quem assina e o quê

Os executáveis de release do **YT-DLP Media Desk** são assinados através da
**SignPath Foundation** — serviço de assinatura de código gratuito para
projetos open source (plano OSS) — usando um certificado de assinatura de
código OV.

> **Free code signing provided by [SignPath.io](https://about.signpath.io),
> certificate by [SignPath Foundation](https://signpath.org).**

| | |
|---|---|
| Projeto | YT-DLP Media Desk |
| Licença | **GPL-3.0** (`LICENSE`, `licenses/GPL-3.0.txt`) — licença aprovada pela OSI |
| Repositório (código-fonte) | <https://github.com/nunodacosta/MediaDesk> |
| Mantenedor | ALDACO |

Executáveis assinados em cada release:

- `MediaDesk-Portable.exe` — pacote auto-extraível
- `MediaDesk-Setup.exe` — instalador (Inno Setup)
- `MediaDesk-Portable\YT-DLP-Media-Desk.exe` — launcher da versão portátil

O processo de build é reproduzível a partir do código público
(`build_portable.ps1`) e o conteúdo da aplicação é verificado por hashes
(`checksums.json` + `verificar-integridade.ps1`).

### Papéis (roles) e aprovação

| Papel | Quem | Responsabilidade |
|---|---|---|
| **Autor (Author)** | [@nunodacosta](https://github.com/nunodacosta) | Mantém o código-fonte, o build e a metadata de release |
| **Revisor (Reviewer)** | [@nunodacosta](https://github.com/nunodacosta) | Revê o diff da release, dependências e resultados do CI antes de se criar o pedido de assinatura |
| **Aprovador (Approver)** | [@nunodacosta](https://github.com/nunodacosta) | Confirma a proveniência do artefacto e aprova/rejeita explicitamente cada pedido de assinatura |

Membros dos papéis, conforme os termos da SignPath Foundation:

- **Committers and reviewers:** [@nunodacosta](https://github.com/nunodacosta)
- **Approvers:** [@nunodacosta](https://github.com/nunodacosta)

Todos os membros usam **autenticação multifator (MFA)** no acesso ao GitHub e à
SignPath.

A assinatura de release **nunca é automática** num *tag*: cada pedido passa por
uma ação deliberada (aprovação manual). Sendo um projeto de um único
mantenedor, os três papéis coincidem na mesma pessoa — isso é declarado
explicitamente, em vez de se fingir uma separação que não existe.

> **Nota de estado:** se a release que descarregou **não** tiver assinatura
> digital, é porque foi publicada antes da aprovação no plano OSS da SignPath
> Foundation. Nesse caso a integridade é garantida exclusivamente pelos hashes
> SHA-256 abaixo. Ver [SIGNPATH.md](SIGNPATH.md).

## 2. Como verificar uma release

1. Descarregue `SHA256SUMS.txt` junto com os artefactos.
2. Compare o hash do ficheiro descarregado:

   ```powershell
   # Windows
   Get-FileHash .\MediaDesk-Portable.zip -Algorithm SHA256
   # Linux / macOS
   sha256sum -c SHA256SUMS.txt
   ```

3. Se a release estiver assinada, confirme a assinatura:

   ```powershell
   Get-AuthenticodeSignature .\MediaDesk-Setup.exe | Format-List Status, SignerCertificate
   # SignerCertificate.Subject deve corresponder à SignPath Foundation
   ```

## 3. Política de privacidade

**Este programa não transfere qualquer informação para outros sistemas em rede
a menos que tal seja especificamente solicitado pelo utilizador ou pela pessoa
que o instala ou opera.**

Em concreto:

- O **YT-DLP Media Desk** é uma aplicação **local**. A interface comunica apenas
  com o servidor local da própria aplicação (`http://127.0.0.1`).
- **Não** recolhe telemetria, estatísticas de utilização ou dados pessoais.
- Liga-se à Internet **apenas** quando o utilizador inicia uma transferência:
  o motor **yt-dlp** descarrega dos sítios indicados pelo próprio utilizador.
- Os ficheiros descarregados, histórico, sessões e cookies ficam **no
  computador do utilizador** (por omissão em `%LOCALAPPDATA%\YTDLP-MediaDesk`).
- Componentes de terceiros redistribuídos (Python, FFmpeg, Deno, yt-dlp,
  WebView2 da Microsoft) têm as suas próprias políticas e licenças, listadas em
  `licenses/` (ver `THIRD-PARTY-NOTICES.txt`).

## 4. Privacidade do próprio serviço de assinatura

Os pedidos de assinatura são submetidos à SignPath durante o processo de
release. Nesse âmbito, apenas os **executáveis a assinar** e os **dados de
build** (identificador do repositório/commit) são enviados à SignPath. Nenhum
dado do utilizador final é transmitido.
