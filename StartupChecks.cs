using System.Security.Cryptography;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;

sealed record ComponentStatus(string Name, string RelativePath, bool Critical, bool Present, string? Version = null);

sealed record IntegrityResult(int Total, int Ok, List<string> Changed, List<string> Missing)
{
    public bool Clean => Changed.Count == 0 && Missing.Count == 0;
}

sealed record UpdateFinding(string Group, string Name, string? Installed, string? Latest, string Status);

sealed class UpdateCheckResult
{
    public string Group { get; init; } = "";
    public bool Completed { get; set; }
    public bool Offline { get; set; }
    public string Note { get; set; } = "";
    public List<UpdateFinding> Findings { get; } = new();
}

// Verificacoes executadas pelo splash: presenca dos componentes, integridade
// (checksums.json), e procura de atualizacoes de bibliotecas Python/JavaScript,
// dos binarios (Python, FFmpeg, Deno, yt-dlp, .NET, WebView2) e da propria app.
static class StartupChecks
{
    static readonly HttpClient Http = CreateClient(TimeSpan.FromSeconds(8));

    static HttpClient CreateClient(TimeSpan timeout)
    {
        var client = new HttpClient { Timeout = timeout };
        client.DefaultRequestHeaders.UserAgent.ParseAdd("YT-DLP-Media-Desk-Launcher");
        return client;
    }

    public static List<ComponentStatus> CheckComponents(string baseDir)
    {
        bool Has(string rel) => File.Exists(Path.Combine(baseDir, rel));
        string pythonDir = Path.Combine(baseDir, "bin", "python");
        bool stdlib = Directory.Exists(pythonDir) &&
                      (Directory.GetFiles(pythonDir, "python3*.zip").Length > 0 || Directory.Exists(Path.Combine(pythonDir, "Lib", "encodings")));
        string? webview = null;
        try { webview = CoreWebView2Environment.GetAvailableBrowserVersionString(); } catch { }

        return new List<ComponentStatus>
        {
            new("server.py", "server.py", true, Has("server.py")),
            new("index.html", "index.html", true, Has("index.html")),
            new("activity_service.py", "activity_service.py", true, Has("activity_service.py")),
            new("Microsoft Edge WebView2", "", true, !string.IsNullOrEmpty(webview), webview),
            new("Python", @"bin\python\python.exe", false, Has(@"bin\python\python.exe")),
            new("Python stdlib", @"bin\python\python3*.zip", false, stdlib),
            new("yt-dlp", @"bin\yt-dlp.exe", false, Has(@"bin\yt-dlp.exe")),
            new("FFmpeg", @"bin\ffmpeg.exe", false, Has(@"bin\ffmpeg.exe")),
            new("Deno", @"bin\deno.exe", false, Has(@"bin\deno.exe")),
            new("version.json", "version.json", false, Has("version.json")),
            new("checksums.json", "checksums.json", false, Has("checksums.json")),
        };
    }

    public static IntegrityResult VerifyIntegrity(string baseDir, IProgress<(int done, int total)>? progress)
    {
        var changed = new List<string>();
        var missing = new List<string>();
        string manifest = Path.Combine(baseDir, "checksums.json");
        if (!File.Exists(manifest)) return new IntegrityResult(0, 0, changed, missing);

        using var doc = JsonDocument.Parse(File.ReadAllText(manifest));
        if (!doc.RootElement.TryGetProperty("ficheiros", out var files) || files.ValueKind != JsonValueKind.Object)
            return new IntegrityResult(0, 0, changed, missing);

        var entries = files.EnumerateObject().ToList();
        int ok = 0, done = 0;
        foreach (var entry in entries)
        {
            string full = Path.Combine(baseDir, entry.Name.Replace('/', Path.DirectorySeparatorChar));
            try
            {
                if (!File.Exists(full)) missing.Add(entry.Name);
                else
                {
                    using var stream = File.OpenRead(full);
                    string hash = Convert.ToHexString(SHA256.HashData(stream));
                    if (string.Equals(hash, entry.Value.GetString(), StringComparison.OrdinalIgnoreCase)) ok++;
                    else changed.Add(entry.Name);
                }
            }
            catch { changed.Add(entry.Name); }
            progress?.Report((++done, entries.Count));
        }
        return new IntegrityResult(entries.Count, ok, changed, missing);
    }

    public static string ReadAppVersion(string baseDir)
    {
        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(baseDir, "version.json")));
            if (doc.RootElement.TryGetProperty("version", out var v) && v.GetString() is { Length: > 0 } s) return s;
        }
        catch { }
        return Application.ProductVersion.Split('+')[0];
    }

    // yt-dlp, FFmpeg, Python, Deno, .NET e WebView2: reutiliza a verificacao do
    // servidor (/check_libraries), que ja conhece as versoes locais e as fontes.
    public static async Task<UpdateCheckResult> CheckBinariesAsync(string appUrl, CancellationToken token)
    {
        var result = new UpdateCheckResult { Group = "binários" };
        using var client = CreateClient(TimeSpan.FromSeconds(30));
        using var response = await client.GetAsync(appUrl + "check_libraries", token);
        response.EnsureSuccessStatusCode();
        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync(token));
        var root = doc.RootElement;
        result.Offline = root.TryGetProperty("offline", out var off) && off.ValueKind == JsonValueKind.True;
        if (root.TryGetProperty("libraries", out var libs) && libs.ValueKind == JsonValueKind.Array)
        {
            foreach (var lib in libs.EnumerateArray())
            {
                string status = Get(lib, "status") ?? "unknown";
                if (status is not ("update" or "missing")) continue;
                result.Findings.Add(new UpdateFinding(result.Group, Get(lib, "name") ?? Get(lib, "id") ?? "?",
                    Get(lib, "installed"), Get(lib, "latest"), status));
            }
        }
        result.Completed = true;
        return result;
    }

    public static async Task<UpdateCheckResult> CheckPythonPackagesAsync(string baseDir, CancellationToken token)
    {
        var result = new UpdateCheckResult { Group = "Python" };
        string site = Path.Combine(baseDir, "bin", "python", "Lib", "site-packages");
        var packages = new List<(string name, string version)>();
        if (Directory.Exists(site))
        {
            foreach (var dir in Directory.GetDirectories(site, "*.dist-info"))
            {
                string stem = Path.GetFileName(dir)[..^".dist-info".Length];
                int dash = stem.LastIndexOf('-');
                if (dash > 0) packages.Add((stem[..dash], stem[(dash + 1)..]));
            }
        }
        result.Note = packages.Count.ToString();
        var checks = packages.Select(async pkg =>
        {
            try
            {
                using var doc = JsonDocument.Parse(await Http.GetStringAsync($"https://pypi.org/pypi/{Uri.EscapeDataString(pkg.name)}/json", token));
                string? latest = doc.RootElement.GetProperty("info").GetProperty("version").GetString();
                if (IsNewer(latest, pkg.version))
                    lock (result.Findings) result.Findings.Add(new UpdateFinding(result.Group, pkg.name, pkg.version, latest, "update"));
                return true;
            }
            catch (OperationCanceledException) when (token.IsCancellationRequested) { throw; }
            catch { return false; }
        }).ToList();
        var answers = await Task.WhenAll(checks);
        result.Offline = answers.Length > 0 && answers.All(a => !a);
        result.Completed = true;
        return result;
    }

    public static async Task<UpdateCheckResult> CheckJavaScriptPackagesAsync(string baseDir, CancellationToken token)
    {
        var result = new UpdateCheckResult { Group = "JavaScript" };
        string manifest = Path.Combine(baseDir, "package.json");
        var packages = new List<(string name, string version)>();
        if (File.Exists(manifest))
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(manifest));
            foreach (var section in new[] { "dependencies", "devDependencies" })
            {
                if (!doc.RootElement.TryGetProperty(section, out var deps) || deps.ValueKind != JsonValueKind.Object) continue;
                foreach (var dep in deps.EnumerateObject())
                {
                    string version = dep.Value.GetString() ?? "";
                    string installed = Path.Combine(baseDir, "node_modules", dep.Name.Replace('/', Path.DirectorySeparatorChar), "package.json");
                    try
                    {
                        if (File.Exists(installed))
                        {
                            using var pkg = JsonDocument.Parse(File.ReadAllText(installed));
                            version = pkg.RootElement.GetProperty("version").GetString() ?? version;
                        }
                    }
                    catch { }
                    packages.Add((dep.Name, version.TrimStart('^', '~', '>', '=', 'v', ' ')));
                }
            }
        }
        result.Note = packages.Count.ToString();
        var checks = packages.Select(async pkg =>
        {
            try
            {
                string name = pkg.name.Replace("/", "%2F");
                using var doc = JsonDocument.Parse(await Http.GetStringAsync($"https://registry.npmjs.org/{name}/latest", token));
                string? latest = doc.RootElement.GetProperty("version").GetString();
                if (IsNewer(latest, pkg.version))
                    lock (result.Findings) result.Findings.Add(new UpdateFinding(result.Group, pkg.name, pkg.version, latest, "update"));
                return true;
            }
            catch (OperationCanceledException) when (token.IsCancellationRequested) { throw; }
            catch { return false; }
        }).ToList();
        var answers = await Task.WhenAll(checks);
        result.Offline = answers.Length > 0 && answers.All(a => !a);
        result.Completed = true;
        return result;
    }

    public static async Task<UpdateCheckResult> CheckAppUpdateAsync(string repo, string current, CancellationToken token)
    {
        var result = new UpdateCheckResult { Group = "app" };
        using var request = new HttpRequestMessage(HttpMethod.Get, $"https://api.github.com/repos/{repo}/releases/latest");
        request.Headers.Accept.ParseAdd("application/vnd.github+json");
        try
        {
            using var response = await Http.SendAsync(request, token);
            if (response.StatusCode == System.Net.HttpStatusCode.NotFound)
            {
                result.Note = "sem releases";
                result.Completed = true;
                return result;
            }
            response.EnsureSuccessStatusCode();
            using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync(token));
            string latest = (Get(doc.RootElement, "tag_name") ?? "").TrimStart('v', 'V');
            if (IsNewer(latest, current))
                result.Findings.Add(new UpdateFinding(result.Group, "YT-DLP Media Desk", current, latest, "update"));
            result.Completed = true;
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested) { throw; }
        catch { result.Offline = true; result.Completed = true; }
        return result;
    }

    static string? Get(JsonElement e, string name) =>
        e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() : null;

    static int[] Parts(string? value)
    {
        var digits = System.Text.RegularExpressions.Regex.Matches(value ?? "", @"\d+");
        return digits.Take(4).Select(m => int.TryParse(m.Value, out var n) ? n : 0).ToArray();
    }

    public static bool IsNewer(string? latest, string? installed)
    {
        if (string.IsNullOrWhiteSpace(latest) || string.IsNullOrWhiteSpace(installed)) return false;
        if (System.Text.RegularExpressions.Regex.IsMatch(latest, @"(a|b|rc|dev|alpha|beta)\d*", System.Text.RegularExpressions.RegexOptions.IgnoreCase)) return false;
        var a = Parts(latest);
        var b = Parts(installed);
        if (a.Length == 0 || b.Length == 0) return false;
        for (int i = 0; i < Math.Max(a.Length, b.Length); i++)
        {
            int x = i < a.Length ? a[i] : 0, y = i < b.Length ? b[i] : 0;
            if (x != y) return x > y;
        }
        return false;
    }
}
