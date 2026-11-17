# DPMS Outlook Connector: исходный код, сборка и границы безопасности

Дата проверки: 17.11.2026. Версия приложения: 0.1.0, тестовый кандидат.
Source commit: `01541ca4b0573fca8be276a8a106dbf0162d6d25`.

**Статус: НЕ одобрен для установки в корпоративный контур.** Это техническое
описание и материал для IT/ИБ, а не сертификат безопасности. Код создан Codex
в рамках этой разработки и проверялся автоматизированными тестами и агентским
review. Независимого человеческого аудита и полной native-приёмки Windows не было.
17.11 пользователь сообщил, что EXE запустился на рабочем Windows. Это подтверждение
старта со слов пользователя, не проверка COM, DPAPI, сети или безопасности.
Отсутствие неизвестных уязвимостей не доказано. До допуска IT не подключать
реальную рабочую почту и не обходить ограничения организации.

## 1. Что является листингом

`SOURCE-LISTING.txt` рядом с этим документом - **ЛИСТИНГ ИСХОДНОГО КОДА**, а не
псевдокод, не сокращённый пример и не декомпиляция EXE. Он автоматически собран
из Git-объектов указанного commit, с именами файлов, SHA-256 и номерами строк.
В `source/` находятся те же исходные файлы без добавленных номеров строк.

Листинг содержит весь собственный Windows-клиент, его project/config/manifest,
тесты и серверный/UI scope этой функции. Разделы явно разделены: Python и
TypeScript не компилируются внутрь Windows EXE. Это не полный монорепозиторий
DPMS и не исходники Microsoft .NET, Outlook или Windows. Эти сторонние компоненты
имеют собственную реализацию и риски; их нельзя проверить по нашему листингу.
`SOURCE-MANIFEST.json` связывает пути и hashes с source commit.

Этот файл - **пояснительная записка**, не листинг. `export-review.mjs` - отдельный
служебный генератор пакета для review; он не входит в EXE, не устанавливается
на рабочем Windows и не запускается клиентом.

## 2. На чём написано

| Часть | Технология | Входит в EXE |
| --- | --- | --- |
| Окно и значок tray | C#, Windows Forms, `net10.0-windows` | Да |
| Протокол, лимиты, повторы | C#, библиотека Core, `net10.0` | Да |
| Чтение Outlook | Windows COM/MAPI через установленный classic Outlook | Клиентский код да; Outlook отдельно |
| Защита локального подключения | Windows DPAPI через системные `crypt32.dll`/`kernel32.dll` | Вызовы да; Windows DLL отдельно |
| Приём и хранение на сервере | Python, FastAPI, SQLAlchemy, PostgreSQL | Нет |
| Настройки и просмотр в DPMS | TypeScript, React | Нет |
| Тесты | C#/xUnit, Python unittest, Playwright | Нет |

Это не Outlook-макрос, не PowerShell-скрипт, не драйвер и не Windows service.
Клиент не содержит AI-модель и в проверенном коде не обращается к AI API.
Для работы требуется уже запущенный classic Outlook с доступным профилем.

Карта основных файлов, от корня `source/connectors/outlook-windows/`:

- `Desktop/Program.cs`: точка входа, один экземпляр окна и режим scanner.
- `Desktop/MainForm.cs`: подключение, ручной старт/пауза, tray, автозапуск,
  создание дочернего процесса этого же EXE с аргументом `--scan`.
- `Desktop/OutlookReader.cs`: чтение default Inbox и вложений через COM.
- `Core/DpmsClient.cs`: только HTTP POST pair/sync, обработка ACK и ошибок.
- `Core/Protocol.cs`: формат данных, разрешённый HTTPS URL и размеры.
- `Core/SyncEngine.cs`, `ScanSnapshot.cs`: повторная доставка и очередь снимка.
- `Desktop/ProtectedState.cs`, `AttachmentStaging.cs`: локальное состояние
  и удаление временных вложений.
- `Desktop/app.manifest`: `asInvoker`, без запроса повышения прав.

## 3. Поток данных и доступ к инфраструктуре

```text
Уже открытый classic Outlook / локальный кэш Exchange
  -> дочерний процесс EXE --scan, COM/MAPI
  -> JSON в перенаправленном stdout pipe родительскому процессу
  -> HTTPS POST в выбранный приёмник
  -> серверный API -> primary PostgreSQL DPMS
```

Передаются тема, отправитель, To/CC, даты, признаки встреч и выбранные группы
данных: plain text/HTML и вложения. Для встреч читаются свойства входящего
сообщения, не содержимое всего Calendar; HTML тела встречи отдельно не извлекается.
SHA-256 идентификаторов используется для дедупликации, **не для обезличивания**:
сама почта, адрес ящика и вложения передаются открытым содержимым внутри TLS.
Base64 вложений также не является шифрованием.

В коде Windows-клиента нет SQL-драйвера, пароля PostgreSQL, обращения к SQL-порту,
сканера сети, собственного TCP/HTTP listener, удалённой командной оболочки,
самообновления или загрузки исполняемого кода с сервера. Нет вызовов отправки,
удаления, перемещения или сохранения изменений объектов Outlook. Это наблюдения
по конкретным исходникам, а не доказательство отсутствия всех побочных эффектов.
Outlook, Windows, runtime и корпоративные надстройки могут выполнять свои действия.

Важное различие: `asInvoker` означает права запустившего пользователя, а не
песочницу. COM-доступ не ограничен отдельным read-only permission. Клиент сам
выбирает не вызывать изменяющие методы. При ошибке, подмене EXE или компрометации
процесса потенциальный доступ шире, чем описанный сценарий. Запуск с повышенными
правами не нужен и увеличивает последствия возможной ошибки.

### Сеть

- Приёмник вводится пользователем. Допустим HTTPS origin без пути, query,
  fragment или пароля в URL; произвольный hostname/IP и HTTPS-порт не запрещены.
- Запросы клиента: `POST /api/mail-import/pair` и `POST /api/mail-import/sync`.
- TLS verification не отключена; автоматические redirects и cookies отключены.
  Deadline запроса 45 секунд, ответ ограничен 64 KiB; batch ограничен 32 MiB.
- Нет закреплённого allowlist доменов или certificate pinning. Ошибочный либо
  подконтрольный третьей стороне HTTPS endpoint может принять код подключения,
  выдать формально корректный ответ и затем получить почту после старта sync.
  TLS подтверждает соединение с выбранным адресом, не полномочия получателя.
- Proxy не настроен явно: `HttpClient` может использовать системные или
  environment proxy settings. Это нужно проверять в корпоративной среде.
  [Microsoft: DefaultProxy](https://learn.microsoft.com/en-us/dotnet/api/system.net.http.httpclient.defaultproxy?view=net-10.0).
- DNS, проверка сертификатов и собственный Exchange-трафик Outlook не описываются
  двумя URL клиента. Утверждение «весь компьютер общается только с DPMS» неверно.
- Строки `http://schemas.microsoft.com/mapi/...` в исходниках - имена MAPI
  свойств для `PropertyAccessor`, не команды скачать сайт по HTTP.
  [Microsoft: namespaces](https://learn.microsoft.com/en-us/office/vba/outlook/how-to/navigation/referencing-properties-by-namespace).

### Локальные изменения

| Объект | Что происходит | Ограничение |
| --- | --- | --- |
| `%LOCALAPPDATA%\DPMS\OutlookConnector\connection.state` | DPAPI-шифрованные параметры, device secret, очередь и hashes подтверждённых items | Не защищает от процесса того же пользователя/компрометации сессии |
| `connection.state.tmp` там же | Временная шифрованная запись перед заменой state | Не body cache |
| `staging\<GUID>\attachment.bin` там же | Fallback `SaveAsFile` для некоторых вложений, ACL текущего пользователя | Файл plaintext; после crash может остаться до следующего запуска |
| `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, значение `DPMS.OutlookConnector` | Opt-in checkbox создаёт запись автозапуска; снятие checkbox удаляет её | «Отвязать» само по себе не снимает checkbox |
| Память и pipes процессов | Тела, файлы и device secret нужны в plaintext для обработки | Полная очистка managed strings, swap и crash dumps не гарантируется |

DPAPI привязывает защиту к контексту Windows-пользователя; это не отдельное
хранилище с независимым паролем и не шифрование всей рабочей машины.
[Microsoft: CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata).

Штатного журнала с телами писем нет, но внутренний режим `--scan` возвращает
полные данные через stdout. Он может читать Outlook с переданными scan options
без UI pairing: pairing защищает серверный API, а не локальный доступ к Outlook.
Не запускать `--scan` с реальной почтой с перенаправлением в общедоступный log.
Очистка staging ограничена ожидаемыми файлами и не является
гарантированным стиранием следов на диске. Обычные вложения читаются в память;
файлы и HTML намеренно не открываются/не исполняются.

Закрытие окна оставляет приложение в tray. Для остановки нужен «Выход»; пауза
останавливает синхронизацию. Opt-in автозапуск может возобновить ранее включённую
синхронизацию при следующем входе. Отзыв устройства на сервере отдельный от
локального «Отвязать»; уже импортированные письма от этого не удаляются.

## 4. Как получен EXE

Сборка выполнялась на Mac для Windows x64, не на рабочем компьютере и не на
сервере организации. Текущая проверка окружения и сохранённых build metadata:

- .NET SDK `10.0.402`, MSBuild `18.9.15+a8dd0577c`, host `osx-arm64`.
- C# compiler Roslyn `5.9.0-1.26505.111`, commit `a8dd0577c5c13f43a2f57fe33b4ff11b90f6371e`.
- Target `win-x64`, Release; приложение `0.1.0`.
- В self-contained output: `Microsoft.NETCore.App` и `Microsoft.WindowsDesktop.App`
  версии `10.0.13` по `runtimeconfig.json`/`deps.json` сохранённой сборки.
- Informational version: `0.1.0+01541ca4b0573fca8be276a8a106dbf0162d6d25`.
- Нет Native AOT, обфускации или дополнительного packer в команде сборки;
  trimming выключен. `DebugType=None` исключает обычные debug symbols.

Фактическая финальная команда из корня репозитория после restore:

```sh
dotnet publish connectors/outlook-windows/Desktop/Desktop.csproj \
  -c Release -r win-x64 --self-contained true \
  -p:PublishSingleFile=true \
  -p:IncludeNativeLibrariesForSelfExtract=true \
  -p:DebugType=None \
  -p:SourceRevisionId=01541ca4b0573fca8be276a8a106dbf0162d6d25 \
  -o connectors/outlook-windows/artifacts/win-x64 --no-restore
```

C# компилируется в managed IL; .NET исполняет его с JIT-компиляцией. Publish
упаковывает код и runtime в один Windows EXE. Размер не означает, что весь EXE
написан для этого проекта: значительную часть составляет Microsoft runtime.
[Microsoft: managed execution](https://learn.microsoft.com/en-us/dotnet/standard/managed-execution-process).

`IncludeNativeLibrariesForSelfExtract=true` означает, что при запуске runtime
может извлекать native DLL на диск: обычно `%TEMP%\.net`, либо в заданный
`DOTNET_BUNDLE_EXTRACT_BASE_DIR`. Это дополнительные локальные файлы помимо
нашего state/staging; права на каталог требуют проверки IT.
[Microsoft: single-file deployment](https://learn.microsoft.com/en-us/dotnet/core/deploying/single-file/overview).

Self-contained runtime не становится актуальным только от обновления отдельно
установленного .NET: владелец приложения должен выпускать обновлённую сборку.
[Microsoft: publishing modes](https://learn.microsoft.com/en-us/dotnet/core/deploying/).

### Зависимости

В `Core.csproj` и `Desktop.csproj` нет сторонних application `PackageReference`;
Desktop ссылается на собственный Core. Это не означает «без стороннего кода»:
Microsoft runtime, SDK, Windows COM и Outlook остаются зависимостями.
В restore metadata есть build-time `Microsoft.NET.ILLink.Tasks/10.0.13` и runtime
packs Microsoft. Список runtime libraries сохранённой сборки: собственные
`DPMS.OutlookConnector/0.1.0`, `Core/1.0.0` и два runtimepack `10.0.13` выше.

Tests отдельно используют `Microsoft.NET.Test.Sdk 17.14.1`, `xunit 2.9.3`,
`xunit.runner.visualstudio 3.0.2`; среди транзитивных test-only зависимостей есть
`Newtonsoft.Json 13.0.3`, Microsoft.TestPlatform/CodeCoverage и компоненты xUnit.
Они не перечислены как runtime libraries EXE. Repository `NuGet.Config` указывает
публичный `nuget.org`; установка SDK использовала Homebrew. Build chain и caches
не прошли независимый supply-chain audit. Полный SBOM и актуальный CVE-аудит
всех Microsoft/OS/Outlook компонентов не заявляются.

`global.json` и locked dependency restore для исходного snapshot отсутствуют.
Поэтому новая сборка на другом SDK/cache может дать другие байты. Для независимого
повтора IT следует зафиксировать SDK/runtime/packages, проверить их происхождение
и строить в чистой VM из `source/`, с явным `--configfile` для NuGet. Сам Git SHA
не фиксирует весь toolchain. Node.js-генератор review нужен только для документов,
не для сборки C# и не для запуска EXE.

Для IT: в чистой среде с утверждённым SDK, из корня `source/`, перед приведённой
командой publish можно восстановить build dependencies и отдельно выполнить
тесты. Это инструкции для независимого повтора, не выполненные сейчас команды:

```sh
dotnet restore connectors/outlook-windows/Desktop/Desktop.csproj \
  -r win-x64 -p:SelfContained=true -p:PublishSingleFile=true \
  --configfile connectors/outlook-windows/NuGet.Config
dotnet restore connectors/outlook-windows/Tests/Tests.csproj \
  --configfile connectors/outlook-windows/NuGet.Config
dotnet test connectors/outlook-windows/Tests/Tests.csproj -c Release --no-restore
```

Restore может обращаться к публичному NuGet: выполнять только в разрешённой
build-среде или использовать проверенное корпоративное зеркало. При сравнении
байтов toolchain и версии пакетов нужно фиксировать отдельно; успешная новая
сборка без такого сравнения не доказывает идентичность исходному EXE.

## 5. Как связаны код и выданный файл

SHA-256 выданного EXE:

```text
c41f4d734cc17ae9934d535272933c6ba7954b9eb3b30b096fdb1d89d5a902f8
```

SHA-256 первоначального `DPMS-OutlookConnector-win-x64-01541ca-candidate.zip`:

```text
2d68690eb68d01e8556fa62eb83086810dab40328081ba5a4225f5ca21b8961f
```

При подготовке этого review-пакета EXE не пересобирался и не менялся. Hash повторно
проверен. В review-архиве находится копия того же EXE; hash всего review-архива
другой, поскольку добавлены документы и исходники.

Проверка файла на Windows без его запуска:

```powershell
Get-FileHash .\DPMS.OutlookConnector.exe -Algorithm SHA256
Get-AuthenticodeSignature .\DPMS.OutlookConnector.exe
```

Сборка unsigned: Authenticode-подпись организации не добавлялась. Совпадение hash
доказывает совпадение файлов, **не безопасность**. Source SHA и build record -
наша трассировка происхождения, не независимое доказательство, что внутри нет
ничего сверх исходников. Независимая чистая сборка/сравнение и анализ бинарника
IT сильнее такого утверждения. Байт-в-байт воспроизводимость не проверена.

## 6. Что проверено и чего не проверяли

16.11 пройдены152 synthetic tests:37 C# protocol/client,64 backend (из них31 на
изолированной PostgreSQL),51 browser. Проверены повторы, ACK после commit,
границы данных, изоляция владельцев, отзыв, stale/conflict, вложения, rollback,
конкуренция и защита уже импортированного содержимого при смене grants.
Проверены TypeScript/ESLint, сборки и scoped source review. Это результаты
разработки; они не равны pentest, антивирусному заключению или аудиту Windows.

17.11 пользователь подтвердил только запуск EXE на рабочем Windows; сайт DPMS
оттуда не открывается. Не выполнены: проверка реального обмена с Outlook,
контроль трафика/registry/files
под EDR, проверка COM-policy prompts, native DPI/tray/DPAPI, crash cleanup,
malformed-mail fuzzing, независимый бинарный анализ и проверка всех CVE.
Агент не проверял корпоративную сеть. Server migration/deploy не
выполнены; отсутствие доступа к сайту известно со слов пользователя, TCP/proxy
маршрут к отдельному приёмнику ещё не проверен. Адрес приёмника не выбран.
Реальные письма и credentials агентом
не читались; проверки проводились на synthetic данных.

## 7. Остаточные риски и допуск IT

| Риск | Почему актуален | Что требуется до рабочей установки |
| --- | --- | --- |
| Экспорт конфиденциальной почты | Это основное назначение программы; DLP/labels/IRM она не заменяет | Разрешение владельца данных и ИБ, допустимый объём/классы данных, retention/deletion policy |
| Неверный получатель | Нет endpoint allowlist; корректного TLS недостаточно | Утверждённый адрес и egress rules; при необходимости отдельное code hardening |
| Привилегии Outlook/пользователя | Нет отдельного read-only sandbox | Только обычный пользователь, проверенный EXE, изолированная тестовая среда |
| Plaintext и вредоносные вложения | Память/pipe/staging; файлы не сканируются самим коннектором | Проверка ACL/crash cleanup, approved antivirus/quarantine, отсутствие реальных писем в dump/log |
| Ошибки парсинга и нагрузка | COM/native runtime, большие mailbox/вложения и повторный опрос | Негативные тесты, мониторинг CPU/RAM/IO; лимиты не доказывают отсутствие DoS |
| Подмена/уязвимости сборки | Unsigned EXE, включённый runtime, нет независимой аттестации | Чистая сборка IT, проверка зависимостей, подпись и правила обновления |
| Серверное хранение | Текст и BYTEA доступны серверу; нет application E2E encryption | Сегментация, TLS, backup, контроль администраторов, storage encryption/retention и ingress limits |

Предлагаемый порядок допуска:

1. IT/ИБ читают эту записку, листинг и diff указанного source commit.
2. Подтверждают право переносить рабочую почту и разрешённое место хранения.
3. Проверяют checksum, зависимости и бинарник approved tools либо собирают сами.
4. Запускают в изолированной Windows VM с тестовым Outlook-профилем без реальных
   писем, под обычным пользователем; наблюдают процессы, сеть, registry и файлы.
5. Проверяют неверный адрес, отказ TLS/proxy, revoke, pause/exit, crash, вредоносные
   и oversized fixtures, целостность писем/вложений, отсутствие source mutations.
6. Отдельно разрешают endpoint/firewall и server deployment после backup.
7. Только после документированного допуска выполняют ограниченный пилот.

Outlook Object Model Guard может показывать запросы доступа: не отключать
его и не обходить EDR/SmartScreen ради теста.
[Microsoft: security warnings](https://learn.microsoft.com/en-us/office/vba/outlook/how-to/security/outlook-object-model-security-warnings).

Вывод: пакет делает код и происхождение проверяемыми. Он **не позволяет обещать
«угроз для внутренней инфраструктуры нет»**. До проверки и решения IT это
исследовательский кандидат, а не разрешённое рабочее ПО.

Практический порядок установки и подключения: `QUICK-START.md` рядом с этим
документом. Обновление серверной части DPMS требуется до получения рабочего кода.
