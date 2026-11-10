using System.Diagnostics;
using System.Runtime.InteropServices;

// Garante que so existe UMA janela do Media Desk por sessao do Windows.
// Sem isto, abrir "Media Desk.exe" e depois "iniciar.bat" (ou clicar duas vezes
// no atalho) arrancava duas instancias completas: duas janelas, dois servidores
// Python e dois splashes. A segunda instancia passa a ativar a primeira.
static class SingleInstance
{
    const string MutexName = @"Local\YTDLP-MediaDesk-SingleInstance";
    const int SwRestore = 9;

    // Mensagem registada pelo Windows e enviada em broadcast para a janela ja
    // aberta. Nao depende de permissoes de foreground nem de nomes de processo.
    public static readonly int ActivationMessage = (int)RegisterWindowMessage("YTDLP-MediaDesk-Activate");

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern uint RegisterWindowMessage(string lpString);

    [DllImport("user32.dll")]
    static extern bool PostMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll")]
    static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

    [DllImport("user32.dll")]
    static extern bool IsIconic(IntPtr hWnd);

    static readonly IntPtr HwndBroadcast = new(0xffff);

    // Cria o mutex. Devolve true quando esta e a primeira instancia (e fica com
    // a posse do mutex); false quando ja existe outra instancia viva.
    public static bool Acquire(out Mutex mutex)
    {
        mutex = new Mutex(true, MutexName, out bool createdNew);
        if (createdNew) return true;
        mutex.Dispose();
        return false;
    }

    // Pede a instancia existente para se mostrar. Tenta durante alguns segundos
    // porque a primeira janela pode ainda estar a arrancar (splash).
    public static void ActivateExisting(int attempts = 12)
    {
        for (int i = 0; i < attempts; i++)
        {
            PostMessage(HwndBroadcast, (uint)ActivationMessage, IntPtr.Zero, IntPtr.Zero);
            Thread.Sleep(180);
        }
    }

    // Chamado na janela que ja esta aberta (MainForm.WndProc).
    public static void BringToForeground(IntPtr handle)
    {
        if (handle == IntPtr.Zero) return;
        if (IsIconic(handle)) ShowWindow(handle, SwRestore);
        SetForegroundWindow(handle);
    }

    // Registo de diagnostico sem depender do launcher.log da primeira instancia
    // (que pode estar a ser escrito neste momento).
    public static void LogSecondLaunch()
    {
        try
        {
            string dir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "YTDLP-MediaDesk");
            Directory.CreateDirectory(dir);
            File.AppendAllText(Path.Combine(dir, "instances.log"),
                $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] segunda instancia: a ativar a janela existente (pid {Environment.ProcessId})\n");
        }
        catch { }
    }

    public static void DebugAttach()
    {
        if (Debugger.IsAttached) Debug.WriteLine("SingleInstance: instancia secundaria detetada.");
    }
}
