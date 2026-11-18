using System.Buffers.Binary;
using System.IO.Pipes;
using Dpms.OutlookConnector.Desktop;
using Xunit;

namespace Dpms.OutlookConnector.Tests;

public sealed class InstanceHandoffTests
{
    private static readonly TimeSpan TestTimeout = TimeSpan.FromSeconds(10);

    [Fact]
    public async Task ValidRequestReturnsOldPidAndDispatchesExactlyOnce()
    {
        var name = Guid.NewGuid().ToString("N");
        using var server = InstanceHandoff.CreateServer(name);
        using var deadline = new CancellationTokenSource(TestTimeout);
        var requests = 0;
        var listener = InstanceHandoff.ListenAsync(server, Environment.ProcessId,
            () => Interlocked.Increment(ref requests), deadline.Token);

        Assert.Equal(Environment.ProcessId, await InstanceHandoff.RequestExitAsync(name, deadline.Token));
        await listener.WaitAsync(deadline.Token);
        Assert.Equal(1, requests);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task InvalidOrIdlePeerDoesNotDispatchAndNextRequestWorks(bool sendInvalidCommand)
    {
        var name = Guid.NewGuid().ToString("N");
        using var server = InstanceHandoff.CreateServer(name);
        using var deadline = new CancellationTokenSource(TestTimeout);
        var requests = 0;
        var listener = InstanceHandoff.ListenAsync(server, Environment.ProcessId,
            () => Interlocked.Increment(ref requests), deadline.Token);

        using (var client = new NamedPipeClientStream(".", name, PipeDirection.InOut,
                   PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly))
        {
            await client.ConnectAsync(deadline.Token);
            if (sendInvalidCommand)
                await client.WriteAsync(new byte[] { 0 }, deadline.Token);

            Assert.Equal(0, await client.ReadAsync(new byte[1], deadline.Token));
        }

        Assert.False(listener.IsCompleted);
        Assert.Equal(0, Volatile.Read(ref requests));
        Assert.Equal(Environment.ProcessId, await InstanceHandoff.RequestExitAsync(name, deadline.Token));
        await listener.WaitAsync(deadline.Token);
        Assert.Equal(1, requests);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task UnconfirmedPidDoesNotDispatchAndNextRequestWorks(bool disconnect)
    {
        var name = Guid.NewGuid().ToString("N");
        using var server = InstanceHandoff.CreateServer(name);
        using var deadline = new CancellationTokenSource(TestTimeout);
        var requests = 0;
        var listener = InstanceHandoff.ListenAsync(server, Environment.ProcessId,
            () => Interlocked.Increment(ref requests), deadline.Token);

        using (var client = new NamedPipeClientStream(".", name, PipeDirection.InOut,
                   PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly))
        {
            await client.ConnectAsync(deadline.Token);
            await client.WriteAsync(new byte[] { 1 }, deadline.Token);
            var reply = new byte[sizeof(int)];
            await client.ReadExactlyAsync(reply, deadline.Token);
            Assert.Equal(Environment.ProcessId, BinaryPrimitives.ReadInt32LittleEndian(reply));

            if (!disconnect)
                Assert.Equal(0, await client.ReadAsync(reply, deadline.Token));
        }

        Assert.False(listener.IsCompleted);
        Assert.Equal(0, Volatile.Read(ref requests));
        Assert.Equal(Environment.ProcessId, await InstanceHandoff.RequestExitAsync(name, deadline.Token));
        await listener.WaitAsync(deadline.Token);
        Assert.Equal(1, requests);
    }

    [Fact]
    public async Task LifetimeCancellationStopsListener()
    {
        using var server = InstanceHandoff.CreateServer(Guid.NewGuid().ToString("N"));
        using var lifetime = new CancellationTokenSource();
        var dispatched = false;
        var listener = InstanceHandoff.ListenAsync(server, Environment.ProcessId, () => dispatched = true, lifetime.Token);

        lifetime.Cancel();

        await listener.WaitAsync(TestTimeout);
        Assert.False(dispatched);
    }
}
