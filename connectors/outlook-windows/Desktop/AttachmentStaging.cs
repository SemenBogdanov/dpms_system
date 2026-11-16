namespace Dpms.OutlookConnector.Desktop;

internal static class AttachmentStaging
{
    internal static string Root => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "DPMS", "OutlookConnector", "staging");

    internal static void Cleanup()
    {
        if (!Directory.Exists(Root)) return;
        var root = new DirectoryInfo(Root);
        if (root.Attributes.HasFlag(FileAttributes.ReparsePoint))
            throw new ConnectorException("staging_cleanup_failed");
        try
        {
            foreach (var directory in root.EnumerateDirectories())
            {
                // Only this exporter owns these GUID directories; never traverse links or unrelated content.
                if (!Guid.TryParseExact(directory.Name, "N", out _) || directory.Attributes.HasFlag(FileAttributes.ReparsePoint))
                    throw new ConnectorException("staging_cleanup_failed");
                foreach (var file in directory.EnumerateFileSystemInfos())
                {
                    if (file.Name != "attachment.bin" || file.Attributes.HasFlag(FileAttributes.ReparsePoint)
                        || file.Attributes.HasFlag(FileAttributes.Directory))
                        throw new ConnectorException("staging_cleanup_failed");
                    file.Delete();
                }
                directory.Delete();
            }
        }
        catch (ConnectorException) { throw; }
        catch { throw new ConnectorException("staging_cleanup_failed"); }
    }
}
