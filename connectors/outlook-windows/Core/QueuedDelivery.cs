namespace Dpms.OutlookConnector;

public static class QueuedDelivery
{
    public static bool CanSend(LinkState mail, LinkState dpms) =>
        mail == LinkState.Online && dpms == LinkState.Online;

    public static async Task<DeliveryReport?> Send(
        DurableOutbox queue, IReadOnlyList<OutboxEntry> entries, ScanResult scan, LinkState mail, LinkState dpms,
        LocalState state, IIngestionClient client, Action<LocalState> persist, CancellationToken cancellation,
        Action<ImportedItem>? onVersionConflict = null)
    {
        cancellation.ThrowIfCancellationRequested();
        if (!CanSend(mail, dpms)) return null;
        if (entries.Any(entry => entry.MailboxId != scan.MailboxId)
            || queue.MailboxId is { } queuedMailbox && queuedMailbox != scan.MailboxId)
            throw new ConnectorException("mailbox_mismatch");
        var reportScan = scan with
        {
            Items = entries.Select(entry => entry.Item).ToList(),
            Skipped = Math.Min(5000, scan.Skipped + queue.HeldCount),
            Truncated = scan.Truncated || entries.Count < queue.WaitingCount,
            RemainingEntries = null, SkipDetails = null, ItemIssues = null,
        };
        try
        {
            return await new SyncEngine().Deliver(reportScan, state, client, persist, cancellation, advanceCursor: false,
                onVersionConflict: onVersionConflict);
        }
        finally
        {
            // Reconcile only durable ACKs and isolated version conflicts; a transport failure is neither.
            foreach (var entry in entries)
            {
                var key = entry.MailboxId + ":" + entry.Item.SourceId;
                if (state.Acknowledged.TryGetValue(key, out var ack) && ack == SyncEngine.Fingerprint(entry.Item))
                    queue.Remove(entry.Id);
                else if (state.ConflictedVersions.TryGetValue(key, out var rejected) && rejected == entry.Item.SourceModifiedAt.UtcTicks)
                    queue.Hold(entry.Id);
            }
        }
    }
}
