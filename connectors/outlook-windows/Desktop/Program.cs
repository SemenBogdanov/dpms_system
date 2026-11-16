using System.Text.Json;
using Dpms.OutlookConnector;

namespace Dpms.OutlookConnector.Desktop;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Contains("--scan"))
        {
            try
            {
                var options = JsonSerializer.Deserialize<ScanOptions>(Console.In.ReadToEnd(), Protocol.Json)
                    ?? throw new ConnectorException("invalid_scan_options");
                Console.Out.Write(JsonSerializer.Serialize(OutlookReader.Scan(options), Protocol.Json));
                return 0;
            }
            catch (Exception error)
            {
                var code = error is ConnectorException known ? known.Code : "outlook_scan_failed";
                Console.Out.Write(JsonSerializer.Serialize(new ScanResult("", "", "offline", [], 0, false, code), Protocol.Json));
                return 1;
            }
        }
        using var instance = new Mutex(true, "Local\\DPMS.OutlookConnector", out var created);
        if (!created) return 0;
        ApplicationConfiguration.Initialize();
        Application.Run(new MainForm(args.Contains("--minimized")));
        return 0;
    }
}
