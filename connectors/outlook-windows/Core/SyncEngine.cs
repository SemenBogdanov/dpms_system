using System.Text.Json;

namespace Dpms.OutlookConnector;

public sealed record DeliveryReport(int Sent, int Created, int Updated, int Stale, bool Incomplete,
    int Skipped = 0, int VersionConflicts = 0, bool ConflictCheckDeferred = false);

public sealed class SyncEngine
{
    public const int MaximumRememberedConflicts = 5000;
    private const int MaximumConflictProbes = 16;

    public async Task<DeliveryReport> Deliver(
        ScanResult scan, LocalState state, IIngestionClient client,
        Action<LocalState> persist, CancellationToken cancellation, bool advanceCursor = true,
        Action<ImportedItem>? onVersionConflict = null)
    {
        if (scan.Error is not null) throw new ConnectorException(scan.Error);
        if (scan.Items.Count > 5000 || scan.MailboxId.Length != 64)
            throw new ConnectorException("invalid_scan");
        ScanSnapshot.Validate(scan.RemainingEntries ?? []);
        scan = scan with
        {
            Skipped = Math.Min(5000, scan.Skipped + (advanceCursor ? state.CycleSkipped : 0)),
            Truncated = scan.Truncated || scan.RemainingEntries is { Count: > 0 },
        };
        var items = scan.Items.GroupBy(item => item.SourceId)
            .Select(group => group.OrderByDescending(item => item.SourceModifiedAt).First()).ToList();
        var fingerprints = new Dictionary<string, string>();
        var pending = new List<ImportedItem>();
        var versionConflicts = 0;
        foreach (var item in items)
        {
            cancellation.ThrowIfCancellationRequested();
            var fingerprint = Fingerprint(item);
            var key = CheckKey(scan, item);
            fingerprints[item.SourceId] = fingerprint;
            if (state.Acknowledged.TryGetValue(key, out var acknowledged) && acknowledged == fingerprint) continue;
            if (state.ConflictedVersions.TryGetValue(key, out var rejectedVersion)
                && rejectedVersion == item.SourceModifiedAt.UtcTicks)
            {
                versionConflicts++;
                onVersionConflict?.Invoke(item);
            }
            else pending.Add(item);
        }
        var previouslyKnownConflicts = versionConflicts;
        var probesLeft = MaximumConflictProbes;
        var sent = 0;
        var created = 0;
        var updated = 0;
        var stale = 0;
        var pageFinished = true;
        var batches = Batches(scan, pending).ToArray();
        for (var index = 0; index < batches.Length; index++)
        {
            // A later request in this page may still fail: only the final batch can declare it complete.
            var batch = batches[index];
            if (index < batches.Length - 1) batch = batch with { ScanComplete = false };
            if (await DeliverBatch(batch)) continue;
            pageFinished = false;
            break;
        }
        if (versionConflicts > previouslyKnownConflicts || !pageFinished)
            await DeliverBatch(Batch(scan with { Truncated = true }, []));

        var skipped = Skipped();
        if (pageFinished && advanceCursor)
        {
            // Do not advance the snapshot over a group that still needs conflict isolation.
            var previousEntries = state.PendingEntries;
            var previousMailbox = state.SnapshotMailboxId;
            var previousSkipped = state.CycleSkipped;
            state.PendingEntries = scan.RemainingEntries?.ToList() ?? [];
            state.SnapshotMailboxId = state.PendingEntries.Count > 0 ? scan.MailboxId : null;
            state.CycleSkipped = state.PendingEntries.Count == 0 ? 0 : skipped;
            try { persist(state); }
            catch
            {
                state.PendingEntries = previousEntries;
                state.SnapshotMailboxId = previousMailbox;
                state.CycleSkipped = previousSkipped;
                throw;
            }
        }
        return new DeliveryReport(sent, created, updated, stale, scan.Truncated || skipped != 0 || !pageFinished,
            skipped, versionConflicts, !pageFinished);

        int Skipped() => Math.Min(5000, scan.Skipped + versionConflicts);

        async Task<bool> DeliverBatch(SyncBatch batch, bool probe = false)
        {
            cancellation.ThrowIfCancellationRequested();
            if (probe)
            {
                if (probesLeft == 0) return false;
                probesLeft--;
            }
            SyncResult result;
            try
            {
                result = await client.Sync(batch with
                {
                    ScanComplete = batch.ScanComplete && !probe && Skipped() == 0,
                    SkippedItems = Skipped(),
                }, cancellation);
            }
            catch (ConnectorException error) when (error.Code == "item_version_conflict" && batch.Items.Count > 0)
            {
                if (batch.Items.Count == 1)
                {
                    RememberConflict(batch.Items[0]);
                    versionConflicts++;
                    onVersionConflict?.Invoke(batch.Items[0]);
                    return true;
                }
                // The rejected batch was atomic; split it without acknowledging any rejected item.
                var midpoint = batch.Items.Count / 2;
                return await DeliverBatch(batch with { Items = batch.Items.Take(midpoint).ToArray() }, probe: true)
                    && await DeliverBatch(batch with { Items = batch.Items.Skip(midpoint).ToArray() }, probe: true);
            }

            // No local checkpoint moves until the server has committed and acknowledged the batch.
            var previousAcks = state.Acknowledged;
            var previousConflicts = state.ConflictedVersions;
            var previousDelivery = state.LastSyncAt;
            var next = new Dictionary<string, string>(previousAcks);
            var nextConflicts = previousConflicts;
            foreach (var item in batch.Items)
            {
                var key = CheckKey(scan, item);
                next[key] = fingerprints[item.SourceId];
                if (nextConflicts.ContainsKey(key))
                {
                    if (ReferenceEquals(nextConflicts, previousConflicts))
                        nextConflicts = new Dictionary<string, long>(previousConflicts);
                    nextConflicts.Remove(key);
                }
            }
            if (next.Count > 10_000)
            {
                var current = items.Select(item => CheckKey(scan, item)).ToHashSet();
                next = next.Where(pair => current.Contains(pair.Key)).ToDictionary();
            }
            state.Acknowledged = next;
            state.ConflictedVersions = nextConflicts;
            state.LastSyncAt = result.SyncedAt;
            try { persist(state); }
            catch
            {
                // A spool item may be deleted only against a durable acknowledgement.
                state.Acknowledged = previousAcks;
                state.ConflictedVersions = previousConflicts;
                state.LastSyncAt = previousDelivery;
                throw;
            }
            sent += result.Accepted;
            created += result.Created;
            updated += result.Updated;
            stale += result.Stale;
            return true;
        }

        void RememberConflict(ImportedItem item)
        {
            var key = CheckKey(scan, item);
            var previous = state.ConflictedVersions;
            var next = new Dictionary<string, long>(previous) { [key] = item.SourceModifiedAt.UtcTicks };
            if (next.Count > MaximumRememberedConflicts)
                next.Remove(next.Where(entry => entry.Key != key).MinBy(entry => entry.Value).Key);
            state.ConflictedVersions = next;
            try { persist(state); }
            catch
            {
                state.ConflictedVersions = previous;
                throw;
            }
        }
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
