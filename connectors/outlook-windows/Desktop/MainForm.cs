using System.Drawing.Text;
using Dpms.OutlookConnector;
using Microsoft.Win32;

namespace Dpms.OutlookConnector.Desktop;

internal sealed class MainForm : Form
{
    private const string RunPath = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const int MaxLogEvents = 500;
    private readonly ProtectedState storage = new();
    private readonly OutlookWorker outlookWorker = new();
    private readonly System.Windows.Forms.Timer scheduler = new() { Interval = 1000 };
    private readonly ToolTip tooltips = new();
    private readonly NotifyIcon tray = new() { Icon = SystemIcons.Application, Text = "DPMS Outlook", Visible = true };
    private readonly Label mailBadge = Badge("Почта");
    private readonly Label dpmsBadge = Badge("DPMS");
    private readonly Button connection = Command("Соединение", "\uE713");
    private readonly Button start = Command("Запустить", "\uE768");
    private readonly Button sync = Command("Синхронизировать", "\uE895");
    private readonly Button unlink = Command("Отвязать", "\uE8A7");
    private readonly Button logButton = Command("Лог", "\uE9D9");
    private readonly Button exitButton = Command("Выход", "\uE8BB");
    private readonly Queue<JournalEvent> activity = new(MaxLogEvents);
    private LocalState state = new();
    private ConnectorSettings settings = new();
    private LinkReading mail = new(LinkState.Unknown, "check_required");
    private LinkReading dpms = new(LinkState.Unknown, "check_required");
    private OutlookProbeResult? profile;
    private DurableOutbox? outbox;
    private IReadOnlyList<OutboxPreview> queuePreview = [];
    private int waiting, held;
    private ConnectionForm? connectionWindow;
    private LogForm? logWindow;
    private DateTimeOffset nextSync, nextCheck, nextAlert;
    private CancellationTokenSource? operation;
    private Task? activeJob;
    private bool invalidState, exiting, readyToClose;

    private sealed record LinkReading(LinkState State, string Code, DateTimeOffset? CheckedAt = null);
    private bool Busy => operation is not null;
    private bool BothOnline => QueuedDelivery.CanSend(mail.State, dpms.State);
    private bool Editing => connectionWindow is { IsDisposed: false };
    private bool Configured => settings.Transport == ConnectorTransport.PostgreSql
        ? settings.Database is not null : !string.IsNullOrWhiteSpace(settings.ServerUrl);

    public MainForm(bool minimized, bool replaced = false)
    {
        Text = "DPMS Outlook";
        Icon = SystemIcons.Application;
        Font = new Font("Segoe UI", 10);
        AutoScaleDimensions = new SizeF(96, 96);
        AutoScaleMode = AutoScaleMode.Dpi;
        FormBorderStyle = FormBorderStyle.FixedSingle;
        MaximizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(232, 306);
        BuildLayout();

        var version = typeof(MainForm).Assembly.GetName().Version?.ToString(3) ?? "";
        Write(JournalLevel.Info, "Коннектор", "started",
            replaced ? $"Предыдущий процесс завершён. Запущен коннектор {version}." : $"Запущен коннектор {version}.");
        LoadState();
        try { AttachmentStaging.Cleanup(); }
        catch (ConnectorException error) { invalidState = true; WriteError("Outlook", error); }

        connection.Click += (_, _) => ShowConnection();
        start.Click += async (_, _) => await Toggle();
        sync.Click += async (_, _) => await RunCommand(SyncNow);
        unlink.Click += async (_, _) => await Unlink();
        logButton.Click += (_, _) => ShowLog();
        exitButton.Click += async (_, _) => await ExitApp();
        scheduler.Tick += async (_, _) => await Tick();
        var menu = new ContextMenuStrip();
        menu.Items.Add("Открыть", null, (_, _) => ShowWindow());
        menu.Items.Add("Лог", null, (_, _) => ShowLog());
        menu.Items.Add("Синхронизировать", null, async (_, _) => await RunCommand(SyncNow));
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("Выход", null, async (_, _) => await ExitApp());
        tray.ContextMenuStrip = menu;
        tray.DoubleClick += (_, _) => ShowWindow();
        Shown += async (_, _) =>
        {
            if (minimized && !invalidState && state.Session is not null) Hide();
            scheduler.Start();
            if (!invalidState && Configured)
                await RunCommand(async cancellation =>
                {
                    if (state.Session is not null) await OpenOutbox();
                    await CheckRuntime(cancellation, flushOnRecovery: false);
                    if (state.AutoSync) await SyncNow(cancellation);
                    else nextSync = DateTimeOffset.UtcNow.AddMinutes(settings.SyncMinutes);
                });
        };
        RefreshUi();
    }

    private void BuildLayout()
    {
        var layout = new TableLayoutPanel { ColumnCount = 1, RowCount = 7, Dock = DockStyle.Fill, Padding = new Padding(10) };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 30));
        var badges = new FlowLayoutPanel { Dock = DockStyle.Fill, WrapContents = false, Margin = Padding.Empty };
        badges.Controls.AddRange([mailBadge, dpmsBadge]);
        layout.Controls.Add(badges, 0, 0);
        var buttons = new[] { connection, start, sync, unlink, logButton, exitButton };
        for (var index = 0; index < buttons.Length; index++)
        {
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 39));
            layout.Controls.Add(buttons[index], 0, index + 1);
            tooltips.SetToolTip(buttons[index], buttons[index].Text);
        }
        Controls.Add(layout);
    }

    private static Label Badge(string name) => new()
    {
        AutoSize = true, Text = name, AccessibleName = name, Margin = new Padding(2, 4, 10, 0),
    };

    private static Button Command(string text, string glyph) => new()
    {
        Text = text, AccessibleName = text, Image = IconImage(glyph), TextAlign = ContentAlignment.MiddleLeft,
        ImageAlign = ContentAlignment.MiddleLeft, TextImageRelation = TextImageRelation.ImageBeforeText,
        Dock = DockStyle.Fill, Margin = new Padding(0, 2, 0, 2), Padding = new Padding(8, 0, 4, 0),
    };

    private static Bitmap IconImage(string glyph)
    {
        var image = new Bitmap(20, 20);
        using var graphics = Graphics.FromImage(image);
        using var font = new Font("Segoe MDL2 Assets", 13, GraphicsUnit.Pixel);
        using var brush = new SolidBrush(SystemColors.ControlText);
        graphics.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
        graphics.DrawString(glyph, font, brush, new PointF(1, 3));
        return image;
    }

    private void LoadState()
    {
        try
        {
            state = storage.Load();
            if (state.Acknowledged is null || state.Acknowledged.Count > 10_000
                || state.ConflictedVersions is null || state.ConflictedVersions.Count > SyncEngine.MaximumRememberedConflicts
                || state.ConflictedVersions.Values.Any(ticks => ticks <= 0 || ticks > DateTime.MaxValue.Ticks)
                || state.PendingEntries is null || state.CycleSkipped is < 0 or > 5000
                || state.CaptureMailboxId is { } mailbox && !ValidHash(mailbox))
                throw new ConnectorException("local_state_invalid");
            ScanSnapshot.Validate(state.PendingEntries);
            if (state.Session is { } bound && (bound.DeviceId == Guid.Empty
                || bound.Transport is not (ConnectorTransport.PostgreSql or ConnectorTransport.Https)))
                throw new ConnectorException("local_state_invalid");
            settings = state.Settings ?? FromLegacyState();
            settings.Validate(requireEndpoint: state.Session is not null);
            if (state.Session is { } session && !SameDestination(settings, session))
                throw new ConnectorException("local_state_invalid");
            if (state.Session is not null)
                Write(JournalLevel.Info, "Коннектор", "state_loaded",
                    state.AutoSync ? "Подключение восстановлено. Синхронизация активна." : "Подключение восстановлено. Синхронизация на паузе.");
        }
        catch
        {
            // Do not replace a protected state that could not be read.
            invalidState = true;
            Write(JournalLevel.Error, "Коннектор", "local_state_invalid", ConnectorText.Describe("local_state_invalid"));
        }
    }

    private ConnectorSettings FromLegacyState()
    {
        var autorun = false;
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(RunPath);
            autorun = key?.GetValue("DPMS.OutlookConnector") is string;
        }
        catch { }
        return new ConnectorSettings
        {
            Transport = state.Session?.Transport ?? ConnectorTransport.PostgreSql,
            Database = state.Session?.Database, ServerUrl = state.Session?.ServerUrl ?? "",
            DeviceName = Environment.MachineName, HistoryDays = state.HistoryDays, Autorun = autorun,
        };
    }

    private static bool SameDestination(ConnectorSettings draft, DeviceSession session)
    {
        if (session.Transport != draft.Transport) return false;
        if (session.Transport == ConnectorTransport.Https)
            return Protocol.Server(draft.ServerUrl).Equals(Protocol.Server(session.ServerUrl));
        return draft.Database is { } wanted && session.Database is { } bound
            && wanted.Host.Equals(bound.Host, StringComparison.OrdinalIgnoreCase) && wanted.Port == bound.Port
            && wanted.Database == bound.Database && wanted.Schema == bound.Schema && wanted.Username == bound.Username;
    }

    private void ShowConnection()
    {
        if (exiting || Busy || invalidState) return;
        if (connectionWindow is { IsDisposed: false } open) { open.Activate(); return; }
        var window = new ConnectionForm(settings, state.Session is not null, OutlookSummary(profile, mail.CheckedAt),
            (draft, cancellation) => RunExclusive(token => CheckDraft(draft, token), cancellation),
            (draft, code, cancellation) => RunExclusive(async token =>
            {
                await BindHttps(draft, code, token);
                return true;
            }, cancellation),
            SaveSettings, ConnectorText.Describe);
        connectionWindow = window;
        window.FormClosed += (_, _) => { connectionWindow = null; if (!exiting) RefreshUi(); };
        window.Show(this);
        RefreshUi();
    }

    private void SaveSettings(ConnectorSettings draft)
    {
        if (Busy || exiting) throw new ConnectorException("operation_busy");
        draft.Validate();
        var oldSession = state.Session;
        if (oldSession is not null && !SameDestination(draft, oldSession))
            throw new ConnectorException("settings_invalid");
        var oldOptions = state.Settings;
        var oldDays = state.HistoryDays;
        var staleDpms = settings.Transport != draft.Transport || settings.Database != draft.Database
            || settings.ServerUrl != draft.ServerUrl;
        var oldEntries = state.PendingEntries;
        var oldSnapshot = state.SnapshotMailboxId;
        var oldSkipped = state.CycleSkipped;
        var oldStarted = state.CaptureCycleStartedAt;
        var oldHealthy = state.CaptureCycleHealthy;
        var oldOutlookIncident = state.OutlookIncident;
        var oldDpmsIncident = state.DpmsIncident;
        var newAlerts = settings.Alerts != draft.Alerts;
        if (settings.Autorun != draft.Autorun || draft.Autorun) SetAutorun(draft.Autorun);
        try
        {
            state.Settings = draft;
            state.HistoryDays = draft.HistoryDays;
            if (oldSession?.Transport == ConnectorTransport.PostgreSql)
                state.Session = oldSession with { Database = draft.Database };
            if (oldDays != draft.HistoryDays) ResetPage();
            if (newAlerts) state.OutlookIncident = state.DpmsIncident = null;
            Persist(state);
        }
        catch
        {
            state.Settings = oldOptions;
            state.HistoryDays = oldDays;
            state.Session = oldSession;
            state.PendingEntries = oldEntries;
            state.SnapshotMailboxId = oldSnapshot;
            state.CycleSkipped = oldSkipped;
            state.CaptureCycleStartedAt = oldStarted;
            state.CaptureCycleHealthy = oldHealthy;
            state.OutlookIncident = oldOutlookIncident;
            state.DpmsIncident = oldDpmsIncident;
            if (settings.Autorun != draft.Autorun)
            {
                try { SetAutorun(settings.Autorun); }
                catch (ConnectorException error) { WriteError("Настройки", error); }
            }
            throw;
        }
        settings = draft;
        var now = DateTimeOffset.UtcNow;
        nextCheck = (staleDpms || newAlerts) && Configured ? now : now.AddMinutes(settings.CheckMinutes);
        nextSync = now.AddMinutes(settings.SyncMinutes);
        if (staleDpms) dpms = new LinkReading(LinkState.Unknown, "check_required");
        Write(JournalLevel.Info, "Настройки", "settings_saved", "Настройки сохранены локально.");
        RefreshUi();
    }

    private static void SetAutorun(bool enabled)
    {
        try
        {
            using var key = Registry.CurrentUser.CreateSubKey(RunPath);
            if (enabled) key.SetValue("DPMS.OutlookConnector", $"\"{Environment.ProcessPath}\" --minimized");
            else key.DeleteValue("DPMS.OutlookConnector", throwOnMissingValue: false);
        }
        catch { throw new ConnectorException("autorun_failed"); }
    }

    private async Task BindHttps(ConnectorSettings draft, string code, CancellationToken cancellation)
    {
        if (state.Session is not null || draft.Transport != ConnectorTransport.Https)
            throw new ConnectorException("settings_invalid");
        draft.Validate();
        using var client = new DpmsClient(draft.ServerUrl);
        var result = await client.Pair(code, cancellation);
        SetBoundSession(draft, result, automatic: false);
        try { SetAutorun(draft.Autorun); }
        catch (ConnectorException error) { WriteError("Настройки", error); }
        nextCheck = DateTimeOffset.UtcNow;
    }

    private void SetBoundSession(ConnectorSettings draft, PairResult result, bool automatic)
    {
        var next = new LocalState
        {
            Settings = draft, HistoryDays = draft.HistoryDays, AutoSync = automatic,
            Session = new DeviceSession(draft.Transport == ConnectorTransport.Https ? Protocol.Server(draft.ServerUrl).AbsoluteUri : "",
                result.DeviceId, result.DeviceSecret, result.OwnerName, result.IncludeBody, result.IncludeAttachments,
                Transport: draft.Transport, Database: draft.Database),
        };
        Persist(next);
        settings = draft;
        state = next;
        outbox = null;
        profile = null;
        mail = dpms = new LinkReading(LinkState.Unknown, "check_required");
        Write(JournalLevel.Info, "DPMS", "paired", "Устройство подключено.");
        RefreshUi();
    }

    private async Task Toggle()
    {
        if (exiting || invalidState || Editing) return;
        if (state.AutoSync)
        {
            try
            {
                state.AutoSync = false;
                try { Persist(state); } catch { state.AutoSync = true; throw; }
                Cancel();
                Write(JournalLevel.Info, "Коннектор", "paused", "Синхронизация поставлена на паузу.");
            }
            catch (Exception error) { WriteError("Коннектор", error); }
            RefreshUi();
            return;
        }
        if (Busy) return;
        if (state.Session is null && (settings.Transport != ConnectorTransport.PostgreSql || settings.Database is null))
        { ShowConnection(); return; }
        await RunCommand(async cancellation =>
        {
            if (state.Session is null)
            {
                settings.Validate();
                using var database = new PostgresClient(settings.Database!);
                var result = await database.Connect(settings.DeviceName, cancellation);
                SetBoundSession(settings, result, automatic: true);
            }
            else
            {
                state.AutoSync = true;
                try { Persist(state); } catch { state.AutoSync = false; throw; }
            }
            Write(JournalLevel.Info, "Коннектор", "resumed", "Автоматическая синхронизация включена.");
            RefreshUi();
            await SyncNow(cancellation);
        });
    }

    private async Task Tick()
    {
        if (Busy || Editing || exiting || invalidState || !Configured) return;
        var now = DateTimeOffset.UtcNow;
        if (now >= nextCheck)
            await RunCommand(cancellation => CheckRuntime(cancellation, flushOnRecovery: true));
        else if (now >= nextSync && state.AutoSync && state.Session is not null)
            await RunCommand(SyncNow);
    }

    private async Task<ConnectionCheckSummary> CheckDraft(ConnectorSettings draft, CancellationToken cancellation)
    {
        var observed = await ProbeOutlook(draft, cancellation);
        var matching = state.Session is { } linked && SameDestination(draft, linked);
        var remote = await ProbeDpms(draft, matching ? state.Session : null, cancellation);
        if (Configured && (matching || state.Session is null) && draft.Transport == settings.Transport
            && draft.Database == settings.Database && draft.ServerUrl == settings.ServerUrl)
        {
            ApplyOutlook(observed);
            ApplyDpms(remote);
            nextCheck = DateTimeOffset.UtcNow.AddMinutes(settings.CheckMinutes);
            await TryNotify(cancellation);
        }
        Write(remote.State == LinkState.Online && observed.State == LinkState.Online ? JournalLevel.Info : JournalLevel.Warning,
            "Связь", "manual_check", $"Почта: {ProbeText(observed)}. DPMS: {ConnectorText.Describe(remote.Code)}");
        return new ConnectionCheckSummary(OutlookSummary(observed, DateTimeOffset.UtcNow),
            ConnectorText.Describe(remote.Code) + (remote.CheckedAt is { } at ? $" ({at.ToLocalTime():g})" : ""));
    }

    private async Task CheckRuntime(CancellationToken cancellation, bool flushOnRecovery)
    {
        nextCheck = DateTimeOffset.UtcNow.AddMinutes(settings.CheckMinutes);
        var wasOnline = BothOnline;
        ApplyOutlook(await ProbeOutlook(settings, cancellation));
        ApplyDpms(await ProbeDpms(settings, state.Session, cancellation));
        await TryNotify(cancellation);
        if (flushOnRecovery && !wasOnline && BothOnline && state.AutoSync)
            await SyncNow(cancellation);
    }

    private async Task<OutlookProbeResult> ProbeOutlook(ConnectorSettings options, CancellationToken cancellation)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        timeout.CancelAfter(TimeSpan.FromSeconds(options.CheckTimeoutSeconds));
        try { return await outlookWorker.Probe(timeout.Token); }
        catch (OperationCanceledException) when (!cancellation.IsCancellationRequested)
        { return new OutlookProbeResult(false, LinkState.Offline, "check_timeout"); }
        catch (Exception error) when (!cancellation.IsCancellationRequested)
        { return new OutlookProbeResult(false, LinkState.Offline, ConnectorText.Code(error)); }
    }

    private static async Task<LinkReading> ProbeDpms(ConnectorSettings draft, DeviceSession? session, CancellationToken cancellation)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        timeout.CancelAfter(TimeSpan.FromSeconds(draft.CheckTimeoutSeconds));
        try
        {
            if (draft.Transport == ConnectorTransport.PostgreSql)
            {
                using var client = new PostgresClient(draft.Database ?? throw new ConnectorException("settings_invalid"), session?.DeviceSecret);
                await client.CheckConnection(timeout.Token);
            }
            else
            {
                using var client = new DpmsClient(draft.ServerUrl);
                await client.CheckConnection(timeout.Token);
            }
            return new LinkReading(LinkState.Online, "dpms_ok", DateTimeOffset.UtcNow);
        }
        catch (OperationCanceledException) when (!cancellation.IsCancellationRequested)
        { return new LinkReading(LinkState.Offline, "check_timeout", DateTimeOffset.UtcNow); }
        catch (Exception error) when (!cancellation.IsCancellationRequested)
        { return new LinkReading(LinkState.Offline, ConnectorText.Code(error), DateTimeOffset.UtcNow); }
    }

    private static string ProbeText(OutlookProbeResult result) => result.State == LinkState.Online
        ? "доступен" : ConnectorText.Describe(result.Code);

    private static string OutlookSummary(OutlookProbeResult? result, DateTimeOffset? checkedAt = null) => result is null
        ? "Outlook не проверен"
        : $"{(result.ClientAvailable ? "Classic Outlook доступен" : "Classic Outlook недоступен")}\n"
            + $"{(result.AccountType == "exchange" ? "Microsoft Exchange / Microsoft 365" : result.AccountType ?? "Тип учётной записи не определён")}  {result.MailboxLabel ?? ""}\n"
            + "Почтовый сервер: " + ProbeText(result)
            + (checkedAt is { } at ? $" ({at.ToLocalTime():g})" : "");

    private void ApplyOutlook(OutlookProbeResult result)
    {
        if (result.MailboxId is { } observed && !MatchesMailbox(observed))
            result = result with { State = LinkState.Unknown, Code = "mailbox_mismatch" };
        profile = result;
        var reading = new LinkReading(result.State, result.Code, DateTimeOffset.UtcNow);
        LogLink("Почта", mail, reading);
        mail = reading;
        RecordIncident(outlook: true, reading);
        RefreshUi();
    }

    private void ApplyDpms(LinkReading reading)
    {
        LogLink("DPMS", dpms, reading);
        dpms = reading;
        if (reading.Code == "access_denied" && state.AutoSync)
        {
            // A healthy endpoint is not proof that a revoked device may resume importing.
            state.AutoSync = false;
            try { Persist(state); }
            catch (ConnectorException error) { WriteError("DPMS", error); }
            Write(JournalLevel.Warning, "DPMS", "access_paused", "Автоматический импорт остановлен: доступ отклонён.");
        }
        RecordIncident(outlook: false, reading);
        RefreshUi();
    }

    private void LogLink(string stage, LinkReading previous, LinkReading next)
    {
        if (previous.CheckedAt is not null && previous.State == next.State && previous.Code == next.Code) return;
        Write(next.State == LinkState.Offline ? JournalLevel.Error
            : next.State == LinkState.Unknown ? JournalLevel.Warning : JournalLevel.Info, stage, next.Code,
            next.State == LinkState.Online ? "Связь подтверждена." : ConnectorText.Describe(next.Code));
    }

    private void RecordIncident(bool outlook, LinkReading reading)
    {
        if (!Configured) return;
        var previous = outlook ? state.OutlookIncident : state.DpmsIncident;
        var next = LinkIncident.Observe(previous, reading.State, reading.Code, DateTimeOffset.UtcNow);
        if (previous == next) return;
        if (outlook) state.OutlookIncident = next; else state.DpmsIncident = next;
        try { Persist(state); }
        catch (ConnectorException error)
        {
            if (outlook) state.OutlookIncident = previous; else state.DpmsIncident = previous;
            WriteError("Уведомления", error);
        }
    }

    private async Task TryNotify(CancellationToken cancellation)
    {
        if (cancellation.IsCancellationRequested || !Configured || settings.Alerts is not { } smtp
            || DateTimeOffset.UtcNow < nextAlert) return;
        var outlook = state.OutlookIncident is { Notified: false } ? state.OutlookIncident : null;
        var remote = state.DpmsIncident is { Notified: false } ? state.DpmsIncident : null;
        if (outlook is null && remote is null) return;
        nextAlert = DateTimeOffset.UtcNow.AddMinutes(5);
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        timeout.CancelAfter(TimeSpan.FromSeconds(settings.CheckTimeoutSeconds));
        try
        {
            await OutageMail.Send(smtp, outlook, remote, waiting, ConnectorText.Describe, timeout.Token);
            if (outlook is not null) state.OutlookIncident = outlook.ConfirmNotification();
            if (remote is not null) state.DpmsIncident = remote.ConfirmNotification();
            nextAlert = default;
            Write(JournalLevel.Info, "Уведомления", "alert_sent", "SMTP принял уведомление о сбое связи.");
            try { Persist(state); }
            catch (ConnectorException error) { WriteError("Уведомления", error); }
        }
        catch (Exception) when (!cancellation.IsCancellationRequested)
        { Write(JournalLevel.Error, "Уведомления", "alert_failed", "Уведомление не подтверждено. Проверьте SMTP и параметры отправки."); }
    }

    private async Task SyncNow(CancellationToken cancellation)
    {
        if (state.Session is not { } session) return;
        nextSync = DateTimeOffset.UtcNow.AddMinutes(settings.SyncMinutes);
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        deadline.CancelAfter(TimeSpan.FromSeconds(settings.SyncTimeoutSeconds));
        var token = deadline.Token;
        try
        {
            var queue = await OpenOutbox();
            if (dpms.State == LinkState.Unknown)
                ApplyDpms(await ProbeDpms(settings, session, token));
            ScanResult scan;
            try { scan = await CaptureInbox(session, queue, token); }
            catch (ConnectorException error) when (queue.WaitingCount > 0 && error.Code is
                "snapshot_too_large" or "source_changed_during_scan" or "outlook_scan_failed")
            {
                WriteError("Outlook", error);
                if (dpms.State != LinkState.Online) return;
                var observed = await ProbeOutlook(settings, token);
                ApplyOutlook(observed);
                if (!BothOnline || observed.MailboxId is not { } mailbox || mailbox != queue.MailboxId
                    || observed.MailboxLabel is not { } label) return;
                // A failed scan leaves its checkpoint in place, but does not block a previously protected batch.
                scan = new ScanResult(mailbox, label, "cached", [], 0, Truncated: true);
            }
            if (!BothOnline)
            {
                Write(JournalLevel.Warning, "Очередь", "buffering",
                    $"Накопление. Ожидают: {waiting}. Передача приостановлена до подтверждения обеих связей.");
                return;
            }
            await Deliver(queue, session, scan, token);
        }
        catch (OperationCanceledException) when (!cancellation.IsCancellationRequested)
        { Write(JournalLevel.Warning, "Коннектор", "sync_timeout", ConnectorText.Describe("sync_timeout")); }
        finally
        {
            RefreshQueue();
            if (!cancellation.IsCancellationRequested && !exiting) await TryNotify(cancellation);
        }
    }

    private async Task<DurableOutbox> OpenOutbox()
    {
        if (outbox is not null) return outbox;
        var deviceId = state.Session?.DeviceId ?? throw new ConnectorException("not_paired");
        outbox = await Task.Run(() => new DurableOutbox(storage.OutboxRoot, deviceId, ProtectedState.Protect, ProtectedState.Unprotect));
        RefreshQueue();
        return outbox;
    }

    private async Task<ScanResult> CaptureInbox(DeviceSession session, DurableOutbox queue, CancellationToken cancellation)
    {
        var started = DateTimeOffset.UtcNow;
        if (state.CaptureWatermark is null)
        {
            var legacy = state.LastSyncAt;
            state.CaptureWatermark = legacy is not null && legacy <= started ? legacy : started;
            try { Persist(state); } catch { state.CaptureWatermark = null; throw; }
        }
        var since = CaptureWindow.Since(started, settings.HistoryDays, state.CaptureWatermark);
        // A pre-outbox snapshot has no durable capture start. Rebuild it, keeping the original mailbox and ACKs.
        var pending = state.CaptureCycleStartedAt is not null ? state.PendingEntries : null;
        ScanResult scan;
        try
        {
            Write(JournalLevel.Info, "Outlook", "scan_started", "Чтение входящих писем.");
            scan = await outlookWorker.Scan(new ScanOptions(session.IncludeBody, session.IncludeAttachments,
                settings.HistoryDays, Acknowledged: state.Acknowledged, PendingEntries: pending,
                SnapshotMailboxId: state.SnapshotMailboxId, SinceUtc: since), cancellation);
            if (scan.Error is not null) throw new ConnectorException(scan.Error);
        }
        catch (ConnectorException error) when (error.Code is "outlook_unavailable" or "mailbox_identity_unavailable")
        {
            ApplyOutlook(new OutlookProbeResult(false, LinkState.Offline, error.Code));
            throw;
        }
        if (scan.Outlook is not { } source || source.MailboxId != scan.MailboxId)
            throw new ConnectorException("invalid_scan");
        ApplyOutlook(source);
        if (!MatchesMailbox(scan.MailboxId)) throw new ConnectorException("mailbox_mismatch");
        LogScanIssues(scan);

        // Advance the local read checkpoint only after the full page is durable in the spool.
        var captured = await Task.Run(() => queue.Stage(scan, cancellation), cancellation);
        var skipped = Math.Min(5000, state.CycleSkipped + scan.Skipped);
        if (!captured.Full) CommitCapture(scan, started, skipped);
        else Write(JournalLevel.Error, "Очередь", "outbox_full", ConnectorText.Describe("outbox_full"));
        RefreshQueue();
        Write(JournalLevel.Info, "Очередь", "capture_complete",
            $"Добавлено: {captured.Added}. Ожидают: {waiting}. Конфликты: {held}. Пропуски чтения: {skipped}.");
        return scan with { Skipped = skipped, Truncated = scan.Truncated || captured.Full };
    }

    private void CommitCapture(ScanResult scan, DateTimeOffset started, int skipped)
    {
        var previous = (state.CaptureMailboxId, state.CaptureWatermark, state.CaptureCycleStartedAt, state.CaptureCycleHealthy,
            state.PendingEntries, state.SnapshotMailboxId, state.CycleSkipped);
        var healthy = state.CaptureCycleHealthy && mail.State == LinkState.Online && skipped == 0;
        var cycleStart = state.CaptureCycleStartedAt ?? started;
        state.CaptureMailboxId = scan.MailboxId;
        state.PendingEntries = scan.RemainingEntries?.ToList() ?? [];
        if (state.PendingEntries.Count > 0)
        {
            state.CaptureCycleStartedAt = cycleStart;
            state.CaptureCycleHealthy = healthy;
            state.SnapshotMailboxId = scan.MailboxId;
            state.CycleSkipped = skipped;
        }
        else
        {
            if (healthy && !scan.Truncated && cycleStart >= state.CaptureWatermark) state.CaptureWatermark = cycleStart;
            ResetPage();
        }
        try { Persist(state); }
        catch
        {
            (state.CaptureMailboxId, state.CaptureWatermark, state.CaptureCycleStartedAt, state.CaptureCycleHealthy,
                state.PendingEntries, state.SnapshotMailboxId, state.CycleSkipped) = previous;
            throw;
        }
    }

    private void ResetPage()
    {
        state.PendingEntries = [];
        state.SnapshotMailboxId = null;
        state.CycleSkipped = 0;
        state.CaptureCycleStartedAt = null;
        state.CaptureCycleHealthy = true;
    }

    private bool MatchesMailbox(string mailbox)
    {
        if (!ValidHash(mailbox)) return false;
        var expected = state.CaptureMailboxId ?? outbox?.MailboxId ?? state.SnapshotMailboxId;
        if (expected is not null) return expected == mailbox;
        // For old installations, an acknowledged mailbox still identifies the original source.
        return state.Acknowledged.Count == 0 || state.Acknowledged.Keys.Any(key => key.StartsWith(mailbox + ":", StringComparison.Ordinal));
    }

    private static bool ValidHash(string value) => value.Length == 64 && value.All(char.IsAsciiHexDigit);

    private async Task Deliver(DurableOutbox queue, DeviceSession session, ScanResult scan, CancellationToken cancellation)
    {
        using var client = IngestionClient.Create(session, state, Persist);
        var sent = 0;
        var created = 0;
        var updated = 0;
        var conflicts = 0;
        var failed = false;
        // Finish a bounded number of batches per interval; the remaining spool survives exit or a timeout.
        for (var pass = 0; pass < 12 && BothOnline; pass++)
        {
            cancellation.ThrowIfCancellationRequested();
            var entries = await Task.Run(() => queue.ReadBatch(cancellation), cancellation);
            if (entries.Count == 0 && pass != 0) break;
            DeliveryReport? report;
            try
            {
                report = await QueuedDelivery.Send(queue, entries, scan, mail.State, dpms.State, state, client, Persist, cancellation,
                    item => Write(JournalLevel.Warning, "DPMS", "item_version_conflict",
                        ConnectorText.Describe("item_version_conflict"), item.Subject, item.ReceivedAt, item.SourceId));
            }
            catch (Exception error) when (error is not OperationCanceledException)
            {
                var code = ConnectorText.Code(error);
                if (IsDpmsDisconnect(error)) ApplyDpms(new LinkReading(LinkState.Offline, code, DateTimeOffset.UtcNow));
                var single = entries.Count == 1 ? entries[0].Item : null;
                Write(ErrorLevel(code), "DPMS", code, $"Ошибка обработки партии ({entries.Count}): {ConnectorText.Describe(code)}",
                    single?.Subject, single?.ReceivedAt, single?.SourceId);
                failed = true;
                break;
            }
            if (report is null) break;
            sent += report.Sent;
            created += report.Created;
            updated += report.Updated;
            conflicts += report.VersionConflicts;
            if (report.ConflictCheckDeferred || queue.WaitingCount == 0 || entries.Count == 0) break;
        }
        RefreshQueue();
        Write(failed || conflicts > 0 || scan.Skipped > 0 || scan.Truncated || waiting > 0 || held > 0
            ? JournalLevel.Warning : JournalLevel.Info, "DPMS",
            "delivery_finished", $"Передано: {sent}. Новых: {created}. Обновлено: {updated}. Ожидают: {waiting}. Конфликты: {held}.");
    }

    private static bool IsDpmsDisconnect(Exception error) => error is HttpRequestException
        || ConnectorText.Code(error) is "db_unavailable" or "db_tls_failed" or "db_tls_pin_rejected"
            or "db_login_failed" or "db_not_installed" or "db_login_not_provisioned" or "access_denied"
            or "endpoint_unavailable" or "server_unavailable";

    private void LogScanIssues(ScanResult scan)
    {
        foreach (var issue in scan.ItemIssues ?? [])
            Write(issue.Code is "outlook_com" or "outlook_read_failed" ? JournalLevel.Error : JournalLevel.Warning,
                "Outlook", issue.Code, $"{ConnectorText.Stage(issue.Stage)}: {ConnectorText.Describe(issue.Code)}"
                    + (issue.HResult is { } status ? $" (0x{status:X8})" : ""),
                issue.Subject, issue.ReceivedAt, issue.Reference);
        if (scan.Skipped > (scan.ItemIssues?.Count ?? 0))
            Write(JournalLevel.Warning, "Outlook", "scan_skips", $"Всего пропущено при чтении: {scan.Skipped}.");
    }

    private async Task Unlink()
    {
        if (Busy || exiting || Editing || invalidState || state.Session is null) return;
        await RunCommand(async cancellation =>
        {
            var queue = await OpenOutbox();
            cancellation.ThrowIfCancellationRequested();
            var ask = queue.WaitingCount + queue.HeldCount == 0
                ? "Удалить локальную привязку? Уже принятые письма останутся в DPMS."
                : $"В очереди ждут: {queue.WaitingCount}, конфликты: {queue.HeldCount}. Они останутся защищены на этом компьютере, но новая привязка их не отправит. Отвязать устройство?";
            if (MessageBox.Show(this, ask,
                "Отвязать Outlook", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes
                || exiting || cancellation.IsCancellationRequested) return;
            var cleared = settings with { Database = null, ServerUrl = "", Alerts = null };
            var next = new LocalState { HistoryDays = cleared.HistoryDays, Settings = cleared };
            Persist(next);
            state = next;
            settings = cleared;
            outbox = null;
            mail = dpms = new LinkReading(LinkState.Unknown, "check_required");
            profile = null;
            RefreshQueue();
            Write(JournalLevel.Info, "Коннектор", "unlinked", "Локальная привязка удалена.");
        });
    }

    private async Task RunCommand(Func<CancellationToken, Task> work)
    {
        if (Busy || exiting || invalidState) return;
        try { await RunExclusive(async cancellation => { await work(cancellation); return true; }); }
        catch (OperationCanceledException) { }
        catch (Exception error) { if (!exiting) WriteError("Коннектор", error); }
    }

    private Task<T> RunExclusive<T>(Func<CancellationToken, Task<T>> work, CancellationToken parent = default)
    {
        if (Busy || exiting || invalidState) throw new ConnectorException("operation_busy");
        var running = CancellationTokenSource.CreateLinkedTokenSource(parent);
        operation = running;
        RefreshUi();
        var job = Execute();
        activeJob = job;
        return job;

        async Task<T> Execute()
        {
            try { return await work(running.Token); }
            finally { operation = null; running.Dispose(); if (!exiting) RefreshUi(); }
        }
    }

    private void Persist(LocalState value)
    {
        try { storage.Save(value); }
        catch { throw new ConnectorException("local_protection_failed"); }
    }

    private void RefreshQueue()
    {
        waiting = outbox?.WaitingCount ?? 0;
        held = outbox?.HeldCount ?? 0;
        queuePreview = outbox?.Preview() ?? [];
        if (logWindow is { IsDisposed: false } window) window.UpdateQueue(queuePreview, waiting, held);
        RefreshUi();
    }

    private void RefreshUi()
    {
        var enabled = !exiting && !invalidState && !Editing;
        connection.Enabled = !exiting && !invalidState && !Busy;
        sync.Enabled = enabled && !Busy && state.Session is not null;
        unlink.Enabled = enabled && !Busy && state.Session is not null;
        start.Enabled = enabled && (!Busy || state.AutoSync);
        logButton.Enabled = exitButton.Enabled = !exiting;
        var text = state.AutoSync ? "Пауза" : "Запустить";
        if (start.Text != text)
        {
            start.Text = start.AccessibleName = text;
            var old = start.Image;
            start.Image = IconImage(state.AutoSync ? "\uE769" : "\uE768");
            old?.Dispose();
            tooltips.SetToolTip(start, text);
        }
        tooltips.SetToolTip(sync, $"Синхронизировать. Ожидают: {waiting}. Конфликты: {held}.");
        SetBadge(mailBadge, "Почта", mail);
        SetBadge(dpmsBadge, "DPMS", dpms);
        tray.Text = !state.AutoSync ? "DPMS Outlook: пауза" : BothOnline ? "DPMS Outlook: синхронизация" : "DPMS Outlook: накопление";
    }

    private void SetBadge(Label label, string title, LinkReading value)
    {
        label.Text = (value.State == LinkState.Online ? "\u2713 " : value.State == LinkState.Offline ? "\u00D7 " : "? ") + title;
        label.ForeColor = value.State switch { LinkState.Online => Color.DarkGreen, LinkState.Offline => Color.Firebrick, _ => Color.DarkGoldenrod };
        label.AccessibleName = title + ": " + (value.State == LinkState.Online ? "доступно" : ConnectorText.Describe(value.Code));
        tooltips.SetToolTip(label, label.AccessibleName + (value.CheckedAt is { } at ? $" ({at.ToLocalTime():g})" : ""));
    }

    private void WriteError(string stage, Exception error)
    {
        var code = ConnectorText.Code(error);
        Write(ErrorLevel(code), stage, code, ConnectorText.Describe(code));
    }

    private static JournalLevel ErrorLevel(string code) => code is "db_pending" or "rate_limited" or "db_queue_full"
        ? JournalLevel.Warning : JournalLevel.Error;

    private void Write(JournalLevel level, string stage, string code, string message,
        string? subject = null, DateTimeOffset? received = null, string? reference = null)
    {
        if (activity.Count == MaxLogEvents) activity.Dequeue();
        if (code.Length > 64 || !code.All(c => char.IsAsciiLetterOrDigit(c) || c == '_')) code = "operation_failed";
        var id = reference is null ? null : new string(reference.Where(char.IsAsciiHexDigit).Take(10).ToArray());
        activity.Enqueue(new JournalEvent(DateTimeOffset.Now, level, stage, code, message, JournalEvent.LocalSubject(subject), received, id));
        if (logWindow is { IsDisposed: false } window) window.UpdateLog(activity);
    }

    private void ShowLog()
    {
        if (exiting) return;
        if (logWindow is { IsDisposed: false } open) { open.Activate(); return; }
        logWindow = new LogForm();
        logWindow.UpdateLog(activity);
        logWindow.UpdateQueue(queuePreview, waiting, held);
        logWindow.Show(this);
    }

    private void ShowWindow() { if (!exiting) { Show(); WindowState = FormWindowState.Normal; Activate(); } }

    internal void RequestReplacement()
    {
        try { BeginInvoke((Action)(async () => await ExitApp(replacing: true))); }
        catch (InvalidOperationException) when (IsDisposed || !IsHandleCreated) { }
    }

    private void Cancel()
    {
        try { operation?.Cancel(); }
        catch (AggregateException) { Write(JournalLevel.Warning, "Коннектор", "cancel_failed", "Ожидаю завершения операции."); }
    }

    private async Task ExitApp(bool replacing = false)
    {
        if (exiting) return;
        exiting = true;
        scheduler.Stop();
        RefreshUi();
        Write(JournalLevel.Info, "Коннектор", "stopping", replacing ? "Выход для запуска новой копии." : "Завершение работы.");
        Cancel();
        try { if (activeJob is { } job) await job; } catch { }
        try { await outlookWorker.Stop(); }
        catch (ConnectorException error)
        {
            exiting = false;
            WriteError("Outlook", error);
            RefreshUi();
            scheduler.Start();
            if (replacing) ShowWindow();
            return;
        }
        try { AttachmentStaging.Cleanup(); }
        catch (ConnectorException error) { WriteError("Outlook", error); }
        readyToClose = true;
        tray.Visible = false;
        Close();
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        if (!readyToClose && e.CloseReason == CloseReason.UserClosing)
        {
            e.Cancel = true;
            if (!exiting) Hide();
        }
        else
        {
            if (!readyToClose)
            {
                exiting = true;
                scheduler.Stop();
                Cancel();
                outlookWorker.StopOnShutdown();
            }
            tray.Dispose();
            scheduler.Dispose();
            tooltips.Dispose();
            foreach (var button in new[] { connection, start, sync, unlink, logButton, exitButton }) button.Image?.Dispose();
        }
        base.OnFormClosing(e);
    }
}
