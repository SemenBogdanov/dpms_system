using System.Globalization;

namespace Dpms.OutlookConnector;

public enum LinkState { Unknown, Online, Offline }

public sealed record OutlookProbeResult(bool ClientAvailable, LinkState State, string Code,
    string? MailboxId = null, string? MailboxLabel = null, string? AccountType = null);

public sealed record OutlookItemIssue(string Reference, string? Subject, DateTimeOffset? ReceivedAt,
    ScanStage Stage, string Code, int? HResult);

public static class OutlookHealth
{
    public const int ExchangeAccountType = 0; // olExchange

    public static OutlookProbeResult ForAccount(int? accountType, int? connectionMode,
        string mailboxId, string mailboxLabel)
    {
        var type = accountType switch
        {
            ExchangeAccountType => "exchange",
            1 => "imap",
            2 => "pop3",
            3 => "http",
            4 => "eas",
            5 => "other",
            _ => null,
        };
        var (state, code) = accountType == ExchangeAccountType
            ? connectionMode switch
            {
                500 or 600 or 700 or 800 => (LinkState.Online, "ok"),
                100 or 200 or 300 or 400 => (LinkState.Offline, "exchange_offline"),
                _ => (LinkState.Unknown, "exchange_unverified"),
            }
            : (LinkState.Unknown, type is null ? "outlook_unverified" : "outlook_non_exchange");
        return new OutlookProbeResult(true, state, code, mailboxId, mailboxLabel, type);
    }

    public static OutlookItemIssue ItemIssue(string mailboxId, string entryId, string? subject,
        DateTimeOffset? receivedAt, ScanStage stage, Exception error)
    {
        // Use the same allowlist as the scan summary without retaining the exception.
        var diagnostic = new ScanDiagnostics();
        diagnostic.Add(stage, error);
        var detail = diagnostic.Summary()[0];
        var reference = Protocol.Hash("outlook-issue:" + mailboxId + ":" + entryId)[..16];
        return new OutlookItemIssue(reference, CleanSubject(subject), receivedAt, stage, detail.Code, detail.HResult);
    }

    private static string? CleanSubject(string? subject)
    {
        if (string.IsNullOrWhiteSpace(subject)) return null;
        var length = Math.Min(subject.Length, 200);
        if (char.IsHighSurrogate(subject[length - 1])) length--;
        var text = new string(subject[..length].Select(c =>
            char.IsWhiteSpace(c) || char.IsControl(c) || char.GetUnicodeCategory(c) == UnicodeCategory.Format
                ? ' ' : c).ToArray()).Trim();
        return text.Length == 0 ? null : text;
    }
}
