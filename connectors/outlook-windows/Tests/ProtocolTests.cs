using System.Net;
using System.Text;
using System.Text.Json;
using Dpms.OutlookConnector;
using Xunit;

namespace Dpms.OutlookConnector.Tests;

public sealed class ProtocolTests
{
    internal static ImportedItem Item(int index = 1) => new(Protocol.Hash("item:" + index), "mail",
        DateTimeOffset.Parse("2026-11-16T10:00:00Z"), DateTimeOffset.Parse("2026-11-16T09:00:00Z"),
        "Synthetic subject", "Synthetic sender", "sender@example.invalid", null, false);

    internal static ScanResult Scan(params ImportedItem[] items) =>
        new(new string('a', 64), "Synthetic Inbox", "cached", items.ToList(), 0, false);

    [Theory]
    [InlineData("http://example.invalid")]
    [InlineData("https://user:pass@example.invalid")]
    [InlineData("https://example.invalid/api")]
    [InlineData("https://example.invalid/?secret=value")]
    [InlineData("https://example.invalid/#fragment")]
    [InlineData("not a URL")]
    public void ServerRejectsUnsafeOrigins(string value) => Assert.Throws<ArgumentException>(() => Protocol.Server(value));

    [Fact]
    public void ServerNormalizesHttpsOrigin() =>
        Assert.Equal("https://example.invalid:8443/", Protocol.Server(" https://example.invalid:8443 ").AbsoluteUri);

    [Fact]
    public void BodyIsNeverSilentlyTruncated()
    {
        var body = new string('x', Protocol.MaximumBody);
        Assert.Equal(body, Protocol.PlainBody(body, true));
        Assert.Null(Protocol.PlainBody(body + "x", false));
        Assert.Equal("item_too_large", Assert.Throws<ConnectorException>(() => Protocol.PlainBody(body + "x", true)).Code);
        Assert.Throws<ConnectorException>(() => Protocol.PlainBody("nul\0text", true));
        Assert.Throws<ConnectorException>(() => Protocol.Limited("oversized", 3));
    }

    [Fact]
    public void WireFormatMatchesServerContractAndOmitsAbsentAttachments()
    {
        var batch = new SyncBatch(new string('a', 64), "Synthetic", "cached", [Item()]);
        using var json = JsonDocument.Parse(JsonSerializer.Serialize(batch, Protocol.Json));
        Assert.Equal(1, json.RootElement.GetProperty("protocol_version").GetInt32());
        Assert.Equal("mail", json.RootElement.GetProperty("items")[0].GetProperty("kind").GetString());
        Assert.False(json.RootElement.GetProperty("items")[0].TryGetProperty("attachments", out _));
        var roundTrip = JsonSerializer.Deserialize<SyncBatch>(json.RootElement.GetRawText(), Protocol.Json)!;
        Assert.Equal(batch.MailboxId, roundTrip.MailboxId);
    }

    [Fact]
    public void FullContentWireFixtureIsAvailableForServerContractTest()
    {
        var bytes = Encoding.UTF8.GetBytes("Synthetic attachment\n");
        var item = Item() with
        {
            BodyText = "Synthetic full text", BodyHtml = "<p>Synthetic full text</p>",
            ToRecipients = "Recipient <recipient@example.invalid>", CcRecipients = "Copy <copy@example.invalid>",
            Attachments = [new ImportedAttachment("fixture.txt", "text/plain", Convert.ToBase64String(bytes),
                Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(bytes)))],
        };
        var json = JsonSerializer.Serialize(new SyncBatch(new string('a', 64), "Synthetic Inbox", "cached", [item]), Protocol.Json);
        Assert.Contains("data_base64", json);
        var output = Environment.GetEnvironmentVariable("OUTLOOK_SYNTHETIC_CONTRACT_OUTPUT");
        if (output is not null) File.WriteAllText(output, json, new UTF8Encoding(false));
    }

    [Fact]
    public void BatchesRespectCountAndCarryIncompleteSourceStatus()
    {
        var scan = Scan(Enumerable.Range(1, 101).Select(Item).ToArray()) with { Skipped = 2, Truncated = true };
        var batches = SyncEngine.Batches(scan, scan.Items).ToArray();
        Assert.Equal(new[] { 50, 50, 1 }, batches.Select(b => b.Items.Count));
        Assert.All(batches, b => { Assert.False(b.ScanComplete); Assert.Equal(2, b.SkippedItems); });
    }

    [Fact]
    public void BatchesAreBoundedByActualUtf8JsonSize()
    {
        var attachment = new ImportedAttachment("sample.bin", "application/octet-stream",
            Convert.ToBase64String(new byte[Protocol.MaximumAttachmentBytes]), Protocol.Hash("fixture"));
        var items = Enumerable.Range(1, 4).Select(i => Item(i) with { Attachments = [attachment] }).ToArray();
        var batches = SyncEngine.Batches(Scan(items), items).ToArray();
        Assert.True(batches.Length > 1);
        Assert.All(batches, b => Assert.True(JsonSerializer.SerializeToUtf8Bytes(b, Protocol.Json).Length <= Protocol.MaximumBatchBytes));
    }

    [Fact]
    public async Task CheckpointMovesOnlyAfterAckAndOnlyForSuccessfulBatches()
    {
        var scan = Scan(Enumerable.Range(1, 51).Select(Item).ToArray());
        var state = new LocalState();
        var persisted = new List<int>();
        var calls = 0;
        var client = new FakeClient(batch => ++calls == 2 ? throw new HttpRequestException("synthetic offline") : Ack(batch));
        await Assert.ThrowsAsync<HttpRequestException>(() => new SyncEngine().Deliver(scan, state, client,
            s => persisted.Add(s.Acknowledged.Count), CancellationToken.None));
        Assert.Equal(new[] { 50 }, persisted);
        Assert.Equal(50, state.Acknowledged.Count);
        var retry = new FakeClient(Ack);
        var report = await new SyncEngine().Deliver(scan, state, retry, _ => { }, CancellationToken.None);
        Assert.Equal(1, report.Sent);
        Assert.Equal(51, state.Acknowledged.Count);
    }

    [Fact]
    public async Task LostAckIsRetriedAndEmptyHeartbeatStillUpdatesLastDelivery()
    {
        var scan = Scan(Item());
        var state = new LocalState();
        await Assert.ThrowsAsync<HttpRequestException>(() => new SyncEngine().Deliver(scan, state,
            new FakeClient(_ => throw new HttpRequestException()), _ => Assert.Fail("must not persist"), CancellationToken.None));
        Assert.Empty(state.Acknowledged);
        var delivered = await new SyncEngine().Deliver(scan, state, new FakeClient(Ack), _ => { }, CancellationToken.None);
        Assert.Equal(1, delivered.Sent);
        var heartbeat = new FakeClient(Ack);
        var duplicate = await new SyncEngine().Deliver(scan, state, heartbeat, _ => { }, CancellationToken.None);
        Assert.Equal(0, duplicate.Sent);
        Assert.Empty(Assert.Single(heartbeat.Batches).Items);
        Assert.NotNull(state.LastSyncAt);
    }

    [Fact]
    public async Task ScanFailureAndCancellationDoNotAdvanceCheckpoint()
    {
        var client = new FakeClient(Ack);
        var state = new LocalState();
        await Assert.ThrowsAsync<ConnectorException>(() => new SyncEngine().Deliver(Scan(Item()) with { Error = "outlook_unavailable" },
            state, client, _ => Assert.Fail("must not persist"), CancellationToken.None));
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => new SyncEngine().Deliver(Scan(Item()),
            state, client, _ => Assert.Fail("must not persist"), new CancellationToken(canceled: true)));
        Assert.Empty(client.Batches);
        Assert.Empty(state.Acknowledged);
    }

    [Fact]
    public void AttachmentsAndReadChangesAffectLocalFingerprint()
    {
        var original = Item();
        Assert.NotEqual(SyncEngine.Fingerprint(original), SyncEngine.Fingerprint(original with { SourceIsRead = true }));
        Assert.NotEqual(SyncEngine.Fingerprint(original), SyncEngine.Fingerprint(original with
        {
            Attachments = [new ImportedAttachment("fixture.txt", "text/plain", "dGVzdA==", Protocol.Hash("test"))],
        }));
    }

    [Fact]
    public async Task SnapshotResumesPastFirstPageOnlyAfterAckAndCarriesIncompleteCycle()
    {
        var state = new LocalState();
        var page = Scan(Item()) with { RemainingEntries = ["CC", "DD"], Truncated = true, Skipped = 2 };
        await Assert.ThrowsAsync<HttpRequestException>(() => new SyncEngine().Deliver(page, state,
            new FakeClient(_ => throw new HttpRequestException()), _ => { }, CancellationToken.None));
        Assert.Empty(state.PendingEntries);
        await new SyncEngine().Deliver(page, state, new FakeClient(Ack), _ => { }, CancellationToken.None);
        Assert.Equal(new[] { "CC", "DD" }, state.PendingEntries);
        Assert.Equal(2, state.CycleSkipped);
        var lastClient = new FakeClient(Ack);
        var report = await new SyncEngine().Deliver(Scan(Item(5001)), state, lastClient, _ => { }, CancellationToken.None);
        Assert.False(Assert.Single(lastClient.Batches).ScanComplete);
        Assert.Equal(2, report.Skipped);
        Assert.Empty(state.PendingEntries);
        Assert.Equal(0, state.CycleSkipped);
    }

    [Fact]
    public async Task AcknowledgedPageCanAdvanceWithoutResendingItems()
    {
        var state = new LocalState();
        var client = new FakeClient(Ack);
        await new SyncEngine().Deliver(Scan() with { RemainingEntries = ["CC"], Truncated = true }, state, client, _ => { }, CancellationToken.None);
        Assert.Equal(new[] { "CC" }, state.PendingEntries);
        Assert.Empty(Assert.Single(client.Batches).Items);
    }

    [Fact]
    public async Task FailedTailPreservesPreviousPageCursor()
    {
        var state = new LocalState { PendingEntries = ["AA", "BB"] };
        var call = 0;
        var page = Scan(Enumerable.Range(1, 51).Select(Item).ToArray()) with { RemainingEntries = ["CC"], Truncated = true };
        await Assert.ThrowsAsync<HttpRequestException>(() => new SyncEngine().Deliver(page, state,
            new FakeClient(batch => ++call == 2 ? throw new HttpRequestException() : Ack(batch)), _ => { }, CancellationToken.None));
        Assert.Equal(new[] { "AA", "BB" }, state.PendingEntries);
        Assert.Equal(50, state.Acknowledged.Count);
    }

    [Fact]
    public async Task RemovingAnEarlierMessageCannotShiftThePendingSnapshot()
    {
        var inbox = new Dictionary<string, ImportedItem> { ["AA"] = Item(1), ["BB"] = Item(2), ["CC"] = Item(3), ["DD"] = Item(4) };
        var state = new LocalState();
        await new SyncEngine().Deliver(Scan(inbox["AA"], inbox["BB"]) with { RemainingEntries = ["CC", "DD"] },
            state, new FakeClient(Ack), _ => { }, CancellationToken.None);
        inbox.Remove("AA");
        var next = state.PendingEntries.Select(id => inbox[id]).ToArray();
        Assert.Equal(new[] { Item(3).SourceId, Item(4).SourceId }, next.Select(item => item.SourceId));
        var report = await new SyncEngine().Deliver(Scan(next), state, new FakeClient(Ack), _ => { }, CancellationToken.None);
        Assert.Equal(2, report.Sent);
        Assert.False(report.Incomplete);
    }

    [Fact]
    public void SnapshotIsBoundedAndContainsOnlyOpaqueEntryIdentifiers()
    {
        ScanSnapshot.Validate(["AABB", "ccdd"]);
        Assert.Throws<ConnectorException>(() => ScanSnapshot.Validate(["not an entry"]));
        Assert.Throws<ConnectorException>(() => ScanSnapshot.Validate(Enumerable.Repeat("AA", 10_001).ToArray()));
        Assert.Throws<ConnectorException>(() => ScanSnapshot.Validate(Enumerable.Repeat(new string('A', 2000), 1000).ToArray()));
    }

    [Fact]
    public void ExchangeIdentityKeepsTheExistingHashAndNeverReadsFallbacks()
    {
        var bytes = new byte[] { 1, 2, 3, 4 };
        var expected = Protocol.Hash("mail:exchange-source:01020304");
        Assert.Equal(expected, OutlookMapping.ItemIdentity("mail", property =>
        {
            Assert.Equal(OutlookMapping.SourceIdentity, property);
            return (true, bytes);
        }));
        var nonzeroBound = Array.CreateInstance(typeof(byte), [1], [3]);
        nonzeroBound.SetValue((byte)0x72, 3);
        Assert.Equal(Protocol.Hash("mail:exchange-source:72"), OutlookMapping.ItemIdentity("mail", _ => (true, nonzeroBound)));
    }

    private static string RecordIdentity(byte store = 1, byte record = 2, string kind = "mail") =>
        OutlookMapping.ItemIdentity(kind, property => property switch
        {
            OutlookMapping.SourceIdentity => (false, null),
            OutlookMapping.StoreRecordIdentity => (true, new byte[] { store }),
            OutlookMapping.ItemRecordIdentity => (true, new byte[] { record }),
            _ => throw new InvalidOperationException(),
        });

    [Fact]
    public async Task StoreScopedRecordIdentityIsDistinctAndReplaysWithoutDuplicateDelivery()
    {
        var id = RecordIdentity();
        Assert.Equal(Protocol.Hash("mail:mapi-record-v1:01:02"), id);
        Assert.NotEqual(id, RecordIdentity(store: 3));
        Assert.NotEqual(id, RecordIdentity(record: 3));
        Assert.NotEqual(id, RecordIdentity(kind: "meeting"));
        var state = new LocalState();
        var client = new FakeClient(Ack);
        var item = Item() with { SourceId = id };
        var first = await new SyncEngine().Deliver(Scan(item), state, client, _ => { }, CancellationToken.None);
        Assert.Equal(1, first.Sent);
        var second = await new SyncEngine().Deliver(Scan(item with { SourceId = RecordIdentity() }), state, client, _ => { }, CancellationToken.None);
        Assert.Equal(0, second.Sent);
        Assert.Empty(client.Batches[1].Items);
    }

    [Fact]
    public void IdentityDoesNotSwitchOnMalformedValuesOrReadFailures()
    {
        foreach (var malformed in new object?[] { null, Array.Empty<byte>(), new byte[4097], "entry-id" })
        {
            var error = Assert.Throws<ConnectorException>(() => OutlookMapping.ItemIdentity("mail", property =>
            {
                Assert.Equal(OutlookMapping.SourceIdentity, property);
                return (true, malformed);
            }));
            Assert.Equal("invalid_item_identity", error.Code);
        }
        Assert.Equal("missing_item_identity", Assert.Throws<ConnectorException>(() => OutlookMapping.ItemIdentity("mail",
            property => property == OutlookMapping.ItemRecordIdentity ? (true, new byte[] { 1 }) : (false, null))).Code);
        Assert.Throws<InvalidOperationException>(() => OutlookMapping.ItemIdentity("mail", _ => throw new InvalidOperationException()));
    }

    [Fact]
    public void MeetingUsesMessagePropertiesAndUtcDatesWithoutCalendarState()
    {
        var values = new Dictionary<string, object?>
        {
            [OutlookMapping.Meeting + "00260003"] = 0x00010000,
            [OutlookMapping.Appointment + "820D0040"] = new DateTime(2026, 11, 16, 10, 0, 0),
            [OutlookMapping.Appointment + "820E0040"] = new DateTime(2026, 11, 16, 11, 0, 0),
            [OutlookMapping.Appointment + "8215000B"] = true,
            [OutlookMapping.Appointment + "8223000B"] = true,
            [OutlookMapping.Appointment + "8208001F"] = "Synthetic room",
            [OutlookMapping.Meeting + "00230102"] = new byte[] { 4, 5, 6 },
        };
        var result = OutlookMapping.ReadMeeting("IPM.Schedule.Meeting.Request", name => values.GetValueOrDefault(name));
        Assert.Equal("updated", result.Status);
        Assert.Equal(TimeSpan.Zero, result.Start!.Value.Offset);
        Assert.Equal(10, result.Start.Value.Hour);
        Assert.True(result.AllDay);
        Assert.True(result.Recurring);
        Assert.Equal("Synthetic room", result.Location);
        Assert.NotNull(result.Identity);
        Assert.Equal("cancelled", OutlookMapping.ReadMeeting("IPM.Schedule.Meeting.Canceled", name => values.GetValueOrDefault(name)).Status);
    }

    [Fact]
    public void TransientMetadataFailureIsNotTurnedIntoAcknowledgedNulls()
    {
        Assert.Throws<InvalidOperationException>(() => OutlookMapping.ReadMeeting("IPM.Schedule.Meeting.Request",
            _ => throw new InvalidOperationException("synthetic transient failure")));
        Assert.Throws<ConnectorException>(() => OutlookMapping.ReadMeeting("IPM.Schedule.Meeting.Request",
            name => name.EndsWith("820D0040") ? new DateTime(2026, 11, 16) : null));
        var empty = OutlookMapping.ReadMeeting("IPM.Schedule.Meeting.Resp.Pos", _ => null);
        Assert.Equal("response", empty.Status);
        Assert.Null(empty.Start);
        Assert.Null(empty.End);
    }

    internal static SyncResult Ack(SyncBatch batch) => new(batch.Items.Count, batch.Items.Count, 0, 0, 0, DateTimeOffset.UtcNow);

    private sealed class FakeClient(Func<SyncBatch, SyncResult> response) : IIngestionClient
    {
        public List<SyncBatch> Batches { get; } = new();
        public Task<SyncResult> Sync(SyncBatch batch, CancellationToken cancellation)
        {
            Batches.Add(batch);
            return Task.FromResult(response(batch));
        }
    }
}

public sealed class HttpTests
{
    [Fact]
    public async Task HttpHealthCheckNeverSendsBearerOrMail()
    {
        using var client = new DpmsClient("https://example.invalid", "synthetic-device-value", new Handler(request =>
        {
            Assert.Equal(HttpMethod.Get, request.Method);
            Assert.Equal("/health", request.RequestUri?.AbsolutePath);
            Assert.Null(request.Headers.Authorization);
            Assert.Null(request.Content);
            return JsonResponse(new { status = "ok" });
        }));
        await client.CheckConnection(CancellationToken.None);
    }

    [Theory]
    [InlineData(401, "access_denied")]
    [InlineData(403, "access_denied")]
    [InlineData(404, "endpoint_unavailable")]
    [InlineData(409, "sync_conflict")]
    [InlineData(413, "batch_too_large")]
    [InlineData(429, "rate_limited")]
    [InlineData(302, "redirect_blocked")]
    [InlineData(503, "server_unavailable")]
    public async Task FailureNeverEchoesResponseContent(int status, string expected)
    {
        using var client = new DpmsClient("https://example.invalid", "synthetic-device-value", new Handler(_ =>
            new HttpResponseMessage((HttpStatusCode)status) { Content = new StringContent("PRIVATE MAIL TEXT") }));
        var error = await Assert.ThrowsAsync<ConnectorException>(() => client.Sync(Batch(), CancellationToken.None));
        Assert.Equal(expected, error.Code);
        Assert.DoesNotContain("PRIVATE", error.ToString());
    }

    [Fact]
    public async Task InvalidAckIsNotAccepted()
    {
        using var client = new DpmsClient("https://example.invalid", "synthetic-device-value", new Handler(_ =>
            JsonResponse(new SyncResult(0, 0, 0, 0, 0, DateTimeOffset.UtcNow))));
        Assert.Equal("invalid_ack", (await Assert.ThrowsAsync<ConnectorException>(() =>
            client.Sync(Batch(), CancellationToken.None))).Code);
    }

    [Fact]
    public async Task DeviceBearerAndRelativeEndpointAreUsed()
    {
        using var client = new DpmsClient("https://example.invalid", "synthetic-device-value", new Handler(request =>
        {
            Assert.Equal("https://example.invalid/api/mail-import/sync", request.RequestUri!.AbsoluteUri);
            Assert.Equal("Bearer", request.Headers.Authorization?.Scheme);
            Assert.Equal("synthetic-device-value", request.Headers.Authorization?.Parameter);
            Assert.Equal("application/json", request.Content!.Headers.ContentType!.MediaType);
            return JsonResponse(ProtocolTests.Ack(Batch()));
        }));
        Assert.Equal(1, (await client.Sync(Batch(), CancellationToken.None)).Accepted);
    }

    [Fact]
    public async Task PairRequiresSupportedProtocolAndDoesNotUseBearer()
    {
        using var client = new DpmsClient("https://example.invalid", handler: new Handler(request =>
        {
            Assert.Null(request.Headers.Authorization);
            return JsonResponse(new PairResult(Guid.NewGuid(), new string('x', 43), "Synthetic", true, 2, true));
        }));
        Assert.Equal("invalid_response", (await Assert.ThrowsAsync<ConnectorException>(() =>
            client.Pair(new string('p', 43), CancellationToken.None))).Code);
    }

    [Fact]
    public async Task OversizedOrInvalidResponseIsBounded()
    {
        foreach (var text in new[] { new string('x', 70_000), "not json" })
        {
            using var client = new DpmsClient("https://example.invalid", "synthetic-device-value", new Handler(_ =>
                new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(text) }));
            Assert.Equal("invalid_response", (await Assert.ThrowsAsync<ConnectorException>(() =>
                client.Sync(Batch(), CancellationToken.None))).Code);
        }
    }

    [Fact]
    public async Task DeadlineCoversBodyAfterSuccessfulHeaders()
    {
        using var client = new DpmsClient("https://example.invalid", "synthetic-device-value", new Handler(_ =>
            new HttpResponseMessage(HttpStatusCode.OK) { Content = new StreamContent(new NeverEndingStream()) }),
            requestTimeout: TimeSpan.FromMilliseconds(40));
        var task = client.Sync(Batch(), CancellationToken.None);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => task.WaitAsync(TimeSpan.FromSeconds(2)));
    }

    private static SyncBatch Batch() => new(new string('a', 64), "Synthetic", "cached", [ProtocolTests.Item()]);
    private static HttpResponseMessage JsonResponse<T>(T result) => new(HttpStatusCode.OK)
    { Content = new StringContent(JsonSerializer.Serialize(result, Protocol.Json), Encoding.UTF8, "application/json") };

    private sealed class Handler(Func<HttpRequestMessage, HttpResponseMessage> response) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) =>
            Task.FromResult(response(request));
    }

    private sealed class NeverEndingStream : Stream
    {
        public override bool CanRead => true;
        public override bool CanSeek => false;
        public override bool CanWrite => false;
        public override long Length => throw new NotSupportedException();
        public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
        public override void Flush() => throw new NotSupportedException();
        public override int Read(byte[] buffer, int offset, int count) => throw new NotSupportedException();
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
        public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
        {
            await Task.Delay(Timeout.Infinite, cancellationToken);
            return 0;
        }
    }
}
