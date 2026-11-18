using System.Buffers.Binary;
using System.Net;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Authentication;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text.Json;
using Dpms.OutlookConnector;
using Npgsql;
using Xunit;

namespace Dpms.OutlookConnector.Tests;

public sealed class PostgresTlsTests
{
    private static PostgresSettings Settings => new("127.0.0.1", 5432, "synthetic", "app", "synthetic", "test-only");

    [Fact]
    public void PinIsOptionalAndAcceptsPlainHexOrColonPairs()
    {
        var pairs = string.Join(":", Enumerable.Repeat("aF", 32));
        byte[] expected = Enumerable.Repeat((byte)0xaf, 32).ToArray();
        Assert.Equal(expected, (Settings with { ServerCertificateSha256 = " " + pairs + " " }).GetServerCertificatePin());
        Assert.Equal(expected, (Settings with { ServerCertificateSha256 = pairs.Replace(":", "") }).GetServerCertificatePin());
        Assert.Null((Settings with { ServerCertificateSha256 = "    " }).GetServerCertificatePin());
        Assert.Equal(SslMode.VerifyFull, (Settings with { ServerCertificateSha256 = pairs }).ConnectionSettings().SslMode);
        Assert.Equal(SslMode.VerifyFull, Settings.ConnectionSettings().SslMode);
    }

    [Fact]
    public void MalformedPinsAndExplicitCaWithPinAreRejected()
    {
        var pairs = string.Join(":", Enumerable.Repeat("12", 32));
        foreach (var value in new[] { pairs[1..], "SHA256 Fingerprint=" + pairs, new string('G', 64),
                     new string('a', 40), pairs.Replace(':', '-'), "1:212" + pairs[5..], "*" })
        {
            var invalid = Settings with { ServerCertificateSha256 = value };
            Assert.Equal("db_tls_pin_invalid", Assert.Throws<ConnectorException>(invalid.Validate).Code);
        }
        var conflict = Settings with { RootCertificate = "synthetic.crt", ServerCertificateSha256 = pairs };
        Assert.Equal("db_tls_pin_conflict", Assert.Throws<ConnectorException>(conflict.Validate).Code);
    }

    [Fact]
    public void DpapiPayloadRemainsCompatibleAndRetainsExplicitPin()
    {
        var old = JsonSerializer.Deserialize<PostgresSettings>(
            """{"host":"127.0.0.1","port":5432,"database":"synthetic","schema":"app","username":"synthetic","password":"test-only"}""", Protocol.Json)!;
        Assert.Equal(Settings, old);
        Assert.Null(old.GetServerCertificatePin());
        var pinned = old with { ServerCertificateSha256 = new string('b', 64) };
        var restored = JsonSerializer.Deserialize<PostgresSettings>(JsonSerializer.Serialize(pinned, Protocol.Json), Protocol.Json);
        Assert.Equal(pinned, restored);
    }

    [Fact]
    public void PinChecksExactLeafAndValidityEvenWhenTheChainIsTrusted()
    {
        var now = DateTimeOffset.UtcNow;
        using var leaf = NewCertificate(now.AddDays(-1), now.AddDays(1));
        using var sameNameOtherLeaf = NewCertificate(now.AddDays(-1), now.AddDays(1));
        var pin = leaf.GetCertHash(HashAlgorithmName.SHA256);
        Assert.True(NpgsqlExecutor.MatchesServerCertificate(leaf,
            SslPolicyErrors.RemoteCertificateNameMismatch | SslPolicyErrors.RemoteCertificateChainErrors, pin, now));
        Assert.False(NpgsqlExecutor.MatchesServerCertificate(sameNameOtherLeaf, SslPolicyErrors.None, pin, now));
        Assert.False(NpgsqlExecutor.MatchesServerCertificate(leaf, SslPolicyErrors.RemoteCertificateNotAvailable, pin, now));
        Assert.False(NpgsqlExecutor.MatchesServerCertificate(null, SslPolicyErrors.None, pin, now));
        Assert.False(NpgsqlExecutor.MatchesServerCertificate(leaf, SslPolicyErrors.None, pin, now.AddDays(-2)));
        Assert.False(NpgsqlExecutor.MatchesServerCertificate(leaf, SslPolicyErrors.None, pin, now.AddDays(2)));
    }

    [Theory]
    [InlineData("match", true, "db_login_failed", true)]
    [InlineData("other", true, "db_tls_pin_rejected", false)]
    [InlineData("absent", true, "db_tls_failed", false)]
    [InlineData("match", false, "db_unavailable", false)]
    public async Task NpgsqlNeverSendsStartupBeforeValidatingTls(string pin, bool supportsTls, string expectedError, bool expectStartup)
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        using var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        var now = DateTimeOffset.UtcNow;
        using var leaf = NewCertificate(now.AddDays(-1), now.AddDays(1));
        var digest = leaf.GetCertHash(HashAlgorithmName.SHA256);
        if (pin == "other") digest[0] ^= 1;
        using var client = new PostgresClient(Settings with
        {
            Port = ((IPEndPoint)listener.LocalEndpoint).Port,
            ServerCertificateSha256 = pin == "absent" ? null : Convert.ToHexString(digest),
        });
        var peer = ObserveStartup(listener, leaf, supportsTls, deadline.Token);
        try
        {
            var error = await Assert.ThrowsAsync<ConnectorException>(() => client.CheckConnection(deadline.Token));
            Assert.Equal(expectedError, error.Code);
            Assert.Equal(expectStartup, await peer);
            Assert.False(listener.Pending()); // No second connection that could fall back to plaintext.
        }
        finally
        {
            await deadline.CancelAsync();
            try { await peer; } catch (OperationCanceledException) when (deadline.IsCancellationRequested) { }
        }
    }

    private static X509Certificate2 NewCertificate(DateTimeOffset notBefore, DateTimeOffset notAfter)
    {
        using var key = RSA.Create(2048);
        var request = new CertificateRequest("CN=synthetic.invalid", key, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
        return request.CreateSelfSigned(notBefore, notAfter);
    }

    // This loopback fixture negotiates PostgreSQL TLS. It is not a database and asks for no password.
    private static async Task<bool> ObserveStartup(TcpListener listener, X509Certificate2 leaf, bool supportsTls,
        CancellationToken cancellation)
    {
        using var peer = await listener.AcceptTcpClientAsync(cancellation);
        await using var wire = peer.GetStream();
        var header = new byte[8];
        await wire.ReadExactlyAsync(header, cancellation);
        Assert.Equal(8, BinaryPrimitives.ReadInt32BigEndian(header));
        Assert.Equal(80877103, BinaryPrimitives.ReadInt32BigEndian(header.AsSpan(4)));
        await wire.WriteAsync(new byte[] { (byte)(supportsTls ? 'S' : 'N') }, cancellation);
        if (!supportsTls)
            return await wire.ReadAsync(header.AsMemory(0, 1), cancellation) != 0;

        await using var tls = new SslStream(wire);
        try
        {
            await tls.AuthenticateAsServerAsync(new SslServerAuthenticationOptions { ServerCertificate = leaf }, cancellation);
            if (await tls.ReadAsync(header.AsMemory(0, 1), cancellation) == 0) return false;
        }
        catch (AuthenticationException) { return false; }
        catch (IOException) { return false; }

        await tls.ReadExactlyAsync(header.AsMemory(1), cancellation);
        var length = BinaryPrimitives.ReadInt32BigEndian(header);
        Assert.InRange(length, 9, 4096);
        await tls.ReadExactlyAsync(new byte[length - 8], cancellation);

        // Reject this synthetic login without any SQL or credential exchange.
        var fields = "SFATAL\0C28P01\0Msynthetic login rejected\0\0"u8;
        var error = new byte[5 + fields.Length];
        error[0] = (byte)'E';
        BinaryPrimitives.WriteInt32BigEndian(error.AsSpan(1), 4 + fields.Length);
        fields.CopyTo(error.AsSpan(5));
        await tls.WriteAsync(error, cancellation);
        return true;
    }
}
