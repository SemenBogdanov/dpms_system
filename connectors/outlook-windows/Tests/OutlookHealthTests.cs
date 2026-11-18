using System.Runtime.InteropServices;
using System.Text.Json;
using Dpms.OutlookConnector;
using Xunit;

namespace Dpms.OutlookConnector.Tests;

public sealed class OutlookHealthTests
{
    [Theory]
    [InlineData(500, LinkState.Online, "ok")]
    [InlineData(600, LinkState.Online, "ok")]
    [InlineData(700, LinkState.Online, "ok")]
    [InlineData(800, LinkState.Online, "ok")]
    [InlineData(100, LinkState.Offline, "exchange_offline")]
    [InlineData(200, LinkState.Offline, "exchange_offline")]
    [InlineData(300, LinkState.Offline, "exchange_offline")]
    [InlineData(400, LinkState.Offline, "exchange_offline")]
    [InlineData(0, LinkState.Unknown, "exchange_unverified")]
    [InlineData(900, LinkState.Unknown, "exchange_unverified")]
    [InlineData(null, LinkState.Unknown, "exchange_unverified")]
    public void MapsOnlyDocumentedExchangeModes(int? mode, LinkState state, string code)
    {
        var result = OutlookHealth.ForAccount(OutlookHealth.ExchangeAccountType, mode, "hash", "Inbox");

        Assert.Equal(new OutlookProbeResult(true, state, code, "hash", "Inbox", "exchange"), result);
    }

    [Theory]
    [InlineData(1, "imap", "outlook_non_exchange")]
    [InlineData(2, "pop3", "outlook_non_exchange")]
    [InlineData(3, "http", "outlook_non_exchange")]
    [InlineData(4, "eas", "outlook_non_exchange")]
    [InlineData(5, "other", "outlook_non_exchange")]
    [InlineData(6, null, "outlook_unverified")]
    [InlineData(null, null, "outlook_unverified")]
    public void DoesNotInferLinkHealthWithoutAnExchangeAccount(int? accountType, string? name, string code)
    {
        foreach (var mode in new[] { 300, 800 })
        {
            var result = OutlookHealth.ForAccount(accountType, mode, "hash", "Inbox");

            Assert.Equal(new OutlookProbeResult(true, LinkState.Unknown, code, "hash", "Inbox", name), result);
        }
    }

    [Fact]
    public void ItemIssueKeepsOnlyBoundedSubjectAndOpaqueReferenceWithNumericComStatus()
    {
        const string entryId = "private-synthetic-entry-id";
        const int accessDenied = unchecked((int)0x80070005);
        var error = new COMException("private-synthetic-error", accessDenied);
        var received = new DateTimeOffset(2026, 11, 18, 12, 34, 56, TimeSpan.Zero);
        var issue = OutlookHealth.ItemIssue("hash", entryId, "Inbox\n\u202e item\0", received,
            ScanStage.Attachments, error);

        Assert.Matches("^[0-9a-f]{16}$", issue.Reference);
        Assert.Equal(issue.Reference, OutlookHealth.ItemIssue("hash", entryId, null, null, ScanStage.Body, error).Reference);
        Assert.NotEqual(issue.Reference, OutlookHealth.ItemIssue("other", entryId, null, null, ScanStage.Body, error).Reference);
        Assert.Equal("Inbox   item", issue.Subject);
        Assert.Equal(received, issue.ReceivedAt);
        Assert.Equal(ScanStage.Attachments, issue.Stage);
        Assert.Equal("outlook_com", issue.Code);
        Assert.Equal(accessDenied, issue.HResult);
        Assert.DoesNotContain("private-synthetic", JsonSerializer.Serialize(issue, Protocol.Json));
    }

    [Fact]
    public void ItemIssueOmitsUnavailableMetadataAndRejectsArbitraryCodes()
    {
        var issue = OutlookHealth.ItemIssue("hash", "entry", null, null, ScanStage.OpenItem,
            new ConnectorException("private-synthetic-reason"));

        Assert.Equal("outlook_read_failed", issue.Code);
        Assert.Null(issue.Subject);
        Assert.Null(issue.ReceivedAt);
        Assert.Null(issue.HResult);

        var prefix = new string('x', 199);
        var withLongSubject = OutlookHealth.ItemIssue("hash", "entry", prefix + "\U0001F4E7extra", null,
            ScanStage.Properties, new ConnectorException("source_changed_during_scan"));

        Assert.Equal("source_changed_during_scan", withLongSubject.Code);
        Assert.Equal(prefix, withLongSubject.Subject);
    }

    [Fact]
    public void PerItemIssueStaysInScanOutputAndIsNotIncludedInDelivery()
    {
        var issue = OutlookHealth.ItemIssue("hash", "entry", "synthetic-local-subject", null, ScanStage.Body,
            new ConnectorException("item_too_large"));
        var scan = new ScanResult("hash", "Inbox", "cached", [], 1, false, ItemIssues: [issue]);

        Assert.Contains("synthetic-local-subject", JsonSerializer.Serialize(scan, Protocol.Json));
        var batch = Assert.Single(SyncEngine.Batches(scan, []));
        Assert.Equal(1, batch.SkippedItems);
        var json = JsonSerializer.Serialize(batch, Protocol.Json);
        Assert.DoesNotContain("synthetic-local-subject", json);
        Assert.DoesNotContain(issue.Reference, json);
    }
}
