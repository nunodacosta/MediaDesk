# YT-DLP Media Desk Launcher

1. Coloque esta pasta na raiz da app, junto de `server.py`, `index.html`, `config.json`, `bin` e `downloads`.
2. Instale apenas o .NET 8 SDK na máquina de compilação.
3. Execute `build_exe.bat`. O resultado é `YT-DLP-Media-Desk.exe`.
4. Distribua o EXE com os ficheiros da aplicação. Na máquina cliente, o EXE é self-contained e não requer .NET.

## Encerramento seguro
O launcher cria um Windows Job Object com `KILL_ON_JOB_CLOSE`. O Python iniciado e os seus processos-filho, incluindo PowerShell, yt-dlp e ffmpeg, ficam associados ao Job. Ao fechar a janela, apenas essa árvore é terminada. Processos Python/PowerShell já existentes e não pertencentes à aplicação não são tocados.

## WebView2
É necessário WebView2 Runtime. Está normalmente presente no Windows 11 e em muitos Windows 10. Para portabilidade offline total, distribua a versão Fixed Runtime e adapte `EnsureCoreWebView2Async` para indicar a pasta.

## Nota
O launcher não substitui a preparação inicial do Python do antigo BAT. Para zero instalação, distribua `bin\python` já preparado, com as dependências instaladas.

## Licença
Software livre — **GNU GPL-3.0** (ver `LICENSE`). © 2026 Alexandre da Costa /
ALDACO. Créditos: conceito, design e direção de Alexandre da Costa / ALDACO;
implementação técnica assistida por IA, sob direção do autor. Para os detalhes,
abrir a aplicação em *Ajuda > Termos e aviso legal* ou ler
`licenses/ALDACO-IP-NOTICE.txt`. Os componentes de terceiros (yt-dlp, FFmpeg,
Python, Deno, WebView2, .NET) têm as licenças próprias listadas em
`licenses.json`.
