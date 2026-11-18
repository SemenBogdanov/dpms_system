using Dpms.OutlookConnector;
using Xunit;

namespace Dpms.OutlookConnector.Tests;

public sealed class QueuedDeliveryTests
{
    [Theory]
    [InlineData(LinkState.Offline, LinkState.Online)]
    [InlineData(LinkState.Online, LinkState.Offline)]
    [InlineData(LinkState.Unknown, LinkState.Online)]
    public async Task SpoolWaitsForBothLinksThenRestartsAndDeliversOnce(LinkState mail, LinkState dpms)
    {
        using var fixture = new Folder();
        var state = new LocalState { PendingEntries = ["AA", "BB"] };
        var scan = ProtocolTests.Scan(ProtocolTests.Item());
        var queue = fixture.Open();
        queue.Stage(scan, CancellationToken.None);
        var receiver = new Receiver();
        Assert.Null(await Send(queue, scan, state, receiver, _ => { }, mail, dpms));
        Assert.Equal(0, receiver.Calls);
        Assert.Equal(1, queue.WaitingCount);

        queue = fixture.Open();
        Assert.Equal(1, (await Send(queue, scan, state, receiver, _ => { }))?.Sent);
        Assert.Single(state.Acknowledged);
        Assert.Equal(new[] { "AA", "BB" }, state.PendingEntries);
        Assert.Equal(0, fixture.Open().WaitingCount);
        Assert.Equal(1, receiver.Calls);
    }

    [Fact]
    public async Task SaveFailureOrTransportErrorRetainsSpoolAndDoesNotAdvanceAck()
    {
        using var fixture = new Folder();
        var queue = fixture.Open();
        var state = new LocalState();
        var scan = ProtocolTests.Scan(ProtocolTests.Item());
        queue.Stage(scan, CancellationToken.None);
        await Assert.ThrowsAsync<ConnectorException>(() => Send(queue, scan, state,
            new Receiver("db_unavailable"), _ => { }));
        await Assert.ThrowsAsync<IOException>(() => Send(queue, scan, state, new Receiver(),
            _ => throw new IOException("synthetic disk failure")));
        Assert.Empty(state.Acknowledged);
        Assert.Equal(1, fixture.Open().WaitingCount);
    }

    [Fact]
    public async Task VersionConflictStaysInHeldQueueAndIdentifiesTheLetter()
    {
        using var fixture = new Folder();
        var queue = fixture.Open();
        var state = new LocalState();
        var scan = ProtocolTests.Scan(ProtocolTests.Item());
        queue.Stage(scan, CancellationToken.None);
        var conflicts = new List<ImportedItem>();
        var report = await QueuedDelivery.Send(queue, queue.ReadBatch(CancellationToken.None), scan,
            LinkState.Online, LinkState.Online, state, new Receiver("item_version_conflict"), _ => { },
            CancellationToken.None, conflicts.Add);
        Assert.Equal(1, report?.VersionConflicts);
        Assert.Equal(scan.Items[0].Subject, Assert.Single(conflicts).Subject);
        Assert.Equal(1, fixture.Open().HeldCount);
        Assert.Equal(0, fixture.Open().WaitingCount);
        Assert.Empty(state.Acknowledged);
    }

    [Fact]
    public async Task AnotherOutlookMailboxCannotSendAnExistingQueue()
    {
        using var fixture = new Folder();
        var queue = fixture.Open();
        var scan = ProtocolTests.Scan(ProtocolTests.Item());
        queue.Stage(scan, CancellationToken.None);
        var receiver = new Receiver();
        var other = scan with { MailboxId = new string('b', 64) };
        var error = await Assert.ThrowsAsync<ConnectorException>(() => Send(queue, other, new(), receiver, _ => { }));
        Assert.Equal("mailbox_mismatch", error.Code);
        Assert.Equal(0, receiver.Calls);
        Assert.Equal(1, queue.WaitingCount);
    }

    [Fact]
    public void AWeekOfflineDoesNotShrinkCaptureToTheLastDay()
    {
        var now = DateTimeOffset.Parse("2026-11-18T15:00:00Z");
        Assert.Equal(now.AddDays(-1), CaptureWindow.Since(now, 1, null));
        Assert.Equal(now.AddDays(-7).AddMinutes(-5), CaptureWindow.Since(now, 1, now.AddDays(-7)));
        Assert.Equal(now.AddDays(-30), CaptureWindow.Since(now, 30, now.AddDays(-5)));
    }

    [Fact]
    public void AlertRemainsPendingOnRecoveryAndDoesNotRepeatAfterReceipt()
    {
        var now = DateTimeOffset.Parse("2026-11-18T15:00:00Z");
        var offline = LinkIncident.Observe(null, LinkState.Offline, "db_unavailable", now)!;
        Assert.False(offline.Notified);
        var online = LinkIncident.Observe(offline, LinkState.Online, "dpms_ok", now.AddMinutes(1))!;
        Assert.False(online.Active);
        Assert.Null(online.ConfirmNotification());
        var reported = offline.ConfirmNotification()!;
        Assert.True(reported.Notified);
        Assert.Same(reported, LinkIncident.Observe(reported, LinkState.Offline, "db_unavailable", now.AddMinutes(60)));
        Assert.Null(LinkIncident.Observe(reported, LinkState.Online, "dpms_ok", now.AddMinutes(61)));
    }

    [Fact]
    public void CopiedDiagnosticsOmitSubjectAndItemId()
    {
        var entry = new JournalEvent(DateTimeOffset.Now, JournalLevel.Warning, "Outlook", "missing_item_identity",
            "Synthetic fixed message.", "Synthetic private subject", DateTimeOffset.Now, "private-id");
        Assert.DoesNotContain("Synthetic private subject", entry.RedactedLine());
        Assert.DoesNotContain("private-id", entry.RedactedLine());
        Assert.Contains("missing_item_identity", entry.RedactedLine());
    }

    private static Task<DeliveryReport?> Send(DurableOutbox queue, ScanResult scan, LocalState state, Receiver client,
        Action<LocalState> persist, LinkState mail = LinkState.Online, LinkState dpms = LinkState.Online) =>
        QueuedDelivery.Send(queue, queue.ReadBatch(CancellationToken.None), scan, mail, dpms, state, client, persist, CancellationToken.None);

    private sealed class Receiver(string? fail = null) : IIngestionClient
    {
        public int Calls { get; private set; }
        public Task<SyncResult> Sync(SyncBatch batch, CancellationToken cancellation)
        {
            Calls++;
            if (fail is not null && batch.Items.Count != 0) throw new ConnectorException(fail);
            return Task.FromResult(ProtocolTests.Ack(batch));
        }
    }

    private sealed class Folder : IDisposable
    {
        private readonly string root = Canonical(Directory.CreateTempSubdirectory("dpms-delivery-tests-"));
        private readonly Guid device = Guid.NewGuid();

        // The storage-specific tests exercise authenticated ciphertext; this fixture tests delivery decisions.
        private static byte[] Transform(byte[] bytes) => bytes.Select(value => (byte)(value ^ 0xa7)).ToArray();

        public DurableOutbox Open() => new(root, device, Transform, Transform);
        public void Dispose() => Directory.Delete(root, recursive: true);

        private static string Canonical(DirectoryInfo path)
        {
            if (path.Parent is not { } parent) return path.FullName;
            var actual = new DirectoryInfo(Path.Combine(Canonical(parent), path.Name));
            return actual.ResolveLinkTarget(true)?.FullName ?? actual.FullName;
        }
    }
}
