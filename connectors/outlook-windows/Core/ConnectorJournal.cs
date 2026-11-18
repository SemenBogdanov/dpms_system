namespace Dpms.OutlookConnector;

public enum JournalLevel { Info, Warning, Error }

public sealed record JournalEvent(DateTimeOffset At, JournalLevel Level, string Stage, string Code,
    string Message, string? Subject = null, DateTimeOffset? ReceivedAt = null, string? Reference = null)
{
    public string RedactedLine() => $"{At:yyyy-MM-dd HH:mm:ss zzz} {Level} {Stage} {Code} {Message}";

    public static string? LocalSubject(string? subject)
    {
        if (string.IsNullOrWhiteSpace(subject)) return null;
        var clean = new string(subject.Where(c => !char.IsControl(c) && char.GetUnicodeCategory(c)
            != System.Globalization.UnicodeCategory.Format).Take(160).ToArray()).Trim();
        return clean.Length > 0 ? clean : null;
    }
}

public sealed record LinkIncident(DateTimeOffset Since, string Code, bool Active = true, bool Notified = false)
{
    public static LinkIncident? Observe(LinkIncident? previous, LinkState status, string code, DateTimeOffset now) =>
        status switch
        {
            LinkState.Offline when previous is { Active: true } => previous,
            LinkState.Offline when previous is { Notified: false } => previous with { Active = true },
            LinkState.Offline => new LinkIncident(now, code),
            LinkState.Online when previous is { Notified: false } => previous with { Active = false },
            LinkState.Online => null,
            _ => previous,
        };

    public LinkIncident? ConfirmNotification() => Active ? this with { Notified = true } : null;
}
