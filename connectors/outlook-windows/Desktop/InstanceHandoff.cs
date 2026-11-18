using System.Buffers.Binary;
using System.IO.Pipes;

namespace Dpms.OutlookConnector.Desktop;

internal static class InstanceHandoff
{
    private const PipeOptions Options = PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly;
    private const byte ExitCommand = 1;
    private const byte PidReceived = 2;
    private static readonly TimeSpan RequestTimeout = TimeSpan.FromSeconds(5);
    private static readonly TimeSpan PeerTimeout = TimeSpan.FromSeconds(2);

    public static NamedPipeServerStream CreateServer(string name) =>
        new(name, PipeDirection.InOut, 1, PipeTransmissionMode.Byte, Options);

    public static async Task<int> RequestExitAsync(string name, CancellationToken cancellation)
    {
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        deadline.CancelAfter(RequestTimeout);
        using var client = new NamedPipeClientStream(".", name, PipeDirection.InOut, Options);
        try
        {
            await client.ConnectAsync(deadline.Token).ConfigureAwait(false);
            await client.WriteAsync(new byte[] { ExitCommand }, deadline.Token).ConfigureAwait(false);
            var reply = new byte[sizeof(int)];
            await client.ReadExactlyAsync(reply, deadline.Token).ConfigureAwait(false);
            var processId = BinaryPrimitives.ReadInt32LittleEndian(reply);
            if (processId <= 0) throw new InvalidDataException("Invalid instance handoff PID.");
            await client.WriteAsync(new byte[] { PidReceived }, deadline.Token).ConfigureAwait(false);
            return processId;
        }
        catch (OperationCanceledException) when (!cancellation.IsCancellationRequested && deadline.IsCancellationRequested)
        {
            throw new TimeoutException("Instance handoff timed out.");
        }
    }

    public static async Task ListenAsync(NamedPipeServerStream server, int processId, Action requestExit,
        CancellationToken cancellation)
    {
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(processId);
        var command = new byte[1];
        var reply = new byte[sizeof(int)];
        BinaryPrimitives.WriteInt32LittleEndian(reply, processId);

        while (!cancellation.IsCancellationRequested)
        {
            try
            {
                await server.WaitForConnectionAsync(cancellation).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (cancellation.IsCancellationRequested)
            {
                return;
            }

            using var peer = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
            peer.CancelAfter(PeerTimeout);
            if (await TryConfirmAsync(server, command, reply, peer.Token).ConfigureAwait(false))
                requestExit();

            // On a failed shutdown the same instance can accept another replacement request.
            if (cancellation.IsCancellationRequested) return;
            server.Disconnect();
        }
    }

    private static async Task<bool> TryConfirmAsync(NamedPipeServerStream server, byte[] command, byte[] reply,
        CancellationToken cancellation)
    {
        try
        {
            if (await server.ReadAsync(command, cancellation).ConfigureAwait(false) != 1 || command[0] != ExitCommand)
                return false;

            await server.WriteAsync(reply, cancellation).ConfigureAwait(false);
            // A queued reply is not enough: the old process can exit only after the client reads the PID.
            return await server.ReadAsync(command, cancellation).ConfigureAwait(false) == 1 && command[0] == PidReceived;
        }
        catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { return false; }
        catch (IOException) { return false; }
    }
}
