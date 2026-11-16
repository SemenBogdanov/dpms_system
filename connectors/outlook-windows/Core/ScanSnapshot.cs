namespace Dpms.OutlookConnector;

public static class ScanSnapshot
{
    public static void Validate(IReadOnlyList<string> entries)
    {
        if (entries.Count > 10_000 || entries.Sum(entry => (long)(entry?.Length ?? 0)) > 1_500_000)
            throw new ConnectorException("snapshot_too_large");
        if (entries.Any(entry => string.IsNullOrEmpty(entry) || entry.Length > 2048 || !entry.All(char.IsAsciiHexDigit)))
            throw new ConnectorException("invalid_snapshot");
    }
}
