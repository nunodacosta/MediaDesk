# 🎯 Funcionalidades Futuras Recomendadas — YT-DLP Media Desk

> **Documento gerado a pedido do gestor de projetos** como análise estratégica do roadmap
> do YT-DLP Media Desk. Este arquivo **não modifica nenhum código existente** e **não
> contém implementação** — é um guia de priorização para as próximas versões.

**Contexto do produto:** aplicação desktop local (Windows) que envolve o motor
[yt-dlp](https://github.com/yt-dlp/yt-dlp) para download, organização e gestão de vídeo
e áudio, com servidor local Python + interface WebView2, organização por «gavetas»,
fila persistente de downloads, recomendação automática de qualidade e histórico.

**Estado atual:** versão `3.10.0` (outubro de 2026) — com splash de arranque, motor de
versões, integração de feeds auth (cookies/PO Token/Visitor Data), opções avançadas,
temas, i18n (PT/EN/ES/FR/DE) e verificações de integridade.

---

## 🔴 Prioridade Alta — Próximas Versões (short-term roadmap)

### FP-01 — Player integrado na interface
- **Descrição:** reproduzir diretamente na aplicação os arquivos já descarregados
  (HTML5 video/audio), sem depender do player externo do sistema.
- **Valor:** transforma a ferramenta num *media center* completo; elimina o passo de
  abrir o ficheiro no VLC/players externos.
- **Alavancagem:** WebView2 + HTML5; baixo esforço técnico relativo ao resto.
- **Sugestões de sub-itens:** play/pause, seek, velocidade de reprodução, PiP,
  continuar de onde parou, playlist da biblioteca por gaveta/uploader.

### FP-02 — Transcrição automática e inteligência artificial (IA)
- **Descrição:** integração de modelos de IA (ex.: Whisper) para transcrição automática
  de vídeo/áudio, com timestamps, capítulos automáticos e resumo textual.
- **Valor:** diferencial competitivo forte para o mercado de *media downloaders*; uso
  estratégico da IA já alinhado ao perfil técnico do produto.
- **Sub-itens sugeridos:** transcrição por idioma, geração automática de capítulos,
  resumo executivo, legendas *word-level*.

### FP-03 — Automação por feeds RSS / subscriptions
- **Descrição:** assinar canais de YouTube (via feeds RSS) e agendar download automático
  de novos episódios/vídeos.
- **Valor:** evita uso manual; encaixa no padrão de *watch later* inteligente.
- **Sub-itens:** intervalo de polling, filtro por duração/tópico, estado de ciclo
  (novo/ouvido/visto).

### FP-04 — Anti-duplicados e downloads inteligentes
- **Descrição:** antes de baixar, verificar se o conteúdo (por URL ou hash) já existe na
  biblioteca.
- **Valor:** reduz desperdício de espaço e tempo; evita re-downloads de playlists já vistas.

---

## 🟡 Prioridade Média — Próximas 2–3 Versões (mid-term roadmap)

### FP-05 — Otimização e conversão de mídia (transcodificação)
- **Descrição:** compressão/transcodificação (ex.: H.265/HEVC, preset de bitrate) e
  normalização de áudio durante o download.
- **Valor:** biblioteca com tamanho reduzido, mais fácil de arquivar/em transporte.
- **Sub-itens:** preset de qualidade (ex.: "compacto 1080p", "alta fidelidade"),
  conversão de formato no final do job.

### FP-06 — Busca e filtros avançados na mediateca
- **Descrição:** busca full-text (título, uploader, metadados), tags personalizadas e
  filtros combináveis com o estado da fila.
- **Valor:** escalabilidade da biblioteca conforme o volume cresce.

### FP-07 — Modo linha de comando (CLI) / headless
- **Descrição:** interface CLI ou modo servidor para downloads e gestão por script.
- **Valor:** automação para power users e integração com pipelines externos
  (n8n, scripts de CI, assistentes).

### FP-08 — Sincronização e backup na nuvem (opcional, criptografado)
- **Descrição:** sincronização do histórico/gabarito entre dispositivos, com criptografia
  de ponta a ponta.
- **Valor:** multi-dispositivo; requer decisão de privacidade/arquitetura antes.

---

## 🟢 Backlog — Longo Prazo (roadmap estratégico)

### FP-09 — Notificações do sistema e bandeja do sistema (tray)
- Integração com notificações nativas Windows (Toast) e minimização para tray com
  estado da fila.

### FP-10 — Expansão de plataformas suportadas
- TikTok, Instagram, Facebook, Twitter/X, Vimeo, Twitch (já detectadas no código) com
  suporte efetivo completo e legendas multilíngue.

### FP-11 — Temas e localização adicionais
- Novos idiomas e customização avançada de tema/paletas.

### FP-12 — Exportação de relatórios
- Exportação de histórico/fila/relatórios em CSV/JSON para análise externa.

---

## ✅ Itens já mapeados no repositório (próximas entregas imediatas)

Estas funcionalidades já constam como pendências ou em discussão interna no codebase:

1. **Controles de fila** (`TODO.md`): botões de **Pausar** e **Cancelar** na interface e
   endpoints no `server.py` (item já estruturado via flags de ficheiros `.pause`/`.cancel`
   e config `file_based_pause_cancel`).
2. **Ajustes de UI pendentes** (`ADICIONAR.txt`): opções de visibilidade na mediateca
   devem afetar a pesquisa.
3. **Correções de interface registradas** (`correções e implementações.txt`):
   - Nome do vídeo na Atividade (ao lado do link);
   - Ícone da rede social + percentagem no início da barra de progresso;
   - Contadores de vídeo/áudio por rede social no separador superior.

---

## 📋 Sugestão de priorização para o roadmap

| Fase | Foco | Features | Resultado esperado |
|---|---|---|---|
| **V3.11** | UX e reprodutibilidade | FP-01, correções pendentes, ajuda/i18n | Player integrado + qualidade de release |
| **V3.12** | IA e automação | FP-02, FP-03, FP-04 | Diferencial de IA e redução de carga manual |
| **V3.13+** | Engenharia e escala | FP-05 a FP-12 | Convergência técnica e capacidade enterprise |

---

*Este arquivo foi gerado como análise de roadmap e não constitui alteração ao código do projeto.*