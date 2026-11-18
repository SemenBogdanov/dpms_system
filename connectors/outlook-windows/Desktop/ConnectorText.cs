using Dpms.OutlookConnector;

namespace Dpms.OutlookConnector.Desktop;

internal static class ConnectorText
{
    public static string Code(Exception error) => error switch
    {
        ConnectorException known => known.Code,
        OperationCanceledException => "operation_cancelled",
        HttpRequestException => "server_unavailable",
        ArgumentException => "settings_invalid",
        _ => "operation_failed",
    };

    public static string Describe(Exception error) => Describe(Code(error));

    public static string Describe(string code) => code switch
    {
        "ok" or "dpms_ok" => "Доступно",
        "check_required" => "Связь не проверена",
        "check_timeout" => "Тайм-аут проверки связи",
        "sync_timeout" => "Тайм-аут синхронизации. Неподтверждённые письма остаются в очереди.",
        "operation_cancelled" => "Операция отменена",
        "operation_busy" => "Дождитесь окончания текущей операции.",
        "settings_invalid" or "db_settings_invalid" or "connector_settings_invalid" or "invalid_server_url" => "Проверьте параметры подключения и сроки ожидания.",
        "smtp_settings_invalid" => "Проверьте разрешённый SMTP-сервер, порт STARTTLS и адреса отправителя и получателя.",
        "autorun_failed" => "Не удалось изменить автозапуск Windows.",
        "not_paired" => "Сначала подключите устройство.",
        "invalid_pairing_code" => "Некорректный код подключения HTTPS.",
        "invalid_device_name" => "Укажите имя устройства от 1 до 100 символов.",
        "pair_uncertain" => "Результат привязки неизвестен. Проверьте состояние устройства в DPMS перед повтором.",
        "db_unavailable" => "База DPMS не отвечает.",
        "db_tls_failed" => "Не удалось установить защищённое соединение с БД.",
        "db_tls_pin_invalid" => "Неверный формат SHA-256 сертификата сервера.",
        "db_tls_pin_conflict" => "Укажите либо CA, либо SHA-256, но не оба.",
        "db_tls_pin_rejected" => "Сертификат сервера не совпал с отпечатком или недействителен.",
        "db_tls_configuration" => "Мешают неявные TLS-настройки PostgreSQL (PGSSL* или локальные сертификаты).",
        "db_login_failed" => "PostgreSQL отклонил вход. Проверьте пароль и правила доступа.",
        "db_login_not_provisioned" => "Логин БД не привязан к активному пользователю DPMS.",
        "db_not_installed" => "Приёмник DPMS не найден в указанной базе и схеме.",
        "db_pending" => "DPMS ещё обрабатывает запрос. Идентификатор запроса сохранён.",
        "db_queue_full" => "Очередь приёмника DPMS заполнена. Локальные письма сохранены.",
        "access_denied" => "Доступ устройства DPMS отклонён или отозван.",
        "outlook_unavailable" => "Classic Outlook недоступен.",
        "outlook_timeout" => "Outlook не ответил в отведённое время.",
        "outlook_scanner_stop_failed" => "Не удалось остановить процесс чтения Outlook. Закройте запросы Outlook и повторите «Выход».",
        "mailbox_identity_unavailable" => "Не удалось определить основной ящик Outlook.",
        "outlook_offline" or "exchange_offline" or "exchange_disconnected" => "Outlook не подключён к почтовому серверу.",
        "outlook_unverified" or "exchange_unverified" or "outlook_non_exchange" or "exchange_state_unknown"
            or "outlook_account_type_unknown" or "outlook_probe_failed" => "Связь Outlook с почтовым сервером не подтверждена.",
        "mailbox_mismatch" or "outbox_mailbox_mismatch" => "Выбран другой ящик Outlook. Письма текущей привязки не отправлены.",
        "snapshot_too_large" => "Слишком много писем в области чтения. Уже накопленные письма сохранены.",
        "source_changed_during_scan" => "Источник изменился во время чтения.",
        "source_left_inbox" => "Письмо уже не во «Входящих».",
        "source_not_downloaded" => "Письмо ещё не загружено целиком.",
        "missing_item_identity" => "Outlook не предоставил идентификатор письма.",
        "invalid_item_identity" => "Неверный формат идентификатора письма.",
        "item_too_large" or "batch_too_large" or "scan_too_large" => "Превышен предел размера.",
        "unsupported_attachment" => "Неподдерживаемый формат вложения.",
        "unsupported_text" => "Неподдерживаемые символы в письме.",
        "invalid_source_date" => "Некорректная дата письма.",
        "incomplete_meeting" => "Outlook не предоставил полные данные встречи.",
        "outlook_com" or "outlook_read_failed" or "outlook_scan_failed" or "invalid_scan" => "Не удалось прочитать данные Outlook.",
        "local_state_invalid" => "Локальные настройки не прочитаны.",
        "local_protection_failed" => "Не удалось сохранить защищённое локальное состояние.",
        "staging_cleanup_failed" => "Не удалось удалить временное вложение.",
        "outbox_full" => "Локальная очередь заполнена. Непринятые письма не удалены.",
        "outbox_invalid" or "outbox_io_failed" or "outbox_protection_failed" => "Не удалось прочитать или сохранить локальную очередь. Перенос остановлен.",
        "endpoint_unavailable" => "HTTPS-приёмник DPMS не отвечает.",
        "redirect_blocked" => "Перенаправление DPMS заблокировано.",
        "sync_conflict" => "DPMS отклонил пачку. Письма в очереди сохранены.",
        "item_version_conflict" => "Конфликт версии. Сохранённая копия DPMS не изменена.",
        "rate_limited" => "Слишком много запросов. Письма сохранены для повтора.",
        "server_unavailable" => "Сервер DPMS временно недоступен.",
        "invalid_ack" or "invalid_response" => "Некорректное подтверждение. Письма не удалены из очереди.",
        _ => "Операция не завершена.",
    };

    public static string Stage(ScanStage stage) => stage switch
    {
        ScanStage.OpenItem => "открытие письма", ScanStage.VerifyInbox => "папка «Входящие»",
        ScanStage.MessageClass => "тип письма", ScanStage.DownloadState => "загрузка",
        ScanStage.Identity => "идентификатор", ScanStage.Properties => "свойства",
        ScanStage.Meeting => "встреча", ScanStage.Body => "текст", ScanStage.Recipients => "получатели",
        ScanStage.Attachments => "вложения", ScanStage.Encode => "подготовка",
        _ => "чтение Outlook",
    };
}
