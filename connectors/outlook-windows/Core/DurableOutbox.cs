using System.Security.Cryptography;
using System.Text.Json;

namespace Dpms.OutlookConnector;

public sealed record OutboxStageResult(int Added, bool Full);

public sealed record OutboxEntry(string Id, string MailboxId, string MailboxLabel, string SourceState,
    ImportedItem Item, DateTimeOffset QueuedAt)
{
    public override string ToString() => "OutboxEntry { redacted }";
}

public sealed record OutboxPreview(string Id, string Subject, DateTimeOffset ReceivedAt, bool Held)
{
    public override string ToString() => "OutboxPreview { redacted }";
}

public sealed class DurableOutbox
{
    private const long MaximumBytes = 256 * 1024 * 1024;
    private const int MaximumItems = 5000;
    private const int MaximumItemBytes = 30_000_000;
    private const int MaximumFileBytes = Protocol.MaximumBatchBytes + 1024 * 1024;
    private const int Format = 1;

    private readonly string directory;
    private readonly Guid deviceId;
    private readonly Func<byte[], byte[]> protect;
    private readonly Func<byte[], byte[]> unprotect;
    private readonly long byteLimit;
    private readonly int itemLimit;
    private readonly int batchTarget;
    private readonly Dictionary<string, FileEntry> index = new(StringComparer.Ordinal);
    private long usedBytes;
    private int retainedScratchItems;
    private DateTimeOffset lastQueuedAt;
    private bool needsReopen;

    public DurableOutbox(string root, Guid deviceId, Func<byte[], byte[]> protect, Func<byte[], byte[]> unprotect)
        : this(root, deviceId, protect, unprotect, MaximumBytes, MaximumItems, MaximumItemBytes) { }

    internal DurableOutbox(string root, Guid deviceId, Func<byte[], byte[]> protect, Func<byte[], byte[]> unprotect,
        long maximumBytes, int maximumItems, int batchTarget = MaximumItemBytes)
    {
        if (deviceId == Guid.Empty || string.IsNullOrWhiteSpace(root) || !Path.IsPathFullyQualified(root)) throw Invalid();
        if (maximumBytes is <= 0 or > MaximumBytes || maximumItems is <= 0 or > MaximumItems
            || batchTarget is <= 0 or > MaximumItemBytes) throw Invalid();
        ArgumentNullException.ThrowIfNull(protect);
        ArgumentNullException.ThrowIfNull(unprotect);
        this.deviceId = deviceId;
        this.protect = protect;
        this.unprotect = unprotect;
        byteLimit = maximumBytes;
        itemLimit = maximumItems;
        this.batchTarget = batchTarget;
        directory = Io(() => Path.Combine(Path.GetFullPath(root), deviceId.ToString("N")));
        Io(() =>
        {
            CheckDirectory(create: true);
            RebuildIndex();
        });
    }

    public int WaitingCount => index.Values.Count(file => file.State == FileState.Pending);
    public int HeldCount => index.Values.Count(file => file.State == FileState.Held);
    public string? MailboxId { get; private set; }

    public OutboxStageResult Stage(ScanResult scan, CancellationToken cancellation) => Io(() =>
    {
        cancellation.ThrowIfCancellationRequested();
        CheckDirectory();
        if (scan.Error is not null || scan.Items is null || scan.Items.Count > MaximumItems) throw Invalid();
        ValidateMailbox(scan.MailboxId, scan.MailboxLabel, scan.SourceState);
        if (MailboxId is not null && MailboxId != scan.MailboxId)
            throw new ConnectorException("outbox_mailbox_mismatch");
        var envelopeBytes = EnvelopeSize(scan.MailboxId, scan.MailboxLabel, scan.SourceState);
        var added = 0;
        foreach (var item in scan.Items)
        {
            cancellation.ThrowIfCancellationRequested();
            ValidateItem(item);
            var id = EntryId(scan.MailboxId, item);
            if (index.TryGetValue(id, out var existing))
            {
                // Keep the first capture even if the payload changed at the same revision.
                VerifyIndexed(existing);
                continue;
            }
            if (index.Count + retainedScratchItems >= itemLimit || usedBytes >= byteLimit) return new OutboxStageResult(added, true);
            var itemBytes = Measure(item);
            if (itemBytes > MaximumItemBytes || envelopeBytes + itemBytes > Protocol.MaximumBatchBytes)
                throw new ConnectorException("item_too_large");

            var now = DateTimeOffset.UtcNow;
            var queuedAt = now > lastQueuedAt ? now : lastQueuedAt.AddTicks(1);
            var entry = new OutboxEntry(id, scan.MailboxId, scan.MailboxLabel, scan.SourceState, item, queuedAt);
            var plain = JsonSerializer.SerializeToUtf8Bytes(new StoredEntry(Format, deviceId, entry), Protocol.Json);
            try
            {
                var encrypted = Transform(protect, plain);
                try
                {
                    if (encrypted.Length > MaximumFileBytes) throw ProtectionFailed();
                    if (usedBytes + encrypted.Length > byteLimit) return new OutboxStageResult(added, true);
                    cancellation.ThrowIfCancellationRequested();
                    var digest = Convert.ToHexStringLower(SHA256.HashData(encrypted));
                    WriteEntry(id, encrypted);
                    Add(new FileEntry(id, scan.MailboxId, item.SourceId, queuedAt, itemBytes, envelopeBytes,
                        encrypted.Length, digest, FileState.Pending, item.Subject, item.ReceivedAt));
                    added++;
                }
                finally { CryptographicOperations.ZeroMemory(encrypted); }
            }
            finally { CryptographicOperations.ZeroMemory(plain); }
        }
        return new OutboxStageResult(added, false);
    });

    public IReadOnlyList<OutboxEntry> ReadBatch(CancellationToken cancellation) => Io<IReadOnlyList<OutboxEntry>>(() =>
    {
        cancellation.ThrowIfCancellationRequested();
        CheckDirectory();
        var selected = new List<OutboxEntry>();
        var sources = new HashSet<string>(StringComparer.Ordinal);
        var size = 0;
        foreach (var file in Ordered())
        {
            cancellation.ThrowIfCancellationRequested();
            if (file.State != FileState.Pending || !sources.Add(file.SourceId)) continue;
            if (selected.Count == 0) size = file.EnvelopeBytes;
            var next = size + file.ItemBytes + (selected.Count == 0 ? 0 : 1);
            if (selected.Count != 0 && next > batchTarget) break;
            selected.Add(ReadIndexed(file));
            size = next;
            if (selected.Count == 50) break;
        }
        return selected;
    });

    public IReadOnlyList<OutboxPreview> Preview(int maximum = 200)
    {
        if (maximum < 0) throw Invalid();
        return Ordered().Take(maximum)
            .Select(file => new OutboxPreview(file.Id, file.Subject, file.ReceivedAt, file.State == FileState.Held))
            .ToArray();
    }

    // Only the delivery caller knows which entries a terminal ACK covers.
    public void Remove(string id) => Io(() =>
    {
        if (!IsId(id)) throw Invalid();
        CheckDirectory();
        if (!index.TryGetValue(id, out var file)) return;
        VerifyIndexed(file);
        File.Delete(PathFor(id, file.State));
        index.Remove(id);
        usedBytes -= file.Size;
        if (index.Count == 0) MailboxId = null;
    });

    public void Hold(string id) => Io(() =>
    {
        if (!IsId(id)) throw Invalid();
        CheckDirectory();
        if (!index.TryGetValue(id, out var file)) return;
        VerifyIndexed(file);
        if (file.State == FileState.Held) return;
        File.Move(PathFor(id, FileState.Pending), PathFor(id, FileState.Held));
        index[id] = file with { State = FileState.Held };
    });

    private void RebuildIndex()
    {
        var scratch = new List<string>();
        foreach (var path in Directory.EnumerateFileSystemEntries(directory))
        {
            var name = Path.GetFileName(path);
            if (name.Length <= 64 || !IsId(name[..64])) throw Invalid();
            var id = name[..64];
            var state = name[64..] switch
            {
                ".pending" => FileState.Pending,
                ".held" => FileState.Held,
                ".tmp" => FileState.Temporary,
                _ => throw Invalid(),
            };
            if (state == FileState.Temporary)
            {
                if (scratch.Count >= MaximumItems) throw Invalid();
                scratch.Add(id);
                continue;
            }
            var size = FileSize(path);
            if (index.Count >= MaximumItems || usedBytes + size > MaximumBytes || index.ContainsKey(id)) throw Invalid();
            var (_, file) = ReadFile(path, id, state, size);
            if (MailboxId is not null && MailboxId != file.MailboxId) throw Invalid();
            Add(file);
        }

        // Published files are authoritative, including held entries, even if a scratch name also survived.
        foreach (var id in scratch) RecoverScratch(id);
    }

    private void RecoverScratch(string id)
    {
        var path = PathFor(id, FileState.Temporary);
        var length = RegularFileLength(path);
        if (length > MaximumFileBytes) throw Invalid();
        if (length == 0)
        {
            DiscardScratch(id, length);
            return;
        }

        FileEntry file;
        try { (_, file) = ReadFile(path, id, FileState.Temporary, (int)length); }
        catch (ConnectorException error) when (error.Code == "outbox_protection_failed")
        {
            // A reserved scratch file never counted as queued. A torn write has no authenticated payload.
            DiscardScratch(id, length);
            return;
        }

        if (index.TryGetValue(id, out var committed))
        {
            if (committed.Digest != file.Digest) throw Invalid();
            DiscardScratch(id, length);
            return;
        }
        if (MailboxId is not null && MailboxId != file.MailboxId || index.Count + retainedScratchItems >= MaximumItems
            || usedBytes + file.Size > MaximumBytes) throw Invalid();
        using (var stream = new FileStream(path, FileMode.Open, FileAccess.Write, FileShare.None))
            stream.Flush(flushToDisk: true);
        File.Move(path, PathFor(id, FileState.Pending));
        Add(file with { State = FileState.Pending });
    }

    private void DiscardScratch(string id, long length)
    {
        var path = PathFor(id, FileState.Temporary);
        if (RegularFileLength(path) != length) throw Invalid();
        try { File.Delete(path); }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or System.Security.SecurityException)
        {
            // A locked scratch file does not hide committed mail, but still occupies spool space.
            retainedScratchItems++;
            usedBytes += length;
        }
    }

    private void Add(FileEntry file)
    {
        index.Add(file.Id, file);
        usedBytes += file.Size;
        MailboxId = file.MailboxId;
        if (file.QueuedAt > lastQueuedAt) lastQueuedAt = file.QueuedAt;
    }

    private IEnumerable<FileEntry> Ordered() => index.Values.OrderBy(file => file.QueuedAt)
        .ThenBy(file => file.Id, StringComparer.Ordinal);

    private OutboxEntry ReadIndexed(FileEntry expected)
    {
        var path = PathFor(expected.Id, expected.State);
        var size = FileSize(path);
        if (size != expected.Size) throw Invalid();
        var (entry, actual) = ReadFile(path, expected.Id, expected.State, size);
        if (expected != actual) throw Invalid();
        return entry;
    }

    private void VerifyIndexed(FileEntry file)
    {
        var path = PathFor(file.Id, file.State);
        if (FileSize(path) != file.Size) throw Invalid();
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (stream.Length != file.Size || Convert.ToHexStringLower(SHA256.HashData(stream)) != file.Digest) throw Invalid();
    }

    private (OutboxEntry Entry, FileEntry File) ReadFile(string path, string id, FileState state, int size)
    {
        var encrypted = new byte[size];
        byte[]? plain = null;
        try
        {
            using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
            {
                if (stream.Length != size) throw Invalid();
                stream.ReadExactly(encrypted);
            }
            var digest = Convert.ToHexStringLower(SHA256.HashData(encrypted));
            plain = Transform(unprotect, encrypted);
            if (plain.Length > Protocol.MaximumBatchBytes) throw Invalid();
            var stored = JsonSerializer.Deserialize<StoredEntry>(plain, Protocol.Json);
            if (stored is not { Version: Format, Entry: { } entry } || stored.DeviceId != deviceId
                || entry.Id != id || entry.QueuedAt == default || entry.QueuedAt == DateTimeOffset.MaxValue
                || entry.QueuedAt.Offset != TimeSpan.Zero) throw Invalid();
            ValidateMailbox(entry.MailboxId, entry.MailboxLabel, entry.SourceState);
            ValidateItem(entry.Item);
            if (EntryId(entry.MailboxId, entry.Item) != id) throw Invalid();
            var itemSize = Measure(entry.Item);
            var envelope = EnvelopeSize(entry.MailboxId, entry.MailboxLabel, entry.SourceState);
            if (itemSize > MaximumItemBytes || envelope + itemSize > Protocol.MaximumBatchBytes) throw Invalid();
            return (entry, new FileEntry(id, entry.MailboxId, entry.Item.SourceId, entry.QueuedAt, itemSize,
                envelope, size, digest, state, entry.Item.Subject, entry.Item.ReceivedAt));
        }
        catch (JsonException) { throw Invalid(); }
        finally
        {
            CryptographicOperations.ZeroMemory(encrypted);
            if (plain is not null) CryptographicOperations.ZeroMemory(plain);
        }
    }

    private void WriteEntry(string id, byte[] ciphertext)
    {
        var temporary = PathFor(id, FileState.Temporary);
        var pending = PathFor(id, FileState.Pending);
        if (Attributes(pending) is not null || Attributes(PathFor(id, FileState.Held)) is not null) throw Invalid();
        var created = false;
        var flushed = false;
        try
        {
            using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                created = true;
                stream.Write(ciphertext);
                stream.Flush(flushToDisk: true);
                flushed = true;
            }
            File.Move(temporary, pending);
        }
        catch
        {
            // Only an incomplete scratch file created in this call can be discarded.
            if (created && !flushed)
            {
                try { File.Delete(temporary); }
                catch (Exception error) when (error is IOException or UnauthorizedAccessException or System.Security.SecurityException)
                { needsReopen = true; }
            }
            else if (created) needsReopen = true;
            throw;
        }
    }

    private void CheckDirectory(bool create = false)
    {
        if (needsReopen) throw new ConnectorException("outbox_io_failed");
        var ancestors = new Stack<DirectoryInfo>();
        for (var entry = new DirectoryInfo(directory); entry is not null; entry = entry.Parent) ancestors.Push(entry);
        var volume = ancestors.Peek().FullName;
        if (OperatingSystem.IsWindows() && (volume.Length != 3 || !char.IsAsciiLetter(volume[0])
            || new DriveInfo(volume).DriveType == DriveType.Network)) throw Invalid();
        foreach (var ancestor in ancestors)
        {
            var attributes = Attributes(ancestor.FullName);
            if (attributes is null && create)
            {
                Directory.CreateDirectory(ancestor.FullName);
                attributes = Attributes(ancestor.FullName);
            }
            if (attributes is null || (attributes & (FileAttributes.Directory | FileAttributes.ReparsePoint))
                != FileAttributes.Directory) throw Invalid();
        }
    }

    private static int FileSize(string path)
    {
        var size = RegularFileLength(path);
        if (size is <= 0 or > MaximumFileBytes) throw Invalid();
        return (int)size;
    }

    private static long RegularFileLength(string path)
    {
        var attributes = Attributes(path);
        if (attributes is null || (attributes & (FileAttributes.Directory | FileAttributes.ReparsePoint | FileAttributes.Device)) != 0)
            throw Invalid();
        return new FileInfo(path).Length;
    }

    private static FileAttributes? Attributes(string path)
    {
        try { return File.GetAttributes(path); }
        catch (FileNotFoundException) { return null; }
        catch (DirectoryNotFoundException) { return null; }
    }

    private string PathFor(string id, FileState state) => Path.Combine(directory, id + (state switch
    {
        FileState.Pending => ".pending",
        FileState.Held => ".held",
        _ => ".tmp",
    }));

    private static string EntryId(string mailboxId, ImportedItem item) =>
        Protocol.Hash(FormattableString.Invariant($"outlook-outbox:v1:{mailboxId}:{item.SourceId}:{item.SourceModifiedAt.UtcTicks}"));

    private static bool IsId(string? id) => id is { Length: 64 } && id.All(c => c is >= '0' and <= '9' or >= 'a' and <= 'f');

    private static void ValidateMailbox(string id, string label, string sourceState)
    {
        if (!IsId(id) || label is null || label.Length > 200 || sourceState is not ("cached" or "offline" or "online"))
            throw Invalid();
    }

    private static void ValidateItem(ImportedItem item)
    {
        if (item is null || !IsId(item.SourceId) || item.Kind is not ("mail" or "meeting")
            || item.Subject is null || item.Subject.Length > 1000 || item.SourceModifiedAt == default || item.ReceivedAt == default)
            throw Invalid();
    }

    private static int EnvelopeSize(string mailboxId, string label, string sourceState) =>
        Measure(new SyncBatch(mailboxId, label, sourceState, [], ScanComplete: false, SkippedItems: 5000));

    private static int Measure<T>(T value)
    {
        var bytes = JsonSerializer.SerializeToUtf8Bytes(value, Protocol.Json);
        try { return bytes.Length; }
        finally { CryptographicOperations.ZeroMemory(bytes); }
    }

    private static byte[] Transform(Func<byte[], byte[]> transform, byte[] input)
    {
        byte[] output;
        try { output = transform(input); }
        catch (Exception) { throw ProtectionFailed(); }
        if (output is null || output.Length == 0) throw ProtectionFailed();
        if (!output.AsSpan().SequenceEqual(input)) return output;
        CryptographicOperations.ZeroMemory(output);
        throw ProtectionFailed();
    }

    private static T Io<T>(Func<T> action)
    {
        try { return action(); }
        catch (ArgumentException) { throw Invalid(); }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or System.Security.SecurityException)
        { throw new ConnectorException("outbox_io_failed"); }
    }

    private static void Io(Action action) => Io(() => { action(); return 0; });
    private static ConnectorException Invalid() => new("outbox_invalid");
    private static ConnectorException ProtectionFailed() => new("outbox_protection_failed");

    private enum FileState { Pending, Held, Temporary }
    private sealed record StoredEntry(int Version, Guid DeviceId, OutboxEntry Entry);
    private sealed record FileEntry(string Id, string MailboxId, string SourceId, DateTimeOffset QueuedAt,
        int ItemBytes, int EnvelopeBytes, int Size, string Digest, FileState State, string Subject, DateTimeOffset ReceivedAt);
}
