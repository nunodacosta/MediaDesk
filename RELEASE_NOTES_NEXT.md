# Notas de release (rascunho) — próxima versão

> **Rascunho para a próxima release.** Ainda **não** é a fonte oficial: a fonte de
> verdade da versão é o `version.json` (gerido por `tools/sync_version.ps1`).
> Editar/curtir antes de publicar. As notas automáticas do GitHub
> (`generate_release_notes`) são substituídas por este texto no corpo da release.

## Versão: `v3.7.4`

*Patch* (`3.7.3` → `3.7.4`): corrige «Mostrar na pasta» na Atividade e o bloqueio
de novas descargas depois de um download falhar, e acrescenta «Escolher pasta
externa…» ao menu de cada cartão.

---

## YT-DLP Media Desk v3.7.4

### Corrigido
- **«Mostrar na pasta» (Atividade) não selecionava o ficheiro.** A opção
  `/select,` era passada ao Explorador de forma que ele abria a pasta errada
  (por exemplo, *Documentos*). Passa a abrir a **pasta correta** com o
  **ficheiro realçado** — mesmo com **acentos**, **espaços** ou ficheiros dentro
  de uma **gaveta**.
- **Depois de um download falhar (ou ser cancelado) já não era possível iniciar
  novos downloads** sem recarregar a aplicação: o botão «Iniciar download» ficava
  desativado, porque o servidor só sinalizava o fim do pedido quando havia
  sucesso. Passa a sinalizar **sempre** o fim do pedido (sucesso, falha ou
  cancelamento), reativando o botão automaticamente. Válido também para lotes.

### Melhorado
- **Menu «mover para» de cada cartão:** passa a incluir
  **«Escolher pasta externa…»**, permitindo mover um ficheiro para uma pasta
  **fora da aplicação** diretamente a partir da carta (antes só existia no
  diálogo «Mover ficheiros»).
- **Diálogo «Mover ficheiros»** abre mesmo quando **não existem gavetas**,
  deixando a opção de **pasta externa** disponível (com uma nota a indicar como
  criar gavetas). O **seletor de pasta** passa a ter um **título próprio**
  («Escolher pasta de destino»).

### Nota
- O `title` do diálogo nativo de escolha de pasta passa a ser configurável pelo
  cliente (`/browse_folder`), com retrocompatibilidade (valor por omissão
  mantido).

### Assinatura (quando ativa)
- Os 3 executáveis (`MediaDesk-Portable.exe`, `MediaDesk-Setup.exe` e
  `MediaDesk-Portable\YT-DLP-Media-Desk.exe`) assinados com Authenticode e
  *timestamp* através do fluxo SignPath (ver `SIGNPATH.md`).

---

## Como publicar (dispara o workflow `.github/workflows/signpath.yml`)

```bash
# 1) decidir a versão: editar version.json (version/date/build + entrada em history)
#    e depois propagar para index.html, server.py, .csproj e .iss:
powershell -ExecutionPolicy Bypass -File tools\sync_version.ps1

# 2) rebuild dos artefactos (dist\)
powershell -ExecutionPolicy Bypass -File build_portable.ps1

# 3) fechar o código e criar a tag
git add -A
git commit -m "release: v3.7.4"
git tag -a v3.7.4 -m "YT-DLP Media Desk v3.7.4"
git push origin main
git push origin v3.7.4      # a tag 'v*' dispara build + (se configurado) assinatura + release

# Alternativa sem tag (teste): Actions > "Release + SignPath" > Run workflow,
# com publish=true para publicar a release.
```

Antes de publicar, confirmar:
- [x] `dist\` reconstruído: `MediaDesk-Portable\`, `MediaDesk-Portable.zip`,
      `MediaDesk-Portable.exe` (SFX) e `MediaDesk-Setup.exe`; launcher
      `YT-DLP-Media-Desk.exe` na raiz.
- [x] Instalador com os 5 idiomas (`installer/mediadesk.iss`, ficheiro UTF-8 com
      BOM para os acentos de `Español`/`Français`/`Deutsch`).
- [x] Avisos de licença **dentro** dos pacotes (`licenses/FFmpeg-NOTICE.txt`
      e `licenses/SOURCE-OFFER.txt`); ver `LICENCA.md`.
- [x] `index.html` / `server.py` / `version.json` / `checksums.json`
      sincronizados (`tools/sync_version.ps1` + `tools/gen_checksums.ps1`).

<details>
<summary>Notas da <b>v3.7.2</b> (já publicada) — Instalador em 5 idiomas</summary>

### Melhorado
- **Instalador (`Setup.exe`)**: seletor de idioma do assistente de instalação em
  **Português, English, Español, Français e Deutsch** (traduções oficiais do
  Inno Setup).
- Mensagens personalizadas **traduzidas** nos 5 idiomas: criar atalho no
  ambiente de trabalho, grupo «Atalhos», «Desinstalar …» e «Executar …».

### Nota
- A **aplicação** já tinha a interface nos 5 idiomas (seletor «Idioma» na
  Configuração); a `v3.7.2` corrigiu apenas os idiomas do **instalador**.

</details>

<details>
<summary>Notas da <b>v3.7.1</b> (já publicada) — Avisos de licença (GPL) dentro dos pacotes</summary>

### Adicionado
- `licenses/FFmpeg-NOTICE.txt` — revisão exata do FFmpeg distribuída, a licença
  (**GPL-3.0-or-later**, `--enable-gpl --enable-version3`) e a **oferta escrita**
  do código-fonte correspondente (GPL-3.0 §6).
- `licenses/SOURCE-OFFER.txt` — mapa de fontes e licenças de **todos** os
  componentes redistribuídos (FFmpeg, yt-dlp, Python, Deno, .NET/WebView2).
- Ambos são gerados **automaticamente** a partir dos binários empacotados por
  `tools/gen_licenses_notice.ps1`, invocado no `build_portable.ps1` — o que é
  anunciado corresponde sempre ao que é distribuído.

### Melhorado
- O «Acerca» passa a indicar que o código-fonte dos componentes e a oferta de
  código-fonte (GPL) acompanham a distribuição (pasta `licenses/`).

### Nota
- Em `v3.7.0` a oferta de código-fonte acompanhava a **página de descarga**;
  a partir de `v3.7.1` acompanha também **dentro** dos pacotes
  (`.zip` / `Portable.exe` / `Setup.exe`).

</details>

<details>
<summary>Notas da <b>v3.7.0</b> (já publicada) — Gavetas, cores, correção de datas</summary>

### Adicionado
- **Gavetas** para separar filmes, séries ou outros grupos: criadas na
  Configuração como **pastas reais** dentro da pasta de downloads, cada uma
  pertencendo a uma das duas áreas — **Vídeo** ou **Áudio**. Vídeo e áudio nunca
  se cruzam.
- **Grelha de cartas de gaveta** no painel lateral, com a contagem de ficheiros
  por gaveta e um número máximo de cartas por linha configurável (1 a 6).
  «Todos» e «Sem gaveta» ficam em destaque acima da grelha.
- **Cor por gaveta**, escolhida na Configuração, e **dístico colorido** com o nome
  da gaveta em cada ficheiro (na mediateca e na Atividade).
- **Menu vertical de movimentação** em cada cartão de ficheiro: propõe apenas as
  gavetas do **mesmo tipo** (Vídeo ou Áudio), além de «Sem gaveta». A movimentação
  reflete-se de imediato na Atividade.
- **Movimentação para uma pasta externa**, escolhida no momento da ação.
- **Remoção de uma gaveta** diretamente a partir da sua carta no painel lateral: se
  ainda tiver ficheiros, o utilizador escolhe entre **mantê-los** (movidos para
  «Sem gaveta») ou **apagá-los** do disco.

### Melhorado
- O **filtro de gavetas** do painel lateral acompanha o tipo escolhido (Vídeo
  mostra só gavetas de vídeo, Áudio só de áudio, Todos mostra todos).
- **Seletor de cor** das gavetas baseado na **paleta da aplicação** (10 cores
  harmonizadas), com opção de cor personalizada que é **harmonizada
  automaticamente** à paleta e ao tema — mantém a matiz e ajusta a saturação e a
  luminosidade (S 35–90 %, L 40–62 %), garantindo legibilidade nos temas claro e
  escuro. As cores quase sem cor (preto, branco, cinzento) recebem a matiz da cor
  de destaque da aplicação, para não destoarem.
- **Ajuda** atualizada com uma nova secção **Gavetas** (criação, cores,
  movimentação e remoção) nos 5 idiomas (PT/EN/ES/FR/DE).

### Corrigido
- **Histórico com datas de fuso horário:** entradas cujo `date` inclui fuso (por
  exemplo, `2026-10-14T10:00:00Z`) deixavam de conseguir ser comparadas com a data
  dos ficheiros (naive vs. *aware*), o que fazia o endpoint `/get_downloads`
  devolver um corpo vazio e **a mediateca não carregar**. As datas passam a ser
  normalizadas para hora local antes da comparação.

### Infraestrutura e segurança
- **Launcher migrado para .NET 8** (o .NET 7 chegou ao fim de vida). Sem alteração
  para o utilizador; corrige alertas de runtime descontinuado.
- **FFmpeg: build GPL fixada** (variante `win64-gpl` do BtbN/FFmpeg-Builds,
  `--enable-gpl --enable-version3`, logo GPL-3.0-or-later) em vez de `latest`,
  para builds reprodutíveis e verificáveis. O `tools/prepare_runtime.ps1` fixa a
  tag/asset para o *refresh* do runtime no próximo build.
- **Oferta do código-fonte correspondente (GPL).** Cada distribuição passa a
  incluir `licenses/FFmpeg-NOTICE.txt` (revisão exata do FFmpeg distribuída +
  **oferta escrita**, GPL-3.0 §6) e `licenses/SOURCE-OFFER.txt` (mapa de fontes
  e licenças de todos os componentes). São gerados automaticamente a partir dos
  binários empacotados por `tools/gen_licenses_notice.ps1`, invocado no
  `build_portable.ps1` — evitando divergência entre o que é anunciado e o que é
  distribuído.
- **Preparação para assinatura de código** via SignPath Foundation (plano OSS):
  *artifact configuration* versionada e normalização dos metadados do instalador
  (`signpath/artifact-configuration.xml`, `tools/normalize_versioninfo.ps1`).
- `.gitignore`: ignora backups locais (`config.json.bak`, `*.bak`).

### Assinatura (quando ativa)
- Os 3 executáveis (`MediaDesk-Portable.exe`, `MediaDesk-Setup.exe` e
  `MediaDesk-Portable\YT-DLP-Media-Desk.exe`) assinados com Authenticode e
  *timestamp* através do fluxo SignPath (ver `SIGNPATH.md`).

</details>
