using System.Net.Mail;

namespace Dpms.OutlookConnector;

public sealed record ConnectorSettings
{
    public ConnectorTransport Transport { get; init; } = ConnectorTransport.PostgreSql;
    public PostgresSettings? Database { get; init; }
    public string ServerUrl { get; init; } = "";
    public string DeviceName { get; init; } = "";
    public int HistoryDays { get; init; } = 30;
    public int SyncMinutes { get; init; } = 10;
    public int SyncTimeoutSeconds { get; init; } = 180;
    public int CheckMinutes { get; init; } = 60;
    public int CheckTimeoutSeconds { get; init; } = 15;
    public bool Autorun { get; init; }
    public SmtpSettings? Alerts { get; init; }

    public void Validate(bool requireEndpoint = true)
    {
        if (Transport is not (ConnectorTransport.PostgreSql or ConnectorTransport.Https)
            || HistoryDays is < 1 or > 90 || SyncMinutes is < 1 or > 1440 || SyncTimeoutSeconds is < 10 or > 1800
            || CheckMinutes is < 1 or > 1440 || CheckTimeoutSeconds is < 2 or > 120)
            throw new ConnectorException("connector_settings_invalid");
        if (DeviceName is not { Length: <= 100 } || DeviceName.Any(char.IsControl))
            throw new ConnectorException("invalid_device_name");

        if (Transport == ConnectorTransport.PostgreSql)
        {
            if (requireEndpoint && Database is null) throw new ConnectorException("db_settings_invalid");
            Database?.Validate();
        }
        else
        {
            if (ServerUrl is not { Length: <= 500 } || ServerUrl.Any(char.IsControl))
                throw new ConnectorException("invalid_server_url");
            if (requireEndpoint || !string.IsNullOrWhiteSpace(ServerUrl))
            {
                try { _ = Protocol.Server(ServerUrl); }
                catch (ArgumentException) { throw new ConnectorException("invalid_server_url"); }
            }
        }

        Alerts?.Validate();
    }

    public override string ToString() => "ConnectorSettings { redacted }";
}

public sealed record SmtpSettings(string Host, int Port, string Username, string Password, string From, string To)
{
    public void Validate()
    {
        if (!IsHostname(Host) || Port is < 1 or > 65535 or 465
            || Username is not { Length: <= 254 } || Password is not { Length: <= 1024 }
            || (Username.Length == 0) != (Password.Length == 0)
            || Username.Length > 0 && string.IsNullOrWhiteSpace(Username)
            || Username.Any(IsUnsafe) || Password.Any(IsUnsafe)
            || !IsMailbox(From) || !IsMailbox(To))
            throw new ConnectorException("smtp_settings_invalid");
    }

    private static bool IsHostname(string? value) => value is { Length: > 0 and <= 253 }
        && value.Split('.').All(label => label is { Length: > 0 and <= 63 }
            && char.IsAsciiLetterOrDigit(label[0]) && char.IsAsciiLetterOrDigit(label[^1])
            && label.All(c => char.IsAsciiLetterOrDigit(c) || c == '-'));

    private static bool IsMailbox(string? value) => value is { Length: > 0 and <= 254 } && !value.Any(IsUnsafe)
        && MailAddress.TryCreate(value, out var address) && address.DisplayName.Length == 0
        && string.Equals(value, address.Address, StringComparison.Ordinal);

    private static bool IsUnsafe(char value) => char.IsControl(value) || value is '\u2028' or '\u2029';

    public override string ToString() => "SmtpSettings { redacted }";
}
