using System.Security.Authentication;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Npgsql;
using NpgsqlTypes;

namespace Dpms.OutlookConnector;

public sealed record PostgresSettings(string Host, int Port, string Database, string Schema,
    string Username, string Password, string? RootCertificate = null)
{
    public void Validate()
    {
        if (string.IsNullOrWhiteSpace(Host) || Host.Length > 253
            || Uri.CheckHostName(Host) == UriHostNameType.Unknown
            || Host.IndexOfAny([',', '/', '\\', ';', ' ', '\t', '\n', '\r']) >= 0
            || Port is < 1 or > 65535 || !Identifier(Schema)
            || string.IsNullOrWhiteSpace(Database) || Database.Length > 63 || Database.Any(char.IsControl)
            || string.IsNullOrWhiteSpace(Username) || Username.Length > 63 || Username.Any(char.IsControl)
            || string.IsNullOrEmpty(Password) || Password.Contains('\0')
            || RootCertificate?.Contains('\0') == true)
            throw new ConnectorException("db_settings_invalid");
    }

    private static bool Identifier(string value) => !string.IsNullOrEmpty(value) && value.Length <= 63
        && (char.IsAsciiLetter(value[0]) || value[0] == '_')
        && value.All(c => char.IsAsciiLetterOrDigit(c) || c == '_');

    internal NpgsqlConnectionStringBuilder ConnectionSettings()
    {
        Validate();
        return new NpgsqlConnectionStringBuilder
        {
            Host = Host, Port = Port, Database = Database, Username = Username, Password = Password,
            SslMode = SslMode.VerifyFull, GssEncryptionMode = GssEncryptionMode.Disable,
            SslNegotiation = SslNegotiation.Postgres,
            RequireAuth = "ScramSHA256,MD5,Password",
            RootCertificate = string.IsNullOrWhiteSpace(RootCertificate) ? null : RootCertificate, Options = "",
            PersistSecurityInfo = false, IncludeErrorDetail = false, LogParameters = false,
            Pooling = false, Timeout = 10, CommandTimeout = 30, CancellationTimeout = 2000,
            ApplicationName = "DPMS.OutlookConnector", SearchPath = "pg_catalog",
        };
    }

    internal void RejectImplicitTlsFiles(Func<string, string?> environment, Func<string, bool> exists, bool windows)
    {
        var home = environment(windows ? "APPDATA" : "HOME");
        var directory = home is null ? null : Path.Combine(home, windows ? "postgresql" : ".postgresql");
        // Do not let Npgsql silently load a user's unrelated client identity or CA file.
        if (environment("PGSSLCERT") is not null || environment("PGSSLKEY") is not null
            || directory is not null && exists(Path.Combine(directory, "postgresql.crt"))
            || string.IsNullOrWhiteSpace(RootCertificate) && (environment("PGSSLROOTCERT") is not null
                || directory is not null && exists(Path.Combine(directory, "root.crt"))))
            throw new ConnectorException("db_tls_configuration");
    }

    // Records otherwise include passwords in their generated ToString().
    public override string ToString() => "PostgresSettings { redacted }";
}

internal interface IPostgresExecutor : IDisposable
{
    Task<string> Execute(string function, object[] arguments, CancellationToken cancellation);
}

internal sealed class NpgsqlExecutor(PostgresSettings settings) : IPostgresExecutor
{
    public async Task<string> Execute(string function, object[] arguments, CancellationToken cancellation)
    {
        if (function is not ("mail_import_db_protocol" or "mail_import_db_pair" or "mail_import_db_connect"
            or "mail_import_db_enqueue" or "mail_import_db_status"))
            throw new ConnectorException("invalid_request");
        try
        {
            settings.RejectImplicitTlsFiles(Environment.GetEnvironmentVariable, File.Exists, OperatingSystem.IsWindows());
            await using var connection = new NpgsqlConnection(settings.ConnectionSettings().ConnectionString);
            await connection.OpenAsync(cancellation);
            var parameters = string.Join(",", Enumerable.Range(1, arguments.Length).Select(i => "$" + i));
            await using var command = new NpgsqlCommand($"SELECT \"{settings.Schema}\".\"{function}\"({parameters})::text", connection);
            foreach (var argument in arguments)
                command.Parameters.Add(new NpgsqlParameter
                {
                    NpgsqlDbType = argument is Guid ? NpgsqlDbType.Uuid : NpgsqlDbType.Text, Value = argument,
                });
            return await command.ExecuteScalarAsync(cancellation) as string
                ?? throw new ConnectorException("invalid_response");
        }
        catch (PostgresException error)
        {
            throw new ConnectorException(error.SqlState switch
            {
                "28P01" or "28000" => "db_login_failed",
                "42501" => "access_denied",
                "42883" or "3F000" or "42P01" => "db_not_installed",
                "53300" or "53400" => "db_queue_full",
                _ => "db_unavailable",
            });
        }
        catch (NpgsqlException error)
        {
            throw new ConnectorException(HasTlsFailure(error) ? "db_tls_failed" : "db_unavailable");
        }
        catch (AuthenticationException) { throw new ConnectorException("db_tls_failed"); }
        catch (IOException) { throw new ConnectorException("db_tls_failed"); }
    }

    private static bool HasTlsFailure(Exception error) => error is AuthenticationException
        || error.InnerException is { } inner && HasTlsFailure(inner);

    public void Dispose() { }
}

public sealed class PostgresRequestJournal(LocalState state, Action<LocalState> save)
{
    public DatabaseRequest? Pending
    {
        get
        {
            var pending = state.PendingDatabaseRequest;
            if (pending is not null && (pending.RequestId == Guid.Empty || pending.PayloadHash is not { Length: 64 }
                || pending.PayloadHash.Any(c => !char.IsAsciiHexDigit(c))))
                throw new ConnectorException("local_state_invalid");
            return pending;
        }
    }

    public DatabaseRequest Begin(string hash)
    {
        if (Pending is not null) throw new ConnectorException("sync_conflict");
        var request = new DatabaseRequest(Guid.NewGuid(), hash);
        Set(request);
        return request;
    }

    public void Complete(Guid id)
    {
        if (Pending?.RequestId != id) throw new ConnectorException("local_state_invalid");
        Set(null);
    }

    private void Set(DatabaseRequest? value)
    {
        var previous = state.PendingDatabaseRequest;
        state.PendingDatabaseRequest = value;
        try { save(state); }
        catch
        {
            state.PendingDatabaseRequest = previous;
            throw new ConnectorException("local_protection_failed");
        }
    }
}

public sealed class PostgresClient : IConnectorClient
{
    private readonly IPostgresExecutor executor;
    private readonly string? deviceSecret;
    private readonly TimeSpan timeout;
    private readonly TimeSpan pollInterval;
    private readonly PostgresRequestJournal journal;

    public PostgresClient(PostgresSettings settings, string? deviceSecret = null, PostgresRequestJournal? journal = null)
        : this(new NpgsqlExecutor(settings), deviceSecret, TimeSpan.FromMinutes(2), TimeSpan.FromSeconds(1), journal)
    { settings.Validate(); }

    internal PostgresClient(IPostgresExecutor executor, string? deviceSecret = null,
        TimeSpan? timeout = null, TimeSpan? pollInterval = null, PostgresRequestJournal? journal = null)
    {
        this.executor = executor;
        this.deviceSecret = deviceSecret;
        this.timeout = timeout ?? TimeSpan.FromMinutes(2);
        this.pollInterval = pollInterval ?? TimeSpan.FromSeconds(1);
        this.journal = journal ?? new PostgresRequestJournal(new LocalState(), _ => { });
        if (this.timeout <= TimeSpan.Zero || this.pollInterval < TimeSpan.Zero) throw new ArgumentOutOfRangeException(nameof(timeout));
    }

    public async Task<PairResult> Pair(string code, CancellationToken cancellation)
    {
        code = code.Trim();
        if (!ValidSecret(code)) throw new ConnectorException("invalid_pairing_code");
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        deadline.CancelAfter(timeout);
        using var protocol = await Call("mail_import_db_protocol", [], deadline.Token);
        if (!protocol.RootElement.TryGetProperty("protocol_version", out var version) || version.ValueKind != JsonValueKind.Number
            || !version.TryGetInt32(out var protocolVersion) || protocolVersion != 1
            || !protocol.RootElement.TryGetProperty("maximum_batch_bytes", out var limit) || limit.ValueKind != JsonValueKind.Number
            || !limit.TryGetInt32(out var maxBytes) || maxBytes != Protocol.MaximumBatchBytes)
            throw new ConnectorException("invalid_response");
        var secret = Convert.ToBase64String(RandomNumberGenerator.GetBytes(32)).TrimEnd('=').Replace('+', '-').Replace('/', '_');
        try
        {
            // Pairing is single-use. A lost response must not silently create a second binding.
            using var response = await Call("mail_import_db_pair", [code, secret], deadline.Token);
            var result = Deserialize<PairResult>(response.RootElement);
            if (result.ProtocolVersion != 1 || result.DeviceId == Guid.Empty || result.DeviceSecret != secret
                || result.OwnerName is not { Length: > 0 and <= 255 })
                throw new ConnectorException("invalid_response");
            return result;
        }
        catch (ConnectorException error) when (error.Code is "db_unavailable" or "invalid_response")
        { throw new ConnectorException("pair_uncertain"); }
        catch (OperationCanceledException) { throw new ConnectorException("pair_uncertain"); }
    }

    public async Task<PairResult> Connect(string deviceName, CancellationToken cancellation)
    {
        deviceName = deviceName.Trim();
        if (deviceName.Length is < 1 or > 120 || deviceName.Any(char.IsControl))
            throw new ConnectorException("db_settings_invalid");
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        deadline.CancelAfter(timeout);
        using var protocol = await Call("mail_import_db_protocol", [], deadline.Token);
        var root = protocol.RootElement;
        if (!root.TryGetProperty("protocol_version", out var version) || version.ValueKind != JsonValueKind.Number
            || !version.TryGetInt32(out var protocolVersion) || protocolVersion != 1
            || !root.TryGetProperty("maximum_batch_bytes", out var limit) || limit.ValueKind != JsonValueKind.Number
            || !limit.TryGetInt32(out var maxBytes) || maxBytes != Protocol.MaximumBatchBytes
            || !root.TryGetProperty("login_mode", out var mode) || mode.ValueKind != JsonValueKind.String
            || mode.GetString() != "role_bound")
            throw new ConnectorException("db_not_installed");
        var secret = Convert.ToBase64String(RandomNumberGenerator.GetBytes(32)).TrimEnd('=').Replace('+', '-').Replace('/', '_');
        try
        {
            // SQL resolves the owner from session_user, never from a client-supplied account identifier.
            using var response = await Retry("mail_import_db_connect", [deviceName, secret], deadline.Token);
            var result = Deserialize<PairResult>(response.RootElement);
            if (result.ProtocolVersion != 1 || result.DeviceId == Guid.Empty || result.DeviceSecret != secret
                || result.OwnerName is not { Length: > 0 and <= 255 })
                throw new ConnectorException("invalid_response");
            return result;
        }
        catch (OperationCanceledException) when (!cancellation.IsCancellationRequested)
        { throw new ConnectorException("db_unavailable"); }
    }

    public async Task<SyncResult> Sync(SyncBatch batch, CancellationToken cancellation)
    {
        if (!ValidSecret(deviceSecret)) throw new ConnectorException("not_paired");
        var payload = JsonSerializer.Serialize(batch, Protocol.Json);
        if (Encoding.UTF8.GetByteCount(payload) > Protocol.MaximumBatchBytes) throw new ConnectorException("batch_too_large");
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        deadline.CancelAfter(timeout);
        var hash = Protocol.Hash(payload);
        try
        {
            if (journal.Pending is { } previous && previous.PayloadHash != hash)
            {
                using var oldReceipt = await WaitForReceipt(previous.RequestId, deadline.Token);
                journal.Complete(previous.RequestId);
                // The previous payload no longer matches this scan. Its ACK cannot acknowledge this batch.
                if (oldReceipt.RootElement.GetProperty("state").GetString() == "error")
                {
                    var code = ErrorCode(oldReceipt.RootElement);
                    if (code == "access_denied") throw new ConnectorException(code);
                }
            }
            var request = journal.Pending ?? journal.Begin(hash);
            var id = request.RequestId;
            // Reuse this identifier on ambiguous enqueue failures. Enqueue alone is never an ACK.
            using var queued = await Retry("mail_import_db_enqueue", [deviceSecret!, id, payload], deadline.Token);
            ValidateReceipt(queued.RootElement, id);
            using var status = await WaitForReceipt(id, deadline.Token);
            var root = status.RootElement;
            if (root.GetProperty("state").GetString() == "error")
            {
                journal.Complete(id);
                throw new ConnectorException(ErrorCode(root));
            }
            if (!root.TryGetProperty("result", out var ack)) throw new ConnectorException("invalid_ack");
            var result = Deserialize<SyncResult>(ack);
            if (result.Accepted != batch.Items.Count || result.Created < 0 || result.Updated < 0
                || result.Unchanged < 0 || result.Stale < 0
                || (long)result.Accepted != (long)result.Created + result.Updated + result.Unchanged + result.Stale
                || result.SyncedAt.Year is < 2000 or > 2200)
                throw new ConnectorException("invalid_ack");
            journal.Complete(id);
            return result;
        }
        catch (OperationCanceledException) when (!cancellation.IsCancellationRequested)
        { throw new ConnectorException("db_pending"); }
    }

    private async Task<JsonDocument> WaitForReceipt(Guid id, CancellationToken cancellation)
    {
        while (true)
        {
            var response = await Retry("mail_import_db_status", [deviceSecret!, id], cancellation);
            var root = response.RootElement;
            if (!root.TryGetProperty("state", out _) && root.TryGetProperty("error_code", out var error)
                && error.ValueKind != JsonValueKind.Null)
            {
                if (root.TryGetProperty("request_id", out var suppliedId)
                    && (suppliedId.ValueKind != JsonValueKind.String || !suppliedId.TryGetGuid(out var actualId) || actualId != id))
                {
                    response.Dispose();
                    throw new ConnectorException("invalid_ack");
                }
                var missing = root.TryGetProperty("error_status", out var number) && number.ValueKind == JsonValueKind.Number
                    && number.TryGetInt32(out var statusCode) && statusCode == 404;
                var code = ErrorCode(root);
                response.Dispose();
                if (!missing) throw new ConnectorException(code);
                // A journal can be persisted before the first enqueue reaches the server.
                return JsonDocument.Parse(JsonSerializer.Serialize(new
                {
                    request_id = id, state = "error", error_code = "request_not_found", error_status = 404,
                }));
            }
            string state;
            try { state = ValidateReceipt(response.RootElement, id); }
            catch { response.Dispose(); throw; }
            if (state != "pending") return response;
            response.Dispose();
            await Task.Delay(pollInterval, cancellation);
        }
    }

    private async Task<JsonDocument> Retry(string function, object[] arguments, CancellationToken cancellation)
    {
        for (var attempt = 0; ; attempt++)
        {
            try { return await Call(function, arguments, cancellation); }
            catch (ConnectorException error) when (error.Code == "db_unavailable" && attempt < 2)
            { await Task.Delay(pollInterval, cancellation); }
        }
    }

    private async Task<JsonDocument> Call(string function, object[] arguments, CancellationToken cancellation)
    {
        cancellation.ThrowIfCancellationRequested();
        var text = await executor.Execute(function, arguments, cancellation);
        if (text.Length > 65536) throw new ConnectorException("invalid_response");
        JsonDocument response;
        try { response = JsonDocument.Parse(text); }
        catch (JsonException) { throw new ConnectorException("invalid_response"); }
        var root = response.RootElement;
        if (root.ValueKind != JsonValueKind.Object) { response.Dispose(); throw new ConnectorException("invalid_response"); }
        if (function != "mail_import_db_status" && root.TryGetProperty("error_code", out var code) && code.ValueKind != JsonValueKind.Null)
        {
            var mapped = ErrorCode(root);
            response.Dispose();
            throw new ConnectorException(mapped);
        }
        return response;
    }

    private static string ErrorCode(JsonElement root)
    {
        var status = root.TryGetProperty("error_status", out var number) && number.ValueKind == JsonValueKind.Number
            && number.TryGetInt32(out var value) ? value : 0;
        return root.TryGetProperty("error_code", out var code) && code.ValueKind == JsonValueKind.String
            && code.GetString() == "db_login_not_provisioned" ? "db_login_not_provisioned" : status switch
        {
            401 or 403 => "access_denied", 409 => "sync_conflict", 413 => "batch_too_large",
            429 => "db_queue_full", 408 or 404 => "db_pending", _ => "request_rejected",
        };
    }

    private static string ValidateReceipt(JsonElement root, Guid id)
    {
        if (!root.TryGetProperty("request_id", out var request) || request.ValueKind != JsonValueKind.String
            || !request.TryGetGuid(out var actual) || actual != id
            || !root.TryGetProperty("state", out var state) || state.ValueKind != JsonValueKind.String
            || state.GetString() is not ("pending" or "done" or "error"))
            throw new ConnectorException("invalid_ack");
        return state.GetString()!;
    }

    private static T Deserialize<T>(JsonElement value)
    {
        try { return value.Deserialize<T>(Protocol.Json) ?? throw new ConnectorException("invalid_response"); }
        catch (JsonException) { throw new ConnectorException("invalid_response"); }
    }

    private static bool ValidSecret(string? secret) => secret is { Length: 43 }
        && secret.All(c => char.IsAsciiLetterOrDigit(c) || c is '_' or '-');

    public void Dispose() => executor.Dispose();
}
