using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Dpms.OutlookConnector;
using Npgsql;
using NpgsqlTypes;
using Xunit;

namespace Dpms.OutlookConnector.Tests;

// The Python harness owns the database, worker and lifetime of every fixture.
public sealed class LivePostgresFactAttribute : FactAttribute
{
    public LivePostgresFactAttribute()
    {
        if (Environment.GetEnvironmentVariable("OUTLOOK_TEST_DOTNET") != "1"
            || Environment.GetEnvironmentVariable("OUTLOOK_TEST_TLS_FIXTURE") is null)
            Skip = "Run backend/tests/test_mail_import_db_client.py with OUTLOOK_TEST_DOTNET=1";
        Timeout = 90000;
    }
}

public sealed class PostgresLiveTests
{
    private static string Required(string name) => Environment.GetEnvironmentVariable(name)
        ?? throw new InvalidOperationException("Missing synthetic fixture configuration");

    private static (PostgresSettings Settings, string Directory) Fixture()
    {
        var directory = Required("OUTLOOK_TEST_TLS_FIXTURE");
        if (!Regex.IsMatch(directory, @"^/(?:private/)?tmp/dpms-outlook-pg\.[A-Za-z0-9_-]+$"))
            throw new InvalidOperationException("Only a generated disposable TLS fixture is allowed");
        var info = new DirectoryInfo(directory);
        if (!info.Exists || info.LinkTarget is not null
            || (!OperatingSystem.IsWindows() && File.GetUnixFileMode(directory)
                != (UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute)))
            throw new InvalidOperationException("Fixture must be a private nonsymlink directory");
        if (File.ReadAllText(Path.Combine(directory, "fixture-id")) != Required("OUTLOOK_TEST_FIXTURE_ID"))
            throw new InvalidOperationException("Fixture identity mismatch");
        var schema = Required("OUTLOOK_TEST_SCHEMA");
        var username = Required("OUTLOOK_TEST_LOGIN");
        if (!Regex.IsMatch(schema, "^outlook_test_[a-f0-9]{32}$")
            || !Regex.IsMatch(username, "^outlook_live_[a-f0-9]{32}$")
            || !int.TryParse(Required("OUTLOOK_TEST_PORT"), out var port) || port is < 1024 or > 65535)
            throw new InvalidOperationException("Invalid disposable database identity");
        // No arbitrary connection string, hostname, database or certificate path is accepted.
        return (new PostgresSettings("localhost", port, "dpms_outlook_test", schema,
            username, "synthetic-disposable-only", Path.Combine(directory, "root.crt")), directory);
    }

    private static void Signal(string directory, string name) =>
        File.WriteAllText(Path.Combine(directory, name), "ok", new UTF8Encoding(false));

    private static async Task WaitFor(string directory, string name, CancellationToken cancellation)
    {
        while (!File.Exists(Path.Combine(directory, name)))
            await Task.Delay(50, cancellation);
    }

    private static PostgresSettings OtherLogin(PostgresSettings settings, string variable)
    {
        var username = Required(variable);
        if (!Regex.IsMatch(username, "^outlook_live_[a-f0-9]{32}$"))
            throw new InvalidOperationException("Invalid synthetic role");
        return settings with { Username = username };
    }

    [LivePostgresFact]
    public async Task ConnectSyncRepeatAndRevokeThroughPythonWorker()
    {
        var (settings, directory) = Fixture();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(65));
        Assert.Null(Environment.GetEnvironmentVariable("OUTLOOK_TEST_PAIRING_CODE"));
        using var enrollment = new PostgresClient(settings);
        await enrollment.CheckConnection(deadline.Token);
        Signal(directory, "connection-checked");
        await WaitFor(directory, "connection-check-verified", deadline.Token);
        var connected = await enrollment.Connect("Synthetic TLS laptop", deadline.Token);
        Assert.NotEqual(Guid.Empty, connected.DeviceId);
        Assert.Equal("Synthetic owner", connected.OwnerName);
        Assert.True(connected.IncludeBody);
        Assert.True(connected.IncludeAttachments);
        Assert.Equal(1, connected.ProtocolVersion);

        var attachment = Encoding.UTF8.GetBytes("Synthetic TLS attachment\n");
        var stamp = DateTimeOffset.Parse("2026-11-16T10:00:00Z");
        var item = new ImportedItem(Protocol.Hash("live-tls-item"), "mail", stamp, stamp,
            "Synthetic TLS subject \u041f\u043e\u0447\u0442\u0430", "Synthetic sender", "sender@example.invalid",
            "Synthetic full text", false, BodyHtml: "<p>Synthetic full text</p>",
            ToRecipients: "Recipient <recipient@example.invalid>",
            Attachments: [new ImportedAttachment("fixture.txt", "text/plain", Convert.ToBase64String(attachment),
                Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(attachment)))]);
        var batch = new SyncBatch(Protocol.Hash("live-tls-mailbox"), "Synthetic Inbox", "cached", [item]);
        var otherSettings = OtherLogin(settings, "OUTLOOK_TEST_OTHER_LOGIN");
        using var other = new PostgresClient(otherSettings, connected.DeviceSecret);
        var stolen = await Assert.ThrowsAsync<ConnectorException>(() => other.Sync(batch, deadline.Token));
        Assert.Equal("access_denied", stolen.Code);

        using var client = new PostgresClient(settings, connected.DeviceSecret);
        var first = await client.Sync(batch, deadline.Token);
        Assert.Equal((1, 1, 0, 0, 0), (first.Accepted, first.Created, first.Updated, first.Unchanged, first.Stale));
        // A separately mapped DB login cannot read another role's receipt even
        // when given the real device secret and request UUID.
        var requestId = Guid.Parse(File.ReadAllText(Path.Combine(directory, "first-request-id")));
        await using (var connection = new NpgsqlConnection(otherSettings.ConnectionSettings().ConnectionString))
        {
            await connection.OpenAsync(deadline.Token);
            await using var status = new NpgsqlCommand(
                $"SELECT \"{settings.Schema}\".mail_import_db_status($1,$2)::text", connection);
            status.Parameters.AddWithValue(NpgsqlDbType.Text, connected.DeviceSecret);
            status.Parameters.AddWithValue(NpgsqlDbType.Uuid, requestId);
            using var denied = JsonDocument.Parse((string)(await status.ExecuteScalarAsync(deadline.Token))!);
            Assert.Equal(401, denied.RootElement.GetProperty("error_status").GetInt32());
        }
        Signal(directory, "first-ack");
        var repeat = await client.Sync(batch, deadline.Token);
        Assert.Equal((1, 0, 0, 1, 0), (repeat.Accepted, repeat.Created, repeat.Updated, repeat.Unchanged, repeat.Stale));
        Signal(directory, "repeat-ack");
        await WaitFor(directory, "revoked", deadline.Token);
        var revoked = await Assert.ThrowsAsync<ConnectorException>(() => client.Sync(batch, deadline.Token));
        Assert.Equal("access_denied", revoked.Code);
        Assert.DoesNotContain(connected.DeviceSecret, revoked.ToString());
        Signal(directory, "revoke-rejected");

        var next = await enrollment.Connect("Synthetic TLS disabled mapping", deadline.Token);
        using var pendingClient = new PostgresClient(settings, next.DeviceSecret);
        var pending = batch with { Items = [item with { SourceId = Protocol.Hash("must-not-import") }] };
        var disabled = await Assert.ThrowsAsync<ConnectorException>(() => pendingClient.Sync(pending, deadline.Token));
        Assert.Equal("access_denied", disabled.Code);
        await WaitFor(directory, "mapping-disabled", deadline.Token);
        var noNewDevice = await Assert.ThrowsAsync<ConnectorException>(() =>
            enrollment.Connect("Must not enroll", deadline.Token));
        Assert.Equal("db_login_not_provisioned", noNewDevice.Code);
        Signal(directory, "mapping-rejected");
    }

    [LivePostgresFact]
    public async Task VerifiedTlsLoginCannotReadOrMutateApplicationTables()
    {
        var (settings, _) = Fixture();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(25));
        await using var connection = new NpgsqlConnection(settings.ConnectionSettings().ConnectionString);
        await connection.OpenAsync(deadline.Token);
        await using (var tls = new NpgsqlCommand(
            "SELECT ssl FROM pg_catalog.pg_stat_ssl WHERE pid = pg_catalog.pg_backend_pid()", connection))
            Assert.Equal(true, await tls.ExecuteScalarAsync(deadline.Token));
        foreach (var table in new[] { "users", "mail_import_devices", "mail_import_items", "mail_import_attachments",
            "mail_import_queue", "mail_import_db_logins", "mail_import_db_devices" })
        {
            var target = $"\"{settings.Schema}\".\"{table}\"";
            foreach (var sql in new[] { $"SELECT * FROM {target} LIMIT 0", $"DELETE FROM {target} WHERE false" })
            {
                await using var command = new NpgsqlCommand(sql, connection);
                var denied = await Assert.ThrowsAsync<PostgresException>(() => command.ExecuteNonQueryAsync(deadline.Token));
                Assert.Equal(PostgresErrorCodes.InsufficientPrivilege, denied.SqlState);
            }
        }
        await using var legacy = new NpgsqlCommand(
            $"SELECT \"{settings.Schema}\".mail_import_db_pair($1,$2)", connection);
        legacy.Parameters.AddWithValue(NpgsqlDbType.Text, new string('a', 43));
        legacy.Parameters.AddWithValue(NpgsqlDbType.Text, new string('b', 43));
        var oldPairDenied = await Assert.ThrowsAsync<PostgresException>(() => legacy.ExecuteNonQueryAsync(deadline.Token));
        Assert.Equal(PostgresErrorCodes.InsufficientPrivilege, oldPairDenied.SqlState);
    }

    [LivePostgresFact]
    public async Task UnmappedLoginAndWrongPasswordCannotConnect()
    {
        var (settings, _) = Fixture();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(25));
        using var unmapped = new PostgresClient(OtherLogin(settings, "OUTLOOK_TEST_UNMAPPED_LOGIN"));
        var denied = await Assert.ThrowsAsync<ConnectorException>(() => unmapped.Connect("Synthetic unmapped", deadline.Token));
        Assert.Equal("db_login_not_provisioned", denied.Code);
        using var wrong = new PostgresClient(settings with { Password = "synthetic-wrong-password" });
        var probe = await Assert.ThrowsAsync<ConnectorException>(() => wrong.CheckConnection(deadline.Token));
        Assert.Equal("db_login_failed", probe.Code);
        var login = await Assert.ThrowsAsync<ConnectorException>(() => wrong.Connect("Synthetic wrong password", deadline.Token));
        Assert.Equal("db_login_failed", login.Code);
    }

    [LivePostgresFact]
    public async Task WrongHostnameAndUntrustedRootFailClosed()
    {
        var (settings, directory) = Fixture();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(25));
        foreach (var invalid in new[]
        {
            settings with { Host = "127.0.0.1" }, // Certificate has DNS:localhost only.
            settings with { RootCertificate = Path.Combine(directory, "untrusted.crt") },
        })
        {
            using var client = new PostgresClient(invalid);
            var error = await Assert.ThrowsAsync<ConnectorException>(() =>
                client.Connect("Synthetic TLS failure", deadline.Token));
            Assert.Equal("db_tls_failed", error.Code);
            Assert.DoesNotContain(settings.Password, error.ToString());
        }
    }
}
