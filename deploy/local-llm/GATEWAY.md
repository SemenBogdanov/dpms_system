# Локальный ИИ: шлюз-кандидат

Статус 17.09.2026: private HTTPS production VPS -> Mac активирован по отдельному
разрешению пользователя. Два полных native stop/start цикла PASS, gateway RUNNING,
Serve включен, Funnel выключен. 120 local tests PASS. Из backend и audit-worker
штатным клиентом выполнены синтетические запросы; каждый вернул две записи.
Проверены отказ gateway, восстановление и реальный полный конфигурационный откат.
Приложение осталось на прежних образах, ИИ-профиль в БД не создавался, реальные ТЗ
не обрабатывались. Это не полный audit-job E2E и не приемка качества атомизации.
Актуальный operational status, ограничения и rollback: [ACTIVATION.md](ACTIVATION.md).

## Границы

- Source scope: `deploy/local-llm/` и scoped overlay hooks двух deploy scripts
  в `feature/local-llama-connector`.
- `gateway.py` использует FastAPI/Uvicorn/HTTPX, как DPMS, без импорта настроек
  приложения, БД, файлов документов или конфигурации с секретами.
- Шлюз слушает только `127.0.0.1:18080`, upstream только `127.0.0.1:8080`.
  Запуск не включает Serve, не публикует порт и не создаёт Docker-контейнеры.
- DPMS продолжит подключаться по HTTPS через приватный Tailscale Serve.
  HTTP между шлюзом и llama.cpp остаётся только внутри Mac. Проверки HTTPS,
  сертификатов и allowlist в существующем backend не ослабляются.
- Единственные API: `GET /v1/models`, `POST /v1/chat/completions` с Bearer.
  Идентификатор модели закреплён; другой идентификатор ответа отклоняется.
- Только текстовые сообщения и текущие параметры DPMS. Нет tool calls,
  изображений/URL-вложений, управляющих API, потоковой выдачи, redirects или
  прокси из окружения. Заголовки клиента, включая ключ, не передаются в llama.
- 60 000 символов, 40 сообщений, 512 KiB запроса, 2 MiB ответа, до 4096 output
  tokens. Пустой или обрезанный ответ не выдаётся как успешный реестр.
- Один процесс, одна операция к модели одновременно. При занятости возвращается
  `429` с `Retry-After: 5`, очереди внутри шлюза нет. При перегрузке самого
  Uvicorn возможен `503`, это другой уровень ограничения.
- Общий deadline операции 80 секунд, короче текущего DPMS read timeout 90 секунд.
  Access logging выключен, ошибки не содержат исходный текст, пути и ключи.
- `BoundedH11Protocol` ограничивает admitted connections до 16 ещё до headers,
  даёт 5 секунд суммарно на заголовки и корректно обрабатывает keepalive.
  Готовая генерация не прерывается этим коротким таймером. Используется прежний
  h11 parser, не собственный HTTP parser. При изменении pinned Uvicorn/h11
  повторить transport review и socket tests; kernel backlog ограничен отдельно.

## Локальная проверка

Из корня worktree:

```sh
python3 -m venv deploy/local-llm/.venv
deploy/local-llm/.venv/bin/python -m pip install -r deploy/local-llm/requirements.txt
deploy/local-llm/.venv/bin/python -m unittest discover -s deploy/local-llm -p 'test_*.py' -v
deploy/local-llm/.venv/bin/python deploy/local-llm/synthetic_smoke.py
```

Unit/socket tests создают только синтетическую модель и временные loopback-порты,
закрывают их после теста. Не подключаются к приложению, БД, VPS или облаку.
Последняя команда обращается к реально запущенному llama.cpp, автоматически
принимает только единственную загруженную модель и отправляет два вымышленных
требования: кнопка Save и поле Name. Ключ для этого процесса случайный, временный,
не печатается и не записывается. Вывод содержит только статус и счётчики.
Smoke использует тот же постоянный несекретный marker незавершённой генерации,
что и основной шлюз. Повтор smoke после неопределённой ошибки не обходит блокировку.

`PASS` smoke подтверждает формат и две записи, но не качество атомизации реального
ТЗ, не интеграцию с audit-worker и не прохождение Tailscale. Содержимое ответа
модели не выводится. При недоступной модели: `BLOCKED`, exit code 2.

## Ручной запуск после проверки

Оператор задаёт через защищённое окружение `DPMS_LOCAL_LLM_BEARER` и
`DPMS_LOCAL_LLM_MODEL`. Ключ: случайные минимум 32 байта в URL-safe base64,
одинаковый для шлюза и отдельного профиля DPMS. Не помещать ключ в командную
строку, shell history, repo, чат или PersonalOS. Файлы с ключами этот кандидат
не читает. Не использовать синтетическую константу из тестов как рабочий ключ.

```sh
deploy/local-llm/.venv/bin/python deploy/local-llm/gateway.py
```

Отсутствующая/неверная конфигурация останавливает запуск без вывода значений.
`DPMS_LOCAL_LLM_PORT` меняет только loopback-порт шлюза, не адрес модели.
Не запускать несколько workers: ограничитель действует на один процесс.
Постоянный запуск установлен: `MacosStore.swift` и `launch_agent.py`.
Helper работает только со своим новым item
в login Keychain, сохраняет существующий item без перезаписи и не имеет команды
вывода ключа. `run` запускает только закреплённый при компиляции gateway.py,
не принимает пользовательские executable/script/аргументы, передаёт ограниченное
окружение и отключает Python user site/environment overrides.

После review ACL оператор готовит helper с абсолютным source path:

```sh
mkdir -p deploy/local-llm/bin
swiftc -O -o deploy/local-llm/bin/dpms-macos-store "$PWD/deploy/local-llm/MacosStore.swift"
deploy/local-llm/bin/dpms-macos-store provision
deploy/local-llm/bin/dpms-macos-store check
```

Место исходников и venv должно оставаться доверенным и доступным только владельцу.
Не переносить compiled helper отдельно от этой установки. macOS может запросить
разблокировку login Keychain; её выполняет пользователь, пароль агенту не передаётся.

`launch_agent.py plan --model <точный-id>` показывает план без установки;
`install --model <точный-id>` создаёт новый plist без ключа и не запускает его.
Существующий plist не перезаписывается. `start`, `stop`, `status` управляют только
этим пользовательским job. `status=RUNNING` требует совпадения PID службы и listener,
но не означает готовность модели к генерации.
Login LaunchAgent использует RunAtLoad, но не KeepAlive: после аварии не возникает
петли автоматических запусков. В logout/reboot без входа пользователя он не работает.
Provision/install/start и два полных stop/start цикла выполнены. `probe-vps`
дополнительно запускает только фиксированный синтетический тест в двух контейнерах;
значение собственного item не выводится и не записывается в файл.

## Отказ и восстановление

Когда Mac/llama недоступен до подключения, шлюз возвращает `503`; новое обращение
может быть выполнено после восстановления. Автоматической подмены на облако нет.

Таймаут или обрыв после отправки запроса модели не означает, что генерация
фактически остановилась. Поэтому шлюз закрывает последующие генерации кодом
`local_model_recovery_required`. Перед запросом создаётся и fsync-ится marker
`~/Library/Application Support/DPMSLocalLLM/state/inference-pending` без текстов
и идентификаторов. Его наличие блокирует inference после любого перезапуска.
Он очищается автоматически только после полностью подтверждённого результата,
полного отказа 429 или ошибки установки соединения до передачи запроса.
Ошибочные/неопределённые ответы, включая HTTP 200 с повреждённым JSON,
marker сохраняют. Health/models ничего не разблокируют.

Оператор останавливает шлюз, подтверждает, что llama больше не генерирует,
фиксирует решение о восстановлении и только тогда удаляет этот конкретный
несекретный marker, затем запускает шлюз. Одного перезапуска теперь недостаточно.
Отдельная безопасная команда подтверждения восстановления пока не реализована.
Сам gateway не перезапускает llama
и не трогает пользовательский процесс. Повторять реальную задачу до проверки
состояния нельзя. Для штатного resume DPMS нужны отдельные worker E2E tests.

## История Gates До Активации

Список ниже сохранен как история подготовки. Актуальные результаты активации,
закрытые проверки и оставшиеся gates перечислены в `ACTIVATION.md`.

1. Локальная проверка реального llama.cpp и соответствия ответа выбранной модели
   выполнена: PASS, две синтетические записи. Это не проверка через audit-worker.
2. Проверить текущие ACL/grants: разрешение только нужной пары устройств;
   узкая запись не отменяет существующий allow-all. Не заменять policy целиком.
3. Проверить завершение генерации при отмене/таймауте и восстановление шлюза.
4. Локальный transport gate закрыт: 25 дополнительных тестов, total header
   deadline, pre-header admission, drip/keepalive/pipeline. После активации
   проверить также опубликованный Serve: его внешние сокеты не принадлежат Uvicorn.
5. Login LaunchAgent установлен, собственный Keychain item создан; отрицательный
   HTTP-smoke PASS. После execve fix повторить два полных stop/start цикла:
   PID службы равен единственному PID listener; после stop исчезли оба; новый
   start создаёт только один listener. START_REQUESTED и HTTP 401 недостаточны.
   После пересборки helper macOS может запросить повторный доступ к item.
   Ротация и operator recovery CLI остаются
   отдельными контролируемыми операциями, существующий ключ не перезаписывается.
   Автозапуск зависит от входа пользователя; reboot/unattended ещё не проверены.
6. Только затем private HTTPS Serve, узкое изменение quarantine, DNS/route из
   backend и audit-worker. Сохранить остальные firewall/DNS/allowlist настройки.
7. Синтетический worker E2E, неверный ключ/другая машина/management route,
   отключение и sleep Mac, pause/resume без облачного fallback. Создание профиля
   не должно автоматически запускать реальные документы.
8. Отдельное разрешение на production-изменения и передачу выбранного реального ТЗ.

Остановка локального шлюза не останавливает DPMS, но делает локальный endpoint
недоступным. Служба и Serve активированы; профиль в БД еще не создан.
Для остановки только собственной службы:

```sh
deploy/local-llm/.venv/bin/python deploy/local-llm/launch_agent.py stop
```

Для production rollback использовать процедуру из `ACTIVATION.md`.

## Проверка предоставленной policy 17.09.2026

История подготовки policy до текущей подтвержденной активации.

Пользователь предоставил действующую policy: один unrestricted grant и стандартный
SSH check к собственным устройствам. Остальные секции только закомментированы.
Узкая дополнительная запись не отменит этот grant. Подготовлен только preview:
`runtime/tailnet-policy-candidate.json`, файл 0600, исключён из git. Адреса взяты
из read-only `tailscale status --json`, не записаны в общие project notes.

Три правила кандидата: известные личные устройства общаются между собой;
обычные TCP/UDP и ICMP к Mac сохраняются, кроме TCP 443; к этому HTTPS-порту
обращается только VPS. VPS не инициирует другие прикладные соединения внутри
tailnet, новые входящие TCP/UDP к VPS не разрешены. Публичные интерфейсы VPS
этими правилами не управляются. Существующая SSH-секция сохранена, однако
без network grant на TCP 22 входящий Tailscale SSH к VPS не разрешён.

В обеих address families указаны только текущие устройства. Новые устройства
и subnet routes требуют отдельного добавления. По текущему read-only status
approved primary routes и exit node options не обнаружены; статус не заменяет
полную инвентаризацию tailnet. При смене адресов/устройств preview устаревает.

Текущий кандидат: 16 native policy tests, отдельно 8 IPv4 и 8 IPv6, 130 assertions
(62 accept, 68 deny). Port/family lint и offline проверка этих assertions PASS.
`policy_checks.py` проверяет только границы портов и совместимость семейств
адресов; это НЕ control-plane validator Tailscale и НЕ сетевой smoke.
Перед каждой передачей JSON выполнить:

```sh
deploy/local-llm/.venv/bin/python deploy/local-llm/policy_checks.py deploy/local-llm/runtime/tailnet-policy-candidate.json
```

Восемь regression tests покрывают обе ошибки подготовки: нулевой начальный
TCP/UDP порт и межсемейные accept/deny пары. IPv4 source проверяется только с IPv4
destination, IPv6 только с IPv6. Grant ipsets при этом сохраняют обе семьи.
Реальную проверку обоих семейств выполнить после встроенной валидации Tailscale
и согласованного применения.

Первое сохранение control plane отклонило `tcp:0-442`. Исправлено на `tcp:1-442`:
для числовых TCP/UDP портов проверять `1 <= start <= end <= 65535`, а не только
логическую матрицу. Следующая попытка выявила `no matching IP protocol` для всех
130 межсемейных пар. Они ошибочно создавались генерацией полного произведения
адресов. Убраны только невозможные пары, все 16 tests и обе семьи сохранены;
grants/ipsets/ssh/tagOwners не менялись. Прежние 260 assertions/2000 matrix checks
не подтверждали корректность тестов Tailscale. После исправлений пользователь
подтвердил принятие policy; независимая выгрузка из control plane не выполнялась.

Критик обнаружил расширение источников при использовании 0.0.0.0/0 и ::/0:
исправлено на точный набор текущих адресов. Второй gate остаётся: Taildrop может
действовать независимо от ACL между устройствами одного владельца. Пользователь
согласовал tagged identity ТОЛЬКО для VPS. В JSON добавлен `tagOwners` только для
`tag:dpms-local-llm` с владельцем `autogroup:admin`. Пользователь применил policy
и назначил метку VPS; read-only status подтвердил её только у VPS. Mac и другие
устройства без меток. Serve выключен, существующий quarantine сохранён.
Глобально выключать Send Files нельзя:
это затронет личные устройства. Mac не тегировать.

Порядок применения администратором: сверить policy с актуальным JSON, сохранить
подготовленный JSON в Access controls с успешными встроенными tests. Затем
Machines -> только `dpms-local-llm` -> Edit tags -> `tag:dpms-local-llm` -> Save.
Одна декларация tagOwners НЕ назначает метку устройству. Точные сетевые разрешения
остаются привязаны к двум адресам VPS, а не ко всем будущим носителям метки.
После назначения проверить ровно один tagged VPS, прежние address bindings и
отсутствие изменений остальных устройств; только затем продолжать activation.
Из текущей сессии нет подключённого браузера управления Tailscale, поэтому эти
два действия переданы пользователю. CLI login/force-reauth не запускались.
Не заменять неизвестные/изменившиеся секции целиком и не отключать quarantine.
Откат к исходному allow-all допустим только после отключения model Serve и
восстановления quarantine, иначе снова открывается доступ к шлюзу другим узлам.

## Источники

- [HTTPS: включение и публичное имя в журнале сертификатов](https://tailscale.com/docs/how-to/set-up-https-certificates).
- [Tailscale Serve: приватный HTTPS и loopback proxy](https://tailscale.com/docs/reference/tailscale-cli/serve).
- [llama.cpp server: OpenAI-compatible API](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).
- [Uvicorn: concurrency и ограничения сервера](https://uvicorn.dev/server-behavior/).
- [Tailscale grants: объединение разрешений и протоколы](https://tailscale.com/docs/reference/syntax/grants).
- [IP sets: точные адреса и исключения](https://tailscale.com/docs/features/tailnet-policy-file/ip-sets).
- [Policy tests и исключение Taildrop](https://tailscale.com/docs/reference/syntax/policy-file).
- [Tagged identities: не назначать теги личному Mac](https://tailscale.com/docs/features/tags).
