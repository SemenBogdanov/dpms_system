namespace Dpms.OutlookConnector.Desktop;

internal sealed class LogForm : Form
{
    private readonly TextBox lines = new()
    {
        Dock = DockStyle.Fill, Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical,
        BackColor = SystemColors.Window, AccessibleName = "Лог коннектора",
    };

    public LogForm()
    {
        Text = "Лог DPMS Outlook";
        Font = new Font("Segoe UI", 10);
        AutoScaleDimensions = new SizeF(96, 96);
        AutoScaleMode = AutoScaleMode.Dpi;
        ClientSize = new Size(620, 400);
        MinimumSize = new Size(360, 220);
        StartPosition = FormStartPosition.CenterParent;
        ShowInTaskbar = false;
        Controls.Add(lines);
    }

    public void UpdateLog(IEnumerable<string> entries)
    {
        var start = lines.SelectionStart;
        var length = lines.SelectionLength;
        var followTail = length == 0 && start == lines.TextLength;
        lines.Text = string.Join(Environment.NewLine, entries);
        if (followTail) lines.Select(lines.TextLength, 0);
        else lines.Select(Math.Min(start, lines.TextLength), Math.Min(length, Math.Max(0, lines.TextLength - start)));
        lines.ScrollToCaret();
    }
}
