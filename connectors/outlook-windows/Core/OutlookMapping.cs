namespace Dpms.OutlookConnector;

public sealed record MeetingDetails(string Status, DateTimeOffset? Start, DateTimeOffset? End,
    bool AllDay, string Location, string? Identity, bool Recurring);

public static class OutlookMapping
{
    public const string SourceIdentity = "http://schemas.microsoft.com/mapi/proptag/0x65E00102";
    public const string StoreRecordIdentity = "http://schemas.microsoft.com/mapi/proptag/0x0FFA0102";
    public const string ItemRecordIdentity = "http://schemas.microsoft.com/mapi/proptag/0x0FF90102";
    public const string Appointment = "http://schemas.microsoft.com/mapi/id/{00062002-0000-0000-C000-000000000046}/";
    public const string Meeting = "http://schemas.microsoft.com/mapi/id/{6ED8DA90-450B-101B-98DA-00AA003F1305}/";

    public static string ItemIdentity(string kind, Func<string, (bool Present, object? Value)> read)
    {
        var source = read(SourceIdentity);
        if (source.Present)
            return Protocol.Hash(kind + ":exchange-source:" + BinaryKey(source.Value));

        // A record key is unique only in its store; namespace it with the store record key.
        var record = read(ItemRecordIdentity);
        if (!record.Present)
            throw new ConnectorException("missing_item_identity");
        var store = read(StoreRecordIdentity);
        if (!store.Present)
            throw new ConnectorException("missing_item_identity");
        return Protocol.Hash(kind + ":mapi-record-v1:" + BinaryKey(store.Value) + ":" + BinaryKey(record.Value));
    }

    private static string BinaryKey(object? value)
    {
        if (value is byte[] { Length: > 0 and <= 4096 } bytes)
            return Convert.ToHexStringLower(bytes);
        // COM can return a one-dimensional byte SAFEARRAY with a nonzero lower bound.
        if (value is Array { Rank: 1, Length: > 0 and <= 4096 } array
            && array.GetType().GetElementType() == typeof(byte))
            return Convert.ToHexStringLower(array.Cast<byte>().ToArray());
        throw new ConnectorException("invalid_item_identity");
    }

    public static MeetingDetails ReadMeeting(string messageClass, Func<string, object?> read)
    {
        var status = messageClass.Contains("Canceled", StringComparison.OrdinalIgnoreCase) ? "cancelled"
            : messageClass.Contains("Resp", StringComparison.OrdinalIgnoreCase) ? "response"
            : read(Meeting + "00260003") is int type && type is 0x00010000 or 0x00020000 ? "updated" : "invited";
        var start = Date(read(Appointment + "820D0040"));
        var end = Date(read(Appointment + "820E0040"));
        if ((start is null) != (end is null) || end < start)
            throw new ConnectorException("incomplete_meeting");
        var identity = read(Meeting + "00230102") ?? read(Meeting + "00030102");
        if (identity is not null and not byte[]) throw new ConnectorException("incomplete_meeting");
        return new MeetingDetails(status, start, end,
            read(Appointment + "8215000B") is true,
            Protocol.Limited(read(Appointment + "8208001F") as string, 1000),
            identity is byte[] { Length: > 0 } bytes ? Protocol.Hash("outlook-meeting:" + Convert.ToHexStringLower(bytes)) : null,
            read(Appointment + "8223000B") is true);
    }

    private static DateTimeOffset? Date(object? value)
    {
        if (value is null) return null;
        if (value is not DateTime time || time.Year is < 1970 or > 2200)
            throw new ConnectorException("invalid_source_date");
        return new DateTimeOffset(DateTime.SpecifyKind(time, DateTimeKind.Utc));
    }
}
