# Графы: расположение и ежедневная работа

Дата: 18.10.2026. Пункт исходного checklist: **3.2**.
Статус: проверенный release candidate, локальные gates завершены.

## Решение Пользователя

Пользователь поручил автовыравнивание, привязки, быстрые команды расположения,
глубокое исследование аналогов и подробный functional prompt. Для этого выпуска
явно разрешён production deploy после успешной разработки и проверок, без
дополнительного ожидания ночной ручной приёмки. Локальный адрес сохраняется:
`http://localhost:55177/graphs`.

## Текущий Scope

- Шесть выравниваний выбранных узлов по краям и центрам. Опора: границы
  выделения либо последний выбранный узел. Закреплённый primary может быть
  неподвижной опорой; остальные закреплённые узлы не перемещаются автоматически.
- Распределение равных зазоров по X/Y, ряд, колонка и сетка. Учитываются реальные
  размеры и масштаб карточек, интервал настраивается. Для распределения нужны
  три узла; отрицательный доступный зазор не применяется.
- Компактная панель выделения и инструменты inspector. На touch доступно
  добавление узлов к выделению без модификатора клавиатуры. Undo и Redo
  доступны отдельными touch-кнопками, в том числе на ширине320px.
- Привязки при drag к краям, центрам и равным промежуткам соседних объектов;
  отдельная привязка к сетке 24 world units. Допуск: 6 screen px с учётом zoom.
  Alt временно отключает привязки. Shift после начала drag ограничивает ось;
  Shift до начала drag по-прежнему создаёт связь.
- Направляющие живут только во время жеста. Выделение и группа перемещаются
  одним delta без изменения внутренних расстояний; semantic zoom учитывается.
- Асинхронная автоукладка всего графа или выделения: hierarchy, radial, compact.
  Иерархия поддерживает LR/RL/TB/BT. Общая иерархия использует локальный Dagre;
  явный outline сохраняет принятый порядок чтения. Группы являются жёсткими
  блоками, закреплённые узлы и неполные группы остаются неподвижными.
- Расчёт можно отменить; поздний ответ worker не меняет другой граф, вид или
  более новое изменение. Полная укладка включает fit камеры в одну undo-запись;
  укладка выделения сохраняет камеру и невыбранные позиции.
- Поиск внутри текущего графа: заголовок, ID, источник, описание, элементы
  списка, custom type; фильтр типа, переход к результату и раскрытие группы.
- Новый узел, child/sibling, стикер и атомы списка размещаются в свободной
  области, не перестраивая существующие узлы.
- Двухпальцевый touch pan/pinch отменяет начатый node preview; single-touch
  drag и прежний mouse/trackpad контракт сохраняются.

## Инварианты

Schema version 3 и backend DTO не меняются. Нет миграций или переноса данных.
ID, содержимое, размеры, типы, membership, связи, порты и ручные точки линий
не переписываются геометрическими командами. Изменяется только active view.

`pinned` остаётся исключением из автоматического размещения, не hard-lock:
ручной drag и nudge разрешены. Автоукладка не исправляет наложения внутри
жёсткой группы и не перемещает неподвижные препятствия ради красивого результата.
Неразрешимые координатные ограничения приводят к отказу, не к частичной записи.

Undo/redo атомарны. Quota failure откатывает изменение. Pending viewport save
и завершение публикации не записывают незавершённый drag/resize/edge preview.
После async PUT используется актуальная metadata, в том числе после rollback;
удалённая локальная копия не воскрешается ответом сервера.

## Архитектура

- `arrangement-geometry.mjs`: чистая геометрия align/distribute/grid/snap.
- `insertion-geometry.mjs`: ближайшая свободная позиция в допустимых границах.
- `layout-engine.mjs`, `outline-layout.mjs`: размерная раскладка и outline.
- `layout-worker.mjs`: изолированный расчёт без блокирования input main thread.
- `vendor/`: Dagre 3.1.1 и лицензии. Runtime CDN и новые package dependencies
  не используются; provenance и checksums записаны в vendor README.
- `index.html`: существующий interaction/storage/history flow. Новый framework
  или второй редактор не добавляются.

## Проверка

Все browser fixtures синтетические, изолированные; реальные API-записи запрещены.
Запускать на собранном кандидате55177, без source override:

```sh
node --test frontend/tests/graph-arrangement-geometry.test.mjs frontend/tests/graph-insertion-geometry.test.mjs frontend/tests/graph-layout-engine.test.mjs
npm --prefix frontend run build
cd frontend
npx playwright test --config playwright.graphs-productivity.config.ts
npx playwright test --config playwright.graphs-productivity-integrity.config.ts
npx playwright test --config playwright.graphs.config.ts
```

Матрица: Chromium/WebKit, desktop, iPhone portrait/landscape; визуальные размеры
320/390/1024/1440/1920 и light/dark/rose. Проверяются first-click после gap input,
scope/reference focus, pins/groups, stale workers, quota, undo/reload, touch,
поиск, вставка, существующие import/theme/connection/trackpad workflows.
Физические устройства и production-записи от имени пользователя не имитируются
как выполненная ручная приёмка.

Завершённые gates:163 unit PASS; legacy regression292 PASS и144 ожидаемых
SKIP; integrity15 PASS и5 WebKit SKIP (нативный CDP touch доступен в Chromium).
После последней правки мобильной панели дополнительно40 theme/knowledge PASS
и36 визуальных состояний PASS. Пропуски не входят в число успешных проверок.
Build, scoped ESLint, syntax/diff, navigation/mobile/calendar smoke PASS.
Полная новая productivity matrix:64/64 PASS,0skip,0fail,0flaky, без retries.
Исходники15 graph-workspace ресурсов побайтово совпадают с собранным55177.
Production exact SHA и postchecks фиксируются отдельно после promote.

UX и integrity review выявили реальные ошибки first-click/focus, scope feedback,
publish/quota и двухпальцевого жеста; исправления подтверждены targeted tests.
Layout review закрыл ложный отказ у координатной границы и fractional overlap.
Ошибки тестовых mocks исправлены без ослабления runtime-инвариантов:
calendar hook, существующая section-view telemetry, порядок Worker listeners.

## Не Входит

Persistent container auto-layout, resize snapping, snap hysteresis, числовой
X/Y inspector, fragment clipboard, hard-lock и obstacle-aware edge routing
остаются возможными следующими улучшениями. Они не объявлены выпущенными.

Multi-document ingestion, извлечение тезисов, устранение дублей функций и
автодополнение проектов документов относятся к отдельному будущему этапу.
Существующий JSON import не является этим документным pipeline.

Исследование шести редакторов и подробный target prompt хранятся в PersonalOS:
`08 Workspace/DPMS Graphs Productivity 2026-10-18/ANALOGS.md` и
`FUNCTIONAL-PROMPT.md`. Они различают подтверждённые факты, рекомендации,
CURRENT RELEASE и FUTURE; все R01-R20 не являются обещанием этого выпуска.
