using System.Globalization;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text.Json;
using Dpms.OutlookConnector;

namespace Dpms.OutlookConnector.Desktop;

internal static class OutlookReader
{
    [DllImport("ole32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
    private static extern void CLSIDFromProgID(string progId, out Guid clsid);

    [DllImport("oleaut32.dll", PreserveSig = false)]
    private static extern void GetActiveObject(ref Guid clsid, IntPtr reserved,
        [MarshalAs(UnmanagedType.IUnknown)] out object result);

    public static ScanResult Scan(ScanOptions options)
    {
        if (options.HistoryDays is < 1 or > 90 || options.MaximumItems is < 1 or > 5000)
            throw new ConnectorException("invalid_scan_options");
        object? application = null, session = null, folder = null, items = null, filtered = null;
        try
        {
            CLSIDFromProgID("Outlook.Application", out var clsid);
            GetActiveObject(ref clsid, IntPtr.Zero, out application);
            session = ((dynamic)application).GetNamespace("MAPI");
            folder = ((dynamic)session).GetDefaultFolder(6); // olFolderInbox; no Calendar mutations.
            var storeId = (string)((dynamic)folder).StoreID;
            var folderId = (string)((dynamic)folder).EntryID;
            var smtp = MailboxAddress(session, storeId);
            if (string.IsNullOrWhiteSpace(smtp)) throw new ConnectorException("mailbox_identity_unavailable");
            var mailboxId = Protocol.Hash("outlook-mailbox:" + smtp.Trim().ToLowerInvariant());
            var sourceState = Read(() => (bool)((dynamic)session).Offline, true) ? "offline" : "cached";
            IReadOnlyList<string> snapshot;
            if (options.PendingEntries is { Count: > 0 } pending)
            {
                if (options.SnapshotMailboxId != mailboxId) throw new ConnectorException("mailbox_mismatch");
                ScanSnapshot.Validate(pending);
                snapshot = pending;
            }
            else
            {
                items = ((dynamic)folder).Items;
                var date = DateTime.Now.AddDays(-options.HistoryDays).ToString("g", CultureInfo.CurrentCulture);
                filtered = ((dynamic)items).Restrict("[ReceivedTime] >= '" + date + "'");
                ((dynamic)filtered).Sort("[ReceivedTime]", true);
                snapshot = CaptureEntries(filtered);
            }
            var remaining = new Queue<string>(snapshot);
            var result = new List<ImportedItem>();
            var diagnostics = new ScanDiagnostics();
            var visited = 0;
            var scannedBytes = 0L;
            while (remaining.Count > 0 && visited < options.MaximumItems)
            {
                object? item = null, parent = null;
                var stage = ScanStage.OpenItem;
                try
                {
                    item = ((dynamic)session).GetItemFromID(remaining.Peek(), storeId);
                    stage = ScanStage.VerifyInbox;
                    parent = ((dynamic)item).Parent;
                    var parentId = (string)((dynamic)parent).EntryID;
                    // One MAPI object can have different binary entry IDs. Let Outlook resolve identity.
                    if (!(bool)((dynamic)session).CompareEntryIDs(parentId, folderId))
                        throw new ConnectorException("source_left_inbox");
                    stage = ScanStage.MessageClass;
                    var messageClass = (string)((dynamic)item).MessageClass;
                    if (messageClass.StartsWith("IPM.Note", StringComparison.OrdinalIgnoreCase)
                        || messageClass.StartsWith("IPM.Schedule.Meeting", StringComparison.OrdinalIgnoreCase))
                    {
                        var parsed = ReadItem(item, messageClass, options.IncludeBody, options.IncludeAttachments, ref stage);
                        stage = ScanStage.Encode;
                        var alreadyDelivered = options.Acknowledged?.TryGetValue(mailboxId + ":" + parsed.SourceId, out var known) == true
                            && known == SyncEngine.Fingerprint(parsed);
                        if (!alreadyDelivered)
                        {
                            var bytes = JsonSerializer.SerializeToUtf8Bytes(parsed, Protocol.Json).Length;
                            if (bytes > 30_000_000) throw new ConnectorException("item_too_large");
                            if (scannedBytes + bytes > 60_000_000) break;
                            result.Add(parsed);
                            scannedBytes += bytes;
                        }
                    }
                }
                catch (Exception error) { diagnostics.Add(stage, error); }
                finally { Release(parent); Release(item); }
                remaining.Dequeue();
                visited++;
            }
            return new ScanResult(mailboxId, smtp.Length > 200 ? smtp[..200] : smtp, sourceState,
                result, diagnostics.Skipped, remaining.Count > 0, RemainingEntries: remaining.ToArray(),
                SkipDetails: diagnostics.Summary());
        }
        catch (ConnectorException) { throw; }
        catch (COMException) { throw new ConnectorException("outlook_unavailable"); }
        catch { throw new ConnectorException("outlook_scan_failed"); }
        finally
        {
            Release(filtered); Release(items); Release(folder); Release(session); Release(application);
        }
    }

    private static List<string> CaptureEntries(object items)
    {
        var count = (int)((dynamic)items).Count;
        if (count > 10_000) throw new ConnectorException("snapshot_too_large");
        var result = new List<string>();
        object? item = ((dynamic)items).GetFirst();
        try
        {
            while (item is not null)
            {
                result.Add((string)((dynamic)item).EntryID);
                if (result.Count > 10_000) throw new ConnectorException("snapshot_too_large");
                Release(item); item = null;
                item = ((dynamic)items).GetNext();
            }
        }
        finally { Release(item); }
        if ((int)((dynamic)items).Count != count || result.Count != count
            || result.Distinct(StringComparer.Ordinal).Count() != result.Count)
            throw new ConnectorException("source_changed_during_scan");
        ScanSnapshot.Validate(result);
        return result;
    }

    private static string MailboxAddress(object session, string storeId)
    {
        object? accounts = null;
        try
        {
            accounts = ((dynamic)session).Accounts;
            for (var i = 1; i <= Math.Min((int)((dynamic)accounts).Count, 100); i++)
            {
                object? account = null, deliveryStore = null;
                try
                {
                    account = ((dynamic)accounts)[i];
                    deliveryStore = ((dynamic)account).DeliveryStore;
                    if (deliveryStore is not null && (string)((dynamic)deliveryStore).StoreID == storeId)
                        return (string)((dynamic)account).SmtpAddress;
                }
                finally { Release(deliveryStore); Release(account); }
            }
            return "";
        }
        finally { Release(accounts); }
    }

    private static ImportedItem ReadItem(object value, string messageClass, bool includeBody, bool includeAttachments,
        ref ScanStage stage)
    {
        dynamic item = value;
        var meeting = messageClass.StartsWith("IPM.Schedule.Meeting", StringComparison.OrdinalIgnoreCase);
        var kind = meeting ? "meeting" : "mail";
        stage = ScanStage.DownloadState;
        if ((int)item.DownloadState != 1) throw new ConnectorException("source_not_downloaded"); // olFullItem
        stage = ScanStage.Identity;
        var id = ReadIdentity(value, kind);
        stage = ScanStage.Properties;
        var received = LocalDate((DateTime)item.ReceivedTime);
        var modified = LocalDate((DateTime)item.LastModificationTime);
        DateTimeOffset? start = null, end = null;
        var location = "";
        var allDay = false;
        var recurring = false;
        string? meetingKey = null;
        string? meetingStatus = null;
        if (meeting)
        {
            stage = ScanStage.Meeting;
            // Use this incoming message's properties, not a mutable associated Calendar item.
            var schedule = OutlookMapping.ReadMeeting(messageClass, name => PropertyValue(value, name));
            meetingStatus = schedule.Status;
            start = schedule.Start; end = schedule.End; allDay = schedule.AllDay;
            recurring = schedule.Recurring; location = schedule.Location; meetingKey = schedule.Identity;
        }
        stage = ScanStage.Properties;
        var senderAddress = Property(value, "http://schemas.microsoft.com/mapi/proptag/0x5D01001F");
        if (senderAddress.Length == 0) senderAddress = Read(() => (string)item.SenderEmailAddress, "");
        senderAddress = Protocol.Limited(senderAddress, 320);
        var subject = Protocol.Limited((string)item.Subject, 1000);
        var sender = Protocol.Limited(Read(() => (string)item.SenderName, ""), 300);
        var isRead = !(bool)item.UnRead;
        stage = ScanStage.Body;
        var body = includeBody ? Protocol.PlainBody((string)item.Body, true) : null;
        var html = includeBody && !meeting ? Protocol.PlainBody((string)item.HTMLBody, true) : null;
        stage = ScanStage.Recipients;
        var to = RecipientField(value, "To");
        var cc = RecipientField(value, "CC");
        stage = ScanStage.Attachments;
        var attachments = includeAttachments ? ReadAttachments(value) : [];
        stage = ScanStage.Properties;
        if (LocalDate((DateTime)item.LastModificationTime) != modified)
            throw new ConnectorException("source_changed_during_scan");
        return new ImportedItem(id, kind, modified, received, subject, sender, senderAddress, body, isRead,
            meetingStatus, start, end, allDay, location, meetingKey, recurring, html, to, cc, attachments);
    }

    private static string ReadIdentity(object item, string kind)
    {
        const int mapiNotFound = unchecked((int)0x8004010F);
        object? accessor = null;
        try
        {
            accessor = ((dynamic)item).PropertyAccessor;
            return OutlookMapping.ItemIdentity(kind, property =>
            {
                // Only an absent property permits switching keys, not a COM access or read failure.
                try { return (true, (object?)((dynamic)accessor).GetProperty(property)); }
                catch (COMException error) when (error.HResult == mapiNotFound) { return (false, null); }
            });
        }
        finally { Release(accessor); }
    }

    private static string RecipientField(object value, string field)
    {
        var text = Property(value, field == "To"
            ? "http://schemas.microsoft.com/mapi/proptag/0x0E04001F"
            : "http://schemas.microsoft.com/mapi/proptag/0x0E03001F");
        if (text.Length > 20_000) throw new ConnectorException("item_too_large");
        if (text.Contains('\0')) throw new ConnectorException("unsupported_text");
        return text;
    }

    private static List<ImportedAttachment> ReadAttachments(object item)
    {
        object? attachments = null;
        try
        {
            attachments = ((dynamic)item).Attachments;
            var count = (int)((dynamic)attachments).Count;
            if (count > 100) throw new ConnectorException("item_too_large");
            var result = new List<ImportedAttachment>();
            var total = 0L;
            for (var i = 1; i <= count; i++)
            {
                object? attachment = null;
                try
                {
                    attachment = ((dynamic)attachments)[i];
                    var type = (int)((dynamic)attachment).Type;
                    if (type is not (1 or 5 or 6)) throw new ConnectorException("unsupported_attachment");
                    if ((int)((dynamic)attachment).Size > Protocol.MaximumAttachmentBytes)
                        throw new ConnectorException("item_too_large");
                    var filename = Path.GetFileName((string)((dynamic)attachment).FileName);
                    if (filename.Length is 0 or > 255 || filename.Any(char.IsControl))
                        throw new ConnectorException("unsupported_attachment");
                    var bytes = AttachmentBytes(attachment);
                    try
                    {
                        total += bytes.Length;
                        if (bytes.Length > Protocol.MaximumAttachmentBytes || total > Protocol.MaximumMessageAttachmentBytes)
                            throw new ConnectorException("item_too_large");
                        var contentId = Property(attachment, "http://schemas.microsoft.com/mapi/proptag/0x3712001F");
                        var mime = Property(attachment, "http://schemas.microsoft.com/mapi/proptag/0x370E001F");
                        if (contentId.Length > 500 || mime.Length > 200) throw new ConnectorException("unsupported_attachment");
                        result.Add(new ImportedAttachment(filename, mime.Length == 0 ? "application/octet-stream" : mime,
                            Convert.ToBase64String(bytes), Convert.ToHexStringLower(SHA256.HashData(bytes)),
                            contentId.Length > 0, contentId));
                    }
                    finally { CryptographicOperations.ZeroMemory(bytes); }
                }
                finally { Release(attachment); }
            }
            return result;
        }
        finally { Release(attachments); }
    }

    private static byte[] AttachmentBytes(object attachment)
    {
        object? accessor = null;
        try
        {
            accessor = ((dynamic)attachment).PropertyAccessor;
            var bytes = ((dynamic)accessor).GetProperty("http://schemas.microsoft.com/mapi/proptag/0x37010102");
            if (bytes is byte[] data) return data;
        }
        catch (COMException error) when (error.HResult == unchecked((int)0x8004010F)
            || error.HResult == unchecked((int)0x8007000E))
        { /* Embedded/large values may require SaveAsFile; access/policy failures are not retried this way. */ }
        finally { Release(accessor); }

        var directory = new DirectoryInfo(Path.Combine(AttachmentStaging.Root, Guid.NewGuid().ToString("N")));
        var security = new DirectorySecurity();
        security.SetAccessRuleProtection(isProtected: true, preserveInheritance: false);
        security.AddAccessRule(new FileSystemAccessRule(WindowsIdentity.GetCurrent().User!,
            FileSystemRights.FullControl, InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit,
            PropagationFlags.None, AccessControlType.Allow));
        Directory.CreateDirectory(directory.Parent!.FullName);
        directory.Create(security);
        try
        {
            var path = Path.Combine(directory.FullName, "attachment.bin");
            ((dynamic)attachment).SaveAsFile(path);
            if (new FileInfo(path).Length > Protocol.MaximumAttachmentBytes)
                throw new ConnectorException("item_too_large");
            return File.ReadAllBytes(path);
        }
        finally { directory.Delete(recursive: true); }
    }

    private static DateTimeOffset LocalDate(DateTime value)
    {
        if (value.Year is < 1970 or > 2200) throw new ConnectorException("invalid_source_date");
        return new DateTimeOffset(DateTime.SpecifyKind(value, DateTimeKind.Local)).ToUniversalTime();
    }

    private static string Property(object item, string name) => PropertyValue(item, name) as string ?? "";

    private static object? PropertyValue(object item, string name)
    {
        object? accessor = null;
        try
        {
            accessor = ((dynamic)item).PropertyAccessor;
            return ((dynamic)accessor).GetProperty(name);
        }
        catch (COMException error) when (error.HResult == unchecked((int)0x8004010F)) { return null; }
        finally { Release(accessor); }
    }

    private static T Read<T>(Func<T> read, T fallback)
    {
        try { return read(); }
        catch (COMException error) when (error.HResult == unchecked((int)0x8004010F)) { return fallback; }
    }

    private static void Release(object? value)
    {
        if (value is not null && Marshal.IsComObject(value)) Marshal.ReleaseComObject(value);
    }
}
