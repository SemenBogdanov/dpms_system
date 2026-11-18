using Dpms.OutlookConnector;

namespace Dpms.OutlookConnector.Desktop;

internal sealed class LogForm : Form
{
    private readonly ComboBox filter = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 150,
        AccessibleName = "Уровень событий" };
    private readonly ListView log = Grid(("Время", 125), ("Уровень", 110), ("Этап / код", 165), ("Письмо", 230), ("Результат", 360));
    private readonly ListView queue = Grid(("Получено", 145), ("Письмо", 330), ("ID", 115), ("Состояние", 140));
    private readonly Label queueCount = new() { AutoSize = true, Padding = new Padding(10, 8, 10, 8), Dock = DockStyle.Top };
    private readonly TextBox detail = new()
    {
        Dock = DockStyle.Bottom, Multiline = true, ReadOnly = true, Height = 72,
        ScrollBars = ScrollBars.Vertical, BackColor = SystemColors.Window, AccessibleName = "Детали события",
    };
    private IReadOnlyList<JournalEvent> entries = [];

    public LogForm()
    {
        Text = "Лог DPMS Outlook";
        Font = new Font("Segoe UI", 9);
        AutoScaleDimensions = new SizeF(96, 96);
        AutoScaleMode = AutoScaleMode.Dpi;
        ClientSize = new Size(850, 445);
        MinimumSize = new Size(380, 240);
        StartPosition = FormStartPosition.CenterParent;
        ShowInTaskbar = false;

        filter.Items.AddRange(["Все события", "Предупреждения", "Ошибки"]);
        filter.SelectedIndex = 0;
        filter.SelectedIndexChanged += (_, _) => RenderLog();
        var copy = new Button { Text = "Копировать диагностику", AutoSize = true };
        copy.Click += (_, _) =>
        {
            var text = string.Join(Environment.NewLine, VisibleEntries().Reverse().Select(entry => entry.RedactedLine()));
            if (text.Length == 0) return;
            try { Clipboard.SetText(text); }
            catch (System.Runtime.InteropServices.ExternalException)
            { detail.Text = "Буфер обмена недоступен."; }
        };
        var toolbar = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true, Padding = new Padding(8), WrapContents = true };
        toolbar.Controls.AddRange([filter, copy]);
        var logTab = new TabPage("События");
        logTab.Controls.Add(log);
        logTab.Controls.Add(detail);
        logTab.Controls.Add(toolbar);
        var queueTab = new TabPage("Очередь");
        queueTab.Controls.Add(queue);
        queueTab.Controls.Add(queueCount);
        var tabs = new TabControl { Dock = DockStyle.Fill };
        tabs.TabPages.AddRange([logTab, queueTab]);
        Controls.Add(tabs);
        log.SelectedIndexChanged += (_, _) =>
        {
            if (log.SelectedItems.Count == 0 || log.SelectedItems[0].Tag is not JournalEvent entry) return;
            detail.Text = $"{Level(entry.Level)} | {entry.Stage} | {entry.Code}\r\n{entry.Message}"
                + (entry.ReceivedAt is { } at ? $"\r\nПолучено: {at.ToLocalTime():g}" : "")
                + (entry.Subject is { } subject ? $"\r\nТема: {subject}" : "")
                + (entry.Reference is { } reference ? $" | ID: {reference}" : "");
        };
    }

    public void UpdateLog(IEnumerable<JournalEvent> events)
    {
        entries = events.ToArray();
        RenderLog();
    }

    public void UpdateQueue(IReadOnlyList<OutboxPreview> preview, int waiting, int held)
    {
        queueCount.Text = $"Ожидают: {waiting}   Конфликты: {held}"
            + (preview.Count < waiting + held ? $"   Показано: {preview.Count}" : "");
        queue.BeginUpdate();
        try
        {
            queue.Items.Clear();
            foreach (var item in preview)
                queue.Items.Add(new ListViewItem([
                    item.ReceivedAt.ToLocalTime().ToString("g"), JournalEvent.LocalSubject(item.Subject) ?? "(без темы)",
                    item.Id[..Math.Min(10, item.Id.Length)], item.Held ? "Конфликт версии" : "Ожидает",
                ]));
        }
        finally { queue.EndUpdate(); }
    }

    private IEnumerable<JournalEvent> VisibleEntries() => entries.Reverse().Where(entry =>
        filter.SelectedIndex switch { 1 => entry.Level == JournalLevel.Warning, 2 => entry.Level == JournalLevel.Error, _ => true });

    private void RenderLog()
    {
        var selected = log.SelectedItems.Count > 0 ? log.SelectedItems[0].Tag as JournalEvent : null;
        log.BeginUpdate();
        try
        {
            log.Items.Clear();
            detail.Clear();
            foreach (var item in VisibleEntries())
            {
                var row = new ListViewItem([item.At.ToLocalTime().ToString("MM-dd HH:mm:ss"), Level(item.Level),
                    item.Stage + " / " + item.Code, item.Subject ?? item.Reference ?? "", item.Message]) { Tag = item };
                log.Items.Add(row);
                if (ReferenceEquals(selected, item)) row.Selected = true;
            }
        }
        finally { log.EndUpdate(); }
    }

    private static ListView Grid(params (string Label, int Width)[] columns)
    {
        var grid = new ListView
        {
            Dock = DockStyle.Fill, View = View.Details, FullRowSelect = true,
            HideSelection = false, MultiSelect = false, HeaderStyle = ColumnHeaderStyle.Nonclickable,
        };
        foreach (var (label, width) in columns) grid.Columns.Add(label, width);
        return grid;
    }

    private static string Level(JournalLevel level) => level switch
    {
        JournalLevel.Warning => "Предупреждение", JournalLevel.Error => "Ошибка", _ => "Событие",
    };
}
