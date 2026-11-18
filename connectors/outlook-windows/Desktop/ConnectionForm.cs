using Dpms.OutlookConnector;

namespace Dpms.OutlookConnector.Desktop;

internal sealed record ConnectionCheckSummary(string Outlook, string Dpms);

internal sealed class ConnectionForm : Form
{
    private const int DefaultDatabasePort = 58923;
    private const int DefaultSmtpPort = 587;
    private readonly ConnectorSettings initial;
    private readonly bool linked;
    private readonly Func<ConnectorSettings, CancellationToken, Task<ConnectionCheckSummary>> check;
    private readonly Func<ConnectorSettings, string, CancellationToken, Task> pairHttps;
    private readonly Action<ConnectorSettings> save;
    private readonly Func<Exception, string> describeError;

    private readonly TabControl tabs = new() { Dock = DockStyle.Fill };
    private readonly TabPage connectionTab = new("Подключение");
    private readonly TabPage scheduleTab = new("Расписание");
    private readonly TabPage alertsTab = new("Уведомления");
    private readonly ToolTip tooltips = new();
    private readonly Label outlookStatus = SummaryLabel();
    private readonly Label dpmsStatus = SummaryLabel();
    private readonly Label feedback = SummaryLabel(46);
    private readonly ComboBox transport = new() { Dock = DockStyle.Fill, DropDownStyle = ComboBoxStyle.DropDownList };
    private readonly TableLayoutPanel postgresInputs = Fields();
    private readonly TableLayoutPanel httpsInputs = Fields();
    private readonly TableLayoutPanel pairingInputs = Fields();
    private readonly TextBox server = Input(500, placeholder: "https://");
    private readonly TextBox pairingCode = Input(100, masked: true);
    private readonly TextBox host = Input(253);
    private readonly NumericUpDown port = Number(1, 65535, DefaultDatabasePort);
    private readonly TextBox database = Input(63);
    private readonly TextBox schema = Input(63);
    private readonly TextBox login = Input(63);
    private readonly TextBox password = Input(masked: true);
    private readonly TextBox ca = Input(placeholder: "Необязательно");
    private readonly TextBox pin = Input(95, placeholder: "Необязательно");
    private readonly TextBox deviceName = Input(100);
    private readonly Button chooseCa = new() { Text = "...", AutoSize = true, AccessibleName = "Выбрать сертификат CA" };

    private readonly NumericUpDown historyDays = Number(1, 90, 30);
    private readonly NumericUpDown syncMinutes = Number(1, 1440, 10);
    private readonly NumericUpDown syncTimeout = Number(10, 1800, 180);
    private readonly NumericUpDown checkMinutes = Number(1, 1440, 60);
    private readonly NumericUpDown checkTimeout = Number(2, 120, 15);
    private readonly CheckBox autorun = new() { Text = "Запускать при входе в Windows", AutoSize = true };

    private readonly CheckBox alertsEnabled = new() { Text = "Отправлять уведомления по почте", AutoSize = true };
    private readonly TableLayoutPanel smtpInputs = Fields();
    private readonly TextBox smtpHost = Input(253);
    private readonly NumericUpDown smtpPort = Number(1, 65535, DefaultSmtpPort);
    private readonly TextBox smtpFrom = Input(254);
    private readonly TextBox smtpTo = Input(254);
    private readonly TextBox smtpLogin = Input(254, placeholder: "Необязательно");
    private readonly TextBox smtpPassword = Input(1024, masked: true);

    private readonly Button testButton = new() { Text = "Проверить Outlook и DPMS", AutoSize = true };
    private readonly Button pairButton = new() { Text = "Привязать HTTPS", AutoSize = true };
    private readonly Button saveButton = new() { Text = "Сохранить", AutoSize = true };
    private readonly Button closeButton = new() { Text = "Закрыть", AutoSize = true };
    private CancellationTokenSource? operation;
    private Task? cancellationWork;
    private bool pairing;
    private bool closeRequested;

    public ConnectionForm(ConnectorSettings settings, bool linked, string outlookSummary,
        Func<ConnectorSettings, CancellationToken, Task<ConnectionCheckSummary>> check,
        Func<ConnectorSettings, string, CancellationToken, Task> pairHttps,
        Action<ConnectorSettings> save, Func<Exception, string> describeError)
    {
        initial = settings;
        this.linked = linked;
        this.check = check;
        this.pairHttps = pairHttps;
        this.save = save;
        this.describeError = describeError;

        SuspendLayout();
        Text = "Настройки DPMS Outlook";
        Icon = SystemIcons.Application;
        Font = new Font("Segoe UI", 10);
        AutoScaleDimensions = new SizeF(96, 96);
        AutoScaleMode = AutoScaleMode.Dpi;
        ClientSize = new Size(580, 470);
        MinimumSize = new Size(440, 320);
        StartPosition = FormStartPosition.CenterParent;
        ShowInTaskbar = false;
        MaximizeBox = false;
        MinimizeBox = false;
        BuildLayout(outlookSummary);
        LoadSettings(settings);
        SetTooltips();

        transport.SelectedIndexChanged += (_, _) => { RefreshControls(); ResetDpmsStatus(); };
        foreach (var field in new[] { server, host, database, schema, login, password, ca, pin })
            field.TextChanged += (_, _) => ResetDpmsStatus();
        port.ValueChanged += (_, _) => ResetDpmsStatus();
        alertsEnabled.CheckedChanged += (_, _) => RefreshControls();
        chooseCa.Click += (_, _) => ChooseCa();
        testButton.Click += async (_, _) => await RunAsync(linkDevice: false);
        pairButton.Click += async (_, _) => await RunAsync(linkDevice: true);
        saveButton.Click += (_, _) => SaveSettings();
        closeButton.Click += (_, _) => Close();
        SetSummary(outlookStatus, "Не проверено");
        ResetDpmsStatus();
        RefreshControls();
        ResumeLayout(performLayout: true);
    }

    private void BuildLayout(string outlookSummary)
    {
        transport.Items.AddRange(["PostgreSQL", "HTTPS"]);
        var connection = PageLayout(connectionTab);
        var overview = Fields();
        var account = SummaryLabel();
        SetSummary(account, string.IsNullOrWhiteSpace(outlookSummary) ? "Не определена" : outlookSummary);
        AddField(overview, "Учётная запись Outlook", account);
        AddField(overview, "Проверка Outlook", outlookStatus);
        AddField(overview, "Проверка DPMS", dpmsStatus);
        AddField(overview, "Тип подключения", transport);
        AddRow(connection, overview);

        AddField(postgresInputs, "Узел БД", host);
        AddField(postgresInputs, "Порт", port);
        AddField(postgresInputs, "База данных", database);
        AddField(postgresInputs, "Схема", schema);
        AddField(postgresInputs, "Пользователь БД", login);
        AddField(postgresInputs, "Пароль БД", password);
        var certificate = Table(2);
        certificate.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        certificate.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        certificate.Controls.Add(ca, 0, 0);
        certificate.Controls.Add(chooseCa, 1, 0);
        ca.AccessibleName = "Сертификат CA";
        AddField(postgresInputs, "Сертификат CA", certificate);
        AddField(postgresInputs, "SHA-256 сервера", pin);
        AddField(postgresInputs, "Имя устройства", deviceName);
        AddRow(connection, postgresInputs);
        AddField(httpsInputs, "Адрес приёмника", server);
        AddRow(connection, httpsInputs);
        AddField(pairingInputs, "Одноразовый код", pairingCode);
        AddRow(connection, pairingInputs);

        var schedule = PageLayout(scheduleTab);
        var timings = Fields();
        AddField(timings, "Глубина импорта, дней", historyDays);
        AddField(timings, "Интервал импорта, мин", syncMinutes);
        AddField(timings, "Таймаут синхронизации, с", syncTimeout);
        AddField(timings, "Интервал проверки, мин", checkMinutes);
        AddField(timings, "Таймаут проверки, с", checkTimeout);
        AddRow(schedule, timings);
        AddRow(schedule, autorun);

        var notifications = PageLayout(alertsTab);
        AddRow(notifications, alertsEnabled);
        AddField(smtpInputs, "SMTP-сервер", smtpHost);
        AddField(smtpInputs, "Порт STARTTLS", smtpPort);
        AddField(smtpInputs, "Отправитель", smtpFrom);
        AddField(smtpInputs, "Получатель", smtpTo);
        AddField(smtpInputs, "Имя пользователя", smtpLogin);
        AddField(smtpInputs, "Пароль SMTP", smtpPassword);
        AddRow(notifications, smtpInputs);

        var actions = new FlowLayoutPanel
        {
            Dock = DockStyle.Top, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink,
            WrapContents = true, FlowDirection = FlowDirection.RightToLeft, Margin = Padding.Empty,
        };
        foreach (var button in new[] { saveButton, closeButton, pairButton, testButton })
        {
            button.Padding = new Padding(8, 4, 8, 4);
            button.Margin = new Padding(6, 4, 0, 0);
            actions.Controls.Add(button);
        }
        var footer = Table(1);
        footer.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        feedback.AccessibleName = "Результат операции";
        AddRow(footer, feedback);
        AddRow(footer, actions);
        var shell = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2, Padding = new Padding(10) };
        shell.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        shell.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        shell.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        shell.ClientSizeChanged += (_, _) =>
        {
            // Constrain the preferred width so the auto-sized footer makes room for a wrapped row.
            var width = Math.Max(1, shell.ClientSize.Width - shell.Padding.Horizontal);
            if (actions.MaximumSize.Width != width) actions.MaximumSize = new Size(width, 0);
        };
        shell.Controls.Add(tabs, 0, 0);
        shell.Controls.Add(footer, 0, 1);
        Controls.Add(shell);
    }

    private void LoadSettings(ConnectorSettings settings)
    {
        transport.SelectedIndex = settings.Transport == ConnectorTransport.Https ? 1 : 0;
        server.Text = settings.ServerUrl;
        host.Text = settings.Database?.Host ?? "";
        LoadNumber(port, settings.Database?.Port ?? DefaultDatabasePort);
        database.Text = settings.Database?.Database ?? "";
        schema.Text = settings.Database?.Schema ?? "";
        login.Text = settings.Database?.Username ?? "";
        password.Text = settings.Database?.Password ?? "";
        ca.Text = settings.Database?.RootCertificate ?? "";
        pin.Text = settings.Database?.ServerCertificateSha256 ?? "";
        deviceName.Text = string.IsNullOrWhiteSpace(settings.DeviceName) ? Environment.MachineName : settings.DeviceName;
        LoadNumber(historyDays, settings.HistoryDays);
        LoadNumber(syncMinutes, settings.SyncMinutes);
        LoadNumber(syncTimeout, settings.SyncTimeoutSeconds);
        LoadNumber(checkMinutes, settings.CheckMinutes);
        LoadNumber(checkTimeout, settings.CheckTimeoutSeconds);
        autorun.Checked = settings.Autorun;
        alertsEnabled.Checked = settings.Alerts is not null;
        smtpHost.Text = settings.Alerts?.Host ?? "";
        LoadNumber(smtpPort, settings.Alerts?.Port ?? DefaultSmtpPort);
        smtpFrom.Text = settings.Alerts?.From ?? "";
        smtpTo.Text = settings.Alerts?.To ?? "";
        smtpLogin.Text = settings.Alerts?.Username ?? "";
        smtpPassword.Text = settings.Alerts?.Password ?? "";
    }

    private void SetTooltips()
    {
        tooltips.SetToolTip(chooseCa, "Выбрать сертификат CA");
        tooltips.SetToolTip(pin, "SHA-256 сертификата сервера, подтверждённый администратором. Вводится вместо CA.");
        tooltips.SetToolTip(testButton, "Проверить Outlook и DPMS без привязки и сохранения настроек");
        tooltips.SetToolTip(smtpHost, "Имя SMTP-сервера, согласованное с администратором");
        tooltips.SetToolTip(smtpPort, "Порт STARTTLS, обычно 587. Порт 465 не поддерживается.");
        tooltips.SetToolTip(smtpFrom, "Один почтовый адрес без имени отправителя");
        tooltips.SetToolTip(smtpTo, "Один почтовый адрес без имени получателя");
        tooltips.SetToolTip(smtpLogin, "Если сервер требует вход, укажите имя пользователя и пароль");
        if (linked)
        {
            const string locked = "Адрес привязан к этому устройству. Отвяжите устройство для смены адреса.";
            foreach (var field in new Control[] { transport, server, host, port, database, schema, login })
                tooltips.SetToolTip(field, locked);
        }
    }

    private ConnectorTransport SelectedTransport => linked ? initial.Transport
        : transport.SelectedIndex == 1 ? ConnectorTransport.Https : ConnectorTransport.PostgreSql;

    private void RefreshControls()
    {
        var postgres = SelectedTransport == ConnectorTransport.PostgreSql;
        var canPair = !linked && !postgres;
        var busy = operation is not null;
        postgresInputs.Visible = postgres;
        httpsInputs.Visible = !postgres;
        pairingInputs.Visible = pairButton.Visible = canPair;
        if (!canPair) pairingCode.Clear();
        foreach (var field in new[] { host, database, schema, login, server, deviceName })
            field.ReadOnly = linked;
        transport.Enabled = !linked && !busy;
        port.Enabled = !linked;
        postgresInputs.Enabled = httpsInputs.Enabled = pairingInputs.Enabled = !busy;
        scheduleTab.Enabled = alertsTab.Enabled = !busy;
        smtpInputs.Enabled = alertsEnabled.Checked && !busy;
        testButton.Enabled = saveButton.Enabled = pairButton.Enabled = !busy;
        closeButton.Enabled = !closeRequested;
    }

    private ConnectorSettings Draft() => initial with
    {
        Transport = SelectedTransport,
        Database = SelectedTransport == ConnectorTransport.PostgreSql ? DraftDatabase() : null,
        ServerUrl = SelectedTransport == ConnectorTransport.Https
            ? (linked ? initial.ServerUrl : server.Text.Trim()) : "",
        DeviceName = linked ? initial.DeviceName
            : string.IsNullOrWhiteSpace(deviceName.Text) ? Environment.MachineName : deviceName.Text.Trim(),
        HistoryDays = (int)historyDays.Value,
        SyncMinutes = (int)syncMinutes.Value,
        SyncTimeoutSeconds = (int)syncTimeout.Value,
        CheckMinutes = (int)checkMinutes.Value,
        CheckTimeoutSeconds = (int)checkTimeout.Value,
        Autorun = autorun.Checked,
        Alerts = alertsEnabled.Checked ? new SmtpSettings(smtpHost.Text.Trim(), (int)smtpPort.Value,
            smtpLogin.Text, smtpPassword.Text, smtpFrom.Text.Trim(), smtpTo.Text.Trim()) : null,
    };

    private PostgresSettings? DraftDatabase()
    {
        var root = string.IsNullOrWhiteSpace(ca.Text) ? null : ca.Text.Trim();
        var fingerprint = string.IsNullOrWhiteSpace(pin.Text) ? null : pin.Text.Trim();
        if (linked)
            return initial.Database is { } bound
                ? bound with { Password = password.Text, RootCertificate = root, ServerCertificateSha256 = fingerprint }
                : null;

        if (port.Value == DefaultDatabasePort && password.TextLength == 0 && root is null && fingerprint is null
            && new[] { host, database, schema, login }.All(field => string.IsNullOrWhiteSpace(field.Text)))
            return null;
        return new PostgresSettings(host.Text.Trim(), (int)port.Value, database.Text.Trim(), schema.Text.Trim(),
            login.Text.Trim(), password.Text, root, fingerprint);
    }

    private void SaveSettings()
    {
        if (operation is not null || closeRequested) return;
        try
        {
            var draft = Draft();
            draft.Validate();
            save(draft);
            if (!IsDisposed) Close();
        }
        catch (Exception error) { ShowError(error); }
    }

    private async Task RunAsync(bool linkDevice)
    {
        if (operation is not null || closeRequested || linkDevice && (linked || SelectedTransport != ConnectorTransport.Https))
            return;
        ConnectorSettings draft;
        var code = "";
        try
        {
            draft = Draft();
            if (linkDevice)
            {
                draft.Validate();
                code = pairingCode.Text.Trim();
                if (code.Length != 43 || code.Any(c => !(char.IsAsciiLetterOrDigit(c) || c is '_' or '-')))
                    throw new ConnectorException("invalid_pairing_code");
                pairingCode.Clear();
            }
        }
        catch (Exception error)
        {
            ShowError(error);
            return;
        }

        using var lifetime = new CancellationTokenSource();
        operation = lifetime;
        pairing = linkDevice;
        var linkedNow = false;
        tabs.SelectedTab = connectionTab;
        RefreshControls();
        try
        {
            if (linkDevice)
            {
                SetSummary(feedback, "Привязка устройства...");
                await pairHttps(draft, code, lifetime.Token);
                linkedNow = true;
            }
            else
            {
                SetSummary(feedback, "");
                SetSummary(outlookStatus, "Проверяется...");
                SetSummary(dpmsStatus, "Проверяется...");
                // The callback checks the two services independently, including an unset DPMS endpoint.
                var result = await check(draft, lifetime.Token);
                if (!closeRequested && !IsDisposed)
                {
                    SetSummary(outlookStatus, result.Outlook);
                    SetSummary(dpmsStatus, result.Dpms);
                }
            }
        }
        catch (Exception error)
        {
            if (!IsDisposed && (!closeRequested || linkDevice))
            {
                closeRequested = false;
                if (!linkDevice)
                {
                    SetSummary(outlookStatus, "Нет результата");
                    SetSummary(dpmsStatus, "Нет результата");
                }
                ShowError(error);
            }
        }
        finally
        {
            if (cancellationWork is { } pending)
            {
                try { await pending; }
                catch (AggregateException) { /* The operation has finished; no callback text is shown. */ }
                cancellationWork = null;
            }
            operation = null;
            pairing = false;
            if (!IsDisposed)
            {
                if (linkedNow || closeRequested) Close();
                else RefreshControls();
            }
        }
    }

    private void ResetDpmsStatus() => SetSummary(dpmsStatus, linked ? "Привязано, не проверено" : "Не проверено");

    private void ShowError(Exception error)
    {
        if (IsDisposed) return;
        var code = (error as ConnectorException)?.Code;
        switch (code)
        {
            case "smtp_settings_invalid": tabs.SelectedTab = alertsTab; break;
            case "connector_settings_invalid": tabs.SelectedTab = scheduleTab; break;
            case "invalid_server_url" or "db_settings_invalid" or "db_tls_pin_conflict" or "db_tls_pin_invalid"
                or "invalid_device_name" or "invalid_pairing_code": tabs.SelectedTab = connectionTab; break;
        }
        var message = code switch
        {
            "connector_settings_invalid" => "Проверьте интервалы и таймауты в расписании.",
            "invalid_server_url" => "Укажите HTTPS-адрес без пути, параметров и учётных данных.",
            "smtp_settings_invalid" => "Проверьте SMTP-сервер, порт STARTTLS, адреса и пару имя пользователя/пароль.",
            "invalid_device_name" => "Имя устройства: до 100 символов без управляющих символов.",
            _ => describeError(error),
        };
        SetSummary(feedback, string.IsNullOrWhiteSpace(message) ? "Операция не завершена." : message);
    }

    private void ChooseCa()
    {
        if (operation is not null) return;
        try
        {
            using var picker = new OpenFileDialog
            {
                Title = "Сертификат центра сертификации",
                Filter = "Сертификаты CA (*.pem;*.crt;*.cer)|*.pem;*.crt;*.cer|Все файлы (*.*)|*.*",
                CheckFileExists = true, Multiselect = false, RestoreDirectory = true, AddToRecent = false,
            };
            if (picker.ShowDialog(this) == DialogResult.OK && !IsDisposed) ca.Text = picker.FileName;
        }
        catch (Exception error) { ShowError(error); }
    }

    protected override void OnShown(EventArgs e)
    {
        var area = Screen.FromControl(this).WorkingArea;
        var fitted = new Size(Math.Min(Width, area.Width), Math.Min(Height, area.Height));
        if (Size != fitted)
        {
            MinimumSize = new Size(Math.Min(MinimumSize.Width, fitted.Width), Math.Min(MinimumSize.Height, fitted.Height));
            Size = fitted;
        }
        Location = new Point(Math.Clamp(Left, area.Left, area.Right - Width), Math.Clamp(Top, area.Top, area.Bottom - Height));
        base.OnShown(e);
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        base.OnFormClosing(e);
        if (e.Cancel || operation is not { } active) return;
        if (e.CloseReason != CloseReason.UserClosing)
        {
            // The owner tracks its callback task. Its shutdown must not wait on this form's UI continuation.
            cancellationWork ??= active.CancelAsync();
            return;
        }
        e.Cancel = true;
        if (closeRequested) return;
        closeRequested = true;
        closeButton.Enabled = false;
        SetSummary(feedback, pairing ? "Завершение привязки..." : "Остановка проверки...");
        if (!pairing) cancellationWork ??= active.CancelAsync();
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            if (operation is { } active) cancellationWork ??= active.CancelAsync();
            tooltips.Dispose();
        }
        base.Dispose(disposing);
    }

    private TableLayoutPanel PageLayout(TabPage page)
    {
        tabs.TabPages.Add(page);
        var viewport = new Panel { Dock = DockStyle.Fill, AutoScroll = true };
        var content = Table(1);
        content.Padding = new Padding(12, 10, 12, 12);
        content.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        viewport.Controls.Add(content);
        page.Controls.Add(viewport);
        return content;
    }

    private static TableLayoutPanel Table(int columns) => new()
    {
        Dock = DockStyle.Top, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink,
        ColumnCount = columns, RowCount = 0, Margin = Padding.Empty,
    };

    private static TableLayoutPanel Fields()
    {
        var table = Table(2);
        table.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 190));
        table.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        return table;
    }

    private static int NextRow(TableLayoutPanel table)
    {
        var row = table.RowCount++;
        table.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        return row;
    }

    private static void AddRow(TableLayoutPanel table, Control control) => table.Controls.Add(control, 0, NextRow(table));

    private static void AddField(TableLayoutPanel table, string title, Control control)
    {
        var row = NextRow(table);
        table.Controls.Add(new Label
        {
            Text = title, AutoSize = true, MaximumSize = new Size(184, 0), Anchor = AnchorStyles.Left,
            Margin = new Padding(0, 3, 3, 3),
        }, 0, row);
        control.AccessibleName ??= title;
        table.Controls.Add(control, 1, row);
    }

    private static TextBox Input(int limit = 32767, bool masked = false, string placeholder = "") => new()
    {
        Dock = DockStyle.Fill, MaxLength = limit, UseSystemPasswordChar = masked, PlaceholderText = placeholder,
    };

    private static NumericUpDown Number(int minimum, int maximum, int value) => new()
    {
        Minimum = minimum, Maximum = maximum, Value = value, Width = 88, Anchor = AnchorStyles.Left,
    };

    private static void LoadNumber(NumericUpDown control, int value) =>
        control.Value = Math.Clamp(value, control.Minimum, control.Maximum);

    private static Label SummaryLabel(int height = 26) => new()
    {
        Dock = DockStyle.Top, Height = height, AutoEllipsis = true, UseMnemonic = false,
        TextAlign = ContentAlignment.MiddleLeft,
    };

    private void SetSummary(Label label, string text)
    {
        label.Text = text;
        tooltips.SetToolTip(label, text);
    }
}
