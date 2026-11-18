using System.ComponentModel;
using System.Diagnostics;
using System.Text.Json;
using Dpms.OutlookConnector;

namespace Dpms.OutlookConnector.Desktop;

internal static class Program
{
    private const string InstanceMutex = @"Local\DPMS.OutlookConnector";
    private const string LaunchMutex = @"Local\DPMS.OutlookConnector.Launch.v1";

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
        var minimized = args.Contains("--minimized");
        ApplicationConfiguration.Initialize();
        try { return RunConnector(minimized); }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or WaitHandleCannotBeOpenedException
            or Win32Exception)
        {
            return StartupError("Не удалось проверить единственный экземпляр коннектора. Запустите его под тем же пользователем и с теми же правами.", minimized);
        }
    }

    private static int RunConnector(bool minimized)
    {
        using var self = Process.GetCurrentProcess();
        var session = self.SessionId;
        var pipeName = $"DPMS.OutlookConnector.Handoff.v1.{session}";
        using var launch = new Mutex(false, LaunchMutex);
        using var instance = new Mutex(false, InstanceMutex);
        if (!Enter(launch, 30_000))
            return StartupError("Другой запуск коннектора ещё не завершился. Повторите попытку позже.", minimized);

        // Keep the startup mutex through the handshake so simultaneous launchers cannot race.
        var ownsLaunch = true;
        var ownsInstance = false;
        var replaced = false;
        try
        {
            ownsInstance = Enter(instance, 0);
            if (!ownsInstance)
            {
                if (minimized) return 0; // Autostart never interrupts an interactive instance.
                int previousId;
                try
                {
                    using var requestDeadline = new CancellationTokenSource(TimeSpan.FromSeconds(3));
                    previousId = InstanceHandoff.RequestExitAsync(pipeName, requestDeadline.Token).GetAwaiter().GetResult();
                }
                catch (Exception error) when (error is OperationCanceledException or IOException or InvalidDataException
                    or TimeoutException or UnauthorizedAccessException)
                {
                    // Older versions have the same mutex but no handoff endpoint.
                    ownsInstance = Enter(instance, 0);
                    if (!ownsInstance)
                        return StartupError("Предыдущий коннектор не принял запрос на выход. Выберите «Выход» в его меню в трее и запустите новый EXE.", minimized);
                    previousId = 0;
                }

                if (!ownsInstance)
                {
                    if (!WaitForPreviousExit(previousId, session))
                        return StartupError("Предыдущий процесс ещё завершает работу. Новая копия не запущена.", minimized);
                    ownsInstance = Enter(instance, 1000);
                    if (!ownsInstance)
                        return StartupError("Коннектор уже запущен. Вторая копия не открыта.", minimized);
                    replaced = true;
                }
            }

            using var server = InstanceHandoff.CreateServer(pipeName);
            using var form = new MainForm(minimized, replaced);
            _ = form.Handle; // The background handoff handler posts onto this UI thread.
            using var stopping = new CancellationTokenSource();
            var listener = InstanceHandoff.ListenAsync(server, Environment.ProcessId, form.RequestReplacement, stopping.Token);
            launch.ReleaseMutex();
            ownsLaunch = false;
            try { Application.Run(form); }
            finally
            {
                stopping.Cancel();
                listener.GetAwaiter().GetResult();
            }
            return 0;
        }
        finally
        {
            if (ownsInstance) instance.ReleaseMutex();
            if (ownsLaunch) launch.ReleaseMutex();
        }
    }

    private static bool Enter(Mutex mutex, int milliseconds)
    {
        try { return mutex.WaitOne(milliseconds); }
        catch (AbandonedMutexException) { return true; }
    }

    private static bool WaitForPreviousExit(int processId, int session)
    {
        if (processId <= 0 || processId == Environment.ProcessId) return false;
        Process previous;
        try { previous = Process.GetProcessById(processId); }
        catch (ArgumentException) { return true; } // The previous process already exited.
        using (previous)
        {
            try { return previous.HasExited || previous.SessionId == session && previous.WaitForExit(25_000); }
            catch (InvalidOperationException) { return previous.HasExited; }
        }
    }

    private static int StartupError(string message, bool minimized)
    {
        if (!minimized)
            MessageBox.Show(message, "DPMS Outlook", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        return 1;
    }
}
