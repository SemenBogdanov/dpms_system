using System.Diagnostics;
using System.Text;
using System.Text.Json;
using Dpms.OutlookConnector;

namespace Dpms.OutlookConnector.Desktop;

internal sealed class OutlookWorker
{
    private Process? child;

    public async Task<ScanResult> Scan(ScanOptions options, CancellationToken cancellation)
    {
        await Stop();
        cancellation.ThrowIfCancellationRequested();
        AttachmentStaging.Cleanup();
        try { return await Run<ScanResult>("--scan", options, 80_000_000, cancellation); }
        finally { if (child is null) AttachmentStaging.Cleanup(); }
    }

    public Task<OutlookProbeResult> Probe(CancellationToken cancellation) =>
        Run<OutlookProbeResult>("--probe-outlook", null, 32_000, cancellation);

    private async Task<T> Run<T>(string command, ScanOptions? options, int maximum, CancellationToken cancellation)
    {
        await Stop();
        cancellation.ThrowIfCancellationRequested();
        var process = new Process
        {
            StartInfo = new ProcessStartInfo(Environment.ProcessPath!, command)
            {
                UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
                StandardInputEncoding = new UTF8Encoding(false), StandardOutputEncoding = Encoding.UTF8,
            },
        };
        try
        {
            if (!process.Start()) throw new ConnectorException("outlook_scan_failed");
            child = process;
            var output = ReadBounded(process.StandardOutput, maximum, cancellation);
            var errors = ReadBounded(process.StandardError, 65536, cancellation);
            if (options is not null)
                await process.StandardInput.WriteAsync(JsonSerializer.Serialize(options, Protocol.Json).AsMemory(), cancellation);
            process.StandardInput.Close();
            await Task.WhenAll(output, errors);
            await process.WaitForExitAsync(cancellation);
            return await Task.Run(() => JsonSerializer.Deserialize<T>(output.Result, Protocol.Json)
                ?? throw new ConnectorException("invalid_scan"), cancellation);
        }
        finally
        {
            if (ReferenceEquals(child, process)) await Stop();
            else process.Dispose();
        }
    }

    public async Task Stop()
    {
        if (child is not { } process) return;
        try
        {
            if (!process.HasExited)
            {
                try { process.Kill(); } catch (InvalidOperationException) when (process.HasExited) { }
                using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
                await process.WaitForExitAsync(deadline.Token);
            }
        }
        catch { throw new ConnectorException("outlook_scanner_stop_failed"); }
        child = null;
        process.Dispose();
    }

    public void StopOnShutdown()
    {
        try
        {
            if (child is not { } process) return;
            if (!process.HasExited)
            {
                process.Kill();
                if (!process.WaitForExit(5000)) return;
            }
            child = null;
            process.Dispose();
            AttachmentStaging.Cleanup();
        }
        catch { }
    }

    private static async Task<string> ReadBounded(StreamReader reader, int maximum, CancellationToken cancellation)
    {
        var text = new StringBuilder();
        var buffer = new char[8192];
        int count;
        while ((count = await reader.ReadAsync(buffer, cancellation).ConfigureAwait(false)) != 0)
        {
            if (text.Length + count > maximum) throw new ConnectorException("scan_too_large");
            text.Append(buffer, 0, count);
        }
        return text.ToString();
    }
}
