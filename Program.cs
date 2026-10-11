using System.Diagnostics;
using System.IO.Compression;
using System.Runtime.InteropServices;
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
        Application.Run(new MainForm(Payload.Prepare()));
    }
}

// YT-DLP Media Desk - Launcher kiosk (WebView2)
// Janela sem barra de titulo nativa. Os controlos (minimizar / restaurar / fechar)
// sao desenhados pela propria interface web e comunicam com este host via
// window.chrome.webview.postMessage(...).
sealed class MainForm : Form
{
    readonly WebView2 web = new() { Dock = DockStyle.Fill };
    readonly Job job = new();
    Process? server;
    readonly string appDir;
    readonly string dataRoot = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "YTDLP-MediaDesk");
    int port = 8181;
    bool fullscreen;
    FormBorderStyle prevBorder = FormBorderStyle.None;
    FormWindowState prevState = FormWindowState.Normal;
    Rectangle prevBounds;
    // Ligeira borda exterior sincronizada com o tema (a janela nao tem barra nativa).
    Color borderColor = Color.FromArgb(42, 47, 58);
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
        BackColor = Color.FromArgb(10, 10, 12);
        web.DefaultBackgroundColor = Color.FromArgb(10, 10, 12);
        Padding = new Padding(BorderWidth);
        DoubleBuffered = true;
        Controls.Add(web);
        Shown += async (_, _) => await StartAsync();
        FormClosing += (_, _) => Shutdown();
        Resize += (_, _) => SendWindowState();
    }

    Icon? LoadAppIcon()
    {
        try { var p = Path.Combine(appDir, "app.ico"); if (File.Exists(p)) return new Icon(p); } catch { }
        try { return Icon.ExtractAssociatedIcon(Environment.ProcessPath!); } catch { }
        return null;
    }

    static Color ThemeBg(bool dark) => dark ? Color.FromArgb(10, 10, 12) : Color.FromArgb(255, 255, 255);

    // Cores de acento por paleta (light, dark) — correspondem as 6 paletas da interface web.
    static readonly Dictionary<string, (Color light, Color dark)> PaletteAccents = new()
    {
        ["indigo"] = (Color.FromArgb(0x4f, 0x46, 0xe5), Color.FromArgb(0x81, 0x8c, 0xf8)),
        ["ocean"] = (Color.FromArgb(0x0e, 0x74, 0x90), Color.FromArgb(0x22, 0xd3, 0xee)),
        ["violet"] = (Color.FromArgb(0x7c, 0x3a, 0xed), Color.FromArgb(0xa7, 0x8b, 0xfa)),
        ["emerald"] = (Color.FromArgb(0x04, 0x78, 0x57), Color.FromArgb(0x34, 0xd3, 0x99)),
        ["amber"] = (Color.FromArgb(0xb4, 0x53, 0x09), Color.FromArgb(0xfb, 0xbf, 0x24)),
        ["graphite"] = (Color.FromArgb(0x3f, 0x46, 0x52), Color.FromArgb(0xcb, 0xd5, 0xe1))
    };

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
        if (!PaletteAccents.TryGetValue(palette ?? "", out var c)) c = PaletteAccents["indigo"];
        var accent = dark ? c.dark : c.light;
        // Mistura o acento com o fundo para uma borda "ligeira", tal como na interface web.
        return Blend(accent, ThemeBg(dark), 0.55);
    }

    void ApplyTheme(bool dark, string palette)
    {
        try { BackColor = ThemeBg(dark); } catch { }
        try { web.DefaultBackgroundColor = ThemeBg(dark); } catch { }
        borderColor = ThemeBorder(dark, palette);
        try { if (Padding != new Padding(BorderWidth)) Padding = new Padding(BorderWidth); } catch { }
        Invalidate();
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
        try
        {
            port = ReadPort();
            var exe = Path.Combine(appDir, "bin", "python", "python.exe");
            if (!File.Exists(exe)) exe = "python.exe";
            var script = Path.Combine(appDir, "server.py");
            if (!File.Exists(script)) throw new FileNotFoundException("server.py não encontrado ao lado do launcher.");

            // Pasta de dados do utilizador num local gravável (necessária também
            // para o ficheiro de resposta do servidor e para o WebView2).
            Directory.CreateDirectory(dataRoot);

            // O servidor escreve a porta REAL (ou {error}) neste ficheiro.
            // Sem isto, se a porta configurada estiver ocupada por outra
            // instância, o launcher podia abrir a UI do servidor errado.
            var respFile = Path.Combine(dataRoot, "server.port");
            try { File.Delete(respFile); } catch { }

            server = Process.Start(new ProcessStartInfo(exe, $"\"{script}\"") { WorkingDirectory = appDir, UseShellExecute = false, CreateNoWindow = true, Environment = { ["PYTHONUNBUFFERED"] = "1", ["PYTHONIOENCODING"] = "utf-8", ["PYTHONUTF8"] = "1", ["MEDIADESK_NO_BROWSER"] = "1", ["MEDIADESK_RESPONSE_FILE"] = respFile } }) ?? throw new Exception("Não foi possível iniciar o servidor.");
            job.Add(server);

            int actualPort = 0;
            bool gotPort = false;
            for (int i = 0; i < 200 && !gotPort; i++)
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
                    if (server.HasExited) throw new Exception($"Servidor terminou com código {server.ExitCode}.");
                    await Task.Delay(100);
                }
            }
            if (!gotPort) throw new TimeoutException("O servidor não comunicou a porta a tempo.");
            port = actualPort;

            using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(1) };
            var url = $"http://127.0.0.1:{port}/";
            for (int i = 0; i < 20; i++)
            {
                try { using var r = await http.GetAsync(url); if (r.IsSuccessStatusCode) break; } catch { }
                await Task.Delay(250);
            }

            // Pasta de dados do WebView2 num local gravavel do utilizador.
            // Isto evita a "restricao" quando o executavel corre numa pasta so de
            // leitura (pendrive protegida, Program Files, etc.).
            var env = await CoreWebView2Environment.CreateAsync(userDataFolder: Path.Combine(dataRoot, "WebView2"));
            await web.EnsureCoreWebView2Async(env);
            var s = web.CoreWebView2.Settings;
            s.AreDefaultContextMenusEnabled = false;
            s.AreDevToolsEnabled = false;
            s.IsStatusBarEnabled = false;
            s.IsWebMessageEnabled = true;

            web.CoreWebView2.WebMessageReceived += OnWebMessage;
            web.CoreWebView2.NewWindowRequested += (_, e) =>
            {
                e.Handled = true;
                try { Process.Start(new ProcessStartInfo(e.Uri) { UseShellExecute = true }); } catch { }
            };
            web.CoreWebView2.NavigationCompleted += (_, _) => SendWindowState();

            web.Source = new Uri(url);
        }
        catch (Exception ex)
        {
            Log(ex);
            MessageBox.Show(
                "Não foi possível iniciar a aplicação.\n\n" + ex.Message +
                "\n\nFoi escrito um registo detalhado em:\n" + Path.Combine(dataRoot, "launcher.log"),
                "YT-DLP Media Desk — Falha ao iniciar", MessageBoxButtons.OK, MessageBoxIcon.Error);
            Close();
        }
    }

    void Log(Exception ex)
    {
        try
        {
            Directory.CreateDirectory(dataRoot);
            File.AppendAllText(Path.Combine(dataRoot, "launcher.log"),
                $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] {ex}\r\n\r\n");
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
                case "window":
                    if (!root.TryGetProperty("action", out var act)) return;
                    switch (act.GetString())
                    {
                        case "minimize": WindowState = FormWindowState.Minimized; break;
                        case "maximize": ToggleMaximize(); break;
                        case "fullscreen": ToggleFullscreen(); break;
                        case "close": Close(); break;
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
        try
        {
            var p = Path.Combine(appDir, "config.json");
            if (File.Exists(p))
            {
                using var j = System.Text.Json.JsonDocument.Parse(File.ReadAllText(p));
                if (j.RootElement.TryGetProperty("server_port", out var x) && x.TryGetInt32(out var n)) return n;
            }
        }
        catch { }
        return 8181;
    }

    void Shutdown()
    {
        try { web.Dispose(); } catch { }
        try { if (server is { HasExited: false }) server.Kill(entireProcessTree: true); } catch { }
        try { job.Dispose(); } catch { }
    }

    protected override void WndProc(ref Message m)
    {
        const int WM_GETMINMAXINFO = 0x0024;
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
        string preferred = Path.Combine(exeDir, "MediaDesk-Portable");
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
