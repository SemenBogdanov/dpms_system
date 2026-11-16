using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text.Json;
using Dpms.OutlookConnector;

namespace Dpms.OutlookConnector.Desktop;

internal sealed class ProtectedState
{
    private readonly object gate = new();
    private readonly string directory = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "DPMS", "OutlookConnector");
    private string FilePath => Path.Combine(directory, "connection.state");

    public LocalState Load()
    {
        if (!File.Exists(FilePath)) return new LocalState();
        if (new FileInfo(FilePath).Length > 5_000_000) throw new ConnectorException("local_state_invalid");
        var bytes = Transform(File.ReadAllBytes(FilePath), protect: false);
        try
        {
            return JsonSerializer.Deserialize<LocalState>(bytes, Protocol.Json)
                ?? throw new ConnectorException("local_state_invalid");
        }
        finally { CryptographicOperations.ZeroMemory(bytes); }
    }

    public void Save(LocalState state)
    {
        lock (gate) SaveLocked(state);
    }

    private void SaveLocked(LocalState state)
    {
        var bytes = JsonSerializer.SerializeToUtf8Bytes(state, Protocol.Json);
        try
        {
            var encrypted = Transform(bytes, protect: true);
            Directory.CreateDirectory(directory);
            var temporary = FilePath + ".tmp";
            File.WriteAllBytes(temporary, encrypted);
            File.Move(temporary, FilePath, overwrite: true);
        }
        finally { CryptographicOperations.ZeroMemory(bytes); }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct Blob { public int Length; public IntPtr Data; }

    [DllImport("crypt32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CryptProtectData(ref Blob input, string description, IntPtr entropy,
        IntPtr reserved, IntPtr prompt, int flags, out Blob output);

    [DllImport("crypt32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CryptUnprotectData(ref Blob input, out IntPtr description, IntPtr entropy,
        IntPtr reserved, IntPtr prompt, int flags, out Blob output);

    [DllImport("kernel32.dll")]
    private static extern IntPtr LocalFree(IntPtr pointer);

    private static byte[] Transform(byte[] bytes, bool protect)
    {
        var input = new Blob { Length = bytes.Length, Data = Marshal.AllocHGlobal(bytes.Length) };
        Blob output = default;
        var description = IntPtr.Zero;
        try
        {
            Marshal.Copy(bytes, 0, input.Data, bytes.Length);
            var success = protect
                ? CryptProtectData(ref input, "DPMS Outlook Connector", IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, 1, out output)
                : CryptUnprotectData(ref input, out description, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, 1, out output);
            if (!success) throw new ConnectorException("local_protection_failed");
            var result = new byte[output.Length];
            Marshal.Copy(output.Data, result, 0, output.Length);
            return result;
        }
        finally
        {
            for (var i = 0; i < input.Length; i++) Marshal.WriteByte(input.Data, i, 0);
            Marshal.FreeHGlobal(input.Data);
            if (output.Data != IntPtr.Zero)
            {
                if (!protect) for (var i = 0; i < output.Length; i++) Marshal.WriteByte(output.Data, i, 0);
                LocalFree(output.Data);
            }
            if (description != IntPtr.Zero) LocalFree(description);
        }
    }
}
