using Dpms.OutlookConnector;
using Xunit;

namespace Dpms.OutlookConnector.Tests;

public sealed class ConnectorSettingsTests
{
    private static readonly SmtpSettings Smtp = new("smtp.example.test", 587, "", "",
        "connector@example.test", "admin@example.test");

    [Fact]
    public void DefaultScheduleAndAlertsAreValidWithoutEndpointWhenNotRequired()
    {
        var settings = new ConnectorSettings();
        Assert.Equal(ConnectorTransport.PostgreSql, settings.Transport);
        Assert.Equal((30, 10, 180, 60, 15), (settings.HistoryDays, settings.SyncMinutes, settings.SyncTimeoutSeconds,
            settings.CheckMinutes, settings.CheckTimeoutSeconds));
        Assert.False(settings.Autorun);
        Assert.Null(settings.Alerts);
        settings.Validate(requireEndpoint: false);
        Assert.Equal("db_settings_invalid", Assert.Throws<ConnectorException>(() => settings.Validate()).Code);
    }

    [Theory]
    [InlineData("invalid\rname")]
    [InlineData("invalid\0name")]
    public void DeviceNameCannotContainControls(string name)
    {
        var settings = new ConnectorSettings { DeviceName = name };
        Assert.Equal("invalid_device_name", Assert.Throws<ConnectorException>(() => settings.Validate(false)).Code);
        Assert.Equal("invalid_device_name",
            Assert.Throws<ConnectorException>(() => (settings with { DeviceName = new string('a', 101) }).Validate(false)).Code);
    }

    [Fact]
    public void OptionalEndpointStillValidatesWhenProvided()
    {
        var settings = new ConnectorSettings { Transport = ConnectorTransport.Https };
        settings.Validate(requireEndpoint: false);
        Assert.Equal("invalid_server_url", Assert.Throws<ConnectorException>(() => settings.Validate()).Code);
        var invalid = settings with { ServerUrl = "https://example.test/api" };
        Assert.Equal("invalid_server_url", Assert.Throws<ConnectorException>(() => invalid.Validate(false)).Code);
        var https = settings with { ServerUrl = "https://example.test:443" };
        https.Validate();

        var database = new ConnectorSettings
        {
            Database = new PostgresSettings("db.example.test", 58923, "dpms", "import", "login", "synthetic-password"),
        };
        database.Validate();
        var partial = database with { Database = database.Database! with { Schema = "" } };
        Assert.Equal("db_settings_invalid", Assert.Throws<ConnectorException>(() => partial.Validate(false)).Code);
    }

    [Theory]
    [InlineData(1, 1, 10, 1, 2, true)]
    [InlineData(90, 1440, 1800, 1440, 120, true)]
    [InlineData(0, 10, 180, 60, 15, false)]
    [InlineData(91, 10, 180, 60, 15, false)]
    [InlineData(30, 0, 180, 60, 15, false)]
    [InlineData(30, 1441, 180, 60, 15, false)]
    [InlineData(30, 10, 9, 60, 15, false)]
    [InlineData(30, 10, 1801, 60, 15, false)]
    [InlineData(30, 10, 180, 0, 15, false)]
    [InlineData(30, 10, 180, 1441, 15, false)]
    [InlineData(30, 10, 180, 60, 1, false)]
    [InlineData(30, 10, 180, 60, 121, false)]
    public void EnforcesAllScheduleLimits(int history, int sync, int syncTimeout, int check, int checkTimeout, bool valid)
    {
        var settings = new ConnectorSettings
        {
            HistoryDays = history, SyncMinutes = sync, SyncTimeoutSeconds = syncTimeout,
            CheckMinutes = check, CheckTimeoutSeconds = checkTimeout,
        };
        if (valid) settings.Validate(requireEndpoint: false);
        else Assert.Equal("connector_settings_invalid", Assert.Throws<ConnectorException>(() => settings.Validate(false)).Code);
    }

    [Fact]
    public void SmtpAcceptsAnonymousOrPairedCredentialsAndRedactsValues()
    {
        Smtp.Validate();
        var authenticated = Smtp with { Username = "synthetic-login", Password = "synthetic-password" };
        var settings = new ConnectorSettings { Alerts = authenticated };
        settings.Validate(requireEndpoint: false);
        Assert.Equal("SmtpSettings { redacted }", authenticated.ToString());
        Assert.Equal("ConnectorSettings { redacted }", settings.ToString());
    }

    [Fact]
    public void SmtpRejectsInvalidAddressAuthorityCredentialsAndImplicitTls()
    {
        SmtpSettings[] invalid =
        [
            Smtp with { Host = "smtp://smtp.example.test" },
            Smtp with { Host = "smtp.example.test:587" },
            Smtp with { Host = "-smtp.example.test" },
            Smtp with { Host = new string('a', 64) + ".example.test" },
            Smtp with { Port = 0 },
            Smtp with { Port = 65536 },
            Smtp with { Port = 465 },
            Smtp with { From = "Connector <connector@example.test>" },
            Smtp with { To = "admin@example.test,another@example.test" },
            Smtp with { To = "admin@example.test\r\nBcc: another@example.test" },
            Smtp with { Username = "only-user" },
            Smtp with { Password = "only-password" },
            Smtp with { Username = new string('u', 255), Password = "synthetic" },
            Smtp with { Username = "synthetic", Password = new string('p', 1025) },
            Smtp with { Username = "synthetic", Password = "bad\0password" },
        ];
        foreach (var settings in invalid)
            Assert.Equal("smtp_settings_invalid", Assert.Throws<ConnectorException>(settings.Validate).Code);
    }
}
