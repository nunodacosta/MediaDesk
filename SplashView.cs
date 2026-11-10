using System.Drawing.Drawing2D;

enum SplashStepState { Pending, Active, Done, Warning }

// Splash de arranque desenhado pelo proprio launcher. As cores seguem o tema e a
// paleta guardados em data/config.enc (as mesmas variaveis CSS da interface web).
sealed class SplashView : Control
{
    sealed class Step
    {
        public string Title = "";
        public string Note = "";
        public SplashStepState State;
    }

    readonly List<Step> steps = new();
    readonly System.Windows.Forms.Timer animation = new() { Interval = 16 };
    double targetPercent;
    double shownPercent;
    float spinner;

    Color bg = Color.FromArgb(10, 10, 12);
    Color card = Color.FromArgb(20, 20, 24);
    Color border = Color.FromArgb(42, 42, 48);
    Color text = Color.FromArgb(237, 237, 238);
    Color textSecondary = Color.FromArgb(161, 161, 170);
    Color accent = Color.FromArgb(0x81, 0x8c, 0xf8);
    static readonly Color Warn = Color.FromArgb(0xf5, 0x9e, 0x0b);

    readonly Font brandFont = new("Segoe UI", 8.25f, FontStyle.Bold);
    readonly Font subtitleFont = new("Segoe UI Semibold", 13f);
    readonly Font stepFont = new("Segoe UI", 9.5f);
    readonly Font smallFont = new("Segoe UI", 8.5f);
    readonly Font percentFont = new("Segoe UI", 9.5f, FontStyle.Bold);
    readonly Font wordmarkFont = new("Segoe UI Black", 72f, FontStyle.Bold);

    static Icon? logo;
    static bool logoLoaded;

    // O icone da aplicacao viaja embebido no executavel (app.ico): o splash
    // desenha-o tal e qual como aparece no Explorer e na barra de tarefas.
    static Icon? Logo
    {
        get
        {
            if (!logoLoaded)
            {
                logoLoaded = true;
                try
                {
                    using var stream = typeof(SplashView).Assembly.GetManifestResourceStream("app.ico");
                    if (stream != null) logo = new Icon(stream, 256, 256);
                }
                catch { logo = null; }
            }
            return logo;
        }
    }

    string subtitle = "";
    string status = "";
    string detail = "";
    string version = "";

    public SplashView()
    {
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                 ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
        animation.Tick += (_, _) => Animate();
        animation.Start();
    }

    public int Percent => (int)Math.Round(targetPercent);

    public string Subtitle { get => subtitle; set { subtitle = value ?? ""; Invalidate(); } }
    public string Status { get => status; set { status = value ?? ""; Invalidate(); } }
    public string Detail { get => detail; set { detail = value ?? ""; Invalidate(); } }
    public string Version { get => version; set { version = value ?? ""; Invalidate(); } }

    public void SetSteps(IEnumerable<string> titles)
    {
        steps.Clear();
        foreach (var t in titles) steps.Add(new Step { Title = t });
        Invalidate();
    }

    public void SetStep(int index, SplashStepState state, string? note = null)
    {
        if (index < 0 || index >= steps.Count) return;
        steps[index].State = state;
        if (note != null) steps[index].Note = note;
        Invalidate();
    }

    public void SetProgress(double percent, string? statusText = null)
    {
        targetPercent = Math.Max(targetPercent, Math.Max(0, Math.Min(100, percent)));
        if (statusText != null) status = statusText;
        Invalidate();
    }

    public void SetTheme(Color background, Color cardBg, Color borderColor, Color primary, Color secondary, Color accentColor)
    {
        bg = background; card = cardBg; border = borderColor; text = primary; textSecondary = secondary; accent = accentColor;
        BackColor = background;
        Invalidate();
    }

    void Animate()
    {
        if (!Visible || IsDisposed) return;
        spinner = (spinner + 9f) % 360f;
        double diff = targetPercent - shownPercent;
        shownPercent = Math.Abs(diff) < 0.2 ? targetPercent : shownPercent + diff * 0.18;
        Invalidate();
    }

    protected override void OnVisibleChanged(EventArgs e)
    {
        base.OnVisibleChanged(e);
        if (Visible) animation.Start(); else animation.Stop();
    }

    static Color Mix(Color a, Color b, double ratioA)
    {
        double r = Math.Max(0, Math.Min(1, ratioA));
        return Color.FromArgb(
            (int)Math.Round(a.R * r + b.R * (1 - r)),
            (int)Math.Round(a.G * r + b.G * (1 - r)),
            (int)Math.Round(a.B * r + b.B * (1 - r)));
    }

    static GraphicsPath Rounded(RectangleF r, float radius)
    {
        var path = new GraphicsPath();
        float d = Math.Min(radius * 2, Math.Min(r.Width, r.Height));
        if (d <= 0) { path.AddRectangle(r); return path; }
        path.AddArc(r.X, r.Y, d, d, 180, 90);
        path.AddArc(r.Right - d, r.Y, d, d, 270, 90);
        path.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90);
        path.AddArc(r.X, r.Bottom - d, d, d, 90, 90);
        path.CloseFigure();
        return path;
    }

    void DrawText(Graphics g, string value, Font font, Color color, Rectangle bounds, TextFormatFlags extra = TextFormatFlags.Left)
    {
        TextRenderer.DrawText(g, value, font, bounds, color,
            extra | TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine |
            TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix | TextFormatFlags.NoPadding);
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        var g = e.Graphics;
        var area = ClientRectangle;
        if (area.Width <= 0 || area.Height <= 0) return;
        g.SmoothingMode = SmoothingMode.AntiAlias;

        using (var gradient = new LinearGradientBrush(area, Mix(accent, bg, 0.12), bg, LinearGradientMode.Vertical))
        {
            var blend = new Blend { Positions = new[] { 0f, 0.66f, 1f }, Factors = new[] { 0f, 1f, 1f } };
            gradient.Blend = blend;
            g.FillRectangle(gradient, area);
        }

        var wordSize = TextRenderer.MeasureText("Media Desk", wordmarkFont);
        TextRenderer.DrawText(g, "Media Desk", wordmarkFont,
            new Point(area.Width / 2 - wordSize.Width / 2, (int)(area.Height * 0.16)), Mix(accent, bg, 0.10));

        // Icone a esquerda do lettering, alinhado ao centro do mesmo. Se a janela
        // for demasiado estreita, o lettering fica sozinho (nunca corta o icone).
        var appIcon = Logo;
        if (appIcon != null)
        {
            const int iconSize = 84;
            int iconLeft = area.Width / 2 - wordSize.Width / 2 - iconSize - 28;
            if (iconLeft >= 16)
            {
                int iconTop = (int)(area.Height * 0.16) + (wordSize.Height - iconSize) / 2;
                var previous = g.InterpolationMode;
                g.InterpolationMode = InterpolationMode.HighQualityBicubic;
                g.DrawIcon(appIcon, new Rectangle(iconLeft, iconTop, iconSize, iconSize));
                g.InterpolationMode = previous;
            }
        }

        int width = Math.Min(560, area.Width - 32);
        int stepsHeight = steps.Count * 26;
        int height = 24 + 16 + 30 + 12 + stepsHeight + 16 + 6 + 10 + 20 + 22 + 18;
        var cardRect = new Rectangle(area.Width / 2 - width / 2, Math.Max(16, area.Height / 2 - height / 2), width, height);
        using (var shadow = Rounded(new RectangleF(cardRect.X, cardRect.Y + 10, cardRect.Width, cardRect.Height), 18))
        using (var shadowBrush = new SolidBrush(Color.FromArgb(40, 0, 0, 0)))
            g.FillPath(shadowBrush, shadow);
        using (var path = Rounded(cardRect, 18))
        using (var fill = new SolidBrush(Mix(card, bg, 0.9)))
        using (var pen = new Pen(Mix(accent, border, 0.24)))
        {
            g.FillPath(fill, path);
            g.DrawPath(pen, path);
        }

        int x = cardRect.X + 24;
        int inner = cardRect.Width - 48;
        int y = cardRect.Y + 24;
        DrawText(g, "Y T - D L P   M E D I A   D E S K", brandFont, Mix(accent, textSecondary, 0.62), new Rectangle(x, y, inner, 16));
        y += 16;
        DrawText(g, subtitle, subtitleFont, text, new Rectangle(x, y, inner, 30));
        y += 30 + 12;

        foreach (var step in steps)
        {
            var dot = new RectangleF(x + 1, y + 8, 10, 10);
            Color stepColor = step.State switch
            {
                SplashStepState.Active => text,
                SplashStepState.Pending => Mix(textSecondary, card, 0.7),
                _ => textSecondary
            };
            DrawDot(g, dot, step.State);
            int noteWidth = string.IsNullOrEmpty(step.Note) ? 0 : Math.Min(inner / 2, TextRenderer.MeasureText(step.Note, smallFont).Width + 4);
            DrawText(g, step.Title, stepFont, stepColor, new Rectangle(x + 22, y, inner - 22 - noteWidth - 8, 26));
            if (noteWidth > 0)
                DrawText(g, step.Note, smallFont, step.State == SplashStepState.Warning ? Warn : textSecondary,
                    new Rectangle(x + inner - noteWidth, y, noteWidth, 26), TextFormatFlags.Right);
            y += 26;
        }
        y += 16;

        var track = new RectangleF(x, y, inner, 6);
        using (var trackPath = Rounded(track, 3))
        using (var trackBrush = new SolidBrush(Mix(textSecondary, card, 0.18)))
            g.FillPath(trackBrush, trackPath);
        float fillWidth = (float)(inner * shownPercent / 100.0);
        if (fillWidth >= 1)
        {
            var bar = new RectangleF(x, y, Math.Max(6, fillWidth), 6);
            using var barPath = Rounded(bar, 3);
            using var barBrush = new LinearGradientBrush(new RectangleF(x, y, Math.Max(6, fillWidth) + 1, 6),
                Mix(accent, card, 0.75), accent, LinearGradientMode.Horizontal);
            g.FillPath(barBrush, barPath);
        }
        y += 6 + 10;

        string percentText = $"{(int)Math.Round(shownPercent)}%";
        int percentWidth = TextRenderer.MeasureText("100%", percentFont).Width + 4;
        DrawText(g, status, smallFont, textSecondary, new Rectangle(x, y, inner - percentWidth - 8, 20));
        DrawText(g, percentText, percentFont, accent, new Rectangle(x + inner - percentWidth, y, percentWidth, 20), TextFormatFlags.Right);
        y += 20;
        DrawText(g, detail, smallFont, Mix(textSecondary, card, 0.85), new Rectangle(x, y, inner, 22));

        if (!string.IsNullOrEmpty(version))
            DrawText(g, version, smallFont, Mix(textSecondary, bg, 0.7),
                new Rectangle(0, area.Height - 34, area.Width, 20), TextFormatFlags.HorizontalCenter);
    }

    void DrawDot(Graphics g, RectangleF dot, SplashStepState state)
    {
        switch (state)
        {
            case SplashStepState.Done:
            case SplashStepState.Warning:
                var color = state == SplashStepState.Done ? accent : Warn;
                using (var brush = new SolidBrush(color)) g.FillEllipse(brush, dot);
                using (var pen = new Pen(card, 1.6f))
                {
                    if (state == SplashStepState.Done)
                        g.DrawLines(pen, new[] { new PointF(dot.X + 2.6f, dot.Y + 5.2f), new PointF(dot.X + 4.4f, dot.Y + 7f), new PointF(dot.X + 7.6f, dot.Y + 3.2f) });
                    else
                    {
                        g.DrawLine(pen, dot.X + 5, dot.Y + 2.4f, dot.X + 5, dot.Y + 5.8f);
                        g.DrawLine(pen, dot.X + 5, dot.Y + 7f, dot.X + 5, dot.Y + 7.8f);
                    }
                }
                break;
            case SplashStepState.Active:
                using (var ring = new Pen(Mix(accent, card, 0.25), 1.6f)) g.DrawEllipse(ring, dot);
                using (var arc = new Pen(accent, 1.8f)) g.DrawArc(arc, dot, spinner, 250);
                break;
            default:
                using (var ring = new Pen(Mix(textSecondary, card, 0.48), 1.5f)) g.DrawEllipse(ring, dot);
                break;
        }
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            animation.Dispose();
            brandFont.Dispose(); subtitleFont.Dispose(); stepFont.Dispose();
            smallFont.Dispose(); percentFont.Dispose(); wordmarkFont.Dispose();
        }
        base.Dispose(disposing);
    }
}
