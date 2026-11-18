using System.Runtime.InteropServices;

namespace Dpms.OutlookConnector;

public enum ScanStage
{
    OpenItem, VerifyInbox, MessageClass, DownloadState, Identity, Properties, Meeting, Body, Recipients, Attachments, Encode,
}

public sealed record ScanSkipDetail(ScanStage Stage, string Code, int? HResult, int Count);

public sealed class ScanDiagnostics
{
    private const int MaximumDetailRows = 6;
    private readonly Dictionary<(ScanStage Stage, string Code, int? HResult), int> counts = new();

    public int Skipped { get; private set; }

    public void Add(ScanStage stage, Exception error)
    {
        // Diagnostics never carry exception messages or values read from Outlook.
        var code = error switch
        {
            ConnectorException { Code: "source_left_inbox" or "source_not_downloaded"
                or "missing_item_identity" or "invalid_item_identity" or "item_too_large" or "unsupported_attachment"
                or "unsupported_text" or "invalid_source_date" or "incomplete_meeting"
                or "source_changed_during_scan" } known => known.Code,
            COMException => "outlook_com",
            _ => "outlook_read_failed",
        };
        var key = (stage, code, error is COMException com ? com.ErrorCode : (int?)null);
        counts[key] = counts.GetValueOrDefault(key) + 1;
        Skipped++;
    }

    public IReadOnlyList<ScanSkipDetail> Summary() => counts.OrderByDescending(x => x.Value)
        .ThenBy(x => x.Key.Stage).ThenBy(x => x.Key.Code, StringComparer.Ordinal).ThenBy(x => x.Key.HResult)
        .Take(MaximumDetailRows)
        .Select(x => new ScanSkipDetail(x.Key.Stage, x.Key.Code, x.Key.HResult, x.Value)).ToArray();
}
