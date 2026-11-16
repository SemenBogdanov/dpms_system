using System.Text.Json;

namespace Dpms.OutlookConnector;

public sealed record DeliveryReport(int Sent, int Created, int Updated, int Stale, bool Incomplete, int Skipped = 0);

public sealed class SyncEngine
{
    public async Task<DeliveryReport> Deliver(
        ScanResult scan, LocalState state, IIngestionClient client,
        Action<LocalState> persist, CancellationToken cancellation)
    {
        if (scan.Error is not null) throw new ConnectorException(scan.Error);
        if (scan.Items.Count > 5000 || scan.MailboxId.Length != 64)
            throw new ConnectorException("invalid_scan");
        ScanSnapshot.Validate(scan.RemainingEntries ?? []);
        scan = scan with
        {
            Skipped = Math.Min(5000, scan.Skipped + state.CycleSkipped),
            Truncated = scan.Truncated || scan.RemainingEntries is { Count: > 0 },
        };
        var items = scan.Items.GroupBy(item => item.SourceId)
            .Select(group => group.OrderByDescending(item => item.SourceModifiedAt).First()).ToList();
        var fingerprints = new Dictionary<string, string>();
        foreach (var item in items)
        {
            cancellation.ThrowIfCancellationRequested();
            fingerprints[item.SourceId] = Fingerprint(item);
        }
        var pending = items.Where(item =>
            !state.Acknowledged.TryGetValue(CheckKey(scan, item), out var hash) || hash != fingerprints[item.SourceId]).ToList();
        var sent = 0;
        var created = 0;
        var updated = 0;
        var stale = 0;
        foreach (var batch in Batches(scan, pending))
        {
            cancellation.ThrowIfCancellationRequested();
            var result = await client.Sync(batch, cancellation);
            // No local checkpoint moves until the server has committed and acknowledged the batch.
            var next = new Dictionary<string, string>(state.Acknowledged);
            foreach (var item in batch.Items) next[CheckKey(scan, item)] = fingerprints[item.SourceId];
            if (next.Count > 10_000)
            {
                var current = items.Select(item => CheckKey(scan, item)).ToHashSet();
                next = next.Where(pair => current.Contains(pair.Key)).ToDictionary();
            }
            state.Acknowledged = next;
            state.LastSyncAt = result.SyncedAt;
            persist(state);
            sent += result.Accepted;
            created += result.Created;
            updated += result.Updated;
            stale += result.Stale;
        }
        // Resume only after every batch in this page has an ACK. A failed save safely replays it.
        state.PendingEntries = scan.RemainingEntries?.ToList() ?? [];
        state.SnapshotMailboxId = state.PendingEntries.Count > 0 ? scan.MailboxId : null;
        state.CycleSkipped = state.PendingEntries.Count == 0 ? 0 : scan.Skipped;
        persist(state);
        return new DeliveryReport(sent, created, updated, stale, scan.Truncated || scan.Skipped != 0, scan.Skipped);
    }

    private static string CheckKey(ScanResult scan, ImportedItem item) => scan.MailboxId + ":" + item.SourceId;
    public static string Fingerprint(ImportedItem item) => Protocol.Hash(JsonSerializer.Serialize(item, Protocol.Json));

    public static IEnumerable<SyncBatch> Batches(ScanResult scan, IReadOnlyList<ImportedItem> items)
    {
        var current = new List<ImportedItem>();
        var envelopeSize = JsonSerializer.SerializeToUtf8Bytes(Batch(scan, []), Protocol.Json).Length;
        var currentSize = envelopeSize;
        foreach (var item in items)
        {
            var itemSize = JsonSerializer.SerializeToUtf8Bytes(item, Protocol.Json).Length;
            if (envelopeSize + itemSize > Protocol.MaximumBatchBytes)
                throw new ConnectorException("item_too_large");
            if (current.Count > 0 && (current.Count >= 50
                || currentSize + itemSize + 1 > 30_000_000))
            {
                yield return Batch(scan, current.ToArray());
                current.Clear();
                currentSize = envelopeSize;
            }
            currentSize += itemSize + (current.Count > 0 ? 1 : 0);
            current.Add(item);
        }
        // Empty heartbeat updates last_sync_at even when all source records were already delivered.
        if (current.Count != 0 || items.Count == 0)
            yield return Batch(scan, current.ToArray());
    }

    private static SyncBatch Batch(ScanResult scan, IReadOnlyList<ImportedItem> items) =>
        new(scan.MailboxId, scan.MailboxLabel, scan.SourceState, items,
            ScanComplete: !scan.Truncated && scan.Skipped == 0, SkippedItems: scan.Skipped);
}
