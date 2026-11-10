using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;

// Leitura das definicoes cifradas (data/config.enc) logo no arranque do
// launcher, antes de o servidor Python existir. O formato e o mesmo escrito por
// activity_service.py: cabecalho "MEDIADESK-CONFIG-DPAPI-v1\n" seguido de um
// blob DPAPI (ambito do utilizador, CRYPTPROTECT_UI_FORBIDDEN, sem entropia).
sealed class LauncherSettings
{
    public const string DefaultReleaseRepo = "nunodacosta/MediaDesk";
    static readonly byte[] Magic = Encoding.ASCII.GetBytes("MEDIADESK-CONFIG-DPAPI-v1\n");

    public string Theme { get; private set; } = "system";
    public string Palette { get; private set; } = "indigo";
    public string Language { get; private set; } = "pt";
    public int ServerPort { get; private set; } = 8181;
    public bool ClipboardMonitor { get; private set; }
    public bool OnlineChecks { get; private set; } = true;
    public string ReleaseRepo { get; private set; } = DefaultReleaseRepo;
    public string Source { get; private set; } = "predefinições";
    public string? Error { get; private set; }

    public bool Portuguese => Language.StartsWith("pt", StringComparison.OrdinalIgnoreCase);

    public static string EncryptedPath(string appDir) => Path.Combine(appDir, "data", "config.enc");

    public static LauncherSettings Load(string appDir)
    {
        var settings = new LauncherSettings();
        string encrypted = EncryptedPath(appDir);
        string legacy = Path.Combine(appDir, "config.json");
        try
        {
            if (File.Exists(encrypted))
            {
                settings.Apply(Decrypt(File.ReadAllBytes(encrypted)));
                settings.Source = "data/config.enc";
            }
            else if (File.Exists(legacy))
            {
                settings.Apply(File.ReadAllText(legacy, Encoding.UTF8));
                settings.Source = "config.json";
            }
        }
        catch (Exception ex)
        {
            settings.Error = ex.Message;
        }
        return settings;
    }

    public static string Decrypt(byte[] blob)
    {
        if (blob.Length <= Magic.Length || !blob.AsSpan(0, Magic.Length).SequenceEqual(Magic))
            throw new InvalidDataException("config.enc não é um ficheiro MediaDesk.");
        var cipher = blob.AsSpan(Magic.Length).ToArray();
        return Encoding.UTF8.GetString(Unprotect(cipher));
    }

    void Apply(string json)
    {
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;
        if (root.ValueKind != JsonValueKind.Object)
            throw new InvalidDataException("As definições não são um objeto JSON.");
        Theme = Str(root, "theme") ?? Theme;
        Palette = Str(root, "theme_palette") ?? Palette;
        Language = Str(root, "language") ?? Language;
        if (root.TryGetProperty("server_port", out var port) && port.TryGetInt32(out var p) && p is > 0 and < 65536)
            ServerPort = p;
        ClipboardMonitor = Bool(root, "clipboard_monitor_enabled") ?? ClipboardMonitor;
        OnlineChecks = Bool(root, "online_checks_enabled") ?? OnlineChecks;
        var repo = Str(root, "app_release_repo");
        if (!string.IsNullOrWhiteSpace(repo)) ReleaseRepo = repo.Trim();
    }

    static string? Str(JsonElement root, string name) =>
        root.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() : null;

    static bool? Bool(JsonElement root, string name) =>
        root.TryGetProperty(name, out var v) && (v.ValueKind == JsonValueKind.True || v.ValueKind == JsonValueKind.False)
            ? v.GetBoolean()
            : null;

    [StructLayout(LayoutKind.Sequential)]
    struct DataBlob { public int cbData; public IntPtr pbData; }

    [DllImport("crypt32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern bool CryptUnprotectData(ref DataBlob dataIn, IntPtr description, IntPtr entropy,
        IntPtr reserved, IntPtr prompt, int flags, ref DataBlob dataOut);

    [DllImport("kernel32.dll")]
    static extern IntPtr LocalFree(IntPtr mem);

    static byte[] Unprotect(byte[] cipher)
    {
        var input = new DataBlob { cbData = cipher.Length, pbData = Marshal.AllocHGlobal(cipher.Length) };
        var output = new DataBlob();
        try
        {
            Marshal.Copy(cipher, 0, input.pbData, cipher.Length);
            if (!CryptUnprotectData(ref input, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, 0x1, ref output))
                throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(),
                    "Não foi possível desencriptar data/config.enc (criado por outra conta ou computador?).");
            var plain = new byte[output.cbData];
            Marshal.Copy(output.pbData, plain, 0, output.cbData);
            return plain;
        }
        finally
        {
            Marshal.FreeHGlobal(input.pbData);
            if (output.pbData != IntPtr.Zero) LocalFree(output.pbData);
        }
    }
}
