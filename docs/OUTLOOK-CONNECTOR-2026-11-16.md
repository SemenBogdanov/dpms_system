# Коннектор Outlook: контракт V1

Статус: локальный кандидат, production не изменён. Windows 11 x64 либо
поддерживаемая Windows 10 LTSC/Enterprise x64, classic Outlook с настроенным
корпоративным Exchange. New Outlook COM не поддерживает.
Baseline `839391d`, ветка `feature/outlook-inbox-connector-20261116`.

## Scope

Односторонний перенос default Inbox: письма и входящие приглашения, обновления
и отмены встреч. Не полное зеркало Calendar/архивных/shared folders.
Источник Outlook не изменяется, исходящие сообщения/ответы не отправляются.
Уточнение пользователя 16.11: переносить всё полностью, включая текст и вложения.
Новая форма подключения выбирает текст и вложения; API сохраняет отдельные
`include_body` / `include_attachments` grants и консервативный default false.
Полный plain text и исходный HTML сохраняются в БД; UI отображает только plain
text, HTML никогда не исполняется. To/CC сохраняются как исходные строки Outlook.
Вложения хранятся в основной PostgreSQL в BYTEA и скачиваются по owner-only API.
Чтение локального Outlook cache не означает подтверждённую свежесть Exchange.

HTTPS ingestion API сохраняет записи в той же primary PostgreSQL, которую
использует DPMS. У Windows-клиента нет DB password или прямого SQL-доступа.
Текущий клиент поддерживает HTTPS, прямое подключение к PostgreSQL не реализовано.
Пользователь первоначально сообщил о доступности только сервера БД, затем уточнил:
проверял только ping. Это не подтверждает доступность TCP/HTTPS/PostgreSQL.
Запрошены проверки с рабочего Windows: сайт:443, DB-host:443, DB-host:5432.
Mac-проверка не заменяет workplace network check.

Три возможных маршрута: основной API сайта, минимальный HTTPS gateway рядом с БД,
либо отдельный будущий direct-DB transport с ограниченной ролью. Предпочтителен
HTTPS, но конкретный маршрут пока не выбран. Gateway candidate принимает только
`/pair` и `/sync`; не открывает owner UI/download routes и не запускает фоновые
службы основного приложения. Установка, сертификат, firewall, schema migration
и production release требуют отдельного approval. Сейчас они не выполнялись.

## API: `/api/mail-import`

Все owner routes используют штатного `get_current_user`; id владельца из payload
не принимается. Только device routes используют узкий opaque device bearer.
Текущий пользователь должен оставаться active; device access привязан к auth_version
на момент привязки. Все datetime timezone-aware; JSON extra fields запрещены.

- `GET /devices` -> `DeviceRead[]`.
- `POST /devices` `{name:string(1..120),include_body:boolean=false,include_attachments:boolean=false}` ->
  `{device:DeviceRead,pairing_code:string,expires_at:datetime}`. Code случайный
  high-entropy, одноразовый, срок10мин. Не обычный пароль DPMS; в БД только hash.
- `POST /devices/{uuid}/revoke` `{}` -> `DeviceRead`; owner-only, не удаляет импорт.
- `POST /pair` `{pairing_code:string}` ->
  `{device_id:uuid,device_secret:string,owner_name:string,include_body:boolean,include_attachments:boolean,protocol_version:1}`.
  Однократный обмен через atomic update/lock, в БД hash секрета, expiry1год.
- `POST /sync` с `Authorization: Bearer <device_secret>` и телом
  `{protocol_version:1,mailbox_id:hex64,mailbox_label:string<=200,
    source_state:"cached"|"online"|"offline",scan_complete:boolean=true,
    skipped_items:int=0,items:ImportedItemInput[]}`.
  Максимум 50 items / 32 MiB JSON на batch. Первый mailbox_id фиксируется у device;
  смена mailbox требует нового подключения. Ответ после commit:
  `{accepted:int,created:int,updated:int,unchanged:int,stale:int,synced_at:datetime}`.
- `GET /items?kind=mail|meeting&unread_only=false&limit=50&offset=0` ->
  `{items:ImportedItemRead[],total:int,unread_count:int}`; kind необязателен.
  Order received_at DESC,id DESC; read body только через detail.
- `GET /items/{uuid}` -> `ImportedItemRead`; owner-only, без авто-mark-read.
- `POST /items/{uuid}/read` `{is_read:boolean=true}` -> `ImportedItemRead`.
- `GET /items/{uuid}/attachments/{attachment_uuid}` -> bytes, owner-only.
  Всегда `application/octet-stream`, `Content-Disposition: attachment`, no-store,
  nosniff; исходный MIME сохраняется как метаданные, но не разрешает inline render.

`DeviceRead`: id,name,status (`pending|active|revoked|expired`),include_body,include_attachments,
mailbox_label nullable,created_at,last_sync_at nullable,source_state nullable,
expires_at nullable,last_scan_complete nullable bool,last_skipped_items int.
Никаких hash/code/secret в обычном ответе. Неполный scan показывается как warning,
last_sync_at означает доставку batch, не доказательство полноты/свежести Exchange.

`ImportedItemInput`:

- `source_id`: hex64 hash стабильного идентификатора входящего объекта;
- `kind`: `mail|meeting`;
- `source_modified_at`, `received_at`: datetime с timezone;
- `subject`: string<=1000, допускается пустой;
- `sender_name`: string<=300; `sender_address`: string<=320;
- `body_text`, `body_html`: nullable string <= 2 000 000 символов каждый,
  rejected при include_body=false; текст не обрезается молча;
- `to_recipients`, `cc_recipients`: строки <= 20 000;
- `attachments`: до 100 файлов, каждый `{filename,content_type,data_base64,sha256,
  is_inline,content_id}`. Имя <= 255, content_type <= 200, content_id <= 500;
  bytes <= 10 MiB на файл, <= 20 MiB на письмо. SHA-256 проверяется сервером.
  Отсутствие include_attachments запрещает непустой список;
- `source_is_read`: bool, не меняет DPMS unread;
- `meeting_status`: nullable `invited|updated|cancelled|response`;
- `starts_at`, `ends_at`: nullable datetime; либо оба заданы, либо оба null;
- `all_day`: bool=false; `location`: string<=1000 default="";
- `meeting_key`: nullable hex64 для связи сообщений одной встречи;
- `is_recurring`: bool=false. V1 хранит входящее приглашение серии, не разворачивает
  будущие occurrences и не обещает синхронизацию полного календаря.

`ImportedItemRead` включает поля input плюс id,mailbox_label,is_read,created_at,
updated_at. В list тела null, detail возвращает разрешённый текст. Вместо
attachment bytes выдаются manifests `{id,filename,content_type,byte_length,
sha256,is_inline,content_id}`. Скачивание отдельно проверяет владельца.

## Persistence И Повторы

Новые таблицы `mail_import_devices`, `mail_import_items`, `mail_import_attachments`,
migration 100 поверх 099. Quota: 10 000 items и 2 GiB imported content на владельца
(UTF-8 текста, HTML, To/CC и decoded attachment bytes).
Unique owner_id+mailbox_id+source_id; distinct incoming messages об изменении
одной встречи сохраняются отдельно, meeting_key связывает их, source_id убирает
повторную доставку того же письма. Никогда не удалять по отсутствию в снимке.
Старые версии не заменяют новые. Equal-version divergent payload ->409,
чтобы не зависеть от порядка доставки. Semantic hash исключает source_is_read,
source_modified_at: изменения прочтения Outlook не сбрасывают DPMS is_read.
Первичный импорт unread; значимое новое изменение существующего item ->unread.
Повтор и stale сохраняют DPMS read state. PostgreSQL transaction/advisory lock
по owner+mailbox сериализует competing devices; device row lock защищает revoke.
Grants монотонны на owner+mailbox: после первого успешного переноса с body/files
устройство с меньшими правами получает `409 mailbox_scope_mismatch` до записей,
в том числе на heartbeat. Revoked/expired история участвует в проверке.
Внутренние `body_captured` / `attachments_captured` отличают непереданную группу
от достоверно пустой. Исключение из equal-version conflict: расширение grants
может дополнить только uncaptured-группу, сохраняя остальные metadata, DPMS read
state и ID ранее captured attachments. Другое расхождение остаётся conflict;
stale версия не заполняет пропущенную группу. Quota и rollback покрывают enrichment.
Идентификатор source item берётся из Exchange PR_SOURCE_KEY и хешируется;
отсутствие/сбой чтения не переключает идентичность на EntryID/Message-ID.
Не вызывать helpers, которые создают email outbox/push/Contact/MessageThread.

## Клиент

Windows tray app .NET10, self-contained win-x64. Данные доступа защищены Windows
DPAPI текущего пользователя; логи не содержат headers, темы, bodies или secrets.
Pairing через код из DPMS. HTTPS без отключения TLS и без автоматических redirects.
Явные старт/пауза/sync now/отвязка, видны состояние источника, последняя успешная
доставка и количество. Автозапуск только по opt-in, без admin и без Windows service.
Опрос 60 сек; initial window 30 дней (выбор 1..90). В начале цикла снимается список
opaque EntryIDs (до 10 000, до 1.5 млн символов); за страницу читается до 5000 items.
После ACK всех batch сохраняется очередь оставшихся EntryIDs, не позиционный
offset живой папки. Удаление/перемещение раннего письма не сдвигает следующие;
недоступный или ушедший из Inbox объект отмечается как skipped. Очередь хранится
только в DPAPI state и не передаётся серверу. В конце начинается новый цикл для
новых/обновлённых items. Изменение count/дубли во время capture отменяют снимок.
Это best-effort чтение кэша, не transactional snapshot или Exchange delta feed.
Один scan возвращает до 60 MB JSON изменённых items. Превышение общего лимита
снимка требует меньшего периода и никогда не объявляется полным переносом.
Checkpoint hashes фиксируются только после ACK; offline/restart повторяет доставку
без дублей. Bodies и обычные attachments читаются в память. Для embedded attachments
Outlook может требовать SaveAsFile: временный файл создаётся в per-user directory
с закрытым ACL, удаляется после чтения. Аварийное завершение процесса может оставить
этот temporary file до следующего запуска: restricted cleanup выполняется при
старте, перед/после scanner и при обычном выходе после ожидания job. Это отдельный
Windows cleanup/acceptance gate, не обещание отсутствия любых plaintext artifacts
в момент crash. Symlinks/reparse points не обходятся, неизвестные файлы не удаляются.
Встречи читаются из MAPI properties самого входящего сообщения; Calendar и
`GetAssociatedAppointment` не используются. Header-only item пропускается до
полной загрузки Outlook. Transient COM error не подменяется null/пустыми полями.
Недоступные schedule details остаются null, не выдумываются из текста письма.

## Проверки И Границы

Synthetic unit/API: owner isolation, pairing one-use/expiry/revoke, source scope,
payload limits/body permission, duplicate/stale/equal-version conflict, unread,
transaction rollback, отсутствие side-effect outbox. Ephemeral PostgreSQL только
для тестов; пользовательские БД и env не использовать.
Client: pure protocol/checkpoint tests на Mac, cross-build Windows; COM, DPAPI,
tray и policy prompts проверяются на настоящем Windows, не считаются выполненными
по результату cross-build. Frontend: synthetic browser desktop/mobile, clipboard
error handling, metadata/text rendering, unread and error/offline/revoke states.
Дополнительно: attachment grant/size/hash/quota, owner-isolated downloads,
неисполнение HTML/файлов, атомарная замена вложений, оба порядка concurrent
scope upgrade/metadata retry, same-version enrichment и commit rollback.

Локально подтверждено 16.11: backend64/64 (включая31 PostgreSQL integration),
.NET37/37; browser51/51 на desktop, iPhone/WebKit и320px. Это synthetic coverage,
не real-user end-to-end acceptance. Ingress перед release должен ограничить
размер запроса, частоту, concurrency и timeout; не публиковать gateway напрямую
без TLS/reverse proxy и согласованной сетевой политики.

Ни успешная сборка, ни ping не являются подтверждением готовности к работе.
Обязательны Windows/Outlook smoke, политика организации на экспорт рабочей почты,
проверка маршрута, отдельный deployment approval и backup перед migration 100.

## Источники

- [Microsoft: новый Outlook и COM](https://learn.microsoft.com/en-us/office/dev/add-ins/outlook/one-outlook).
- [Microsoft: GlobalAppointmentID](https://learn.microsoft.com/en-us/office/vba/api/outlook.appointmentitem.globalappointmentid).
- [Microsoft: локальные даты в Outlook filters](https://learn.microsoft.com/en-us/office/vba/outlook/how-to/search-and-filter/filtering-items-using-a-date-time-comparison).
- [Microsoft: Windows cross-targeting](https://learn.microsoft.com/en-us/dotnet/core/project-sdk/msbuild-props#enablewindowstargeting).
- [Microsoft: поддерживаемые Windows для .NET](https://learn.microsoft.com/en-us/dotnet/core/install/windows).
- [Microsoft: Exchange source identity](https://learn.microsoft.com/en-us/openspecs/exchange_server_protocols/ms-oxprops/2309f198-8bc5-4111-9f6e-985c0dc6a13e).
- [Microsoft: типы обновлений встреч](https://learn.microsoft.com/en-us/office/client-developer/outlook/mapi/pidlidmeetingtype-canonical-property).
- [Microsoft: время входящей встречи](https://learn.microsoft.com/en-us/office/client-developer/outlook/mapi/pidlidappointmentstartwhole-canonical-property).
