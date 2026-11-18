using System.Runtime.InteropServices;
using System.Text.Json;
using Dpms.OutlookConnector;
using Xunit;

namespace Dpms.OutlookConnector.Tests;

public sealed class ScanDiagnosticsTests
{
    [Fact]
    public void GroupsSkipsAndBoundsDetailsWithoutLosingTheTotal()
    {
        var diagnostics = new ScanDiagnostics();
        foreach (var stage in Enum.GetValues<ScanStage>())
            diagnostics.Add(stage, new InvalidOperationException());
        for (var index = 0; index < 7; index++)
            diagnostics.Add(ScanStage.DownloadState, new ConnectorException("source_not_downloaded"));

        Assert.Equal(Enum.GetValues<ScanStage>().Length + 7, diagnostics.Skipped);
        var summary = diagnostics.Summary();
        Assert.Equal(6, summary.Count);
        Assert.Equal(new ScanSkipDetail(ScanStage.DownloadState, "source_not_downloaded", null, 7), summary[0]);
        Assert.True(summary.Sum(x => x.Count) < diagnostics.Skipped);
    }

    [Fact]
    public void KeepsOnlyKnownCodesAndNumericComStatusInLocalDetails()
    {
        var diagnostics = new ScanDiagnostics();
        const int accessDenied = unchecked((int)0x80070005);
        diagnostics.Add(ScanStage.Attachments, new COMException("private-synthetic-filename", accessDenied));
        diagnostics.Add(ScanStage.Body, new ConnectorException("private-synthetic-text"));

        var json = JsonSerializer.Serialize(diagnostics.Summary(), Protocol.Json);
        Assert.DoesNotContain("private-synthetic", json);
        var restored = JsonSerializer.Deserialize<ScanSkipDetail[]>(json, Protocol.Json)!;
        Assert.Contains(new ScanSkipDetail(ScanStage.Attachments, "outlook_com", accessDenied, 1), restored);
        Assert.Contains(new ScanSkipDetail(ScanStage.Body, "outlook_read_failed", null, 1), restored);
    }

    [Fact]
    public void DeliveryBatchContainsSkippedCountButNotLocalReasons()
    {
        var scan = new ScanResult(new string('a', 64), "Synthetic Inbox", "cached", [], 7, false,
            SkipDetails: [new ScanSkipDetail(ScanStage.Identity, "missing_item_identity", null, 7)]);
        var batch = Assert.Single(SyncEngine.Batches(scan, []));
        Assert.False(batch.ScanComplete);
        Assert.Equal(7, batch.SkippedItems);
        Assert.DoesNotContain("missing_item_identity", JsonSerializer.Serialize(batch, Protocol.Json));
    }
}
