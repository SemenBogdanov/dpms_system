using System.Diagnostics;
using System.Text;
using System.Text.Json;
using Microsoft.Win32;
using Dpms.OutlookConnector;

namespace Dpms.OutlookConnector.Desktop;

internal sealed class MainForm : Form
{
    private const string RunPath = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private readonly ProtectedState storage = new();
    private LocalState state = new();
    private readonly TextBox server = new() { Dock = DockStyle.Fill, PlaceholderText = "https://", MaxLength = 500 };
    private readonly TextBox code = new() { Dock = DockStyle.Fill, UseSystemPasswordChar = true, MaxLength = 100 };
    private readonly Button pair = new() { Text = "Подключить", AutoSize = true };
    private readonly Button start = new() { Text = "Запустить", AutoSize = true };
    private readonly Button sync = new() { Text = "Синхронизировать", AutoSize = true };
    private readonly Button unlink = new() { Text = "Отвязать", AutoSize = true };
    private readonly NumericUpDown days = new() { Minimum = 1, Maximum = 90, Value = 30, Width = 90 };
    private readonly CheckBox autorun = new() { Text = "Запускать при входе в Windows", AutoSize = true };
    private readonly Label account = new() { AutoSize = true, MaximumSize = new Size(620, 0) };
    private readonly Label status = new() { Text = "Не подключено", AutoSize = true, MaximumSize = new Size(620, 0) };
    private readonly Label details = new() { AutoSize = true, MaximumSize = new Size(620, 0) };
    private readonly Label last = new() { AutoSize = true, MaximumSize = new Size(620, 0) };
    private readonly NotifyIcon tray = new() { Icon = SystemIcons.Application, Text = "DPMS Outlook", Visible = true };
    private readonly System.Windows.Forms.Timer timer = new() { Interval = 60_000 };
    private CancellationTokenSource? operation;
    private Process? scanner;
    private Task? syncJob;
    private bool exiting;
    private bool busy;
    private bool loading = true;
    private bool invalidState;
    private bool changingSync;

    public MainForm(bool minimized)
    {
        Text = "DPMS Outlook";
        Icon = SystemIcons.Application;
        Font = new Font("Segoe UI", 10);
        AutoScaleMode = AutoScaleMode.Dpi;
        ClientSize = new Size(680, 570);
        MinimumSize = new Size(640, 550);
        StartPosition = FormStartPosition.CenterScreen;
        BuildLayout();
        var menu = new ContextMenuStrip();
        menu.Items.Add("Открыть", null, (_, _) => ShowWindow());
        menu.Items.Add("Синхронизировать", null, async (_, _) => await SyncNow());
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("Выход", null, async (_, _) => await ExitApp());
        tray.ContextMenuStrip = menu;
        tray.DoubleClick += (_, _) => ShowWindow();
        pair.Click += async (_, _) => await Pair();
        sync.Click += async (_, _) => await SyncNow();
        start.Click += async (_, _) => await Toggle();
        unlink.Click += (_, _) => Unlink();
        timer.Tick += async (_, _) => { if (state.AutoSync) await SyncNow(); };
        autorun.CheckedChanged += (_, _) => ChangeAutorun();
        days.ValueChanged += (_, _) =>
        {
            if (loading || busy) return;
            state.HistoryDays = (int)days.Value;
            state.PendingEntries = [];
            state.SnapshotMailboxId = null;
            state.CycleSkipped = 0;
            try { storage.Save(state); } catch { status.Text = ErrorText("local_protection_failed"); }
        };
        try
        {
            state = storage.Load();
            if (state.Acknowledged is null || state.Acknowledged.Count > 10_000 || state.HistoryDays is < 1 or > 90
                || state.PendingEntries is null || state.CycleSkipped is < 0 or > 5000)
                throw new ConnectorException("local_state_invalid");
            ScanSnapshot.Validate(state.PendingEntries);
            days.Value = state.HistoryDays;
            server.Text = state.Session?.ServerUrl ?? "";
        }
        catch
        {
            invalidState = true;
            state = new LocalState();
            status.Text = ErrorText("local_state_invalid");
        }
        try { AttachmentStaging.Cleanup(); }
        catch
        {
            state.AutoSync = false;
            status.Text = ErrorText("staging_cleanup_failed");
        }
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(RunPath);
            autorun.Checked = key?.GetValue("DPMS.OutlookConnector") is string;
        }
        catch { autorun.Enabled = false; }
        loading = false;
        RefreshState();
        Shown += async (_, _) =>
        {
            if (minimized && !invalidState && state.Session is not null) Hide();
            timer.Start();
            if (state.AutoSync && !invalidState) await SyncNow();
        };
    }

    private void BuildLayout()
    {
        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill, Padding = new Padding(24), ColumnCount = 1, AutoScroll = true,
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        void Row(Control control)
        {
            var index = layout.RowCount++;
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            control.Margin = new Padding(0, 0, 0, 12);
            layout.Controls.Add(control, 0, index);
        }
        Row(new Label { Text = "Outlook", Font = new Font(Font.FontFamily, 18, FontStyle.Bold), AutoSize = true });
        Row(account);
        var inputs = new TableLayoutPanel { ColumnCount = 2, Dock = DockStyle.Top, AutoSize = true };
        inputs.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 160));
        inputs.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        inputs.Controls.Add(new Label { Text = "Адрес приёмника", AutoSize = true, Padding = new Padding(0, 5, 0, 0) }, 0, 0);
        inputs.Controls.Add(server, 1, 0);
        inputs.Controls.Add(new Label { Text = "Код подключения", AutoSize = true, Padding = new Padding(0, 5, 0, 0) }, 0, 1);
        inputs.Controls.Add(code, 1, 1);
        inputs.Controls.Add(new Label { Text = "Период, дней", AutoSize = true, Padding = new Padding(0, 5, 0, 0) }, 0, 2);
        inputs.Controls.Add(days, 1, 2);
        Row(inputs);
        var commands = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Top, WrapContents = true };
        foreach (var button in new[] { pair, start, sync, unlink })
        {
            button.Margin = new Padding(0, 0, 8, 8);
            button.Padding = new Padding(8, 4, 8, 4);
            commands.Controls.Add(button);
        }
        Row(commands);
        Row(status);
        Row(details);
        Row(last);
        Row(autorun);
        Controls.Add(layout);
    }

    private async Task Pair()
    {
        if (busy || invalidState || state.Session is not null) return;
        try
        {
            var uri = Protocol.Server(server.Text);
            var value = code.Text.Trim();
            if (value.Length != 43 || value.Any(c => !(char.IsAsciiLetterOrDigit(c) || c is '_' or '-')))
                throw new ConnectorException("invalid_pairing_code");
            SetBusy(true);
            operation = new CancellationTokenSource();
            status.Text = "Подключение...";
            using var client = new DpmsClient(uri.AbsoluteUri);
            var result = await client.Pair(value, operation.Token);
            var next = new LocalState
            {
                HistoryDays = (int)days.Value,
                Session = new DeviceSession(uri.AbsoluteUri, result.DeviceId, result.DeviceSecret,
                    result.OwnerName, result.IncludeBody, result.IncludeAttachments),
            };
            // Keep automatic import off until the user explicitly starts this device.
            storage.Save(next);
            state = next;
            status.Text = "Подключено. Синхронизация на паузе.";
        }
        catch (Exception error) { ShowError(error); }
        finally
        {
            code.Clear();
            operation?.Dispose(); operation = null;
            SetBusy(false);
        }
    }

    private async Task Toggle()
    {
        if (state.Session is null || invalidState || changingSync || exiting) return;
        changingSync = true;
        start.Enabled = false;
        var enabled = !state.AutoSync;
        try
        {
            var previous = state.AutoSync;
            state.AutoSync = enabled;
            if (!enabled)
            {
                operation?.Cancel();
                if (syncJob is { } running) await running;
                status.Text = "На паузе";
            }
            try { storage.Save(state); } catch { state.AutoSync = previous; throw; }
            RefreshState();
        }
        catch (Exception error) { ShowError(error); }
        finally { changingSync = false; if (!exiting) RefreshState(); }
        if (enabled && state.AutoSync && !exiting) await SyncNow();
    }

    private Task SyncNow()
    {
        if (busy || invalidState || state.Session is null || exiting) return Task.CompletedTask;
        return syncJob = RunSync();
    }

    private async Task RunSync()
    {
        SetBusy(true);
        operation = new CancellationTokenSource();
        try
        {
            var session = state.Session ?? throw new ConnectorException("not_paired");
            status.Text = "Чтение Outlook...";
            var scan = await Scan(new ScanOptions(session.IncludeBody, session.IncludeAttachments,
                state.HistoryDays, Acknowledged: state.Acknowledged, PendingEntries: state.PendingEntries,
                SnapshotMailboxId: state.SnapshotMailboxId), operation.Token);
            if (scan.Error is not null) throw new ConnectorException(scan.Error);
            status.Text = "Передача в DPMS...";
            using var client = new DpmsClient(session.ServerUrl, session.DeviceSecret);
            var cancellation = operation.Token;
            var report = await Task.Run(() => new SyncEngine().Deliver(scan, state, client, storage.Save, cancellation), cancellation);
            status.Text = report.Incomplete ? "Перенос неполный" : "Синхронизация завершена";
            details.Text = $"Передано: {report.Sent}. Новых: {report.Created}. Обновлено: {report.Updated}. "
                + $"Пропущено: {report.Skipped}. "
                + (scan.SourceState == "offline" ? "Outlook не в сети." : "Источник: локальный кэш Outlook.")
                + (scan.Truncated ? " Достигнут предел одной проверки; потребуется следующий проход." : "");
        }
        catch (Exception error)
        {
            if (error is ConnectorException { Code: "access_denied" })
            {
                state.AutoSync = false;
                try { storage.Save(state); } catch { /* Keep automatic sync stopped in memory. */ }
            }
            ShowError(error);
        }
        finally
        {
            operation.Dispose(); operation = null;
            syncJob = null;
            SetBusy(false);
        }
    }

    private async Task<ScanResult> Scan(ScanOptions options, CancellationToken cancellation)
    {
        AttachmentStaging.Cleanup();
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        timeout.CancelAfter(TimeSpan.FromMinutes(3));
        using var process = new Process
        {
            StartInfo = new ProcessStartInfo(Environment.ProcessPath!, "--scan")
            {
                UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
                StandardInputEncoding = new UTF8Encoding(false), StandardOutputEncoding = Encoding.UTF8,
            },
        };
        scanner = process;
        try
        {
            process.Start();
            var output = ReadBounded(process.StandardOutput, 80_000_000, timeout.Token);
            var errors = ReadBounded(process.StandardError, 65536, timeout.Token);
            await process.StandardInput.WriteAsync(JsonSerializer.Serialize(options, Protocol.Json).AsMemory(), timeout.Token);
            process.StandardInput.Close();
            var json = await output;
            await errors;
            await process.WaitForExitAsync(timeout.Token);
            return await Task.Run(() => JsonSerializer.Deserialize<ScanResult>(json, Protocol.Json)
                ?? throw new ConnectorException("invalid_scan"), timeout.Token);
        }
        catch (OperationCanceledException) when (!cancellation.IsCancellationRequested)
        { throw new ConnectorException("outlook_timeout"); }
        finally
        {
            try
            {
                if (!process.HasExited)
                {
                    process.Kill();
                    using var killTimeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
                    await process.WaitForExitAsync(killTimeout.Token);
                }
            }
            catch { }
            scanner = null;
            AttachmentStaging.Cleanup();
        }
    }

    private static async Task<string> ReadBounded(StreamReader reader, int maximum, CancellationToken cancellation)
    {
        var result = new StringBuilder();
        var buffer = new char[8192];
        int count;
        while ((count = await reader.ReadAsync(buffer, cancellation).ConfigureAwait(false)) != 0)
        {
            if (result.Length + count > maximum) throw new ConnectorException("scan_too_large");
            result.Append(buffer, 0, count);
        }
        return result.ToString();
    }

    private void Unlink()
    {
        if (busy) return;
        if (MessageBox.Show(this,
            "Удалить подключение с этого компьютера? Доступ устройства на сервере отзывается отдельно в настройках DPMS. Импортированные данные сохранятся.",
            "Отвязать Outlook", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return;
        try
        {
            var next = new LocalState { HistoryDays = (int)days.Value };
            storage.Save(next);
            state = next;
            invalidState = false;
            code.Clear(); details.Text = "";
            status.Text = "Не подключено";
            RefreshState();
        }
        catch (Exception error) { ShowError(error); }
    }

    private void ChangeAutorun()
    {
        if (loading) return;
        try
        {
            using var key = Registry.CurrentUser.CreateSubKey(RunPath);
            if (autorun.Checked) key.SetValue("DPMS.OutlookConnector", $"\"{Environment.ProcessPath}\" --minimized");
            else key.DeleteValue("DPMS.OutlookConnector", throwOnMissingValue: false);
        }
        catch
        {
            loading = true; autorun.Checked = !autorun.Checked; loading = false;
            status.Text = "Не удалось изменить автозапуск Windows.";
        }
    }

    private void SetBusy(bool value)
    {
        busy = value;
        if (!exiting) RefreshState();
    }

    private void RefreshState()
    {
        var session = state.Session;
        account.Text = session is null ? "Нет активного подключения" : $"DPMS: {session.OwnerName}\n"
            + (session.IncludeBody ? "Полный текст" : "Только метаданные")
            + (session.IncludeAttachments ? ", вложения включены" : ", без вложений");
        pair.Enabled = !busy && !invalidState && session is null;
        server.Enabled = code.Enabled = pair.Enabled;
        days.Enabled = !busy && !invalidState;
        start.Enabled = !invalidState && !changingSync && session is not null && (!busy || state.AutoSync);
        start.Text = state.AutoSync ? "Пауза" : "Запустить";
        sync.Enabled = !busy && !invalidState && session is not null;
        unlink.Enabled = !busy && (session is not null || invalidState);
        last.Text = state.LastSyncAt is { } date ? "Последняя доставка: " + date.ToLocalTime().ToString("g") : "Доставок ещё не было";
        tray.Text = state.AutoSync ? "DPMS Outlook: синхронизация включена" : "DPMS Outlook: на паузе";
    }

    private void ShowError(Exception error)
    {
        if (exiting) return;
        status.Text = error switch
        {
            ConnectorException known => ErrorText(known.Code),
            OperationCanceledException => state.AutoSync ? "Нет ответа. Повтор при следующей синхронизации." : "На паузе",
            HttpRequestException => "Нет соединения с приёмником. Доставка будет повторена.",
            ArgumentException => "Нужен HTTPS-адрес без пути, параметров и пароля.",
            _ => "Операция не завершена. Повторите попытку; при сбое подключения создайте новый код в DPMS.",
        };
    }

    private static string ErrorText(string code) => code switch
    {
        "invalid_pairing_code" => "Некорректный код подключения.",
        "access_denied" => "Доступ отклонён или отозван. Проверьте подключение в DPMS.",
        "outlook_unavailable" => "Classic Outlook недоступен. Откройте Outlook с рабочим профилем.",
        "outlook_timeout" => "Outlook не ответил за три минуты. Проверьте его окна и запросы разрешений.",
        "mailbox_identity_unavailable" => "Не удалось определить почтовый ящик Outlook.",
        "snapshot_too_large" => "В выбранном периоде слишком много писем. Уменьшите период; перенос не выполнен.",
        "local_state_invalid" => "Локальное подключение не прочитано. Отвяжите его и подключите заново.",
        "local_protection_failed" => "Не удалось защитить или сохранить подключение Windows.",
        "staging_cleanup_failed" => "Не удалось удалить временные вложения. Передача приостановлена; закройте Outlook-коннектор и проверьте его staging-папку.",
        "endpoint_unavailable" => "На этом адресе нет приёмника DPMS.",
        "redirect_blocked" => "Сервер перенаправляет запрос. Укажите конечный HTTPS-адрес приёмника.",
        "sync_conflict" => "Конфликт данных, почтового ящика или лимита. Проверьте подключение в DPMS.",
        "rate_limited" => "Слишком много запросов. Доставка будет повторена.",
        "batch_too_large" or "scan_too_large" or "item_too_large" => "Достигнут предел размера. Полный перенос не выполнен.",
        "server_unavailable" => "Приёмник временно недоступен. Доставка будет повторена.",
        "invalid_ack" or "invalid_response" => "Некорректное подтверждение сервера. Доставка будет повторена.",
        _ => "Данные не перенесены. Проверьте Outlook, подключение и ограничения размера.",
    };

    private void ShowWindow() { Show(); WindowState = FormWindowState.Normal; Activate(); }

    private async Task ExitApp()
    {
        if (exiting) return;
        exiting = true;
        timer.Stop();
        operation?.Cancel();
        if (syncJob is { } running) await running;
        try { AttachmentStaging.Cleanup(); } catch { /* Startup retries restricted cleanup after an OS/file failure. */ }
        tray.Visible = false;
        Close();
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        if (!exiting && e.CloseReason == CloseReason.UserClosing) { e.Cancel = true; Hide(); }
        else
        {
            exiting = true;
            operation?.Cancel();
            try
            {
                if (scanner is { HasExited: false })
                {
                    scanner.Kill();
                    if (scanner.WaitForExit(5000)) AttachmentStaging.Cleanup();
                }
            }
            catch { }
            tray.Dispose(); timer.Dispose();
        }
        base.OnFormClosing(e);
    }
}
