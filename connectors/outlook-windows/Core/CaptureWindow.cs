namespace Dpms.OutlookConnector;

public static class CaptureWindow
{
    private static readonly TimeSpan Overlap = TimeSpan.FromMinutes(5);

    public static DateTimeOffset Since(DateTimeOffset now, int historyDays, DateTimeOffset? watermark)
    {
        var history = now.AddDays(-historyDays);
        if (watermark is { } previous && previous > DateTimeOffset.UnixEpoch)
        {
            // Keep the older bound after a long outage; overlap the Outlook minute-level filter.
            var recovery = previous - Overlap;
            if (recovery < history) return recovery;
        }
        return history;
    }
}
