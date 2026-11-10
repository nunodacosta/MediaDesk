# Notas de release (rascunho) — próxima versão

> **Rascunho para a próxima release.** Ainda **não** é a fonte oficial: a fonte de
> verdade da versão é o `version.json` (gerido por `tools/sync_version.ps1`).
> Editar/curtir antes de publicar. As notas automáticas do GitHub
> (`generate_release_notes`) são substituídas por este texto no corpo da release.

## Versão: `v3.12.0`

*Minor* (`3.11.4` → `3.12.0`): nova identidade visual inspirada no logotipo em
cristal, comandos só com ícone e tooltips contextuais que se adaptam a cada tema.

---

## YT-DLP Media Desk v3.12.0

### Adicionado
- **Paletas alinhadas com o logotipo:** seis temas — Âmbar, Carmesim, Rosa,
  Violeta, Índigo e Azul — percorrem a gradiente do cristal (amarelo →
  laranja → vermelho → rosa → magenta → roxo → azul), cada um com variante
  clara e escura e contraste legível.
- **Superfícies azuis:** os fundos, bordas, texto, pesquisa, switches e a
  consola deixam de usar preto, branco ou cinzento e passam a tons de azul
  retirados do logotipo, com o mesmo tratamento no modo claro e escuro.
- **Comandos só com ícone:** as ações de download, configuração, fila, RSS,
  propostas e atualizações da mediateca passam a mostrar apenas o ícone; o nome
  da ação aparece na tooltip e no nome acessível do botão, mantendo a interface
  mais limpa sem perder clareza.
- **Tooltips explicativas nos botões de texto:** nos comandos que mantêm o
  rótulo visível, a tooltip descreve brevemente o efeito da ação em vez de
  repetir o texto do botão.
- **Tooltips contextuais:** cada tooltip escolhe automaticamente o lado com mais
  espaço (baixo, topo, direita ou esquerda), nunca fica cortada e a seta aponta
  sempre para o centro do comando.
- **Tooltips por tema:** o fundo, o texto e o contorno das tooltips são
  derivados da paleta ativa, com contraste reforçado no modo claro e escuro.

### Melhorado
- **Navegação por teclado:** todos os comandos em ícone mantêm nome acessível e
  tooltip, incluindo os controlos do carrossel da fila.
- **Migração de definições:** as paletas antigas continuam a ser reconhecidas
  (`ocean` → Rosa, `emerald` → Carmesim, `graphite` → Azul) e a importação
  valida apenas paletas conhecidas.
- **Motor de versões:** o `sync_version.ps1` passa também a sincronizar o
  cabeçalho das notas de release e os comandos de publicação.

### Corrigido
- **Seta das tooltips:** deixa de ficar desalinhada ou fora do balão quando o
  comando está junto às margens da janela.
- **Fila de downloads no painel lateral:** a «Fila de downloads» mantém-se
  visível em qualquer aba, com a barra de progresso sincronizada com o trabalho
  real.

---

## YT-DLP Media Desk v3.9.0

### Adicionado
- **Fila de downloads no painel lateral:** a «Fila de downloads» passa para o
  painel lateral (junto à mediateca), ficando visível em qualquer aba — já não é
  preciso ir à aba «Novo download» para acompanhar os trabalhos.

### Corrigido
- **Barra de progresso sincronizada:** a barra volta a avançar de forma
  contínua e deixa de encher logo na primeira transferência. Quando um vídeo
  precisa de várias transferências (vídeo + áudio), o progresso é repartido por
  todas e a barra **só chega ao fim quando o trabalho conclui**; volta ao início
  quando o download termina.
- **Ordenação da mediateca (por grupo):** os menus de cada grupo (nome, data,
  tamanho e direção ascendente/descendente) voltam a funcionar e o seletor
  «Ordenar por data» mantém-se sincronizado com a lista.
- **Endereços concluídos:** os endereços cujo download já terminou são retirados
  automaticamente da caixa de entrada (os falhados permanecem, para repetir).
- **Painel lateral com barra de deslocamento:** a mediateca e a fila passam a
  poder ser deslocadas quando o conteúdo não cabe no ecrã.

### Melhorado
- **Fases do download:** uma linha de estado indica o que está a acontecer — a
  obter informações, a aguardar entre descargas, a descarregar, a juntar áudio e
  vídeo, a extrair áudio, a incorporar a capa/metadados e a finalizar.
- **Capas:** as miniaturas são convertidas para um formato compatível com o
  contentor (JPG/WebP) antes de serem incorporadas.
- **Repetição de downloads:** o número de tentativas é lido de forma tolerante,
  evitando falhas em trabalhos antigos.
- **Ajuda** atualizada (fila no painel lateral, progresso por fases e opções
  avançadas) nos 5 idiomas (PT/EN/ES/FR/DE).

---

## YT-DLP Media Desk v3.8.3

### Melhorado
- **Layout das opções avançadas:** controlos agrupados em subsecções de
  metadados, listas, recortes, fila e rede, com grelha responsiva e melhor
  aproveitamento do espaço.
- **Switches consistentes:** as opções avançadas e a recomendação automática
  de qualidade usam o mesmo controlo visual das restantes definições.

---

## YT-DLP Media Desk v3.8.2

### Adicionado
- **Filtro temporal da mediateca:** filtra os downloads por data e hora inicial
  e final, incluindo segundos, e ordena do mais recente para o mais antigo ou
  vice-versa. A preferência fica guardada localmente.

### Melhorado
- O **modal de ajuda** explica o filtro temporal e indica que as opções
  avançadas de transferência estão em Configuração.

### Corrigido
- A ordenação cronológica da mediateca passa a respeitar corretamente a direção
  escolhida (mais antigos ou mais recentes primeiro).

---

## YT-DLP Media Desk v3.8.1

### Melhorado
- **Qualidade automática opcional:** a recomendação de resolução pode ser
  ativada/desativada nas Definições, fica guardada e pode ser exportada/importada
  com as definições seguras. A escolha manual continua disponível.
- **Opções avançadas na Configuração:** metadados, capas, capítulos, seleção e
  ordenação de listas, recortes, proxy, agendamento, prioridade e novas
  tentativas passam a estar agrupados na página de Definições.

---

## YT-DLP Media Desk v3.8.0

### Adicionado
- **Ordenação de listas:** ordena os itens selecionados por duração ou qualidade,
  de forma ascendente ou descendente. O MediaDesk lê os metadados e descarrega
  cada item na ordem pedida; itens sem metadados ficam no fim.
- **Qualidade automática:** recomenda uma resolução de vídeo até à altura física
  detetada do ecrã, com seleção manual disponível.

### Melhorado
- O **modal de ajuda** explica a fila persistente, prioridades, agendamento,
  novas tentativas, ordenação de listas e qualidade automática.
- O **motor de versões** passa também a sincronizar a versão estática do
  cabeçalho e a gerar o histórico com escaping seguro para JavaScript.

### Corrigido
- Os campos da fila validam o modo de ordenação e mantêm a seleção dos itens da
  lista antes da ordenação.

---

## Histórico de versões publicadas

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

### Code signing policy
- **Free code signing provided by [SignPath.io](https://about.signpath.io),
  certificate by [SignPath Foundation](https://signpath.org).**
- Os 3 executáveis (`MediaDesk-Portable.exe`, `MediaDesk-Setup.exe` e
  `Media Desk Portable\Media Desk.exe`) assinados com Authenticode e
  *timestamp* através do fluxo SignPath quando ativo (ver `SIGNPATH.md`).
- Política completa, política de privacidade e verificação da assinatura:
  [`CODE_SIGNING_POLICY.md`](CODE_SIGNING_POLICY.md).

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
git commit -m "release: v3.12.0"
git tag -a v3.12.0 -m "YT-DLP Media Desk v3.12.0"
git push origin main
git push origin v3.12.0      # a tag 'v*' dispara build + (se configurado) assinatura + release

# Alternativa sem tag (teste): Actions > "Release + SignPath" > Run workflow,
# com publish=true para publicar a release.
```

Antes de publicar, confirmar:
- [x] `dist\` reconstruído: `Media Desk Portable\`, `Media Desk.zip`,
      `Media Desk.exe` (SFX) e `Media Desk Setup.exe`; launcher
      `Media Desk.exe` na raiz.
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
  `Media Desk Portable\Media Desk.exe`) assinados com Authenticode e
  *timestamp* através do fluxo SignPath (ver `SIGNPATH.md`).

</details>
