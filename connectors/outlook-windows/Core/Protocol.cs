using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Dpms.OutlookConnector;

public static class Protocol
{
    public const int MaximumBody = 2_000_000;
    public const int MaximumAttachmentBytes = 10 * 1024 * 1024;
    public const int MaximumMessageAttachmentBytes = 20 * 1024 * 1024;
    public const int MaximumBatchBytes = 32 * 1024 * 1024;
    public static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = false,
        DefaultIgnoreCondition = JsonIgnoreCondition.Never,
    };

    public static string Hash(string value) =>
        Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(value)));

    public static Uri Server(string value)
    {
        if (!Uri.TryCreate(value.Trim(), UriKind.Absolute, out var uri)
            || uri.Scheme != "https" || uri.UserInfo.Length != 0
            || uri.AbsolutePath != "/" || uri.Query.Length != 0 || uri.Fragment.Length != 0)
            throw new ArgumentException("Укажите HTTPS-адрес сервера без пути, параметров и пароля.");
        return new Uri(uri.GetLeftPart(UriPartial.Authority) + "/");
    }

    public static string Limited(string? text, int length)
    {
        if (text?.Contains('\0') == true) throw new ConnectorException("unsupported_text");
        if (text?.Length > length) throw new ConnectorException("item_too_large");
        return text ?? "";
    }

    public static string? PlainBody(string? body, bool allowed)
    {
        if (!allowed) return null;
        if (body is { Length: > MaximumBody }) throw new ConnectorException("item_too_large");
        if (body?.Contains('\0') == true) throw new ConnectorException("unsupported_text");
        return body ?? "";
    }
}

public sealed record ImportedAttachment(
    string Filename, string ContentType, string DataBase64, string Sha256,
    bool IsInline = false, string ContentId = "");

public sealed record ImportedItem(
    string SourceId,
    string Kind,
    DateTimeOffset SourceModifiedAt,
    DateTimeOffset ReceivedAt,
    string Subject,
    string SenderName,
    string SenderAddress,
    string? BodyText,
    bool SourceIsRead,
    string? MeetingStatus = null,
    DateTimeOffset? StartsAt = null,
    DateTimeOffset? EndsAt = null,
    bool AllDay = false,
    string Location = "",
    string? MeetingKey = null,
    bool IsRecurring = false,
    string? BodyHtml = null,
    string ToRecipients = "",
    string CcRecipients = "",
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    IReadOnlyList<ImportedAttachment>? Attachments = null);

public sealed record ScanOptions(bool IncludeBody, bool IncludeAttachments = false, int HistoryDays = 30,
    int MaximumItems = 5000, IReadOnlyDictionary<string, string>? Acknowledged = null,
    IReadOnlyList<string>? PendingEntries = null, string? SnapshotMailboxId = null);
public sealed record ScanResult(
    string MailboxId, string MailboxLabel, string SourceState,
    List<ImportedItem> Items, int Skipped, bool Truncated, string? Error = null,
    IReadOnlyList<string>? RemainingEntries = null, IReadOnlyList<ScanSkipDetail>? SkipDetails = null);

public sealed record PairResult(
    Guid DeviceId, string DeviceSecret, string OwnerName, bool IncludeBody, int ProtocolVersion,
    bool IncludeAttachments = false);
public sealed record DeviceSession(
    string ServerUrl, Guid DeviceId, string DeviceSecret, string OwnerName, bool IncludeBody,
    bool IncludeAttachments = false, ConnectorTransport Transport = ConnectorTransport.Https,
    PostgresSettings? Database = null)
{
    public override string ToString() => "DeviceSession { redacted }";
}
public enum ConnectorTransport { Https = 0, PostgreSql = 1 }
public sealed record SyncBatch(
    string MailboxId, string MailboxLabel, string SourceState, IReadOnlyList<ImportedItem> Items,
    int ProtocolVersion = 1, bool ScanComplete = true, int SkippedItems = 0);
public sealed record SyncResult(
    int Accepted, int Created, int Updated, int Unchanged, int Stale, DateTimeOffset SyncedAt);
public sealed record DatabaseRequest(Guid RequestId, string PayloadHash);

public sealed class LocalState
{
    public DeviceSession? Session { get; set; }
    public Dictionary<string, string> Acknowledged { get; set; } = new();
    public DateTimeOffset? LastSyncAt { get; set; }
    public int HistoryDays { get; set; } = 30;
    public bool AutoSync { get; set; }
    public List<string> PendingEntries { get; set; } = [];
    public string? SnapshotMailboxId { get; set; }
    public int CycleSkipped { get; set; }
    public DatabaseRequest? PendingDatabaseRequest { get; set; }
}

public sealed class ConnectorException(string code) : Exception(code)
{
    public string Code { get; } = code;
}
