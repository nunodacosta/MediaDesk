using System.Diagnostics;
using System.IO.Compression;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

// Entry point. O atributo [STAThread] e OBRIGATORIO: o WebView2 exige um
// apartment COM STA na thread de UI. Sem ele, CoreWebView2Environment.CreateAsync
// falha com RPC_E_CHANGED_MODE (0x80010106) — "impossivel alterar o modo do
// modulo depois de este ser definido".
static class Program
{
    [STAThread]
    static void Main()
    {
        ApplicationConfiguration.Initialize();

        // Uma sojanela por sessao. A segunda entrada (o .exe e o iniciar.bat
        // sao ambos pontos de entrada) ativa a janela que ja esta aberta em vez
        // de criar outra instancia com outro servidor Python e outro splash.
        if (!SingleInstance.Acquire(out var instanceMutex))
        {
            SingleInstance.DebugAttach();
            SingleInstance.LogSecondLaunch();
            SingleInstance.ActivateExisting();
            return;
        }

        try
        {
            Application.Run(new MainForm(Payload.Prepare()));
        }
        finally
        {
            try { instanceMutex.ReleaseMutex(); } catch { }
            instanceMutex.Dispose();
        }
    }
}

// YT-DLP Media Desk - Launcher kiosk (WebView2)
// Janela sem barra de titulo nativa. Os controlos (minimizar / restaurar / fechar)
// sao desenhados pela propria interface web e comunicam com este host via
// window.chrome.webview.postMessage(...).
sealed class MainForm : Form
{
    readonly WebView2 web = new() { Dock = DockStyle.Fill };
    readonly SplashView startupSplash = new() { Dock = DockStyle.Fill };
    readonly System.Windows.Forms.Timer splashFallback = new() { Interval = 15000 };
    LauncherSettings settings = new();
    bool splashHiding;
    const int StepConfig = 0, StepComponents = 1, StepIntegrity = 2, StepServer = 3, StepUpdates = 4, StepInterface = 5;
    readonly Job job = new();
    // Todos os servidores arrancados por esta instancia. A lista existe para que
    // o encerramento mate SEMPRE todos (e nao apenas o ultimo/principal), mesmo
    // que no futuro a aplicacao passe a arrancar servidores auxiliares.
    readonly List<Process> servers = new();
    readonly object serversGate = new();
    Process? server;
    bool shuttingDown;
    string appDir;
    readonly string dataRoot = Path.Combine(Path.GetDirectoryName(Environment.ProcessPath ?? Application.ExecutablePath) ?? AppDomain.CurrentDomain.BaseDirectory, "data");
    int port = 8181;
    bool fullscreen;
    ClipboardMonitorWindow? clipboardMonitor;
    FormBorderStyle prevBorder = FormBorderStyle.None;
    FormWindowState prevState = FormWindowState.Normal;
    Rectangle prevBounds;
    // Ligeira borda exterior sincronizada com o tema (a janela nao tem barra nativa).
    Color borderColor = Color.FromArgb(42, 48, 80);
    const int BorderWidth = 1;

    public MainForm(string appDir)
    {
        this.appDir = appDir;
        Text = "YT-DLP Media Desk";
        FormBorderStyle = FormBorderStyle.None;
        MinimumSize = new Size(960, 640);
        StartPosition = FormStartPosition.CenterScreen;
        Size = new Size(1400, 880);
        Icon = LoadAppIcon();
        KeyPreview = true;
        KeyDown += (_, e) => { if (e.KeyCode == Keys.Escape && fullscreen) ToggleFullscreen(); };
        BackColor = Color.FromArgb(10, 12, 26);
        web.DefaultBackgroundColor = Color.FromArgb(10, 12, 26);
        Padding = new Padding(BorderWidth);
        DoubleBuffered = true;
        Controls.Add(web);
        Controls.Add(startupSplash);
        startupSplash.BringToFront();
        splashFallback.Tick += (_, _) => HideStartupSplash();
        PrepareStartupSplash();
        Shown += async (_, _) => await StartAsync();
        FormClosing += (_, _) => Shutdown();
        // Redes de seguranca: mesmo que o fecho nao venha do botao da interface
        // (Alt+F4, encerramento do Windows, Environment.Exit), os servidores sao
        // terminados. Shutdown() e idempotente.
        Application.ApplicationExit += (_, _) => Shutdown();
        AppDomain.CurrentDomain.ProcessExit += (_, _) => Shutdown();
        Resize += (_, _) => SendWindowState();
    }

    string L(string pt, string en) => settings.Portuguese ? pt : en;

    // Antes do primeiro paint: resolve a pasta da aplicacao, le data/config.enc
    // e aplica o tema guardado. Assim o splash nunca aparece com cores erradas.
    void PrepareStartupSplash()
    {
        appDir = ResolveBaseDir();
        settings = LauncherSettings.Load(appDir);
        ApplySettings();
        startupSplash.SetSteps(new[]
        {
            L("Ler as definições cifradas", "Read encrypted settings"),
            L("Verificar bibliotecas e componentes", "Check libraries and components"),
            L("Verificar a integridade do sistema (servidor)", "Verify system integrity (server)"),
            L("Iniciar o servidor local", "Start the local server"),
            L("Procurar atualizações", "Look for updates"),
            L("Preparar a interface", "Prepare the interface"),
        });
        startupSplash.Subtitle = L("A preparar o sistema...", "Preparing the system...");
        startupSplash.Version = "v" + StartupChecks.ReadAppVersion(appDir);
        if (settings.Error == null)
            startupSplash.SetStep(StepConfig, SplashStepState.Done, settings.Source);
        else
        {
            startupSplash.SetStep(StepConfig, SplashStepState.Warning, L("predefinições", "defaults"));
            startupSplash.Detail = settings.Error;
            LogText("Não foi possível ler as definições cifradas: " + settings.Error);
        }
        startupSplash.SetProgress(6, L("Definições aplicadas.", "Settings applied."));
    }

    void ApplySettings()
    {
        bool dark = settings.Theme switch
        {
            "dark" => true,
            "light" => false,
            _ => IsSystemDarkTheme()
        };
        ApplyTheme(dark, settings.Palette);
        port = settings.ServerPort;
    }

    string ResolveBaseDir()
    {
        string exeDir = Path.GetDirectoryName(Environment.ProcessPath ?? Application.ExecutablePath) ?? appDir;
        string curDir = Directory.GetCurrentDirectory();
        if (File.Exists(Path.Combine(exeDir, "server.py"))) return exeDir;
        if (File.Exists(Path.Combine(curDir, "server.py"))) return curDir;
        if (!string.IsNullOrEmpty(appDir) && File.Exists(Path.Combine(appDir, "server.py"))) return appDir;
        return exeDir;
    }

    void UpdateStartupStatus(string status)
    {
        if (!startupSplash.IsDisposed && startupSplash.Visible)
            startupSplash.Status = status;
    }

    void SplashProgress(double percent, string? status = null)
    {
        if (!startupSplash.IsDisposed && startupSplash.Visible)
            startupSplash.SetProgress(percent, status);
    }

    async void HideStartupSplash()
    {
        splashFallback.Stop();
        if (splashHiding || startupSplash.IsDisposed || !startupSplash.Visible) return;
        splashHiding = true;
        startupSplash.SetStep(StepInterface, SplashStepState.Done);
        startupSplash.SetProgress(100, L("Tudo pronto. A abrir a interface...", "All set. Opening the interface..."));
        await Task.Delay(350);
        if (startupSplash.IsDisposed) return;
        startupSplash.Visible = false;
        SendWindowState();
    }

    // Registo em disco (em %LOCALAPPDATA%) dos servidores arrancados por cada
    // instancia do launcher. Permite limpar orfaos depois de um fecho abrupto
    // (Task Manager, corte de energia) sem tocar em servidores de OUTRA
    // instancia que ainda esteja viva.
    string ServersFile => Path.Combine(dataRoot, "servers.json");

    Icon? LoadAppIcon()
    {
        try { var p = Path.Combine(appDir, "app.ico"); if (File.Exists(p)) return new Icon(p); } catch { }
        try { return Icon.ExtractAssociatedIcon(Environment.ProcessPath!); } catch { }
        return null;
    }

    static Color ThemeBg(bool dark) => dark ? Color.FromArgb(10, 12, 26) : Color.FromArgb(247, 248, 255);

    // Cores de acento por paleta (light, dark) — alinhadas com a paleta do logotipo:
    // amarelo -> laranja -> vermelho -> rosa -> magenta -> roxo -> azul.
    static readonly Dictionary<string, (Color light, Color dark)> PaletteAccents = new()
    {
        ["amber"] = (Color.FromArgb(0xb4, 0x53, 0x09), Color.FromArgb(0xfa, 0xb0, 0x3e)),
        ["crimson"] = (Color.FromArgb(0xcf, 0x1b, 0x2b), Color.FromArgb(0xff, 0x6b, 0x6b)),
        ["rose"] = (Color.FromArgb(0xc2, 0x18, 0x5b), Color.FromArgb(0xff, 0x6f, 0xa8)),
        ["violet"] = (Color.FromArgb(0x81, 0x34, 0xaf), Color.FromArgb(0xbb, 0x7c, 0xe8)),
        ["indigo"] = (Color.FromArgb(0x4f, 0x46, 0xe5), Color.FromArgb(0x81, 0x8c, 0xf8)),
        ["blue"] = (Color.FromArgb(0x3b, 0x46, 0xc4), Color.FromArgb(0x93, 0xa0, 0xff))
    };

    // Paletas antigas guardadas em configuracoes existentes -> novas equivalentes.
    static readonly Dictionary<string, string> LegacyPalettes = new()
    {
        ["ocean"] = "rose",
        ["emerald"] = "crimson",
        ["graphite"] = "blue"
    };

    static string NormalizePalette(string? palette)
    {
        var id = palette ?? "";
        if (LegacyPalettes.TryGetValue(id, out var mapped)) id = mapped;
        return PaletteAccents.ContainsKey(id) ? id : "indigo";
    }

    static Color Blend(Color a, Color b, double ratioA)
    {
        ratioA = Math.Max(0, Math.Min(1, ratioA));
        double ratioB = 1 - ratioA;
        return Color.FromArgb(
            (int)Math.Round(a.R * ratioA + b.R * ratioB),
            (int)Math.Round(a.G * ratioA + b.G * ratioB),
            (int)Math.Round(a.B * ratioA + b.B * ratioB));
    }

    static Color ThemeBorder(bool dark, string palette)
    {
        var paletteId = NormalizePalette(palette);
        if (!PaletteAccents.TryGetValue(paletteId, out var c)) c = PaletteAccents["indigo"];
        var accent = dark ? c.dark : c.light;
        // Mistura o acento com o fundo para uma borda "ligeira", tal como na interface web.
        return Blend(accent, ThemeBg(dark), 0.55);
    }

    void ApplyTheme(bool dark, string palette)
    {
        var background = ThemeBg(dark);
        var paletteId = NormalizePalette(palette);
        var colors = PaletteAccents[paletteId];
        var accent = dark ? colors.dark : colors.light;
        try { BackColor = background; } catch { }
        try { web.DefaultBackgroundColor = background; } catch { }
        try
        {
            startupSplash.SetTheme(
                background,
                dark ? Color.FromArgb(17, 21, 39) : Color.FromArgb(251, 251, 255),
                dark ? Color.FromArgb(42, 48, 80) : Color.FromArgb(221, 225, 244),
                dark ? Color.FromArgb(238, 240, 251) : Color.FromArgb(21, 26, 54),
                dark ? Color.FromArgb(166, 173, 207) : Color.FromArgb(86, 94, 134),
                accent);
        }
        catch { }
        borderColor = ThemeBorder(dark, paletteId);
        try { if (Padding != new Padding(BorderWidth)) Padding = new Padding(BorderWidth); } catch { }
        Invalidate();
    }

    void ApplySavedStartupTheme(string configJson)
    {
        try
        {
            using var config = System.Text.Json.JsonDocument.Parse(configJson);
            var root = config.RootElement;
            string mode = root.TryGetProperty("theme", out var modeElement)
                ? modeElement.GetString() ?? "system"
                : "system";
            string palette = root.TryGetProperty("theme_palette", out var paletteElement)
                ? paletteElement.GetString() ?? "indigo"
                : "indigo";
            bool dark = mode switch
            {
                "dark" => true,
                "light" => false,
                _ => IsSystemDarkTheme()
            };
            ApplyTheme(dark, palette);
        }
        catch (Exception ex)
        {
            LogText("Não foi possível aplicar o tema guardado ao splash: " + ex.Message);
        }
    }

    static bool IsSystemDarkTheme()
    {
        try
        {
            var value = Microsoft.Win32.Registry.GetValue(
                @"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                "AppsUseLightTheme",
                1);
            return Convert.ToInt32(value) == 0;
        }
        catch
        {
            return false;
        }
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        // Borda fina sincronizada com o tema, contornando o interior da janela kiosk.
        using var pen = new Pen(borderColor, BorderWidth);
        var r = ClientRectangle;
        e.Graphics.DrawRectangle(pen, r.Left, r.Top, r.Width - BorderWidth, r.Height - BorderWidth);
    }

    async Task StartAsync()
    {
        Task? webViewInitialization = null;
        bool webViewInitializationAwaited = false;
        // Tempos por fase no launcher.log: permite ver o que atrasa o arranque
        // sem instrumentacao externa (o Python regista os seus proprios tempos).
        var startupClock = Stopwatch.StartNew();
        void Phase(string name) => LogText($"Arranque: {name} aos {startupClock.ElapsedMilliseconds} ms");
        try
        {
            try
            {
                var procStart = Process.GetCurrentProcess().StartTime;
                LogText($"Arranque: janela pronta (inclui extração do executável) em {Math.Round((DateTime.Now - procStart).TotalMilliseconds)} ms");
            }
            catch { }
            string baseDir = ResolveBaseDir();
            if (!string.Equals(baseDir, appDir, StringComparison.OrdinalIgnoreCase))
            {
                appDir = baseDir;
                settings = LauncherSettings.Load(appDir);
                ApplySettings();
            }
            if (settings.ClipboardMonitor) SetClipboardMonitor(true);

            startupSplash.SetStep(StepComponents, SplashStepState.Active);
            SplashProgress(8, L("A verificar bibliotecas e componentes...", "Checking libraries and components..."));
            var components = await Task.Run(() => StartupChecks.CheckComponents(baseDir));
            var missingCritical = components.Where(c => c.Critical && !c.Present).Select(c => c.Name).ToList();
            var missingOptional = components.Where(c => !c.Critical && !c.Present).Select(c => c.Name).ToList();
            if (missingCritical.Count > 0)
                throw new FileNotFoundException(
                    L("Componentes essenciais em falta: ", "Missing essential components: ") +
                    string.Join(", ", missingCritical) + "\n" + baseDir);
            startupSplash.SetStep(StepComponents,
                missingOptional.Count == 0 ? SplashStepState.Done : SplashStepState.Warning,
                $"{components.Count(c => c.Present)}/{components.Count}");
            Phase("componentes verificados");
            if (missingOptional.Count > 0)
            {
                startupSplash.Detail = L("Em falta: ", "Missing: ") + string.Join(", ", missingOptional);
                LogText("Arranque: componentes em falta: " + string.Join(", ", missingOptional));
            }
            SplashProgress(16);

            port = ReadPort();
            var exe = Path.Combine(baseDir, "bin", "python", "python.exe");
            if (!File.Exists(exe)) exe = "python.exe";
            var script = Path.Combine(baseDir, "server.py");

            // Pasta de dados do utilizador num local gravável (necessária também
            // para o ficheiro de resposta do servidor e para o WebView2).
            Directory.CreateDirectory(dataRoot);

            // Antes de arrancar: terminar servidores que ficaram registados por
            // uma sessao anterior que morreu sem fechar (senao o novo servidor
            // ia para a porta seguinte e o orfao continuava a consumir recursos).
            await Task.Run(CleanupOrphanServers);
            if (shuttingDown) return;

            // O servidor escreve a porta REAL (ou {error}) neste ficheiro.
            // Sem isto, se a porta configurada estiver ocupada por outra
            // instância, o launcher podia abrir a UI do servidor errado.
            var respFile = Path.Combine(dataRoot, "server.port");
            try { File.Delete(respFile); } catch { }

            // Perfil do WebView2 no disco local do utilizador (NVMe/SSD). Na
            // pasta da aplicacao (que pode estar num disco USB lento) cada
            // arranque obrigava o WebView2 a ler/gravar centenas de ficheiros
            // pequenos, atrasando o primeiro paint.
            string webCache = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "YTDLP-MediaDesk", "WebView2");
            Directory.CreateDirectory(webCache);
            webViewInitialization = InitializeWebViewAsync(webCache);

            var proc = Process.Start(new ProcessStartInfo(exe, $"\"{script}\"") { WorkingDirectory = appDir, UseShellExecute = false, CreateNoWindow = true, Environment = { ["PYTHONUNBUFFERED"] = "1", ["PYTHONIOENCODING"] = "utf-8", ["PYTHONUTF8"] = "1", ["MEDIADESK_NO_BROWSER"] = "1", ["MEDIADESK_RESPONSE_FILE"] = respFile } }) ?? throw new Exception("Não foi possível iniciar o servidor.");
            server = proc;
            RegisterServer(proc);

            // A integridade dos ficheiros e verificada pelo servidor Python
            // (integrity_worker em server.py) em segundo plano, com o mesmo
            // manifesto checksums.json; o resultado aparece em "Acerca" e no
            // registo da interface. O launcher nao repete a leitura dos ficheiros
            // aqui: era o mesmo trabalho feito duas vezes e, num disco lento,
            // prendia o splash ate 12 s antes de abrir o servidor.
            startupSplash.SetStep(StepIntegrity, SplashStepState.Done, L("em segundo plano", "in background"));
            SplashProgress(34, L("Integridade verificada pelo servidor.", "Integrity verified by the server."));
            Phase("integridade delegada no servidor");

            startupSplash.SetStep(StepServer, SplashStepState.Active);
            SplashProgress(36, L("A iniciar o servidor local...", "Starting the local server..."));
            int actualPort = 0;
            bool gotPort = false;
            // Num disco USB lento o arranque a frio do Python pode levar dezenas
            // de segundos (milhares de ficheiros da stdlib). O limite e o tempo
            // real e nao o numero de ciclos, para nao falhar por causa do I/O.
            var portDeadline = DateTime.UtcNow.AddSeconds(90);
            while (!gotPort && DateTime.UtcNow < portDeadline)
            {
                if (File.Exists(respFile))
                {
                    try
                    {
                        using var jdoc = System.Text.Json.JsonDocument.Parse(File.ReadAllText(respFile));
                        if (jdoc.RootElement.TryGetProperty("error", out var err))
                            throw new Exception("Não foi possível iniciar o servidor: " + (err.GetString() ?? "Sem portas livres") + ".");
                        if (jdoc.RootElement.TryGetProperty("port", out var pr) && pr.TryGetInt32(out actualPort) && actualPort > 0)
                            gotPort = true;
                    }
                    catch (Exception ex) when (ex.Message.StartsWith("Não foi possível"))
                    {
                        throw;
                    }
                    catch
                    {
                        // Ficheiro ainda a ser escrito (JSON incompleto) — continua a aguardar.
                    }
                }
                if (!gotPort)
                {
                    if (proc.HasExited) throw new Exception($"Servidor terminou com código {proc.ExitCode}.");
                    await Task.Delay(100);
                }
            }
            if (!gotPort) throw new TimeoutException("O servidor não comunicou a porta a tempo.");
            port = actualPort;
            UpdateRegisteredServerPort(actualPort);
            Phase($"servidor Python ligado (porta {actualPort})");

            SplashProgress(42, L("A verificar o servidor local...", "Checking the local server..."));
            using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };
            var appUrl = $"http://127.0.0.1:{port}/";
            var readinessUrl = appUrl + "get_config";
            var readinessDeadline = Stopwatch.StartNew();
            bool serverReady = false;
            string? lastReadinessError = null;
            string startupConfig = "";
            while (readinessDeadline.Elapsed < TimeSpan.FromSeconds(20))
            {
                try
                {
                    using var response = await http.GetAsync(readinessUrl, HttpCompletionOption.ResponseHeadersRead);
                    if (response.IsSuccessStatusCode)
                    {
                        startupConfig = await response.Content.ReadAsStringAsync();
                        serverReady = true;
                        break;
                    }
                    lastReadinessError = $"HTTP {(int)response.StatusCode} ({response.StatusCode})";
                }
                catch (HttpRequestException ex) { lastReadinessError = ex.Message; }
                catch (TaskCanceledException ex) { lastReadinessError = ex.Message; }
                if (proc.HasExited) throw new Exception($"Servidor terminou com código {proc.ExitCode}.");
                await Task.Delay(100);
            }
            if (!serverReady)
                throw new TimeoutException(
                    "O servidor local não respondeu a tempo." +
                    (lastReadinessError == null ? "" : "\nÚltimo erro: " + lastReadinessError));
            ApplySavedStartupTheme(startupConfig);
            startupSplash.SetStep(StepServer, SplashStepState.Done, $":{port}");
            SplashProgress(48);
            Phase("servidor local pronto");

            // As verificacoes online (binarios via servidor, pacotes Python no
            // PyPI, pacotes JavaScript no npm e versao da app no GitHub) usam a
            // rede e podem demorar dezenas de segundos. Executam-se em segundo
            // plano e registam-se no launcher.log; a interface abre de imediato
            // com o painel de atualizacoes alimentado pelo proprio servidor
            // Python (/check_libraries). Nada e saltado: as verificacoes
            // continuam a correr, apenas deixam de bloquear o arranque.
            startupSplash.SetStep(StepUpdates, SplashStepState.Done,
                settings.OnlineChecks ? L("em segundo plano", "in background") : L("desativado", "disabled"));
            SplashProgress(50, settings.OnlineChecks
                ? L("Verificações online em segundo plano.", "Online checks running in background.")
                : L("Verificações online desativadas nas definições.", "Online checks disabled in settings."));
            if (settings.OnlineChecks) _ = CheckUpdatesInBackgroundAsync(appUrl, baseDir);

            // Pasta de dados do WebView2 num local gravavel do utilizador.
            // Isto evita a "restricao" quando o executavel corre numa pasta so de
            // leitura (pendrive protegida, Program Files, etc.).
            startupSplash.SetStep(StepInterface, SplashStepState.Active);
            SplashProgress(90, L("A preparar a interface...", "Preparing the interface..."));
            await (webViewInitialization ?? throw new InvalidOperationException("WebView2 não foi inicializado."));
            webViewInitializationAwaited = true;
            var s = web.CoreWebView2.Settings;
            s.AreDefaultContextMenusEnabled = false;
            s.AreDevToolsEnabled = false;
            s.IsStatusBarEnabled = false;
            s.IsWebMessageEnabled = true;
            Phase("WebView2 inicializado");

            web.CoreWebView2.WebMessageReceived += OnWebMessage;
            web.CoreWebView2.NewWindowRequested += (_, e) =>
            {
                e.Handled = true;
                try { Process.Start(new ProcessStartInfo(e.Uri) { UseShellExecute = true }); } catch { }
            };
            web.CoreWebView2.NavigationCompleted += (_, e) =>
            {
                if (e.IsSuccess)
                {
                    Phase("interface carregada");
                    SplashProgress(94, L("A carregar a mediateca...", "Loading the media library..."));
                    // O splash nativo continua visivel ate a interface web
                    // terminar o arranque e enviar "app-ready". Assim so existe
                    // UM splash: o nativo cobre o Python/WebView2 e a carga dos
                    // dados (config, mediateca, fila, verificacao). O splash
                    // HTML nao aparece dentro do launcher.
                }
                else
                {
                    UpdateStartupStatus($"Não foi possível carregar a interface ({e.WebErrorStatus}).");
                    LogText($"A navegação da interface falhou: {e.WebErrorStatus}.");
                }
                SendWindowState();
            };

            SplashProgress(92, L("A abrir a interface...", "Opening the interface..."));
            // Rede de seguranca: se a pagina nunca concluir a navegacao, o
            // splash nativo nao pode ficar para sempre no ecra.
            splashFallback.Start();
            // "host=launcher" diz a interface web que o splash nativo ja esta a
            // cobrir o arranque: a pagina nao mostra o seu proprio splash e
            // avisa o launcher quando estiver pronta ("app-ready").
            web.Source = new Uri(appUrl + (appUrl.Contains('?') ? "&" : "?") + "host=launcher");

            // Vigiar o servidor depois de a UI estar pronta: se ele morrer, a
            // janela fica inutil (sem backend) — avisa e fecha em vez de deixar
            // a aplicacao "congelada". Durante o encerramento e ignorado.
            try
            {
                proc.EnableRaisingEvents = true;
                proc.Exited += (_, _) => OnServerExited(proc);
            }
            catch (Exception ex) { Log(ex); }
        }
        catch (Exception ex)
        {
            if (webViewInitialization != null && !webViewInitializationAwaited)
            {
                _ = webViewInitialization.ContinueWith(
                    task => Log(task.Exception!.GetBaseException()),
                    CancellationToken.None,
                    TaskContinuationOptions.OnlyOnFaulted,
                    TaskScheduler.Default);
            }
            Log(ex);
            MessageBox.Show(
                "Não foi possível iniciar a aplicação.\n\n" + ex.Message +
                "\n\nFoi escrito um registo detalhado em:\n" + Path.Combine(dataRoot, "launcher.log"),
                "YT-DLP Media Desk — Falha ao iniciar", MessageBoxButtons.OK, MessageBoxIcon.Error);
            Close();
        }
    }

    // Verificacoes online em segundo plano. Correm depois de a interface abrir e
    // nunca tocam nos controlos do splash (sao executadas fora da thread de UI);
    // o resultado fica no launcher.log. O painel "Atualizacoes" da interface e
    // alimentado pelo servidor Python (/check_libraries), que usa cache em disco
    // e refresca em segundo plano.
    async Task CheckUpdatesInBackgroundAsync(string appUrl, string baseDir)
    {
        try
        {
            var clock = Stopwatch.StartNew();
            using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(15));
            string version = StartupChecks.ReadAppVersion(baseDir);
            var checks = new (string Label, Task<UpdateCheckResult> Task)[]
            {
                ("Python, FFmpeg, Deno, yt-dlp, .NET", StartupChecks.CheckBinariesAsync(appUrl, cts.Token)),
                (L("bibliotecas Python", "Python libraries"), StartupChecks.CheckPythonPackagesAsync(baseDir, cts.Token)),
                (L("bibliotecas JavaScript", "JavaScript libraries"), StartupChecks.CheckJavaScriptPackagesAsync(baseDir, cts.Token)),
                ("YT-DLP Media Desk", StartupChecks.CheckAppUpdateAsync(settings.ReleaseRepo, version, cts.Token)),
            };

            var results = new List<UpdateCheckResult>();
            foreach (var check in checks)
            {
                try { results.Add(await check.Task); }
                catch (Exception ex) { LogText($"Arranque: verificação de atualizações ({check.Label}) falhou: {ex.Message}"); }
            }

            var findings = results.SelectMany(r => r.Findings).ToList();
            bool incomplete = results.Count < checks.Length || results.Any(r => r.Offline);
            foreach (var f in findings)
                LogText($"Arranque: atualização disponível [{f.Group}] {f.Name}: {f.Installed ?? "-"} -> {f.Latest ?? "-"} ({f.Status})");

            string summary = findings.Count > 0
                ? $"{findings.Count} atualização(ões) disponível(eis)"
                : incomplete ? "sem ligação" : "tudo atualizado";
            LogText($"Arranque: verificações online concluídas em {clock.ElapsedMilliseconds} ms ({summary}).");
        }
        catch (Exception ex)
        {
            LogText("Arranque: verificações online falharam: " + ex.Message);
        }
    }

    async Task InitializeWebViewAsync(string userDataFolder)
    {
        var env = await CoreWebView2Environment.CreateAsync(userDataFolder: userDataFolder);
        await web.EnsureCoreWebView2Async(env);
    }

    void Log(Exception ex) => LogText(ex.ToString());

    void LogText(string message)
    {
        try
        {
            Directory.CreateDirectory(dataRoot);
            File.AppendAllText(Path.Combine(dataRoot, "launcher.log"),
                $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] {message}\r\n");
        }
        catch { }
    }

    void OnWebMessage(object? sender, Microsoft.Web.WebView2.Core.CoreWebView2WebMessageReceivedEventArgs e)
    {
        string raw;
        try { raw = e.TryGetWebMessageAsString(); } catch { return; }
        if (string.IsNullOrEmpty(raw)) return;
        try
        {
            using var doc = System.Text.Json.JsonDocument.Parse(raw);
            var root = doc.RootElement;
            if (!root.TryGetProperty("type", out var typeEl)) return;

            switch (typeEl.GetString())
            {
                case "app-ready":
                    // A interface web terminou o arranque (config, mediateca,
                    // fila e verificacao). So agora o splash nativo desaparece.
                    string webSplash = root.TryGetProperty("webSplash", out var ws) ? (ws.GetString() ?? "?") : "?";
                    LogText($"Arranque: interface pronta (sinal da pagina; splash web={webSplash})");
                    HideStartupSplash();
                    break;
                case "splash-progress":
                    // Progresso do arranque web (6-100%) mapeado para a ultima
                    // parte do splash nativo (94-100%), sem recuar a barra.
                    if (root.TryGetProperty("percent", out var pc) && pc.TryGetDouble(out var pct))
                        SplashProgress(94 + Math.Clamp(pct, 0, 100) * 0.06);
                    break;
                case "window":
                    if (!root.TryGetProperty("action", out var act)) return;
                    switch (act.GetString())
                    {
                        case "minimize": WindowState = FormWindowState.Minimized; break;
                        case "maximize": ToggleMaximize(); break;
                        case "fullscreen": ToggleFullscreen(); break;
                        case "close": Close(); break;
                        case "restart":
                            try { Shutdown(); }
                            catch { }
                            try
                            {
                                string exe = Environment.ProcessPath ?? Application.ExecutablePath;
                                Process.Start(new ProcessStartInfo(exe) { UseShellExecute = true });
                            }
                            catch { }
                            try { Environment.Exit(0); } catch { Application.Exit(); }
                            break;
                        case "drag":
                            ReleaseCapture();
                            SendMessage(Handle, 0xA1, 0x2, 0); // WM_NCLBUTTONDOWN + HTCAPTION
                            break;
                    }
                    break;
                case "theme":
                    bool dark = root.TryGetProperty("mode", out var m) && m.GetString() == "dark";
                    string palette = root.TryGetProperty("palette", out var p) ? (p.GetString() ?? "indigo") : "indigo";
                    ApplyTheme(dark, palette);
                    break;
                case "clipboard-monitor":
                    if (!root.TryGetProperty("enabled", out var clipboardEnabled)) return;
                    SetClipboardMonitor(clipboardEnabled.ValueKind == System.Text.Json.JsonValueKind.True);
                    break;
                case "browse-downloads":
                    using (var dlg = new FolderBrowserDialog())
                    {
                        dlg.Description = "Escolha a pasta de downloads";
                        dlg.UseDescriptionForTitle = true;
                        if (dlg.ShowDialog(this) == DialogResult.OK && !string.IsNullOrEmpty(dlg.SelectedPath))
                            web.CoreWebView2?.PostWebMessageAsJson("{\"type\":\"browse-result\",\"path\":\"" + JsonEscape(dlg.SelectedPath) + "\"}");
                    }
                    break;
            }
        }
        catch { }
    }

    static string JsonEscape(string s) => (s ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"");

    void SetClipboardMonitor(bool enabled)
    {
        try
        {
            if (!enabled)
            {
                clipboardMonitor?.Dispose();
                clipboardMonitor = null;
                return;
            }
            if (clipboardMonitor != null) return;
            clipboardMonitor = new ClipboardMonitorWindow();
            clipboardMonitor.TextChanged += text =>
            {
                try
                {
                    if (shuttingDown || web.CoreWebView2 == null) return;
                    web.CoreWebView2.PostWebMessageAsJson(
                        System.Text.Json.JsonSerializer.Serialize(new { type = "clipboard-text", text }));
                }
                catch (Exception ex) { Log(ex); }
            };
        }
        catch (Exception ex)
        {
            clipboardMonitor?.Dispose();
            clipboardMonitor = null;
            Log(ex);
            try
            {
                web.CoreWebView2?.PostWebMessageAsJson(
                    System.Text.Json.JsonSerializer.Serialize(new { type = "clipboard-error", message = ex.Message }));
            }
            catch { }
        }
    }

    sealed class ClipboardMonitorWindow : NativeWindow, IDisposable
    {
        const int WmClipboardUpdate = 0x031D;

        [DllImport("user32.dll", SetLastError = true)]
        static extern bool AddClipboardFormatListener(IntPtr hwnd);

        [DllImport("user32.dll", SetLastError = true)]
        static extern bool RemoveClipboardFormatListener(IntPtr hwnd);

        public event Action<string>? TextChanged;

        public ClipboardMonitorWindow()
        {
            CreateHandle(new CreateParams { Caption = "YT-DLP Media Desk Clipboard Monitor" });
            if (!AddClipboardFormatListener(Handle))
            {
                var error = Marshal.GetLastWin32Error();
                DestroyHandle();
                throw new System.ComponentModel.Win32Exception(error, "Não foi possível iniciar a monitorização da área de transferência.");
            }
        }

        protected override void WndProc(ref Message message)
        {
            if (message.Msg == WmClipboardUpdate)
            {
                try
                {
                    if (Clipboard.ContainsText(TextDataFormat.UnicodeText))
                        TextChanged?.Invoke(Clipboard.GetText(TextDataFormat.UnicodeText));
                }
                catch (Exception ex)
                {
                    Debug.WriteLine(ex);
                }
            }
            base.WndProc(ref message);
        }

        public void Dispose()
        {
            if (Handle != IntPtr.Zero)
            {
                RemoveClipboardFormatListener(Handle);
                DestroyHandle();
            }
            TextChanged = null;
        }
    }

    void ToggleMaximize()
    {
        if (WindowState == FormWindowState.Maximized)
        {
            WindowState = FormWindowState.Normal;
        }
        else
        {
            MaximizedBounds = Screen.FromControl(this).WorkingArea;
            WindowState = FormWindowState.Maximized;
        }
        SendWindowState();
    }

    void ToggleFullscreen()
    {
        if (!fullscreen)
        {
            prevState = WindowState;
            prevBorder = FormBorderStyle;
            prevBounds = Bounds;
            if (WindowState == FormWindowState.Maximized) WindowState = FormWindowState.Normal;
            var screen = Screen.FromControl(this);
            FormBorderStyle = FormBorderStyle.None;
            TopMost = true;
            Bounds = screen.Bounds;
            fullscreen = true;
        }
        else
        {
            fullscreen = false;
            TopMost = false;
            FormBorderStyle = prevBorder;
            Bounds = prevBounds;
            WindowState = prevState;
        }
        SendWindowState();
    }

    void SendWindowState()
    {
        try
        {
            bool max = WindowState == FormWindowState.Maximized || fullscreen;
            web.CoreWebView2?.PostWebMessageAsJson($"{{\"type\":\"window-state\",\"maximized\":{(max ? "true" : "false")},\"fullscreen\":{(fullscreen ? "true" : "false")}}}");
        }
        catch { }
    }

    int ReadPort()
    {
        return 8181;
    }

    void Shutdown()
    {
        if (shuttingDown) return;
        shuttingDown = true;
        try { clipboardMonitor?.Dispose(); } catch { }
        clipboardMonitor = null;

        // 1) Todos os servidores arrancados nesta sessao. Mata a arvore inteira
        //    (yt-dlp, ffmpeg, ...) e espera que saiam.
        Process[] started;
        lock (serversGate) { started = servers.ToArray(); servers.Clear(); }
        foreach (var p in started) KillTree(p);

        // 2) Tudo o que ficou registado para ESTE launcher — cobre processos cujo
        //    objeto Process se perdeu (reinicio interno do servidor, falha do
        //    Job Object) e servidores arrancados fora da lista em uso.
        int me = Environment.ProcessId;
        var entries = ReadServerRegistry();
        var remaining = new List<ServerEntry>();
        foreach (var e in entries)
        {
            if (e.Launcher != me) { remaining.Add(e); continue; }  // outra instancia
            if (!KillTree(e.Pid)) remaining.Add(e);
        }
        WriteServerRegistry(remaining);

        // 3) Fechar o Job Object: KILL_ON_JOB_CLOSE garante que netos que tenham
        //    escapado a arvore tambem terminam.
        try { job.Dispose(); } catch { }

        // 4) Estado efemero (a UI nao deve reutilizar uma porta morta) e WebView.
        //    So apaga o server.port se ele pertencer a um servidor desta sessao
        //    (uma segunda instancia viva pode ter escrito o mesmo ficheiro).
        try
        {
            var respFile = Path.Combine(dataRoot, "server.port");
            if (File.Exists(respFile))
            {
                var mine = new HashSet<int>(started.Select(p => p.Id));
                foreach (var e in entries) if (e.Launcher == me) mine.Add(e.Pid);
                bool ours = true;
                try
                {
                    using var doc = System.Text.Json.JsonDocument.Parse(File.ReadAllText(respFile));
                    if (doc.RootElement.TryGetProperty("pid", out var pidEl) && pidEl.TryGetInt32(out var pid))
                        ours = mine.Contains(pid);
                }
                catch { }
                if (ours) File.Delete(respFile);
            }
        }
        catch { }
        try { web.Dispose(); } catch { }
    }

    // ==================== REGISTO DE SERVIDORES ====================

    sealed class ServerEntry
    {
        public int Launcher { get; set; }
        public int Pid { get; set; }
        public int Port { get; set; }
        public string Started { get; set; } = "";
    }

    static readonly System.Text.Json.JsonSerializerOptions RegistryJson = new() { WriteIndented = true };

    List<ServerEntry> ReadServerRegistry()
    {
        try
        {
            if (!File.Exists(ServersFile)) return new();
            var raw = File.ReadAllText(ServersFile);
            if (string.IsNullOrWhiteSpace(raw)) return new();
            return System.Text.Json.JsonSerializer.Deserialize<List<ServerEntry>>(raw) ?? new();
        }
        catch { return new(); }
    }

    void WriteServerRegistry(List<ServerEntry> entries)
    {
        try
        {
            Directory.CreateDirectory(dataRoot);
            var tmp = ServersFile + ".tmp";
            File.WriteAllText(tmp, System.Text.Json.JsonSerializer.Serialize(entries, RegistryJson));
            File.Move(tmp, ServersFile, true);
        }
        catch (Exception ex) { Log(ex); }
    }

    void RegisterServer(Process p)
    {
        lock (serversGate)
        {
            servers.Add(p);
            // Se o Job Object falhar (ex.: ambiente com jobs restritos) o
            // encerramento manual continua a matar o servidor e os seus filhos.
            try { job.Add(p); }
            catch (Exception ex) { LogText("Aviso: servidor nao associado ao Job Object: " + ex.Message); }

            var entries = ReadServerRegistry();
            entries.RemoveAll(e => e.Pid == p.Id);
            entries.Add(new ServerEntry
            {
                Launcher = Environment.ProcessId,
                Pid = p.Id,
                Started = DateTime.Now.ToString("o"),
            });
            WriteServerRegistry(entries);
        }
    }

    void UpdateRegisteredServerPort(int port)
    {
        lock (serversGate)
        {
            var entries = ReadServerRegistry();
            var entry = entries.FirstOrDefault(e => e.Launcher == Environment.ProcessId && e.Pid == server?.Id);
            if (entry == null || entry.Port == port) return;
            entry.Port = port;
            WriteServerRegistry(entries);
        }
    }

    // Arranque: mata servidores orfaos de sessoes anteriores (launcher ja morto)
    // e descarta registos obsoletos. Nunca toca em servidores de outra instancia
    // que ainda esteja a correr.
    void CleanupOrphanServers()
    {
        try
        {
            var entries = ReadServerRegistry();
            if (entries.Count == 0) return;
            var keep = new List<ServerEntry>();
            foreach (var e in entries)
            {
                if (e.Pid <= 0) continue;
                if (!ProcessAlive(e.Pid)) continue;                 // registo obsoleto
                if (e.Launcher == Environment.ProcessId) { keep.Add(e); continue; }
                if (ProcessAlive(e.Launcher)) { keep.Add(e); continue; }  // outra instancia viva
                if (!IsOurServerProcess(e.Pid)) continue;           // PID reutilizado por outro programa
                LogText($"A encerrar servidor orfao (PID {e.Pid}, porta {e.Port}) de uma sessao anterior.");
                if (!KillTree(e.Pid)) keep.Add(e);                  // tenta novamente no fecho
            }
            WriteServerRegistry(keep);
        }
        catch (Exception ex) { Log(ex); }
    }

    static bool ProcessAlive(int pid)
    {
        if (pid <= 0) return false;
        try
        {
            using var p = Process.GetProcessById(pid);
            return !p.HasExited;
        }
        catch { return false; }
    }

    // So mata um PID se for realmente o python empacotado com a aplicacao —
    // evita matar um processo alheio que tenha herdado o mesmo PID.
    bool IsOurServerProcess(int pid)
    {
        try
        {
            using var p = Process.GetProcessById(pid);
            if (p.HasExited) return false;
            string? exePath = null;
            try { exePath = p.MainModule?.FileName; } catch { }
            if (string.IsNullOrEmpty(exePath)) return false;
            var bundled = Path.Combine(appDir, "bin", "python", "python.exe");
            if (File.Exists(bundled))
                return string.Equals(Path.GetFullPath(exePath), Path.GetFullPath(bundled), StringComparison.OrdinalIgnoreCase);
            return string.Equals(Path.GetFileName(exePath), "python.exe", StringComparison.OrdinalIgnoreCase);
        }
        catch { return false; }
    }

    bool KillTree(int pid)
    {
        if (pid <= 0) return true;
        try
        {
            using var p = Process.GetProcessById(pid);
            return KillTree(p);
        }
        catch (ArgumentException) { return true; }   // ja nao existe
        catch (Exception ex) { Log(ex); return false; }
    }

    bool KillTree(Process p)
    {
        try
        {
            if (p.HasExited) return true;
            p.Kill(entireProcessTree: true);
            try { p.WaitForExit(3000); } catch { }
            return p.HasExited;
        }
        catch (InvalidOperationException) { return true; }
        catch (Exception ex) { Log(ex); return false; }
    }

    void OnServerExited(Process p)
    {
        if (shuttingDown) return;
        int code = -1;
        try { code = p.ExitCode; } catch { }
        LogText($"O servidor terminou inesperadamente (PID {p.Id}, codigo {code}).");
        try
        {
            BeginInvoke(new Action(() =>
            {
                if (shuttingDown) return;
                MessageBox.Show(this,
                    "O servidor local terminou inesperadamente e a aplicação vai fechar.\n\n" +
                    "Detalhes em:\n" + Path.Combine(dataRoot, "launcher.log"),
                    "YT-DLP Media Desk", MessageBoxButtons.OK, MessageBoxIcon.Error);
                Close();
            }));
        }
        catch { }
    }

    protected override CreateParams CreateParams
    {
        get
        {
            CreateParams cp = base.CreateParams;
            // Permite redimensionar janela sem barra nativa
            cp.Style |= 0x00040000; // WS_THICKFRAME
            cp.Style &= ~0x00C00000; // WS_CAPTION
            return cp;
        }
    }

    protected override void WndProc(ref Message m)
    {
        // Outra entrada (exe/atalho/iniciar.bat) pediu para mostrar ESTA janela.
        if (m.Msg == SingleInstance.ActivationMessage)
        {
            if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
            Show();
            Activate();
            BringToFront();
            SingleInstance.BringToForeground(Handle);
            return;
        }

        const int WM_GETMINMAXINFO = 0x0024;
        const int WM_NCHITTEST = 0x0084;
        const int HTLEFT = 10;
        const int HTRIGHT = 11;
        const int HTTOP = 12;
        const int HTTOPLEFT = 13;
        const int HTTOPRIGHT = 14;
        const int HTBOTTOM = 15;
        const int HTBOTTOMLEFT = 16;
        const int HTBOTTOMRIGHT = 17;
        if (m.Msg == WM_GETMINMAXINFO)
        {
            var mmi = Marshal.PtrToStructure<MINMAXINFO>(m.LParam);
            IntPtr mon = MonitorFromWindow(Handle, MONITOR_DEFAULTTONEAREST);
            var info = new MONITORINFO { cbSize = Marshal.SizeOf<MONITORINFO>() };
            if (GetMonitorInfo(mon, ref info))
            {
                var wa = info.rcWork; var ma = info.rcMonitor;
                mmi.ptMaxPosition.x = wa.left - ma.left;
                mmi.ptMaxPosition.y = wa.top - ma.top;
                mmi.ptMaxSize.x = wa.right - wa.left;
                mmi.ptMaxSize.y = wa.bottom - wa.top;
                Marshal.StructureToPtr(mmi, m.LParam, false);
            }
            base.WndProc(ref m);
            return;
        }
        if (m.Msg == WM_NCHITTEST && WindowState != FormWindowState.Maximized && !fullscreen)
        {
            int x = (short)(m.LParam.ToInt32() & 0xFFFF);
            int y = (short)((m.LParam.ToInt32() >> 16) & 0xFFFF);
            Point pt = PointToClient(new Point(x, y));
            int grip = 10;
            bool left = pt.X <= grip;
            bool right = pt.X >= ClientSize.Width - grip;
            bool top = pt.Y <= grip;
            bool bottom = pt.Y >= ClientSize.Height - grip;
            if (left && top) { m.Result = (IntPtr)HTTOPLEFT; return; }
            if (right && top) { m.Result = (IntPtr)HTTOPRIGHT; return; }
            if (left && bottom) { m.Result = (IntPtr)HTBOTTOMLEFT; return; }
            if (right && bottom) { m.Result = (IntPtr)HTBOTTOMRIGHT; return; }
            if (left) { m.Result = (IntPtr)HTLEFT; return; }
            if (right) { m.Result = (IntPtr)HTRIGHT; return; }
            if (top) { m.Result = (IntPtr)HTTOP; return; }
            if (bottom) { m.Result = (IntPtr)HTBOTTOM; return; }
        }
        base.WndProc(ref m);
    }

    [StructLayout(LayoutKind.Sequential)] struct POINT { public int x, y; }
    [StructLayout(LayoutKind.Sequential)] struct RECT { public int left, top, right, bottom; }
    [StructLayout(LayoutKind.Sequential)] struct MINMAXINFO { public POINT ptReserved, ptMaxSize, ptMaxPosition, ptMinTrackSize, ptMaxTrackSize; }
    [StructLayout(LayoutKind.Sequential)] struct MONITORINFO { public int cbSize; public RECT rcMonitor, rcWork; public int dwFlags; }
    const int MONITOR_DEFAULTTONEAREST = 2;
    [DllImport("user32.dll")] static extern IntPtr MonitorFromWindow(IntPtr h, int f);
    [DllImport("user32.dll")] static extern bool GetMonitorInfo(IntPtr h, ref MONITORINFO i);
    [DllImport("user32.dll")] static extern bool ReleaseCapture();
    [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr h, int m, int w, int l);
}

// ==================== PACOTE PORTATIL AUTOEXTRAIVEL ====================
// Se o executavel tiver um payload anexado (zip + rodape "MDPL"), extrai-o uma
// unica vez para junto do proprio executavel (ou %LOCALAPPDATA% se o local for
// so de leitura) e arranca a aplicacao a partir dai. Sem payload, corre no local.
static class Payload
{
    const int FooterSize = 32;
    static readonly byte[] Magic = { (byte)'M', (byte)'D', (byte)'P', (byte)'L' };

    public static string Prepare()
    {
        try
        {
            string self = Environment.ProcessPath ?? Application.ExecutablePath;
            using (var probe = File.OpenRead(self))
            {
                if (!TryReadFooter(probe, out long zipOffset, out long zipLength, out long version))
                    return AppContext.BaseDirectory;
                string exeDir = Path.GetDirectoryName(self) ?? AppContext.BaseDirectory;
                string target = ChooseTarget(exeDir);
                string marker = Path.Combine(target, ".payload-version");
                if (File.Exists(marker) && long.TryParse(File.ReadAllText(marker), out var v) && v == version)
                    return target;

                Extract(self, zipOffset, zipLength, target, version);
                return target;
            }
        }
        catch (Exception ex)
        {
            MessageBox.Show("Nao foi possivel preparar os ficheiros da aplicacao:\n\n" + ex.Message,
                "YT-DLP Media Desk", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return AppContext.BaseDirectory;
        }
    }

    // Le o rodape "MDPL" tolerando uma assinatura Authenticode anexada ao fim do
    // ficheiro: o signtool/SignPath colocam a tabela de certificados DEPOIS do
    // rodape, por isso este deixa de estar exatamente nos ultimos 32 bytes.
    // Procura o rodape de tras para a frente e valida a estrutura (o zip fica
    // imediatamente antes do rodape: zipOffset + zipLength == posicao do rodape).
    static bool TryReadFooter(FileStream probe, out long zipOffset, out long zipLength, out long version)
    {
        zipOffset = zipLength = version = 0;
        const int window = 256 * 1024;   // assinaturas OV + timestamp ocupam poucos KB
        long len = probe.Length;
        if (len < FooterSize) return false;

        long start = Math.Max(0, len - window);
        int tailLen = (int)(len - start);
        var tail = new byte[tailLen];
        probe.Seek(start, SeekOrigin.Begin);
        probe.ReadExactly(tail, 0, tailLen);

        for (int i = tailLen - FooterSize; i >= 0; i--)
        {
            if (tail[i + 28] != Magic[0] || tail[i + 29] != Magic[1] ||
                tail[i + 30] != Magic[2] || tail[i + 31] != Magic[3]) continue;

            long zo = BitConverter.ToInt64(tail, i);
            long zl = BitConverter.ToInt64(tail, i + 8);
            long vr = BitConverter.ToInt64(tail, i + 16);
            long footerPos = start + i;
            if (zo >= 0 && zl > 0 && zo + zl == footerPos && zo + zl <= len)
            {
                zipOffset = zo; zipLength = zl; version = vr;
                return true;
            }
        }
        return false;
    }

    static string ChooseTarget(string exeDir)
    {
        // Nome da pasta portatil (igual ao artefacto dist\Media Desk Portable).
        string preferred = Path.Combine(exeDir, "Media Desk Portable");
        if (CanWrite(exeDir))
        {
            try { Directory.CreateDirectory(preferred); return preferred; } catch { }
        }
        string fallback = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "YTDLP-MediaDesk", "Payload");
        Directory.CreateDirectory(fallback);
        return fallback;
    }

    static bool CanWrite(string dir)
    {
        try
        {
            string t = Path.Combine(dir, ".md_writetest");
            using (File.Create(t, 1, FileOptions.DeleteOnClose)) { }
            return true;
        }
        catch { return false; }
    }

    static void Extract(string selfPath, long zipOffset, long zipLength, string target, long version)
    {
        using var form = new ExtractForm();
        Exception? error = null;
        form.Shown += (_, _) =>
        {
            var worker = new Thread(() =>
            {
                try { DoExtract(selfPath, zipOffset, zipLength, target, version, form); }
                catch (Exception ex) { error = ex; }
                finally { try { form.BeginInvoke(new Action(form.Close)); } catch { } }
            })
            { IsBackground = true };
            worker.Start();
        };
        form.ShowDialog();
        if (error != null) throw error;
    }

    static void DoExtract(string selfPath, long zipOffset, long zipLength, string target, long version, ExtractForm form)
    {
        Directory.CreateDirectory(target);
        using var file = File.OpenRead(selfPath);
        using var segment = new SegmentStream(file, zipOffset, zipLength);
        using var zip = new ZipArchive(segment, ZipArchiveMode.Read);

        long total = 0;
        foreach (var e in zip.Entries) total += Math.Max(0, e.Length);
        long done = 0;
        string root = Path.GetFullPath(target) + Path.DirectorySeparatorChar;

        foreach (var e in zip.Entries)
        {
            if (string.IsNullOrEmpty(e.Name)) continue; // entrada de pasta
            string dest = Path.GetFullPath(Path.Combine(target, e.FullName));
            if (!dest.StartsWith(root, StringComparison.OrdinalIgnoreCase))
                throw new IOException("Entrada invalida no pacote: " + e.FullName);
            Directory.CreateDirectory(Path.GetDirectoryName(dest)!);
            e.ExtractToFile(dest, true);
            done += Math.Max(0, e.Length);
            form.Report(total <= 0 ? 0 : (int)(done * 100 / total));
        }
        File.WriteAllText(Path.Combine(target, ".payload-version"), version.ToString());
    }

    sealed class ExtractForm : Form
    {
        readonly ProgressBar bar = new() { Minimum = 0, Maximum = 100, Style = ProgressBarStyle.Continuous, Dock = DockStyle.Fill };
        readonly Label label = new() { Text = "A preparar a aplicacao pela primeira vez...", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft };
        public ExtractForm()
        {
            Text = "YT-DLP Media Desk";
            FormBorderStyle = FormBorderStyle.FixedDialog;
            StartPosition = FormStartPosition.CenterScreen;
            ControlBox = false;
            ShowInTaskbar = true;
            ClientSize = new Size(440, 110);
            BackColor = Color.White;
            var grid = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2, Padding = new Padding(18) };
            grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            grid.RowStyles.Add(new RowStyle(SizeType.Absolute, 34));
            grid.RowStyles.Add(new RowStyle(SizeType.Absolute, 26));
            grid.Controls.Add(label, 0, 0);
            grid.Controls.Add(bar, 0, 1);
            Controls.Add(grid);
        }
        public void Report(int percent)
        {
            try
            {
                int p = Math.Max(0, Math.Min(100, percent));
                if (bar.IsHandleCreated && bar.InvokeRequired)
                {
                    bar.BeginInvoke(new Action<int>(Report), p);
                    return;
                }
                bar.Value = p;
                label.Text = $"A preparar a aplicacao pela primeira vez... {p}%";
            }
            catch { }
        }
    }

    // Vista limitada sobre o proprio executavel, do inicio ao fim do zip anexado.
    sealed class SegmentStream : Stream
    {
        readonly Stream inner; readonly long baseOffset; readonly long length; long pos;
        public SegmentStream(Stream inner, long baseOffset, long length)
        { this.inner = inner; this.baseOffset = baseOffset; this.length = length; }
        public override bool CanRead => true;
        public override bool CanSeek => true;
        public override bool CanWrite => false;
        public override long Length => length;
        public override long Position { get => pos; set => pos = value; }
        public override int Read(byte[] buffer, int offset, int count)
        {
            if (pos >= length) return 0;
            int toRead = (int)Math.Min(count, length - pos);
            inner.Position = baseOffset + pos;
            int n = inner.Read(buffer, offset, toRead);
            pos += n;
            return n;
        }
        public override long Seek(long offset, SeekOrigin origin)
        {
            long np = origin switch
            {
                SeekOrigin.Begin => offset,
                SeekOrigin.Current => pos + offset,
                SeekOrigin.End => length + offset,
                _ => pos
            };
            pos = Math.Max(0, Math.Min(length, np));
            return pos;
        }
        public override void Flush() { }
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
        protected override void Dispose(bool disposing) { if (disposing) inner.Dispose(); base.Dispose(disposing); }
    }
}

sealed class Job : IDisposable
{
    IntPtr h = CreateJobObject(IntPtr.Zero, null);
    public Job() { var info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION(); info.BasicLimitInformation.LimitFlags = 0x2000; int len = Marshal.SizeOf(info); IntPtr p = Marshal.AllocHGlobal(len); Marshal.StructureToPtr(info, p, false); SetInformationJobObject(h, 9, p, (uint)len); Marshal.FreeHGlobal(p); }
    public void Add(Process p) { if (!AssignProcessToJobObject(h, p.Handle)) throw new System.ComponentModel.Win32Exception(); }
    public void Dispose() { if (h != IntPtr.Zero) { CloseHandle(h); h = IntPtr.Zero; } }
    [StructLayout(LayoutKind.Sequential)] struct IO_COUNTERS { public ulong a, b, c, d, e, f; }
    [StructLayout(LayoutKind.Sequential)] struct JOBOBJECT_BASIC_LIMIT_INFORMATION { public long PerProcessUserTimeLimit, PerJobUserTimeLimit; public uint LimitFlags; public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize; public uint ActiveProcessLimit; public UIntPtr Affinity; public uint PriorityClass, SchedulingClass; }
    [StructLayout(LayoutKind.Sequential)] struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION { public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation; public IO_COUNTERS IoInfo; public UIntPtr a, b, c, d; }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] static extern IntPtr CreateJobObject(IntPtr a, string? n);
    [DllImport("kernel32.dll")] static extern bool SetInformationJobObject(IntPtr h, int c, IntPtr i, uint l);
    [DllImport("kernel32.dll")] static extern bool AssignProcessToJobObject(IntPtr j, IntPtr p);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
}
