using System.Net;
using System.Net.Mail;
using System.Text;
using Dpms.OutlookConnector;

namespace Dpms.OutlookConnector.Desktop;

internal static class OutageMail
{
    public static async Task Send(SmtpSettings settings, LinkIncident? outlook, LinkIncident? dpms, int waiting,
        Func<string, string> label, CancellationToken cancellation)
    {
        settings.Validate();
        using var message = new MailMessage(new MailAddress(settings.From), new MailAddress(settings.To))
        {
            Subject = "DPMS Outlook: проблема связи",
            SubjectEncoding = Encoding.UTF8,
            BodyEncoding = Encoding.UTF8,
            IsBodyHtml = false,
        };
        var body = new StringBuilder();
        Add("Почтовый сервер", outlook);
        Add("DPMS", dpms);
        body.Append("Ожидают отправки: ").AppendLine(waiting.ToString(System.Globalization.CultureInfo.InvariantCulture));
        message.Body = body.ToString();

        // The approved relay must offer STARTTLS with normal system certificate verification.
        using var smtp = new SmtpClient(settings.Host, settings.Port)
        {
            EnableSsl = true, UseDefaultCredentials = false, DeliveryMethod = SmtpDeliveryMethod.Network,
            Credentials = settings.Username.Length == 0 ? null : new NetworkCredential(settings.Username, settings.Password),
        };
        await smtp.SendMailAsync(message, cancellation).ConfigureAwait(false);

        void Add(string name, LinkIncident? incident)
        {
            if (incident is not { Notified: false }) return;
            body.Append(name).Append(": ").AppendLine(label(incident.Code));
            body.Append("Обнаружено: ").AppendLine(incident.Since.ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss zzz"));
            body.AppendLine(incident.Active ? "Связь ещё не подтверждена." : "Связь уже восстановлена.");
            body.AppendLine();
        }
    }
}
