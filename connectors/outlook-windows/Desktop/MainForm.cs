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
    private readonly ComboBox transport = new() { Dock = DockStyle.Fill, DropDownStyle = ComboBoxStyle.DropDownList };
    private readonly TextBox server = new() { Dock = DockStyle.Fill, PlaceholderText = "https://", MaxLength = 500 };
    private readonly TextBox databaseHost = new() { Dock = DockStyle.Fill, MaxLength = 253 };
    private readonly NumericUpDown databasePort = new() { Minimum = 1, Maximum = 65535, Value = 58923, Width = 100 };
    private readonly TextBox databaseName = new() { Dock = DockStyle.Fill };
    private readonly TextBox databaseSchema = new() { Dock = DockStyle.Fill };
    private readonly TextBox databaseUsername = new() { Dock = DockStyle.Fill };
    private readonly TextBox databasePassword = new() { Dock = DockStyle.Fill, UseSystemPasswordChar = true };
    private readonly TextBox databaseCertificate = new() { Dock = DockStyle.Fill };
    private readonly TextBox databaseCertificatePin = new() { Dock = DockStyle.Fill, PlaceholderText = "Необязательно" };
    private readonly TextBox deviceName = new() { Dock = DockStyle.Fill, Text = Environment.MachineName, MaxLength = 100 };
    private readonly Button selectCertificate = new() { Text = "...", AutoSize = true, AccessibleName = "Выбрать сертификат CA" };
    private readonly ToolTip tooltips = new();
    private readonly TableLayoutPanel httpsInputs = CreateInputs();
    private readonly TableLayoutPanel databaseInputs = CreateInputs();
    private readonly TableLayoutPanel deviceInputs = CreateInputs();
    private readonly TextBox code = new() { Dock = DockStyle.Fill, UseSystemPasswordChar = true, MaxLength = 100 };
    private readonly Button checkConnection = new() { Text = "Проверить соединение", AutoSize = true };
    private readonly Button pair = new() { Text = "Подключить", AutoSize = true };
    private readonly Button start = new() { Text = "Запустить", AutoSize = true };
    private readonly Button sync = new() { Text = "Синхронизировать", AutoSize = true };
    private readonly Button unlink = new() { Text = "Отвязать", AutoSize = true };
    private readonly NumericUpDown days = new() { Minimum = 1, Maximum = 90, Value = 30, Width = 90 };
    private readonly CheckBox autorun = new() { Text = "Запускать при входе в Windows", AutoSize = true };
    private readonly Label account = new() { AutoSize = true };
    private readonly Label status = new() { Text = "Не подключено", AutoSize = true };
    private readonly Label details = new() { AutoSize = true };
    private readonly Label last = new() { AutoSize = true };
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
        SuspendLayout();
        Text = "DPMS Outlook";
        Icon = SystemIcons.Application;
        Font = new Font("Segoe UI", 10);
        AutoScaleDimensions = new SizeF(96, 96);
        AutoScaleMode = AutoScaleMode.Dpi;
        ClientSize = new Size(720, 720);
        MinimumSize = new Size(480, 320);
        StartPosition = FormStartPosition.CenterScreen;
        transport.Items.AddRange(["PostgreSQL", "HTTPS"]);
        transport.SelectedIndex = 0;
        BuildLayout();
        transport.SelectedIndexChanged += (_, _) => RefreshTransport();
        selectCertificate.Click += (_, _) => SelectCertificate();
        tooltips.SetToolTip(selectCertificate, "Выбрать сертификат CA");
        tooltips.SetToolTip(databaseCertificatePin, "Только SHA-256 сертификата сервера, подтверждённый администратором. Вводится вместо CA.");
        var menu = new ContextMenuStrip();
        menu.Items.Add("Открыть", null, (_, _) => ShowWindow());
        menu.Items.Add("Синхронизировать", null, async (_, _) => await SyncNow());
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("Выход", null, async (_, _) => await ExitApp());
        tray.ContextMenuStrip = menu;
        tray.DoubleClick += (_, _) => ShowWindow();
        checkConnection.Click += async (_, _) => await CheckDatabaseConnection();
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
            LoadConnectionFields();
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
            var area = Screen.FromControl(this).WorkingArea;
            if (Width > area.Width || Height > area.Height)
            {
                var width = Math.Min(Width, area.Width);
                var height = Math.Min(Height, area.Height);
                Bounds = new Rectangle(area.Left + (area.Width - width) / 2,
                    area.Top + (area.Height - height) / 2, width, height);
            }
            if (minimized && !invalidState && state.Session is not null) Hide();
            timer.Start();
            if (state.AutoSync && !invalidState) await SyncNow();
        };
        ResumeLayout(performLayout: true);
    }

    private void BuildLayout()
    {
        var viewport = new Panel { Dock = DockStyle.Fill, AutoScroll = true };
        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Top, Padding = new Padding(24), ColumnCount = 1, RowCount = 0,
            AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink,
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
        var connection = CreateInputs();
        AddInput(connection, "Подключение", transport);
        Row(connection);
        AddInput(httpsInputs, "Адрес приёмника", server);
        AddInput(httpsInputs, "Код подключения", code);
        Row(httpsInputs);
        AddInput(databaseInputs, "Узел БД", databaseHost);
        AddInput(databaseInputs, "Порт", databasePort);
        AddInput(databaseInputs, "База данных", databaseName);
        AddInput(databaseInputs, "Схема", databaseSchema);
        AddInput(databaseInputs, "Пользователь БД", databaseUsername);
        AddInput(databaseInputs, "Пароль БД", databasePassword);
        var certificate = new TableLayoutPanel
        {
            ColumnCount = 2, RowCount = 1, Dock = DockStyle.Top, AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink, Margin = Padding.Empty,
        };
        certificate.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        certificate.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        certificate.Controls.Add(databaseCertificate, 0, 0);
        certificate.Controls.Add(selectCertificate, 1, 0);
        databaseCertificate.PlaceholderText = "Необязательно";
        AddInput(databaseInputs, "Сертификат CA", certificate);
        AddInput(databaseInputs, "SHA-256 сервера", databaseCertificatePin);
        Row(databaseInputs);
        AddInput(deviceInputs, "Имя устройства", deviceName);
        Row(deviceInputs);
        var inputs = CreateInputs();
        AddInput(inputs, "Период, дней", days);
        Row(inputs);
        var commands = new FlowLayoutPanel
        {
            AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink,
            Dock = DockStyle.Top, WrapContents = true,
        };
        foreach (var button in new[] { checkConnection, pair, start, sync, unlink })
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
        layout.SizeChanged += (_, _) =>
        {
            var width = Math.Max(1, layout.ClientSize.Width - layout.Padding.Horizontal);
            foreach (var label in new[] { account, status, details, last })
                label.MaximumSize = new Size(width, 0);
            commands.MaximumSize = new Size(width, 0);
        };
        viewport.Controls.Add(layout);
        Controls.Add(viewport);
        RefreshTransport();
    }

    private static TableLayoutPanel CreateInputs()
    {
        var inputs = new TableLayoutPanel
        {
            ColumnCount = 2, RowCount = 0, Dock = DockStyle.Top,
            AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink,
        };
        inputs.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 160));
        inputs.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        return inputs;
    }

    private static void AddInput(TableLayoutPanel inputs, string text, Control control)
    {
        var row = inputs.RowCount++;
        inputs.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        inputs.Controls.Add(new Label
        {
            Text = text, AutoSize = true, Padding = new Padding(0, 5, 0, 0),
            Anchor = AnchorStyles.Left | AnchorStyles.Top,
        }, 0, row);
        inputs.Controls.Add(control, 1, row);
    }

    private ConnectorTransport SelectedTransport => transport.SelectedIndex == 0
        ? ConnectorTransport.PostgreSql : ConnectorTransport.Https;

    private void RefreshTransport()
    {
        var database = SelectedTransport == ConnectorTransport.PostgreSql;
        databaseInputs.Visible = database;
        deviceInputs.Visible = database && state.Session is null;
        httpsInputs.Visible = !database;
        checkConnection.Visible = database && state.Session is null;
        pair.Text = database && state.Session is null ? "Подключить и начать импорт" : "Подключить";
    }

    private void LoadConnectionFields()
    {
        var session = state.Session;
        if (session is not null && session.Transport is not (ConnectorTransport.Https or ConnectorTransport.PostgreSql))
            throw new ConnectorException("local_state_invalid");
        var settings = session?.Transport == ConnectorTransport.PostgreSql
            ? session.Database ?? throw new ConnectorException("local_state_invalid") : null;
        settings?.Validate();
        transport.SelectedIndex = session?.Transport == ConnectorTransport.Https ? 1 : 0;
        server.Text = session?.ServerUrl ?? "";
        databaseHost.Text = settings?.Host ?? "";
        databasePort.Value = settings?.Port ?? 58923;
        databaseName.Text = settings?.Database ?? "";
        databaseSchema.Text = settings?.Schema ?? "";
        databaseUsername.Text = settings?.Username ?? "";
        databasePassword.Text = settings?.Password ?? "";
        databaseCertificate.Text = settings?.RootCertificate ?? "";
        databaseCertificatePin.Text = settings?.ServerCertificateSha256 ?? "";
        deviceName.Text = Environment.MachineName;
    }

    private PostgresSettings ReadDatabaseSettings()
    {
        var settings = new PostgresSettings(databaseHost.Text.Trim(), (int)databasePort.Value,
            databaseName.Text.Trim(), databaseSchema.Text.Trim(), databaseUsername.Text.Trim(),
            databasePassword.Text,
            RootCertificate: string.IsNullOrWhiteSpace(databaseCertificate.Text) ? null : databaseCertificate.Text.Trim(),
            ServerCertificateSha256: string.IsNullOrWhiteSpace(databaseCertificatePin.Text) ? null : databaseCertificatePin.Text.Trim());
        settings.Validate();
        return settings;
    }

    private void SelectCertificate()
    {
        if (busy || invalidState || state.Session is not null) return;
        try
        {
            using var picker = new OpenFileDialog
            {
                Title = "Сертификат центра сертификации",
                Filter = "Сертификаты CA (*.pem;*.crt;*.cer)|*.pem;*.crt;*.cer|Все файлы (*.*)|*.*",
                CheckFileExists = true, Multiselect = false, RestoreDirectory = true, AddToRecent = false,
            };
            if (picker.ShowDialog(this) == DialogResult.OK) databaseCertificate.Text = picker.FileName;
        }
        catch { status.Text = "Не удалось выбрать сертификат CA."; }
    }

    private async Task CheckDatabaseConnection()
    {
        if (busy || invalidState || exiting || state.Session is not null || SelectedTransport != ConnectorTransport.PostgreSql) return;
        try
        {
            var settings = ReadDatabaseSettings();
            SetBusy(true);
            operation = new CancellationTokenSource();
            status.Text = "Проверка соединения...";
            using var client = new PostgresClient(settings);
            await client.CheckConnection(operation.Token);
            if (!exiting) status.Text = "Соединение с БД установлено. Приёмник DPMS отвечает. Импорт не запущен.";
        }
        catch (Exception error) { ShowError(error); }
        finally
        {
            operation?.Dispose(); operation = null;
            SetBusy(false);
        }
    }

    private async Task Pair()
    {
        if (busy || invalidState || exiting || state.Session is not null) return;
        var startDatabaseSync = false;
        try
        {
            var selectedTransport = SelectedTransport;
            var database = selectedTransport == ConnectorTransport.PostgreSql ? ReadDatabaseSettings() : null;
            var serverUrl = selectedTransport == ConnectorTransport.Https ? Protocol.Server(server.Text).AbsoluteUri : "";
            var value = database is not null ? deviceName.Text.Trim() : code.Text.Trim();
            if (database is not null)
            {
                if (value.Length is < 1 or > 100 || value.Any(char.IsControl))
                    throw new ConnectorException("invalid_device_name");
            }
            else if (value.Length != 43 || value.Any(c => !(char.IsAsciiLetterOrDigit(c) || c is '_' or '-')))
                throw new ConnectorException("invalid_pairing_code");
            SetBusy(true);
            operation = new CancellationTokenSource();
            status.Text = "Подключение...";
            PairResult result;
            if (database is not null)
            {
                using var client = new PostgresClient(database);
                result = await client.Connect(value, operation.Token);
            }
            else
            {
                using var client = new DpmsClient(serverUrl);
                result = await client.Pair(value, operation.Token);
            }
            var next = new LocalState
            {
                HistoryDays = (int)days.Value,
                AutoSync = selectedTransport == ConnectorTransport.PostgreSql,
                Session = new DeviceSession(serverUrl, result.DeviceId, result.DeviceSecret,
                    result.OwnerName, result.IncludeBody, result.IncludeAttachments,
                    Transport: selectedTransport, Database: database),
            };
            // The explicit database connect action starts import only after protected persistence succeeds.
            storage.Save(next);
            state = next;
            startDatabaseSync = next.AutoSync;
            status.Text = next.AutoSync ? "Подключено. Синхронизация включена." : "Подключено. Синхронизация на паузе.";
        }
        catch (Exception error) { ShowError(error); }
        finally
        {
            code.Clear();
            operation?.Dispose(); operation = null;
            SetBusy(false);
        }
        if (startDatabaseSync && state.AutoSync && !exiting) await SyncNow();
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
            using var client = IngestionClient.Create(session, state, storage.Save);
            status.Text = "Чтение Outlook...";
            var scan = await Scan(new ScanOptions(session.IncludeBody, session.IncludeAttachments,
                state.HistoryDays, Acknowledged: state.Acknowledged, PendingEntries: state.PendingEntries,
                SnapshotMailboxId: state.SnapshotMailboxId), operation.Token);
            if (scan.Error is not null) throw new ConnectorException(scan.Error);
            status.Text = "Передача в DPMS...";
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
            LoadConnectionFields();
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
        checkConnection.Enabled = pair.Enabled;
        transport.Enabled = httpsInputs.Enabled = databaseInputs.Enabled = deviceInputs.Enabled = pair.Enabled;
        RefreshTransport();
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
            ConnectorException { Code: "pair_uncertain" } when SelectedTransport == ConnectorTransport.PostgreSql
                => ErrorText("connect_uncertain"),
            ConnectorException known => ErrorText(known.Code),
            OperationCanceledException => state.AutoSync ? "Нет ответа. Повтор при следующей синхронизации." : "На паузе",
            HttpRequestException => "Нет соединения с приёмником. Доставка будет повторена.",
            ArgumentException => SelectedTransport == ConnectorTransport.PostgreSql
                ? ErrorText("db_settings_invalid") : "Нужен HTTPS-адрес без пути, параметров и пароля.",
            _ => SelectedTransport == ConnectorTransport.PostgreSql
                ? "Операция не завершена. Проверьте параметры БД и доступ устройства."
                : "Операция не завершена. Повторите попытку; при сбое подключения создайте новый код в DPMS.",
        };
    }

    private static string ErrorText(string code) => code switch
    {
        "invalid_pairing_code" => "Некорректный код подключения.",
        "invalid_device_name" => "Укажите имя устройства от 1 до 100 символов без управляющих символов.",
        "connect_uncertain" => "Результат подключения неизвестен. Перед повтором попросите администратора проверить привязку устройства.",
        "db_settings_invalid" => "Некорректные параметры БД. Проверьте узел, порт, базу, схему, пользователя, пароль и сертификат CA.",
        "db_unavailable" => "Нет соединения с БД. Проверьте доступность сервера и параметры подключения.",
        "db_tls_failed" => "Не удалось установить защищённое соединение с БД. Проверьте соответствие имени и CA либо используйте подтверждённый SHA-256 сервера.",
        "db_tls_pin_invalid" => "Некорректный SHA-256: нужны 64 шестнадцатеричных символа, можно с двоеточиями между парами.",
        "db_tls_pin_conflict" => "Заполните либо «Сертификат CA», либо «SHA-256 сервера», но не оба поля.",
        "db_tls_pin_rejected" => "Сертификат БД не совпал с SHA-256 или сейчас недействителен. Сверьте сертификат с администратором.",
        "db_tls_configuration" => "Заблокированы неявные настройки TLS PostgreSQL (PGSSL* или локальные сертификаты). Запустите коннектор без этих настроек.",
        "db_login_failed" => "БД отклонила вход. Проверьте пользователя, пароль и права доступа.",
        "db_login_not_provisioned" => "Вход в БД выполнен, но учётная запись не связана с пользователем DPMS. Попросите администратора настроить это соответствие на сервере. Менять пароль не нужно.",
        "db_not_installed" => "Приёмник DPMS не установлен в указанной базе и схеме. Обратитесь к администратору.",
        "db_pending" => "Обработка в БД продолжается. Доставка будет повторена без создания дубликатов.",
        "db_queue_full" => "Очередь приёмника БД заполнена. Доставка будет повторена.",
        "pair_uncertain" => "Результат подключения неизвестен. Проверьте устройства в DPMS; перед повтором отзовите незавершённое подключение и создайте новый код.",
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
            tray.Dispose(); timer.Dispose(); tooltips.Dispose();
        }
        base.OnFormClosing(e);
    }
}
