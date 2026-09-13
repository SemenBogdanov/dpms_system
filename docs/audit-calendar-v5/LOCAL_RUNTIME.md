# Локальный календарный кандидат

Этот стенд не предназначен для production. Он использует только синтетические данные,
отдельную БД `dpms_calendar_v5_candidate` и прежние порты 5177/8004. PostgreSQL остается
в существующем `dpms-local-db-1`; БД `dpms` и ее файлы не мигрируются и не удаляются.

Состояние на 13.09.2026: кандидатные frontend/backend запущены на loopback-портах,
схема088, синтетические данные. Три прежних worker остановлены. Передача допуска
через вход и `/api/auth/me` исправлена. Native browser runner: 40 PASS.
Кандидат доступен для пользовательской приемки (см. `VERIFICATION.md`).

## Подготовка

Из корня данного worktree:

```sh
docker compose -p dpms-local -f docker-compose.calendar-candidate.yml build
```

Миграции и guarded fixture выполняются отдельно только на кандидатной БД. Запуск
backend намеренно не вызывает `app.seed` и не импортирует данные прототипа.
Тестовые учетные записи приведены в сценарии приемки. Не переносить их в production.

## Переключение

Перед переключением убедиться, что общий стенд не занят другой сессией.
Остановить старые фоновые сервисы, не удаляя их или тома:

```sh
docker stop dpms-local-audit-worker-1 dpms-local-deadline-worker-1 dpms-local-email-worker-1
docker compose -p dpms-local -f docker-compose.calendar-candidate.yml up -d --no-build
```

Не использовать `--remove-orphans`, `down -v` или `volume prune`: существующая БД и
тома нужны предыдущей версии. Работает один frontend/backend, а не второй набор портов.
Адрес кандидата: <http://localhost:5177/audit-calendar>.

## Возврат Предыдущего Стенда

На момент подготовки предыдущий runtime относился к
`/Users/bogdanov/Code/dpms-id64a/docker-compose.yml`. Его исходники и конфигурация
не менялись. Предыдущие образы доступны под локальными метками
`dpms-calendar-rollback-backend` и `dpms-calendar-rollback-frontend`.

Возврат выполнить из предыдущего worktree по его протоколу запуска на тех же портах,
предварительно остановив кандидатный frontend/backend. Для возврата не нужно удалять
кандидатную БД и нельзя откатывать миграцию удалением календарной истории.

Production deploy и перенос настоящих календарных данных требуют отдельного разрешения.
