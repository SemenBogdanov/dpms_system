# Календарь: Планирование И Загрузка

Дата: 14.09.2026. Worktree `dpms-audit-calendar-v5`, branch
`feature/calendar-availability-locks`, baseline `d15444aaffce`.
Локальный кандидат; commit/release/deploy не выполнялись. Production, реальные
данные и параллельный Llama/Tailscale slice не затронуты.

## Шесть Изменений

1. Независимый допуск Calendar не требует Audit/Q. Дополнительной зависимости в
   backend не найдено; устранены гонки позднего `/me` и `/state`, способные вернуть
   устаревшие права/данные. Проверены executor, development-only и admin.
2. Карандаш нормы в строке группы на экранах «Справочники» и «Управление».
   Норма на 10 будней, дата действия и основание; прошлые редакции неизменяемы.
3. Availability CAS сравнивает только затронутые получасовые ячейки. Независимые
   записи не конфликтуют из-за общей версии. Реальный конфликт атомарен, черновик
   сохраняется и сравнивается перед явным подтверждением. Свежие права, отпуск,
   замок и архив проверяются под транзакционной блокировкой. Повтор после потери
   ответа использует прежний request_id; старые receipt digest совместимы.
4. Отчет сотрудников: заполненные дни, плановые встречи, свободные слоты, %power.
   Формула: плановые минуты / свободные минуты × 100. Одинаковое рабочее окно
   Пн–Пт 10:00–18:00 Moscow; нет знаменателя → null, не 0. Внеоконные минуты,
   частичные дни, отсутствия и сравнение с нормой вынесены отдельно.
5. Замечания встречи содержат код, имя и user_id конкретного участника.
6. Meeting-options проверяет полную длительность, состав, докладчика, занятость,
   отсутствие, планы и факты. Неизвестная доступность сохраняет предупреждение V5.
   Недоступная выбранная группа не подменяется, черновик не равен назначению.

## Проверки

| Проверка | Результат |
| --- | --- |
| Pure calendar unit tests | 90 PASS |
| PostgreSQL runtime, включая реальную конкуренцию | 26 PASS |
| HTTP routers + PostgreSQL, включая workload | 58 PASS |
| Изолированный UI, Chromium/WebKit | 191 PASS, 1 прежний SKIP |
| Независимые доступы, component regressions | 192 комбинации + 21 тест PASS |
| Native Docker UI/API, helper/employee/admin | 26 PASS |
| Frontend production build + Docker build | PASS |
| Lint | 0 errors, 3 прежних warnings |
| Навигация / доступ / mobile readiness | 22 / 8 / 13 проверок PASS |
| Workspace release invariants, health, diff whitespace | PASS |

Команды: `npm run build`, `npm run lint`, `npx playwright test --config
playwright.audit-calendar.config.ts`, `python -m unittest discover -s tests -p
'*calendar*.py' -q`; HTTP и runtime выполняются отдельно с opt-in только на
`dpms_calendar_v5_http_test` и `dpms_calendar_v5_test`.

Native runner: `node scripts/verify-calendar-controls-native.mjs --candidate-ready
--archive`. Используются только `calendar.*@example.com`. Новые данные не удаляются:
заявки закрыты, контур возвращен в активное состояние, журнал сохранен. Никаких
mock API в native-прогоне; внешние запросы заблокированы.

Доказательства: `artifacts/audit-calendar/native-controls/2026-09-14T10-06-39-236Z/`:
`results.json`, 138 screenshots. Report:1920×1080,1440×900,1024×768,390×844,320×700;
light/dark/rose, Chromium/WebKit. Остальные native-сценарии desktop/mobile.
Изолированный UI: `artifacts/audit-calendar/isolated/`. Визуально проверены реальные
отчет и формы. Мобильная таблица превращается в подписанные строки сотрудника.
После финального native-прогона контур активен; все10 synthetic-заявок закрыты.

## Critic Review

Независимый критик: GO после исправлений позднего `/state` при revoke, legacy
receipt digest, frozen-plan options и модели no-op version в тестах. Дополнены
реальные HTTP-проверки формулы, нулевого знаменателя, границ, фильтра и доступа.
Финальные build/UI/native-прогоны выполнены интегратором после review.

## Локальный Runtime И Ограничения

`http://localhost:5177/audit-calendar`, backend8004. Три прежних работающих
контейнера frontend/backend/db; фоновые worker остаются остановлены. Никаких
дополнительных постоянных портов. Схема `092_calendar_planning_guide`, статья БЗ
`kalendar-audita-plan-fakt` дополнена и проверена в кандидатной БД.

Перед обновлением сохранен synthetic dump:
`artifacts/audit-calendar/calendar-before-planning-followup.dump`, SHA-256
`2994c142d11886d28bdf9349a6fcf472830d33896b2acb58171acffefffff1e6`.
Не применять его к production. Новые теги образов предыдущего091 не созданы
(containerd не разрешил tagging по config digest); возврат стенда описан отдельно
в `LOCAL_RUNTIME.md`, backup исходного V5 остается отдельным checkpoint.

Ограничения: это synthetic QA, не приемка реальных данных; фактическая
производительность сотрудника не выводится из %power. Заполнение независимых ячеек
масштабируется логически, но это не нагрузочный тест многих одновременных клиентов.
Персональные свободные интервалы вне10–18 не входят в %power текущего V5.

Следующее действие: `ACCEPTANCE.md`, раздел «Дополнение: Планирование И Загрузка».
После приемки требуется отдельная команда на release/deploy.

## Уточнение: Четыре Кнопки В Ряд

14.09.2026: замок перенесен в общий ряд со «Свободен», «Занят», «Очистить».
На закрытом дне четвертая кнопка открывает заявку; состояние остается ниже.
Права, серверная логика и история не изменены.

78 focused availability/concurrency browser tests PASS. Геометрия проверена
на320/390/1024/1240/1440/1920px в Chromium/WebKit и трех темах. Build/lint PASS,
3 прежних warnings. Frontend пересобран на5177, backend/БД не менялись.
Native read-only Chromium:2 PASS, формы не сохранялись. Evidence:
`artifacts/audit-calendar/native-controls/2026-09-14T11-16-12-001Z/`.
Первый native-запуск остановился на guard точного числа участников, поскольку
пользователь дополнил локальный состав. Только read-only diagnostic адаптирован
к дополнительным участникам; ограничения mutating runner сохранены.

Подсветка окон графика пока является предложением, не частью кандидата.
