using System.Text.Json;
using Dpms.OutlookConnector;
using Npgsql;
using Xunit;

namespace Dpms.OutlookConnector.Tests;

public sealed class PostgresTests
{
    private static readonly string Secret = new('s', 43);
    private static PostgresSettings Settings => new("db.example.invalid", 58923, "dpms", "app", "inbox_client", "synthetic-only");
    private static SyncBatch Batch => new(new string('a', 64), "Synthetic Inbox", "cached", [ProtocolTests.Item()]);
    private static string Json(object value) => JsonSerializer.Serialize(value, Protocol.Json);
    private static string Receipt(object id, string state = "pending", object? result = null) => Json(new { request_id = id, state, result });
    private static object Ack => new { accepted = 1, created = 1, updated = 0, unchanged = 0, stale = 0, synced_at = "2026-11-17T10:00:00Z" };

    [Fact]
    public void ConnectionAlwaysUsesVerifiedTlsExplicitCredentialsAndNoLogging()
    {
        var settings = Settings.ConnectionSettings();
        Assert.Equal(SslMode.VerifyFull, settings.SslMode);
        Assert.Equal(GssEncryptionMode.Disable, settings.GssEncryptionMode);
        Assert.Equal(SslNegotiation.Postgres, settings.SslNegotiation);
        Assert.Equal("ScramSHA256,MD5,Password", settings.RequireAuth);
        Assert.Equal(58923, settings.Port);
        Assert.Equal("inbox_client", settings.Username);
        Assert.Equal("synthetic-only", settings.Password);
        Assert.False(settings.IncludeErrorDetail);
        Assert.False(settings.LogParameters);
        Assert.False(settings.PersistSecurityInfo);
        Assert.False(settings.Pooling);
        Assert.Equal(10, settings.Timeout);
        Assert.Equal(30, settings.CommandTimeout);
        Assert.Equal("pg_catalog", settings.SearchPath);
        Assert.DoesNotContain("synthetic", Settings.ToString());
        Assert.Equal("test-ca.pem", (Settings with { RootCertificate = "test-ca.pem" }).ConnectionSettings().RootCertificate);
    }

    [Theory]
    [InlineData("host", "/tmp/socket")]
    [InlineData("host", "db.example.invalid,other.invalid")]
    [InlineData("host", "db.example.invalid;SSL Mode=Disable")]
    [InlineData("host", "https://db.example.invalid")]
    [InlineData("schema", "app\";SELECT 1")]
    [InlineData("schema", "")]
    [InlineData("username", "")]
    [InlineData("password", "")]
    [InlineData("database", "")]
    public void UnsafeOrImplicitConnectionSettingsAreRejected(string field, string value)
    {
        var settings = field switch
        {
            "host" => Settings with { Host = value }, "schema" => Settings with { Schema = value },
            "username" => Settings with { Username = value }, "password" => Settings with { Password = value },
            _ => Settings with { Database = value },
        };
        Assert.Equal("db_settings_invalid", Assert.Throws<ConnectorException>(settings.Validate).Code);
    }

    [Fact]
    public void AmbientTlsFilesAreRejectedWithoutReadingThem()
    {
        Settings.RejectImplicitTlsFiles(_ => null, _ => throw new Exception("no path"), false);
        foreach (var variable in new[] { "PGSSLCERT", "PGSSLKEY", "PGSSLROOTCERT" })
            Assert.Equal("db_tls_configuration", Assert.Throws<ConnectorException>(() => Settings.RejectImplicitTlsFiles(
                name => name == variable ? "synthetic-path" : null, _ => false, false)).Code);
        Assert.Throws<ConnectorException>(() => Settings.RejectImplicitTlsFiles(
            name => name == "APPDATA" ? "synthetic-home" : null, path => path.EndsWith("postgresql.crt"), true));
        Assert.Throws<ConnectorException>(() => Settings.RejectImplicitTlsFiles(
            name => name == "HOME" ? "synthetic-home" : null, path => path.EndsWith("root.crt"), false));
        (Settings with { RootCertificate = "explicit-ca.crt" }).RejectImplicitTlsFiles(
            name => name == "PGSSLROOTCERT" ? "ignored-ca" : null, _ => false, false);
    }

    [Fact]
    public void LegacySessionsRemainHttpsAndDatabaseSessionsRetainSettings()
    {
        var legacy = JsonSerializer.Deserialize<DeviceSession>(Json(new
        {
            server_url = "https://example.invalid", device_id = Guid.NewGuid(), device_secret = Secret,
            owner_name = "Synthetic", include_body = false,
        }), Protocol.Json)!;
        Assert.Equal(ConnectorTransport.Https, legacy.Transport);
        using var oldClient = IngestionClient.Create(legacy);
        Assert.IsType<DpmsClient>(oldClient);
        var direct = legacy with { ServerUrl = "", Transport = ConnectorTransport.PostgreSql, Database = Settings };
        var roundtrip = JsonSerializer.Deserialize<DeviceSession>(Json(direct), Protocol.Json)!;
        using var newClient = IngestionClient.Create(roundtrip);
        Assert.IsType<PostgresClient>(newClient);
        Assert.Equal(Settings, roundtrip.Database);
        Assert.Throws<ConnectorException>(() => IngestionClient.Create(direct with { Database = null }));
        Assert.Throws<ConnectorException>(() => IngestionClient.Create(legacy with { Transport = (ConnectorTransport)99 }));
    }

    [Fact]
    public async Task PairChecksProtocolAndGeneratesItsOwnSecretWithoutHttp()
    {
        var fake = new Fake((function, args) => function switch
        {
            "mail_import_db_protocol" => Json(new { protocol_version = 1, maximum_batch_bytes = Protocol.MaximumBatchBytes }),
            "mail_import_db_pair" => Json(new { device_id = Guid.NewGuid(), device_secret = args[1], owner_name = "Synthetic",
                include_body = true, include_attachments = true, protocol_version = 1 }),
            _ => throw new InvalidOperationException(),
        });
        using var client = new PostgresClient(fake);
        var result = await client.Pair(new string('c', 43), CancellationToken.None);
        Assert.Equal(43, result.DeviceSecret.Length);
        Assert.All(result.DeviceSecret, c => Assert.True(char.IsAsciiLetterOrDigit(c) || c is '-' or '_'));
        Assert.NotEqual(new string('c', 43), result.DeviceSecret);
        Assert.True(result.IncludeAttachments);
        Assert.Equal(new[] { "mail_import_db_protocol", "mail_import_db_pair" }, fake.Calls.Select(c => c.Function));
    }

    [Fact]
    public async Task ConnectionCheckUsesOnlyProtocolAndDoesNotRegisterADevice()
    {
        var fake = new Fake((_, _) => Json(new
        {
            protocol_version = 1, maximum_batch_bytes = Protocol.MaximumBatchBytes, login_mode = "role_bound",
        }));
        using var client = new PostgresClient(fake);
        await client.CheckConnection(CancellationToken.None);
        var call = Assert.Single(fake.Calls);
        Assert.Equal("mail_import_db_protocol", call.Function);
        Assert.Empty(call.Arguments);
    }

    [Fact]
    public async Task ConnectionCheckRejectsIncompatibleProtocolWithoutRegistration()
    {
        var fake = new Fake((_, _) => Json(new { protocol_version = 1, maximum_batch_bytes = Protocol.MaximumBatchBytes }));
        using var client = new PostgresClient(fake);
        var error = await Assert.ThrowsAsync<ConnectorException>(() => client.CheckConnection(CancellationToken.None));
        Assert.Equal("db_not_installed", error.Code);
        Assert.Equal("mail_import_db_protocol", Assert.Single(fake.Calls).Function);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task BoundConnectionCheckReadsDeviceStatusWithoutEnqueue(bool revoked)
    {
        var fake = new Fake((function, args) => function switch
        {
            "mail_import_db_protocol" => Json(new
            {
                protocol_version = 1, maximum_batch_bytes = Protocol.MaximumBatchBytes, login_mode = "role_bound",
            }),
            "mail_import_db_status" => Json(new
            {
                request_id = args[1], state = "error", error_status = revoked ? 401 : 404,
                error_code = revoked ? "invalid_device" : "request_not_found",
            }),
            _ => throw new InvalidOperationException("Unexpected test request."),
        });
        using var client = new PostgresClient(fake, Secret);
        if (revoked)
        {
            var failure = await Assert.ThrowsAsync<ConnectorException>(() => client.CheckConnection(CancellationToken.None));
            Assert.Equal("access_denied", failure.Code);
        }
        else await client.CheckConnection(CancellationToken.None);

        Assert.Equal(new[] { "mail_import_db_protocol", "mail_import_db_status" }, fake.Calls.Select(call => call.Function));
    }

    [Fact]
    public async Task DatabaseLoginConnectNeedsNoPairingCodeOrClientOwnerId()
    {
        var fake = new Fake((function, args) => function switch
        {
            "mail_import_db_protocol" => Json(new { protocol_version = 1, maximum_batch_bytes = Protocol.MaximumBatchBytes, login_mode = "role_bound" }),
            "mail_import_db_connect" => Json(new { device_id = Guid.NewGuid(), device_secret = args[1], owner_name = "Synthetic owner",
                include_body = true, include_attachments = true, protocol_version = 1 }),
            _ => throw new InvalidOperationException(),
        });
        using var client = new PostgresClient(fake);
        var result = await client.Connect("Synthetic Laptop", CancellationToken.None);
        Assert.Equal("Synthetic owner", result.OwnerName);
        var connect = fake.Calls[1];
        Assert.Equal("mail_import_db_connect", connect.Function);
        Assert.Equal(2, connect.Arguments.Length);
        Assert.Equal("Synthetic Laptop", connect.Arguments[0]);
        Assert.Equal(result.DeviceSecret, connect.Arguments[1]);
        Assert.Equal(43, result.DeviceSecret.Length);
    }

    [Fact]
    public async Task RepeatedConnectKeepsSameGeneratedSecret()
    {
        var count = 0;
        var fake = new Fake((function, args) => function == "mail_import_db_protocol"
            ? Json(new { protocol_version = 1, maximum_batch_bytes = Protocol.MaximumBatchBytes, login_mode = "role_bound" })
            : ++count == 1 ? throw new ConnectorException("db_unavailable")
            : Json(new { device_id = Guid.NewGuid(), device_secret = args[1], owner_name = "Synthetic", protocol_version = 1 }));
        using var client = new PostgresClient(fake, pollInterval: TimeSpan.Zero);
        await client.Connect("Synthetic Laptop", CancellationToken.None);
        Assert.Equal(fake.Calls[1].Arguments, fake.Calls[2].Arguments);
    }

    [Fact]
    public async Task UnmappedDatabaseLoginAndOldServerFailClosed()
    {
        using var old = new PostgresClient(new Fake((_, _) => Json(new { protocol_version = 1, maximum_batch_bytes = Protocol.MaximumBatchBytes })));
        Assert.Equal("db_not_installed", (await Assert.ThrowsAsync<ConnectorException>(() => old.Connect("Laptop", CancellationToken.None))).Code);
        using var unmapped = new PostgresClient(new Fake((function, _) => function == "mail_import_db_protocol"
            ? Json(new { protocol_version = 1, maximum_batch_bytes = Protocol.MaximumBatchBytes, login_mode = "role_bound" })
            : Json(new { error_code = "db_login_not_provisioned", error_status = 403 })));
        Assert.Equal("db_login_not_provisioned", (await Assert.ThrowsAsync<ConnectorException>(() => unmapped.Connect("Laptop", CancellationToken.None))).Code);
    }

    [Fact]
    public async Task AmbiguousPairIsNeverRetried()
    {
        var fake = new Fake((function, _) => function == "mail_import_db_protocol"
            ? Json(new { protocol_version = 1, maximum_batch_bytes = Protocol.MaximumBatchBytes })
            : throw new ConnectorException("db_unavailable"));
        using var client = new PostgresClient(fake);
        Assert.Equal("pair_uncertain", (await Assert.ThrowsAsync<ConnectorException>(() => client.Pair(new string('c', 43), CancellationToken.None))).Code);
        Assert.Equal(2, fake.Calls.Count);
    }

    [Fact]
    public async Task PendingNeverAcknowledgesUntilWorkerCommitsResult()
    {
        var polls = 0;
        var fake = new Fake((function, args) => Receipt(args[1], function == "mail_import_db_status" && ++polls == 2 ? "done" : "pending", polls == 2 ? Ack : null));
        using var client = new PostgresClient(fake, Secret, pollInterval: TimeSpan.Zero);
        var state = new LocalState();
        var saved = 0;
        await new SyncEngine().Deliver(ProtocolTests.Scan(ProtocolTests.Item()), state, client, _ => saved++, CancellationToken.None);
        Assert.Single(state.Acknowledged);
        Assert.True(saved > 0);
        Assert.Equal(3, fake.Calls.Count);
        Assert.Single(fake.Calls.Select(c => c.Arguments[1]).Distinct());
    }

    [Fact]
    public async Task PendingTimeoutPreservesCheckpoint()
    {
        var fake = new Fake((_, args) => Receipt(args[1]));
        using var client = new PostgresClient(fake, Secret, TimeSpan.FromMilliseconds(30), TimeSpan.FromMilliseconds(5));
        var state = new LocalState();
        Assert.Equal("db_pending", (await Assert.ThrowsAsync<ConnectorException>(() => new SyncEngine().Deliver(
            ProtocolTests.Scan(ProtocolTests.Item()), state, client, _ => Assert.Fail("no ACK"), CancellationToken.None))).Code);
        Assert.Empty(state.Acknowledged);
        Assert.Null(state.LastSyncAt);
    }

    [Fact]
    public async Task PendingRequestSurvivesRestartAndReusesOriginalAck()
    {
        var state = new LocalState();
        using (var first = new PostgresClient(new Fake((_, args) => Receipt(args[1])), Secret,
            TimeSpan.FromMilliseconds(20), TimeSpan.FromMilliseconds(5), new PostgresRequestJournal(state, _ => { })))
            await Assert.ThrowsAsync<ConnectorException>(() => first.Sync(Batch, CancellationToken.None));
        var pending = Assert.IsType<DatabaseRequest>(state.PendingDatabaseRequest);
        var restored = JsonSerializer.Deserialize<LocalState>(Json(state), Protocol.Json)!;
        var retry = new Fake((_, args) => Receipt(args[1], "done", Ack));
        using var second = new PostgresClient(retry, Secret, journal: new PostgresRequestJournal(restored, _ => { }));
        Assert.Equal(1, (await second.Sync(Batch, CancellationToken.None)).Accepted);
        Assert.All(retry.Calls, call => Assert.Equal(pending.RequestId, call.Arguments[1]));
        Assert.Null(restored.PendingDatabaseRequest);
    }

    [Fact]
    public async Task ChangedScanDrainsOldReceiptButDoesNotReuseItsAck()
    {
        var previous = new DatabaseRequest(Guid.NewGuid(), Protocol.Hash("old payload"));
        var state = new LocalState { PendingDatabaseRequest = previous };
        var fake = new Fake((function, args) => Receipt(args[1], function == "mail_import_db_enqueue" ? "pending" : "done", Ack));
        using var client = new PostgresClient(fake, Secret, journal: new PostgresRequestJournal(state, _ => { }));
        await client.Sync(Batch, CancellationToken.None);
        Assert.Equal("mail_import_db_status", fake.Calls[0].Function);
        Assert.Equal(previous.RequestId, fake.Calls[0].Arguments[1]);
        Assert.Equal("mail_import_db_enqueue", fake.Calls[1].Function);
        Assert.NotEqual(previous.RequestId, fake.Calls[1].Arguments[1]);
        Assert.Equal(fake.Calls[1].Arguments[1], fake.Calls[2].Arguments[1]);
        Assert.Null(state.PendingDatabaseRequest);
    }

    [Fact]
    public async Task ChangedScanRecoversJournalWhenEnqueueNeverReachedServer()
    {
        var state = new LocalState { PendingDatabaseRequest = new(Guid.NewGuid(), Protocol.Hash("old payload")) };
        var oldId = state.PendingDatabaseRequest.RequestId;
        var fake = new Fake((function, args) => (Guid)args[1] == oldId
            ? Json(new { error_code = "request_not_found", error_status = 404 })
            : Receipt(args[1], function == "mail_import_db_enqueue" ? "pending" : "done", Ack));
        using var client = new PostgresClient(fake, Secret, journal: new PostgresRequestJournal(state, _ => { }));
        Assert.Equal(1, (await client.Sync(Batch, CancellationToken.None)).Accepted);
        Assert.Equal("mail_import_db_enqueue", fake.Calls[1].Function);
        Assert.Null(state.PendingDatabaseRequest);
    }

    [Fact]
    public async Task UnstructuredStatusDenialRetainsJournalAndMapsToAccessDenied()
    {
        var state = new LocalState();
        var fake = new Fake((function, args) => function == "mail_import_db_enqueue" ? Receipt(args[1])
            : Json(new { error_code = "invalid_device", error_status = 403 }));
        using var client = new PostgresClient(fake, Secret, journal: new PostgresRequestJournal(state, _ => { }));
        Assert.Equal("access_denied", (await Assert.ThrowsAsync<ConnectorException>(() => client.Sync(Batch, CancellationToken.None))).Code);
        Assert.NotNull(state.PendingDatabaseRequest);
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public async Task OnlyTerminalReceiptCanTriggerVersionConflictRecovery(bool terminal)
    {
        var state = new LocalState();
        var fake = new Fake((function, args) => terminal && function == "mail_import_db_enqueue" ? Receipt(args[1])
            : terminal ? Json(new
            {
                request_id = args[1], state = "error", error_code = "item_version_conflict", error_status = 409,
            })
            : Json(new { error_code = "item_version_conflict", error_status = 409 }));
        using var client = new PostgresClient(fake, Secret, journal: new PostgresRequestJournal(state, _ => { }));
        var error = await Assert.ThrowsAsync<ConnectorException>(() => client.Sync(Batch, CancellationToken.None));
        Assert.Equal(terminal ? "item_version_conflict" : "sync_conflict", error.Code);
        if (terminal) Assert.Null(state.PendingDatabaseRequest);
        else Assert.NotNull(state.PendingDatabaseRequest);
    }

    [Fact]
    public async Task JournalMustPersistBeforeEnqueueAndRetainsRequestOnSaveFailure()
    {
        var state = new LocalState();
        var fake = new Fake((_, args) => Receipt(args[1], "done", Ack));
        using var blocked = new PostgresClient(fake, Secret,
            journal: new PostgresRequestJournal(state, _ => throw new IOException("synthetic")));
        Assert.Equal("local_protection_failed", (await Assert.ThrowsAsync<ConnectorException>(() => blocked.Sync(Batch, CancellationToken.None))).Code);
        Assert.Empty(fake.Calls);
        Assert.Null(state.PendingDatabaseRequest);
        var saved = 0;
        using var afterAck = new PostgresClient(fake, Secret, journal: new PostgresRequestJournal(state, _ =>
        {
            if (++saved == 2) throw new IOException("synthetic");
        }));
        Assert.Equal("local_protection_failed", (await Assert.ThrowsAsync<ConnectorException>(() => afterAck.Sync(Batch, CancellationToken.None))).Code);
        Assert.NotNull(state.PendingDatabaseRequest);
    }

    [Fact]
    public async Task LostEnqueueResponseReusesRequestIdAndPayload()
    {
        var enqueue = 0;
        var fake = new Fake((function, args) => function == "mail_import_db_enqueue"
            ? ++enqueue == 1 ? throw new ConnectorException("db_unavailable") : Receipt(args[1])
            : Receipt(args[1], "done", Ack));
        using var client = new PostgresClient(fake, Secret, pollInterval: TimeSpan.Zero);
        Assert.Equal(1, (await client.Sync(Batch, CancellationToken.None)).Accepted);
        Assert.Equal(2, enqueue);
        Assert.Equal(fake.Calls[0].Arguments, fake.Calls[1].Arguments);
    }

    [Theory]
    [InlineData(401, "access_denied")]
    [InlineData(403, "access_denied")]
    [InlineData(409, "sync_conflict")]
    [InlineData(413, "batch_too_large")]
    [InlineData(429, "db_queue_full")]
    [InlineData(408, "db_pending")]
    [InlineData(500, "request_rejected")]
    public async Task ErrorsAreSanitizedAndNeverAcknowledged(int status, string expected)
    {
        var fake = new Fake((_, _) => Json(new { error_code = "private-value-must-not-escape", error_status = status }));
        using var client = new PostgresClient(fake, Secret);
        var error = await Assert.ThrowsAsync<ConnectorException>(() => client.Sync(Batch, CancellationToken.None));
        Assert.Equal(expected, error.Code);
        Assert.DoesNotContain("private-value", error.ToString());
        Assert.Single(fake.Calls);
    }

    [Theory]
    [InlineData("not json")]
    [InlineData("[]")]
    [InlineData("null")]
    [InlineData("{}")]
    [InlineData("{\"request_id\":4,\"state\":\"done\"}")]
    public async Task MalformedReceiptsCannotAdvanceCheckpoint(string response)
    {
        using var client = new PostgresClient(new Fake((_, _) => response), Secret);
        await Assert.ThrowsAsync<ConnectorException>(() => client.Sync(Batch, CancellationToken.None));
    }

    [Fact]
    public async Task WrongRequestIdAndIncompleteFinalAckAreRejected()
    {
        using var wrong = new PostgresClient(new Fake((_, _) => Receipt(Guid.NewGuid(), "done", Ack)), Secret);
        Assert.Equal("invalid_ack", (await Assert.ThrowsAsync<ConnectorException>(() => wrong.Sync(Batch, CancellationToken.None))).Code);
        using var incomplete = new PostgresClient(new Fake((function, args) => Receipt(args[1],
            function == "mail_import_db_enqueue" ? "pending" : "done", new { accepted = 1 })), Secret);
        await Assert.ThrowsAsync<ConnectorException>(() => incomplete.Sync(Batch, CancellationToken.None));
    }

    [Fact]
    public async Task CancellationAndMissingPairingDoNotContactDatabase()
    {
        var fake = new Fake((_, _) => throw new InvalidOperationException());
        using var unpaired = new PostgresClient(fake);
        Assert.Equal("not_paired", (await Assert.ThrowsAsync<ConnectorException>(() => unpaired.Sync(Batch, CancellationToken.None))).Code);
        using var paired = new PostgresClient(fake, Secret);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => paired.Sync(Batch, new CancellationToken(true)));
        Assert.Empty(fake.Calls);
    }

    private sealed class Fake(Func<string, object[], string> response) : IPostgresExecutor
    {
        internal List<(string Function, object[] Arguments)> Calls { get; } = [];
        public Task<string> Execute(string function, object[] arguments, CancellationToken cancellation)
        {
            Calls.Add((function, arguments));
            return Task.FromResult(response(function, arguments));
        }
        public void Dispose() { }
    }
}
