using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Dpms.OutlookConnector;
using Xunit;

namespace Dpms.OutlookConnector.Tests;

public sealed class DurableOutboxTests
{
    private static readonly CancellationToken None = CancellationToken.None;

    [Fact]
    public void CapturedContentSurvivesRestartAsCiphertextAndPlainBuffersAreCleared()
    {
        using var fixture = new Fixture();
        byte[]? writtenPlaintext = null;
        byte[]? readPlaintext = null;
        var item = ProtocolTests.Item() with
        {
            Subject = "Synthetic private subject",
            BodyText = "Synthetic private body",
            Attachments = [new ImportedAttachment("synthetic.txt", "text/plain", "dGVzdA==", Protocol.Hash("test"))],
        };
        var spool = new DurableOutbox(fixture.Root, fixture.Device, bytes =>
        {
            writtenPlaintext = bytes;
            return fixture.Protect(bytes);
        }, fixture.Unprotect);

        Assert.Equal(new OutboxStageResult(1, false), spool.Stage(ProtocolTests.Scan(item), None));
        Assert.All(Assert.IsType<byte[]>(writtenPlaintext), value => Assert.Equal(0, value));
        var path = Assert.Single(fixture.Files());
        var ciphertext = File.ReadAllBytes(path);
        Assert.Equal(-1, ciphertext.AsSpan().IndexOf(Encoding.UTF8.GetBytes(item.Subject)));
        Assert.Equal(-1, ciphertext.AsSpan().IndexOf(Encoding.UTF8.GetBytes(item.BodyText)));
        Assert.DoesNotContain(item.Subject, Path.GetFileName(path));

        var restored = new DurableOutbox(fixture.Root, fixture.Device, fixture.Protect, bytes =>
            readPlaintext = fixture.Unprotect(bytes));
        Assert.Equal(1, restored.WaitingCount);
        Assert.Equal(0, restored.HeldCount);
        Assert.Equal(ProtocolTests.Scan().MailboxId, restored.MailboxId);
        var stored = Assert.Single(restored.ReadBatch(None));
        Assert.Equal(SyncEngine.Fingerprint(item), SyncEngine.Fingerprint(stored.Item));
        var preview = Assert.Single(restored.Preview());
        Assert.Equal(new OutboxPreview(stored.Id, item.Subject, item.ReceivedAt, false), preview);
        Assert.DoesNotContain(item.Subject, stored.ToString());
        Assert.DoesNotContain(item.Subject, preview.ToString());
        Assert.All(Assert.IsType<byte[]>(readPlaintext), value => Assert.Equal(0, value));
    }

    [Fact]
    public void PreviewUsesOnlyMetadataCachedOnStageAndReopen()
    {
        using var fixture = new Fixture();
        var item = ProtocolTests.Item() with { Subject = "Cached synthetic subject", BodyText = "Not needed for preview" };
        var reads = 0;
        DurableOutbox Open() => new(fixture.Root, fixture.Device, fixture.Protect, bytes =>
        {
            reads++;
            return fixture.Unprotect(bytes);
        });

        var spool = Open();
        spool.Stage(ProtocolTests.Scan(item), None);
        var preview = Assert.Single(spool.Preview());
        Assert.Equal(item.Subject, preview.Subject);
        Assert.Equal(item.ReceivedAt, preview.ReceivedAt);
        Assert.Equal(0, reads);
        spool.Hold(preview.Id);
        Assert.True(Assert.Single(spool.Preview()).Held);
        Assert.Equal(0, reads);

        var restored = Open();
        Assert.Equal(1, reads);
        var path = fixture.DevicePath();
        var moved = path + ".moved";
        Directory.Move(path, moved);
        try
        {
            Assert.Equal(preview with { Held = true }, Assert.Single(restored.Preview()));
            Assert.Equal(1, reads);
        }
        finally { Directory.Move(moved, path); }
    }

    [Fact]
    public void SameUtcRevisionKeepsFirstCaptureAndNewerRevisionWaitsSeparately()
    {
        using var fixture = new Fixture();
        var first = ProtocolTests.Item() with { Subject = "First capture" };
        var same = first with { Subject = "Later rendering", SourceModifiedAt = first.SourceModifiedAt.ToOffset(TimeSpan.FromHours(3)) };
        var next = same with { SourceModifiedAt = same.SourceModifiedAt.AddTicks(1) };
        var spool = fixture.Open();
        Assert.Equal(new OutboxStageResult(1, false), spool.Stage(ProtocolTests.Scan(first), None));
        var original = Assert.Single(spool.ReadBatch(None));
        var ciphertext = File.ReadAllBytes(Assert.Single(fixture.Files()));

        spool = fixture.Open();
        Assert.Equal(new OutboxStageResult(0, false), spool.Stage(ProtocolTests.Scan(same), None));
        Assert.Equal(ciphertext, File.ReadAllBytes(Assert.Single(fixture.Files())));
        Assert.Equal(new OutboxStageResult(1, false), spool.Stage(ProtocolTests.Scan(next), None));
        Assert.Equal(2, spool.WaitingCount);
        Assert.Equal(original, Assert.Single(spool.ReadBatch(None)));

        spool.Remove(original.Id);
        var updated = Assert.Single(spool.ReadBatch(None));
        Assert.NotEqual(original.Id, updated.Id);
        Assert.Equal(next, updated.Item);
        spool.Remove(original.Id);
        Assert.Equal(1, fixture.Open().WaitingCount);
    }

    [Fact]
    public void HeldPayloadStaysQueuedButNeverReturnsForDelivery()
    {
        using var fixture = new Fixture();
        var item = ProtocolTests.Item();
        var spool = fixture.Open();
        spool.Stage(ProtocolTests.Scan(item), None);
        var original = Assert.Single(spool.ReadBatch(None));
        var ciphertext = File.ReadAllBytes(Assert.Single(fixture.Files()));
        spool.Hold(original.Id);
        spool.Hold(original.Id);
        var held = Assert.Single(fixture.Files());
        File.Copy(held, Path.ChangeExtension(held, ".tmp"));

        var restored = fixture.Open();
        Assert.Equal(0, restored.WaitingCount);
        Assert.Equal(1, restored.HeldCount);
        Assert.Equal(original.MailboxId, restored.MailboxId);
        Assert.Empty(restored.ReadBatch(None));
        Assert.True(Assert.Single(restored.Preview()).Held);
        Assert.Equal(ciphertext, File.ReadAllBytes(Assert.Single(fixture.Files())));
        Assert.Equal(new OutboxStageResult(0, false), restored.Stage(ProtocolTests.Scan(item), None));
        Assert.Equal(new OutboxStageResult(1, false), restored.Stage(ProtocolTests.Scan(item with
        {
            SourceModifiedAt = item.SourceModifiedAt.AddSeconds(1),
        }), None));
        restored.Remove(Assert.Single(restored.ReadBatch(None)).Id);
        Assert.Equal(1, fixture.Open().HeldCount);
        restored.Remove(original.Id);
        Assert.Null(restored.MailboxId);
        Assert.Empty(fixture.Files());
    }

    [Fact]
    public void CountLimitRetainsPrefixAndCountsHeldItems()
    {
        using var fixture = new Fixture();
        var items = Enumerable.Range(1, 3).Select(ProtocolTests.Item).ToArray();
        var spool = fixture.Open(maximumItems: 2);
        Assert.Equal(new OutboxStageResult(2, true), spool.Stage(ProtocolTests.Scan(items), None));
        Assert.Equal(items.Take(2), spool.ReadBatch(None).Select(entry => entry.Item));
        spool.Hold(spool.ReadBatch(None)[0].Id);

        spool = fixture.Open(maximumItems: 2);
        Assert.Equal(new OutboxStageResult(0, false), spool.Stage(ProtocolTests.Scan(items[..2]), None));
        Assert.Equal(new OutboxStageResult(0, true), spool.Stage(ProtocolTests.Scan(items[2]), None));
        Assert.Equal(1, spool.HeldCount);
        spool.Remove(Assert.Single(spool.ReadBatch(None)).Id);
        Assert.Equal(new OutboxStageResult(1, false), spool.Stage(ProtocolTests.Scan(items[2]), None));
        Assert.Equal(items[2], Assert.Single(spool.ReadBatch(None)).Item);
    }

    [Fact]
    public void ByteLimitCountsCiphertextWithoutEvicting()
    {
        using var fixture = new Fixture();
        var first = ProtocolTests.Item(1);
        var next = ProtocolTests.Item(2);
        fixture.Open().Stage(ProtocolTests.Scan(first), None);
        var path = Assert.Single(fixture.Files());
        var bytes = File.ReadAllBytes(path);

        var spool = fixture.Open(maximumBytes: bytes.Length + 1);
        Assert.Equal(new OutboxStageResult(0, true), spool.Stage(ProtocolTests.Scan(next), None));
        Assert.Equal(path, Assert.Single(fixture.Files()));
        Assert.Equal(bytes, File.ReadAllBytes(path));
        Assert.Equal(first, Assert.Single(spool.ReadBatch(None)).Item);

        using var empty = new Fixture();
        Assert.Equal(new OutboxStageResult(0, true), empty.Open(maximumBytes: 1).Stage(ProtocolTests.Scan(first), None));
        Assert.Empty(empty.Files());
    }

    [Fact]
    public void BatchIsOldestFirstWithFiftyDistinctSources()
    {
        using var fixture = new Fixture();
        var items = Enumerable.Range(1, 52).Select(ProtocolTests.Item).ToList();
        var revision = items[0] with { SourceModifiedAt = items[0].SourceModifiedAt.AddSeconds(1) };
        items.Insert(1, revision);
        fixture.Open().Stage(ProtocolTests.Scan(items.ToArray()), None);
        var spool = fixture.Open();
        var batch = spool.ReadBatch(None);
        Assert.Equal(items.Where(item => item != revision).Take(50), batch.Select(entry => entry.Item));
        Assert.Equal(50, batch.Select(entry => entry.Item.SourceId).Distinct().Count());
        Assert.Equal(2, spool.Preview(2).Count);
        spool.Remove(batch[0].Id);
        Assert.Equal(revision, spool.ReadBatch(None)[0].Item);
    }

    [Fact]
    public void WireBudgetLimitsMultiItemBatchButDoesNotBlockASupportedSingleton()
    {
        using var fixture = new Fixture();
        var first = ProtocolTests.Item(1) with { BodyText = new string('x', 500) };
        var scan = ProtocolTests.Scan(first, ProtocolTests.Item(2));
        var one = new SyncBatch(scan.MailboxId, scan.MailboxLabel, scan.SourceState, [first], ScanComplete: false, SkippedItems: 5000);
        var target = JsonSerializer.SerializeToUtf8Bytes(one, Protocol.Json).Length;
        var spool = fixture.Open(batchTarget: target);
        spool.Stage(scan, None);
        Assert.Equal(first, Assert.Single(spool.ReadBatch(None)).Item);
        Assert.Equal(first, Assert.Single(fixture.Open(batchTarget: 1).ReadBatch(None)).Item);
    }

    [Fact]
    public void DeviceDirectoriesAndMailboxGuardsKeepQueuesSeparate()
    {
        using var fixture = new Fixture();
        var scan = ProtocolTests.Scan(ProtocolTests.Item());
        var otherMailbox = scan with { MailboxId = new string('b', 64) };
        var spool = fixture.Open();
        spool.Stage(scan, None);
        spool.Hold(Assert.Single(spool.ReadBatch(None)).Id);
        var error = Assert.Throws<ConnectorException>(() => spool.Stage(otherMailbox, None));
        Assert.Equal("outbox_mailbox_mismatch", error.Code);

        var otherDevice = Guid.NewGuid();
        var otherSpool = fixture.Open(device: otherDevice);
        Assert.Null(otherSpool.MailboxId);
        Assert.Equal(new OutboxStageResult(1, false), otherSpool.Stage(otherMailbox, None));
        Assert.Equal(otherMailbox.MailboxId, otherSpool.MailboxId);
        Assert.Equal(1, fixture.Open().HeldCount);

        var path = Assert.Single(fixture.Files());
        File.Copy(path, Path.Combine(fixture.DevicePath(otherDevice), Path.GetFileName(path)));
        Assert.Equal("outbox_invalid", Assert.Throws<ConnectorException>(() => fixture.Open(device: otherDevice)).Code);
    }

    [Fact]
    public void AuthenticatedButMisnamedFileAndCorruptCiphertextFailClosed()
    {
        using var fixture = new Fixture();
        var spool = fixture.Open();
        spool.Stage(ProtocolTests.Scan(ProtocolTests.Item()), None);
        var entry = Assert.Single(spool.ReadBatch(None));
        var path = Assert.Single(fixture.Files());
        var wrongPath = Path.Combine(fixture.DevicePath(), new string('0', 64) + ".pending");
        File.Move(path, wrongPath);
        Assert.Equal("outbox_invalid", Assert.Throws<ConnectorException>(() => fixture.Open()).Code);
        File.Move(wrongPath, path);

        var corrupt = File.ReadAllBytes(path);
        corrupt[^1] ^= 1;
        File.WriteAllBytes(path, corrupt);
        Assert.Equal("outbox_protection_failed", Assert.Throws<ConnectorException>(() => fixture.Open()).Code);
        Assert.Throws<ConnectorException>(() => spool.Stage(ProtocolTests.Scan(entry.Item), None));
        Assert.Throws<ConnectorException>(() => spool.ReadBatch(None));
        Assert.Throws<ConnectorException>(() => spool.Hold(entry.Id));
        Assert.Throws<ConnectorException>(() => spool.Remove(entry.Id));
        Assert.Equal(corrupt, File.ReadAllBytes(path));
    }

    [Fact]
    public void AuthenticatedTemporaryPayloadRecovers()
    {
        using var fixture = new Fixture();
        var scan = ProtocolTests.Scan(ProtocolTests.Item());
        fixture.Open().Stage(scan, None);
        var pending = Assert.Single(fixture.Files());
        var temporary = Path.ChangeExtension(pending, ".tmp");
        File.Move(pending, temporary);
        var recovered = fixture.Open();
        Assert.Equal(scan.Items[0], Assert.Single(recovered.ReadBatch(None)).Item);
        Assert.Equal(pending, Assert.Single(fixture.Files()));
    }

    [Theory]
    [InlineData(0)]
    [InlineData(31)]
    public void TornScratchDoesNotHideCommittedMailOrCountAsStaged(int length)
    {
        using var fixture = new Fixture();
        var first = ProtocolTests.Item(1);
        var next = ProtocolTests.Item(2);
        var spool = fixture.Open();
        spool.Stage(ProtocolTests.Scan(first), None);
        var pending = Assert.Single(fixture.Files());
        var committed = File.ReadAllBytes(pending);
        spool.Stage(ProtocolTests.Scan(next), None);
        var publishedNext = Assert.Single(fixture.Files(), file => file != pending);
        var torn = Path.ChangeExtension(publishedNext, ".tmp");
        File.Move(publishedNext, torn);
        using (var stream = new FileStream(torn, FileMode.Open, FileAccess.Write)) stream.SetLength(length);

        var restored = fixture.Open();
        Assert.Equal(first, Assert.Single(restored.ReadBatch(None)).Item);
        Assert.Equal(1, restored.WaitingCount);
        Assert.Equal(pending, Assert.Single(fixture.Files()));
        Assert.Equal(committed, File.ReadAllBytes(pending));
        Assert.Equal(new OutboxStageResult(1, false), restored.Stage(ProtocolTests.Scan(next), None));
        Assert.Equal(new[] { first, next }, restored.ReadBatch(None).Select(file => file.Item));
    }

    [Fact]
    public void UnknownFilesAndPathTraversalAreRejectedWithoutChanges()
    {
        using var fixture = new Fixture();
        var spool = fixture.Open();
        var unknown = Path.Combine(fixture.DevicePath(), "not-owned.outbox");
        File.WriteAllText(unknown, "synthetic outside the outbox format");
        Assert.Equal("outbox_invalid", Assert.Throws<ConnectorException>(() => fixture.Open()).Code);
        Assert.Equal("outbox_invalid", Assert.Throws<ConnectorException>(() => spool.Remove("../not-owned.outbox")).Code);
        Assert.True(File.Exists(unknown));
    }

    [Fact]
    public void ReparseEntriesAndDirectoryAncestorsAreRejected()
    {
        if (OperatingSystem.IsWindows()) return; // Creating a Windows test symlink may require privileges.
        using var fixture = new Fixture();
        var spool = fixture.Open();
        spool.Stage(ProtocolTests.Scan(ProtocolTests.Item()), None);
        var entry = Assert.Single(spool.ReadBatch(None));
        var path = Assert.Single(fixture.Files());
        var outside = Path.Combine(fixture.Root, "outside.outbox");
        File.Move(path, outside);
        File.CreateSymbolicLink(path, outside);
        Assert.Equal("outbox_invalid", Assert.Throws<ConnectorException>(() => fixture.Open()).Code);
        Assert.Throws<ConnectorException>(() => spool.Remove(entry.Id));
        Assert.Throws<ConnectorException>(() => spool.Hold(entry.Id));
        Assert.True(File.Exists(outside));
        File.Delete(path);
        File.Move(outside, path);
        var scratchLink = Path.Combine(fixture.DevicePath(), new string('1', 64) + ".tmp");
        File.CreateSymbolicLink(scratchLink, path);
        Assert.Equal("outbox_invalid", Assert.Throws<ConnectorException>(() => fixture.Open()).Code);
        Assert.True(File.GetAttributes(scratchLink).HasFlag(FileAttributes.ReparsePoint));
        Assert.True(File.Exists(path));

        var alias = Path.Combine(fixture.Root, "alias");
        Directory.CreateSymbolicLink(alias, fixture.Root);
        var invalidRoot = Path.Combine(alias, "must-not-create");
        Assert.Equal("outbox_invalid", Assert.Throws<ConnectorException>(() =>
            new DurableOutbox(invalidRoot, fixture.Device, fixture.Protect, fixture.Unprotect)).Code);
        Assert.False(Directory.Exists(invalidRoot));
    }

    [Fact]
    public void ProtectionFailureDoesNotDiscardAlreadyStagedItemsOrExposeExceptionText()
    {
        using var fixture = new Fixture();
        var calls = 0;
        byte[]? failedInput = null;
        var spool = new DurableOutbox(fixture.Root, fixture.Device, bytes =>
        {
            if (++calls == 1) return fixture.Protect(bytes);
            failedInput = bytes;
            throw new CryptographicException("synthetic private error");
        }, fixture.Unprotect);
        var scan = ProtocolTests.Scan(ProtocolTests.Item(1), ProtocolTests.Item(2));
        var error = Assert.Throws<ConnectorException>(() => spool.Stage(scan, None));
        Assert.Equal("outbox_protection_failed", error.Code);
        Assert.Null(error.InnerException);
        Assert.All(Assert.IsType<byte[]>(failedInput), value => Assert.Equal(0, value));
        Assert.Equal(scan.Items[0], Assert.Single(fixture.Open().ReadBatch(None)).Item);
        Assert.Single(fixture.Files());
    }

    [Fact]
    public void CancellationDoesNotStageOrRemoveMail()
    {
        using var fixture = new Fixture();
        var scan = ProtocolTests.Scan(ProtocolTests.Item());
        var spool = fixture.Open();
        var canceled = new CancellationToken(true);
        Assert.Throws<OperationCanceledException>(() => spool.Stage(scan, canceled));
        Assert.Empty(fixture.Files());
        spool.Stage(scan, None);
        Assert.Throws<OperationCanceledException>(() => spool.ReadBatch(canceled));
        Assert.Equal(1, fixture.Open().WaitingCount);
    }

    private sealed class Fixture : IDisposable
    {
        private const int NonceSize = 12;
        private const int TagSize = 16;
        private readonly byte[] syntheticKey = RandomNumberGenerator.GetBytes(32);

        public string Root { get; } = CanonicalPath(Directory.CreateTempSubdirectory("dpms-outbox-tests-").FullName);
        public Guid Device { get; } = Guid.NewGuid();
        public string DevicePath(Guid? device = null) => Path.Combine(Root, (device ?? Device).ToString("N"));
        public string[] Files() => Directory.GetFiles(DevicePath());

        public DurableOutbox Open(long maximumBytes = 256 * 1024 * 1024, int maximumItems = 5000,
            int batchTarget = 30_000_000, Guid? device = null) =>
            new(Root, device ?? Device, Protect, Unprotect, maximumBytes, maximumItems, batchTarget);

        public byte[] Protect(byte[] data)
        {
            using var aes = new AesGcm(syntheticKey, TagSize);
            var result = new byte[NonceSize + TagSize + data.Length];
            RandomNumberGenerator.Fill(result.AsSpan(0, NonceSize));
            aes.Encrypt(result.AsSpan(0, NonceSize), data, result.AsSpan(NonceSize + TagSize), result.AsSpan(NonceSize, TagSize));
            return result;
        }

        public byte[] Unprotect(byte[] data)
        {
            using var aes = new AesGcm(syntheticKey, TagSize);
            var result = new byte[data.Length - NonceSize - TagSize];
            aes.Decrypt(data.AsSpan(0, NonceSize), data.AsSpan(NonceSize + TagSize), data.AsSpan(NonceSize, TagSize), result);
            return result;
        }

        private static string CanonicalPath(string path)
        {
            var directory = new DirectoryInfo(path);
            if (directory.Parent is not { } parent) return directory.FullName;
            var actual = new DirectoryInfo(Path.Combine(CanonicalPath(parent.FullName), directory.Name));
            return actual.ResolveLinkTarget(returnFinalTarget: true)?.FullName ?? actual.FullName;
        }

        public void Dispose()
        {
            CryptographicOperations.ZeroMemory(syntheticKey);
            Directory.Delete(Root, recursive: true);
        }
    }
}
