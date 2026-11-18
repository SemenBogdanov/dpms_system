using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace Dpms.OutlookConnector;

public interface IIngestionClient
{
    Task<SyncResult> Sync(SyncBatch batch, CancellationToken cancellation);
}

public interface IConnectorClient : IIngestionClient, IDisposable { }

public static class IngestionClient
{
    public static IConnectorClient Create(DeviceSession session, LocalState? state = null, Action<LocalState>? save = null) => session.Transport switch
    {
        ConnectorTransport.Https => new DpmsClient(session.ServerUrl, session.DeviceSecret),
        ConnectorTransport.PostgreSql when session.Database is not null => new PostgresClient(session.Database, session.DeviceSecret,
            state is not null && save is not null ? new PostgresRequestJournal(state, save) : null),
        _ => throw new ConnectorException("local_state_invalid"),
    };
}

public sealed class DpmsClient : IConnectorClient
{
    private readonly HttpClient client;
    private readonly string? deviceSecret;
    private readonly TimeSpan requestTimeout;

    public DpmsClient(string server, string? deviceSecret = null, HttpMessageHandler? handler = null,
        TimeSpan? requestTimeout = null)
    {
        this.deviceSecret = deviceSecret;
        this.requestTimeout = requestTimeout ?? TimeSpan.FromSeconds(45);
        if (this.requestTimeout <= TimeSpan.Zero) throw new ArgumentOutOfRangeException(nameof(requestTimeout));
        client = new HttpClient(handler ?? new HttpClientHandler
        {
            AllowAutoRedirect = false,
            UseCookies = false,
        }) { BaseAddress = Protocol.Server(server), Timeout = Timeout.InfiniteTimeSpan };
    }

    public async Task<PairResult> Pair(string code, CancellationToken cancellation)
    {
        var result = await Post<PairResult>("api/mail-import/pair", new { pairing_code = code.Trim() }, cancellation);
        if (result.ProtocolVersion != 1 || result.DeviceId == Guid.Empty
            || result.DeviceSecret is not { Length: 43 }
            || result.DeviceSecret.Any(c => !(char.IsAsciiLetterOrDigit(c) || c is '_' or '-'))
            || result.OwnerName is not { Length: > 0 and <= 255 })
            throw new ConnectorException("invalid_response");
        return result;
    }

    public async Task<SyncResult> Sync(SyncBatch batch, CancellationToken cancellation)
    {
        if (deviceSecret is null) throw new ConnectorException("not_paired");
        var result = await Post<SyncResult>("api/mail-import/sync", batch, cancellation);
        if (result.Accepted != batch.Items.Count
            || result.Created < 0 || result.Updated < 0 || result.Unchanged < 0 || result.Stale < 0
            || result.Accepted != result.Created + result.Updated + result.Unchanged + result.Stale
            || result.SyncedAt.Year is < 2000 or > 2200)
            throw new ConnectorException("invalid_ack");
        return result;
    }

    public async Task CheckConnection(CancellationToken cancellation)
    {
        // An HTTPS health check checks the API, never sends the device bearer or a sync payload.
        using var response = await client.GetAsync("health", HttpCompletionOption.ResponseHeadersRead, cancellation);
        if (response.StatusCode != HttpStatusCode.OK) throw new ConnectorException("endpoint_unavailable");
        await using var body = await response.Content.ReadAsStreamAsync(cancellation);
        var bytes = new byte[4097];
        var length = await body.ReadAtLeastAsync(bytes, bytes.Length, false, cancellation);
        if (length == bytes.Length) throw new ConnectorException("invalid_response");
        try
        {
            using var document = JsonDocument.Parse(bytes.AsMemory(0, length));
            if (document.RootElement.ValueKind != JsonValueKind.Object
                || !document.RootElement.TryGetProperty("status", out var status)
                || status.ValueKind != JsonValueKind.String || status.GetString() != "ok")
                throw new ConnectorException("invalid_response");
        }
        catch (JsonException) { throw new ConnectorException("invalid_response"); }
    }

    private async Task<T> Post<T>(string path, object payload, CancellationToken cancellation)
    {
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        deadline.CancelAfter(requestTimeout);
        cancellation = deadline.Token;
        var bytes = JsonSerializer.SerializeToUtf8Bytes(payload, Protocol.Json);
        if (bytes.Length > Protocol.MaximumBatchBytes) throw new ConnectorException("batch_too_large");
        using var request = new HttpRequestMessage(HttpMethod.Post, path);
        request.Content = new ByteArrayContent(bytes);
        request.Content.Headers.ContentType = new MediaTypeHeaderValue("application/json");
        if (deviceSecret is not null)
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", deviceSecret);
        using var response = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellation);
        if (!response.IsSuccessStatusCode)
        {
            // Never expose server response bodies: validation errors may echo mailbox data.
            throw new ConnectorException(response.StatusCode switch
            {
                HttpStatusCode.Unauthorized or HttpStatusCode.Forbidden => "access_denied",
                HttpStatusCode.NotFound => "endpoint_unavailable",
                HttpStatusCode.Conflict => "sync_conflict",
                HttpStatusCode.RequestEntityTooLarge => "batch_too_large",
                HttpStatusCode.TooManyRequests => "rate_limited",
                _ when (int)response.StatusCode is >= 300 and < 400 => "redirect_blocked",
                _ when (int)response.StatusCode >= 500 => "server_unavailable",
                _ => "request_rejected",
            });
        }
        await using var stream = await response.Content.ReadAsStreamAsync(cancellation);
        var buffer = new byte[65537];
        var offset = 0;
        while (offset < buffer.Length)
        {
            var count = await stream.ReadAsync(buffer.AsMemory(offset), cancellation);
            if (count == 0) break;
            offset += count;
        }
        if (offset == buffer.Length) throw new ConnectorException("invalid_response");
        try
        {
            return JsonSerializer.Deserialize<T>(buffer.AsSpan(0, offset), Protocol.Json)
                   ?? throw new ConnectorException("invalid_response");
        }
        catch (JsonException) { throw new ConnectorException("invalid_response"); }
    }

    public void Dispose() => client.Dispose();
}
