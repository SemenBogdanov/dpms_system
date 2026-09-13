# Календарь аудита V5: проверка локального кандидата

Статус: локальный кандидат для пользовательской приемки, 13.09.2026.
Документ не является разрешением на релиз или перенос реальных данных.

## Изоляция

- Worktree: `/Users/bogdanov/Code/dpms-audit-calendar-v5`.
- Branch: `feature/audit-calendar-v5`, baseline `e46e8bbbc83be89c930df457431d737bcee40a73`.
- Старый dirty repo и ветка локального ИИ-коннектора не изменяются.
- Проверки PostgreSQL используют только отдельные локальные БД
  `dpms_calendar_v5_test`, `dpms_calendar_v5_upgrade`, `dpms_calendar_v5_http_test`.
  Демонстрационный стенд использует `dpms_calendar_v5_candidate`.
- Production, текущая БД `dpms`, реальные источники и внешние уведомления не затрагиваются.
- Канонический локальный адрес остается `http://localhost:5177`; кандидат пересобран
  и проверен через обычный вход DPMS.

## Выполнено

| Проверка | Результат |
|---|---|
| Эталон V5, `node --test domain.test.cjs planning.test.cjs availability.test.cjs` | 47 PASS |
| Чистая математика, `python -m unittest discover -s tests -p test_audit_calendar_math.py -v` | 35 PASS |
| Независимая сверка целей с посуточным расчетом, synthetic seed | 1500 PASS |
| Гранты, история и сериализация входа, `python -m unittest discover -s tests -p test_calendar_access_integration.py -v` | 7 PASS |
| Независимые проверки политики V5, `python -m unittest discover -s tests -p test_calendar_domain_regressions.py -v` | 8 PASS |
| `node frontend/scripts/check-navigation.mjs` | 22 раздела, 8 guards PASS |
| `node frontend/scripts/check-audit-calendar-access.mjs` | роли/гранты, миграция меню 1–8, повторная нормализация PASS |
| `node frontend/scripts/check-mobile-readiness.mjs` | 13 guards PASS |
| Миграция пустой изолированной БД до текущего baseline086 | PASS |
| `test_audit_calendar_domain.py` | 8 PASS |
| `test_audit_calendar_schema.py` | 17 PASS |
| `test_audit_calendar_runtime.py`, PostgreSQL, 13.09.2026 | 21 PASS |
| `test_calendar_http_integration.py`, FastAPI + PostgreSQL | 5 PASS |
| `test_audit_assignments.py`, включая DB opt-in | 8 PASS |
| `test_audit_case_controls.py` | 3 PASS |
| `npm run test:audit-review` | 30 PASS |
| `npm run test:mobile` | 26 PASS |
| `npm run build`, Docker frontend/backend build | PASS |
| `npm run lint`, включая native runner | PASS, 3 прежних предупреждения |
| `npx playwright test --config playwright.audit-calendar.config.ts` | 43 PASS, 1 skip |
| WebKit, focus/source regression, `--repeat-each 10` | 20 PASS |
| Финальная migration087/088, fresh и086->088 | PASS |
| Canonical source trigger и статья в кандидатной БД | присутствуют |
| Русификация календарных backend ошибок и повтор PG/HTTP | 21 + 5 PASS |
| Все calendar unit suites без DB opt-in | 75 PASS, 26 DB tests запускаются отдельно |
| `node scripts/verify-calendar-native.mjs`, обычный UI-вход и реальная кандидатная БД | 40 PASS |

## Предрелизная Проверка 13.09.2026

Пользователь отдельно разрешил production deploy. Это не приемка реальных данных
и не разрешение на их импорт. Повторены build/lint/navigation, 75 unit, 22 PostgreSQL
и 5 HTTP проверок. Добавленный PostgreSQL сценарий проверяет ожидание блокировки
`users`: migration087 завершается с `55P03` через пять секунд, откатывает частичные
изменения и успешно повторяется после освобождения таблицы. `SET LOCAL lock_timeout`
действует только в транзакции миграции, настройки рабочих соединений не меняются.
Этот сценарий закрывает замечание независимого release-критика об ожидании DDL
при работающем backend; ранее было 21 PostgreSQL проверка, теперь 22.

Calendar evidence: `artifacts/audit-calendar/isolated`, 74 screenshots. Пять размеров,
три темы, Chromium/WebKit, в том числе центральная форма. Для стабильных цветов
скриншоты снимаются с завершением theme transitions. Это изолированный React harness,
а не подтверждение сквозного входа DPMS.

Проверки соседних экранов используют mock API и предупреждают о недоступном
WebSocket proxy в отдельном test-server. Это не проверка production-соединения.

## Независимое Review

UX-критик обнаружил риски потери черновика во время сохранения, смешения периода
и старых данных, stale-версии формы, некорректных URL-дат, остатка модалки после
отзыва допуска, фокуса summary и неверной дневной нагрузки. Frontend worker
исправил их с отдельными browser regression tests. Дополнительно исправлены импортный
stale-rebase и выбор сегодняшнего дня по серверу при неверных часах устройства.

Backend-критик обнаружил повторное восстановление одного source-факта через другой
batch, обход исторических ограничений через `historical-entry` и пропуск конфликта
с известным докладчиком факта неизвестного состава. Все три исправлены; добавленные
PostgreSQL regression tests входят в 21 PASS. Стабильная идентичность источника
защищена также триггером БД. Финальная схема повторно установлена на демонстрационную
синтетическую БД; trigger подтвержден SQL-проверкой.

## Сквозная Интеграция

Найден и исправлен пропуск `audit_calendar_enabled` в ручном `_user_to_read`:
вход и `/api/auth/me` теперь передают фактический допуск. Добавлена регрессия
false -> true -> false для всех системных ролей. Frontend `AuthContext.tsx`
принимает ответ целиком и не потребовал изменений.

Получено явное разрешение пользователя на исключение из правила `*auth*`: только исходники
`backend/app/api/routes/auth.py` и `frontend/src/contexts/AuthContext.tsx`.
Credential-файлы, токены, env и browser/session stores не читаются.

Native runner проверяет пять размеров и три темы, сохранение одной 90-минутной
встречи с повторным чтением, видимость ее сотруднику, запись/очистку собственной
суточной доступности, запрет управления сотруднику, отказ admin без участия и
постороннему. Тестовые встречи после проверки сняты с плана с основанием;
их история остается. Идентификация и календарные API не подменяются.

Evidence: `artifacts/audit-calendar/native/results.json` и 36 PNG рядом.
В тесте соблюдается штатный лимит 5 входов в минуту; защита не ослаблялась.
Перед переходом со страницы входа runner дожидается загрузки «Сообщений», чтобы
программный переход не обрывал lazy chunk и не запускал штатное восстановление страницы.

После просмотра настоящей оболочки исправлены подписи области цели и название
одиночного пункта календаря в стандартной группе «Аудит». Пользовательские названия
меню сохраняются. В `useProtectedModal` добавлена защита от запоздалой установки
фокуса, если пользователь уже перешел в поле; соседние формы проверены повторно
(audit-review 30 PASS, mobile 26 PASS). Высота select задана явно для Safari:
36 px desktop, 44 px mobile; проверяется в матрице модалок.

## Оставшиеся Gates

- [x] Серверный календарь и API-контракт, включая передачу гранта через реальный вход.
- [x] Fresh и upgrade новой схемы, ограничения неизменяемости, отказ опасного downgrade.
- [x] Прямые API-запреты, scope, отзыв доступа, повтор команд, stale/CAS.
- [x] Настоящие конкурентные PostgreSQL-транзакции брони.
- [x] Источники: preview/mapping/apply/replay; standalone fact; историческое исключение.
- [x] Полный frontend build и lint.
- [x] Chromium/WebKit: три темы, пять размеров, модалки и ошибки в изолированном harness.
- [x] Независимые UX и adversarial reviews, исправления, повторная проверка.
- [x] Сквозной вход, реальные роли и layout общего DPMS в native runner.
- [x] Локальная Docker-версия, справка и пользовательский сценарий.

## Ограничения Приемки

- Это один явно ограниченный контур, не корпоративная tenant-изоляция.
- Данные синтетические. Пользовательский Excel/JSON и production не проверялись на запись.
- Нет внешней рассылки, календарных приглашений и фонового автопереноса встреч.
- Изменения другого участника видны после обновления календаря; realtime-доставка не заявлена.
- Мобильный WebKit проверен через автоматизацию, но не на физическом iPhone с экранной клавиатурой.
- Факт фиксируется после окончания встречи; прошлое не подменяется для ускорения ручного теста.
- Нагрузочный тест production и окончательная пользовательская приемка остаются отдельными gates.

Не считать старые скриншоты конструктора доказательством нативной интеграции.
Финальные evidence должны содержать роль, тему, viewport, route, fixture и команду.
