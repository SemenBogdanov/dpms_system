using System.Text.Json;
using Dpms.OutlookConnector;
using Xunit;

namespace Dpms.OutlookConnector.Tests;

public sealed class VersionConflictTests
{
    [Fact]
    public async Task SameVersionConflictDoesNotStopNewMailOrBecomeAnAcknowledgement()
    {
        var original = ProtocolTests.Item(1);
        var healthy = ProtocolTests.Item(2);
        var changed = original with { BodyHtml = "<p>Rebuilt synthetic HTML</p>" };
        var scan = ProtocolTests.Scan(changed, healthy);
        var key = scan.MailboxId + ":" + original.SourceId;
        var oldFingerprint = SyncEngine.Fingerprint(original);
        var state = new LocalState { Acknowledged = { [key] = oldFingerprint } };
        var client = new FixtureClient(item => item.SourceId == original.SourceId && item.SourceModifiedAt == original.SourceModifiedAt);

        var report = await Deliver(scan, state, client);

        Assert.Equal(1, report.Sent);
        Assert.Equal(1, report.Created);
        Assert.True(report.Incomplete);
        Assert.Equal(1, report.Skipped);
        Assert.Equal(1, report.VersionConflicts);
        Assert.Equal(oldFingerprint, state.Acknowledged[key]);
        Assert.Equal(original.SourceModifiedAt.UtcTicks, state.ConflictedVersions[key]);
        Assert.Equal(SyncEngine.Fingerprint(healthy), state.Acknowledged[scan.MailboxId + ":" + healthy.SourceId]);
        Assert.Empty(client.Batches[^1].Items);
        Assert.False(client.Batches[^1].ScanComplete);
        Assert.Equal(1, client.Batches[^1].SkippedItems);

        // Changing HTML at the same source timestamp does not trigger another rejected upload.
        var restored = JsonSerializer.Deserialize<LocalState>(JsonSerializer.Serialize(state, Protocol.Json), Protocol.Json)!;
        client.Batches.Clear();
        var repeat = await Deliver(ProtocolTests.Scan(changed with { BodyHtml = "<p>Another synthetic rendering</p>" }, healthy),
            restored, client);
        Assert.Equal(0, repeat.Sent);
        Assert.Equal(1, repeat.VersionConflicts);
        Assert.Empty(Assert.Single(client.Batches).Items);

        var newer = changed with { SourceModifiedAt = changed.SourceModifiedAt.AddSeconds(1) };
        client.Batches.Clear();
        var retried = await Deliver(ProtocolTests.Scan(newer, healthy), restored, client);
        Assert.Equal(1, retried.Sent);
        Assert.False(retried.Incomplete);
        Assert.Empty(restored.ConflictedVersions);
        Assert.Equal(SyncEngine.Fingerprint(newer), restored.Acknowledged[key]);
    }

    [Fact]
    public async Task RecoveryBudgetDoesNotAdvancePastUnresolvedMessages()
    {
        var items = Enumerable.Range(1, 50).Select(ProtocolTests.Item).ToArray();
        var scan = ProtocolTests.Scan(items) with { RemainingEntries = ["BB"] };
        var state = new LocalState { PendingEntries = ["AA", "BB"], SnapshotMailboxId = scan.MailboxId };
        var client = new FixtureClient(_ => true);

        var report = await Deliver(scan, state, client);

        Assert.True(report.ConflictCheckDeferred);
        Assert.True(report.Incomplete);
        Assert.Equal(0, report.Sent);
        Assert.Empty(state.Acknowledged);
        Assert.NotEmpty(state.ConflictedVersions);
        Assert.Equal(new[] { "AA", "BB" }, state.PendingEntries);
        Assert.Equal(18, client.Batches.Count); // Initial batch, bounded probes, then status heartbeat.
        Assert.Empty(client.Batches[^1].Items);
        Assert.False(client.Batches[^1].ScanComplete);
    }

    [Fact]
    public async Task OtherConflictsAreNotSplitOrSilentlySkipped()
    {
        var state = new LocalState();
        var client = new FixtureClient(_ => true, "sync_conflict");
        var error = await Assert.ThrowsAsync<ConnectorException>(() => Deliver(
            ProtocolTests.Scan(ProtocolTests.Item(1), ProtocolTests.Item(2)), state, client));

        Assert.Equal("sync_conflict", error.Code);
        Assert.Single(client.Batches);
        Assert.Empty(state.ConflictedVersions);
        Assert.Empty(state.Acknowledged);
    }

    [Fact]
    public async Task EarlyBatchDoesNotMarkScanCompleteBeforeLaterFailure()
    {
        var items = Enumerable.Range(1, 51).Select(ProtocolTests.Item).ToArray();
        var state = new LocalState();
        var client = new FixtureClient(item => item.SourceId == items[^1].SourceId, "sync_conflict");
        await Assert.ThrowsAsync<ConnectorException>(() => Deliver(ProtocolTests.Scan(items), state, client));
        Assert.Equal(2, client.Batches.Count);
        Assert.False(client.Batches[0].ScanComplete);
        Assert.Equal(50, state.Acknowledged.Count);
    }

    [Fact]
    public async Task CursorSaveFailurePreservesPreviousPageInMemory()
    {
        var scan = ProtocolTests.Scan(ProtocolTests.Item()) with { RemainingEntries = ["BB"] };
        var state = new LocalState { PendingEntries = ["AA", "BB"], SnapshotMailboxId = scan.MailboxId, CycleSkipped = 2 };
        var client = new FixtureClient(_ => false);
        var saves = 0;
        await Assert.ThrowsAsync<IOException>(() => new SyncEngine().Deliver(scan, state, client, _ =>
        {
            if (++saves == 2) throw new IOException("synthetic cursor save failure");
        }, CancellationToken.None));
        Assert.Single(state.Acknowledged);
        Assert.Equal(new[] { "AA", "BB" }, state.PendingEntries);
        Assert.Equal(scan.MailboxId, state.SnapshotMailboxId);
        Assert.Equal(2, state.CycleSkipped);
    }

    private static Task<DeliveryReport> Deliver(ScanResult scan, LocalState state, FixtureClient client) =>
        new SyncEngine().Deliver(scan, state, client, _ => { }, CancellationToken.None);

    private sealed class FixtureClient(Func<ImportedItem, bool> conflicts, string code = "item_version_conflict") : IIngestionClient
    {
        public List<SyncBatch> Batches { get; } = [];

        public Task<SyncResult> Sync(SyncBatch batch, CancellationToken cancellation)
        {
            Batches.Add(batch);
            if (batch.Items.Any(conflicts)) throw new ConnectorException(code);
            return Task.FromResult(ProtocolTests.Ack(batch));
        }
    }
}
