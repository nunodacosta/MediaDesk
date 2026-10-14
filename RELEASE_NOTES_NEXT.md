# Notas de release (rascunho) — próxima versão

> **Rascunho para a próxima release.** Ainda **não** é a fonte oficial: a fonte de
> verdade da versão é o `version.json` (gerido por `tools/sync_version.ps1`).
> Editar/curtir antes de publicar. As notas automáticas do GitHub
> (`generate_release_notes`) são substituídas por este texto no corpo da release.

## Versão: `v3.7.0`

*Minor bump* (`3.6.0` → `3.7.0`): entra uma **funcionalidade** nova — os
**Gavetas** (organização de vídeo/áudio em subpastas, com cor, filtro,
movimentação e remoção a partir do painel lateral).

---

## YT-DLP Media Desk v3.7.0

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
- **FFmpeg fixado a uma build imutável** (tag BtbN
  `autobuild-2026-10-12-13-12`, asset `ffmpeg-N-127388-g615b07170e-win64-gpl.zip`)
  em vez de `latest`, para builds reprodutíveis e verificáveis.
- **Preparação para assinatura de código** via SignPath Foundation (plano OSS):
  *artifact configuration* versionada e normalização dos metadados do instalador
  (`signpath/artifact-configuration.xml`, `tools/normalize_versioninfo.ps1`).
- `.gitignore`: ignora backups locais (`config.json.bak`, `*.bak`).

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

# 2) rebuild dos artefactos (dist\) — o próximo build já sai em .NET 8
powershell -ExecutionPolicy Bypass -File build_portable.ps1

# 3) fechar o código e criar a tag
git add -A
git commit -m "release: v3.7.0"
git tag -a v3.7.0 -m "YT-DLP Media Desk v3.7.0"
git push origin main
git push origin v3.7.0      # a tag 'v*' dispara build + (se configurado) assinatura + release

# Alternativa sem tag (teste): Actions > "Release + SignPath" > Run workflow,
# com publish=true para publicar a release.
```

Antes de publicar, confirmar:
- [ ] `dist\` reconstruído com o build .NET 8 (o `dist\` atual é ainda .NET 7).
- [ ] `index.html`/`server.py` commitados (Gavetas, cores, remoção, correção de datas).
- [ ] Obrigação de fonte do FFmpeg (GPL) satisfeita — ver `LICENCA.md`.
