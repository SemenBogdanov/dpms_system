# Стабильность DPMS: локальный кандидат, 24.09.2026

## Уточнение пользователя и порядок реализации

Первым этапом пользователь отдельно запросил небольшой файл при загрузке VPS.
Реализуется `deploy/stability/record_boot.py` и systemd oneshot, постоянный
журнал и read-only текстовый отчёт за неделю. Без перезагрузки production.
25.09.2026 boot recorder установлен на VPS отдельным host-only release.
Следующее прямое поручение: автоматически переносить boot-файлы в БД DPMS
и показывать записи в админке. Текущий контракт этого ограниченного этапа:
`docs/stability/BOOT-ADMIN.md`. Он использует PostgreSQL DPMS, не SQLite.

Ниже сохранён только предварительный проект дальнейшего мониторинга
доступности/ресурсов. Он не реализован и не является контрактом boot-import.
SQLite, probes и недельная uptime-лента ниже требуют отдельного пересмотра
с учётом решения пользователя хранить сведения в БД DPMS.

## Scope

Новый независимый серверный сборщик, read-only API для admin и экран недельной
стабильности. Работа в текущем worktree `dpms-graphs-interactions`, отдельные
файлы/точки интеграции; незакоммиченные изменения графов сохраняются.
Тестовый origin остаётся `http://localhost:55177`. Production не изменяется.

## Контракт

- Независимый Python stdlib-процесс на host/systemd, интервал 30 секунд.
- SQLite на отдельном постоянном диске/каталоге host, не в БД DPMS. Одна
  транзакция на sample; backend подключает каталог только для чтения.
- Таблица `samples`: `id INTEGER PRIMARY KEY`, `ts REAL UNIQUE NOT NULL`
  (Unix UTC), `interval_seconds INTEGER NOT NULL`, `status TEXT NOT NULL`
  (`ok/degraded/down/unknown`), `causes_json TEXT NOT NULL`,
  `probes_json TEXT NOT NULL`, `metrics_json TEXT NOT NULL`, `boot_id TEXT`.
  `PRAGMA user_version=1`, индекс ts, retention 14 суток.
- `causes_json`: массив `{code, component, confidence, evidence}`.
  component: `site/api/database/host/container/monitor`; confidence:
  `observed/suspected`; evidence: объект только числовых/boolean значений.
  Без URL, hostname, имён пользователей, содержимого запросов, stacktrace,
  секретов, исходных application logs и текстов ошибок.
- `probes_json`: объект `site/api/database`; каждый `{ok, latency_ms,
  http_status, error}`; error только `timeout/dns/tls/connect/http/invalid_response`
  или null. URL не сохраняется.
- `metrics_json`: числовые/null `cpu_percent/load_per_cpu/memory_percent/
  disk_percent/uptime_seconds`. boot_id — короткий hash, не исходный ID host.
- Причины: `site_unreachable/api_unreachable/db_unavailable/slow_response/
  cpu_pressure/memory_pressure/disk_pressure/container_down/container_oom/
  container_restart/host_restarted/host_metrics_unavailable`.
- Сбой внешнего probe при работающем API не доказывает, что упало приложение.
  OOM-флаг доказывает событие OOM; высокая память — только вероятный фактор.
- Таймауты, ограниченный размер ответа, запрет redirects и userinfo/query/fragment
  в probe URL; никаких управляющих endpoints и перезапусков из приложения.
- Проверка БД `/health/ready`: SELECT 1 с ограничением времени, только общий
  status/HTTP 503 без внутренних деталей. `/health` остаётся liveness.

## Read API и UI

- `GET /api/admin/stability`: только admin, rolling 7 days, без записи в БД DPMS.
- `GET /api/admin/stability/report`: текстовый attachment, такой же permission gate.
- Недельная лента, coverage отдельно от availability, unknown отдельно от down.
  Sample действует до следующего, но не дольше `2 * interval_seconds`.
  Более длинный перерыв и ещё не наблюдавшееся время серые/unknown, не зелёные.
- Инциденты объединяют соседние неуспешные замеры; gap разрывает доказанную
  длительность. Причины/признаки и следующие действия показываются с уверенностью.
- Нет файла/нет наблюдений/stale/corrupt различаются. Никакого выдуманного uptime.
- Экран admin: компактная сводка, 7-дневная лента слева направо, таблица
  инцидентов/детали, обновление по кнопке и скачивание отчёта.

## Проверки и риски

Unit: HTTP timeout/503/bad body, ресурсы, persistence/restart/prune,
gaps/window boundaries/availability, безопасный отчёт, permissions 401/403,
health timeout. Browser: empty/current/down/stale/report, desktop/iPhone,
light/dark/rose, 320px overflow. Синтетические сбои без остановки системы.

Внутренний монитор не видит собственное полное отключение. Точное измерение
полного падения VPS требует отдельного внешнего наблюдателя; пока gap честно
показывается неизвестным. История появляется только после запуска сборщика.
Не называть систему стабильной за период, который не наблюдался.

## Release boundary

Для production отдельно: установить systemd service/timer, задать закрытую
server-side конфигурацию probe URL, persistent volume/read-only mount,
проверить доступ admin и synthetic incident. Никаких новых outbound AI-сервисов.
Rollback: остановить timer и убрать UI/route; журнал сохранить для анализа.
