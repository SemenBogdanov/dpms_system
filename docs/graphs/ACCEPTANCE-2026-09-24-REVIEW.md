# Critic review: замечания к графам от 24.09.2026

Финальный verdict на **24.09.2026, 12:45:27 +0300**: **APPROVED в рамках проверенного локального слайса. R1-R5 закрыты; Critical: 0, High: 0, Medium: 0.** Итоговый desktop-прогон: **99 passed (32.0s)**, включая legacy-circle R1. Целевой mobile/WebKit-прогон: **22 passed (7.2s)**. Оба результата проверены по логам. Исправленная арифметика R1 прошла 26 700 собственных проб critic; source и runtime совпадают по hash `9b0ed5af...`. Прежнее fixture-падение устранено и не является открытым gate. Пункт 3.2 остаётся вне слайса.

Первичный срез: 24.09.2026, 12:03:48 +0300. Повторный срез: **24.09.2026, 12:26:41 +0300**. Review выполнен основной моделью в read-only роли, без внешних моделей. Единственный записанный в этой роли файл: этот отчёт. Исходники, тесты, миграции и документы пункта 2.3 не изменялись.

Проверены текущие изменения и новые модули для пунктов 2.4, 2.6, 2.7, 2.8, 3.1; после появления диалога также проверена интеграция импорта 2.12. Прилегающая геометрия наконечника относится к 2.5. Пункт 3.2 исключён: изменения алгоритмов выравнивания не запрашиваются. Клавиатура мастера и уже переданный пункт 2.3 не пересматриваются.

## Закрытие арифметики R1 на новом runtime

### Verdict и доказательство

**R1 residual (2.4/2.11) закрыт по source и изолированным исполняемым проверкам.** В [handlePointerMove:5218](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/public/graph-workspace/index.html:5218) границы вычисляются до записи width/height. [Guard minimum > maximum:5224](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/public/graph-workspace/index.html:5224) возвращает управление, не меняя модель, когда допустимого диаметра при фиксированной противоположной стороне нет. Это устраняет исходную причину x=100100, а не маскирует её последующим clamp координаты.

Собственные read-only пробы critic, выполняющие извлечённые текущие функции:

1. **2400 обычных resize**: rounded/circle размером 200, x/y из -100000/-99950/0/99950/100000, восемь направлений, camera scale 0.24/1/2.6, delta +/-1000. Проверены допустимые размеры и координаты, сохранение противоположных сторон. Все прошли; некоторые вычислительные направления круга не представлены отдельным handle в UI.
2. **24 300 legacy-circle resize**: width 901/1000/1200, height 64/200/900; шесть X-позиций и пять Y-позиций у обеих границ и в центре; доступные направления e/s/nw/ne/sw/se, три масштаба, delta -1000/-1/0/1/1000. В **3285** случаях пустого диапазона вся модель строго равна исходной, вызов планирования отрисовки отсутствует. В остальных случаях результат остаётся допустимым, diameter <=900, противоположные стороны сохраняются по start-геометрии.
3. Исходный reproducer `circle, width=1000, height=900, x=100000, y=0`, NW (-1,0): **модель полностью неизменна**, x остаётся 100000, width=1000 и height=900 сохраняются. Это предусмотренный отказ от невозможного resize, не принудительная нормализация legacy-узла.
4. Пять последовательных pointermove и настоящий handlePointerUp/commitInteractiveMutation в синтетическом окружении: snapshot и прежние undo/redo неизменны, save/audit/render вызваны **0 раз**. Вспомогательные captureActiveViewState/flushPendingEdit подставлены как no-op: это изолированная проверка отказанного resize, не полный пользовательский workflow.

На 12:41:07 read-only HTTP GET публичного index на **localhost:55177** вернул 200 и SHA-256 **`9b0ed5af190d74bb004f2a14a773de67995307475df146b31393bc3d3c99a921`**, совпадающий с проверенным файлом repo. Старый hash 49504cc... более не является текущим runtime. Build critic не запускал; подтверждено фактическое обновление отдаваемого файла.

### Новая регрессия E2E: закрыта

В [новом тесте:503](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/tests/graphs-acceptance-20260924.spec.ts:503) проверяются NW no-op во время жеста, после pointerup и reload, затем допустимое сжатие восточным handle до 900 с reload. Камера fixture теперь `x=-59920, y=40, scale=0.6`: угол находится вне tool-rail, обычный `nw.hover()` проверяет доступность handle без force. По сообщению main targeted legacy-circle прошёл **1/1**; затем critic независимо прочитал [итоговый общий лог](/tmp/dpms-graphs-acceptance-final-desktop.log:125): **99 passed (32.0s)**, включая [этот R1-тест](/tmp/dpms-graphs-acceptance-final-desktop.log:85).

Предыдущий [лог v2](/tmp/dpms-graphs-final-v2-desktop.log:122) с **98 passed, 1 failed** сохранён как история: timeout был на `nw.hover()` до pointerdown из-за перекрытия панелью, что подтверждал [скриншот](/tmp/dpms-graphs-final-v2-desktop/graphs-acceptance-20260924-4a2d6-size-but-allows-east-shrink-chromium-desktop/test-failed-1.png). Он не воспроизводил дефект координат и более не блокирует закрытие. Изменения layout 3.2 или панели инструментов не понадобились; critic source и тесты не редактировал.

Новый [mobile/WebKit-лог](/tmp/dpms-graphs-final-v2-mobile.log:52) подтверждает **22 passed (7.2s)**: theme, knowledge deep link и отдельный touch-import сценарий с пятью режимами/mapping, отменой и подтверждением tree preview. Это отдельный целевой прогон, а не переименование прежних 18 pass / 36 skip. Main также сообщил **lint: 0 errors, 3 прежних warnings**; critic lint не запускал и его лог не проверял. На 12:45:27 повторный HTTP GET подтвердил новый runtime hash без изменений.

**Финальная позиция:** исправление R1 принято по арифметике и E2E; текущий локальный слайс одобрен в проверенном объёме, активных подтверждённых дефектов R1-R5 нет. Работа critic завершена; новые задачи и прогоны не запускаются.

Остаточные ограничения, не активные findings:

- WebKit-проверки не означают полное touch-покрытие resize, портов/магнита и всех storage workflows; физические устройства не проверялись critic.
- При смене темы подтверждены identity iframe, фокус и незавершённый graphTitle; отдельная комбинация открытого диалога, canvas-выделения и undo/redo с theme switch полностью не заявляется.
- Отказанный невозможный resize legacy-круга является намеренным no-op; диаметр >900 не исправляется молча. Допустимое сжатие с востока проверено E2E.
- Backend/KB/097 и lint имеют отдельно помеченные свидетельства main; critic не выполнял DB-действия, миграции или production-проверки. Этот verdict не является разрешением на deploy.
- Пункт 3.2 остаётся в бэклоге, дополнительных layout-правок не требуется для закрытия этого review.

### Отпечатки нового среза

| Артефакт | SHA-256 |
| --- | --- |
| index.html repo и HTTP 55177 | 9b0ed5af190d74bb004f2a14a773de67995307475df146b31393bc3d3c99a921 |
| frontend/tests/graphs-acceptance-20260924.spec.ts, 12:45:27 | 739668f0a2a20a183739519f0fac04a52aa1dbb007034e806e37ddfe9238a140 |
| /tmp/dpms-graphs-acceptance-final-desktop.log, 99 pass | e522ff6423d2b0e282a8e4292792b284ab46b5d79a64d47d776c813754ee4d43 |
| /tmp/dpms-graphs-final-v2-mobile.log, 22 pass | f4f4446c9b42eac2a169ef01db921a4a6e74fd07c315f1093d663bb0bc662345 |
| /tmp/dpms-graphs-final-v2-desktop.log, история fixture-timeout | aff6e508531b411ad41646021921f6c6459901608107adb664712187f1734c15 |

## История итоговой проверки на 12:34:22

Ниже сохранено предыдущее решение по hash 49504cc...; открытый в нём residual R1 уже устранён и не является текущим активным finding. Актуальный verdict приведён выше.

### Текущие severity и статусы

| Замечание / пункт | Финальный статус | Основание |
| --- | --- | --- |
| R1, 2.4/2.11 | **Medium, открыт только legacy/imported-circle residual** | Исходный NW-сценарий у -100000 прошёл E2E; случай width=1000, height=900, x=+100000 в нём не покрыт и повторно воспроизведён critic. |
| R2, 2.7/2.4 | Закрыт | AutoSize 224x108 и совпадение DOM-порта с SVG-путём прошли E2E; раскрытие семи пунктов и reload также прошли. Дополняет предыдущие 36 DOM/360 port-проб. |
| R3, 2.4/2.5 | Закрыт | В логе прошли северная и южная точки круга для curve/orthogonal/straight с editable points и без них; cardinal/compact арифметика проверена предыдущими пробами critic. |
| R4, 2.6 | Закрыт | E2E подтвердил отсутствие circle-snap в углу (5,5), приоритет фактического B над соседним портом A и создание ожидаемого ребра. Live preview и отпускание вне цели в пределах магнита также прошли. |
| R5, 3.1 | Закрыт в проверенном контракте | Smoke и live DOM/ThemeProvider проверки прошли: light/dark/rose, неизменность iframe/src/document, незавершённый title, фокус и отсутствие graph writes. |
| 2.8 | Проверенный desktop-сценарий пройден | Обычное колесо в обе стороны, инверсия и сохранение после reload подтверждены E2E. Физическое устройство/все браузерные жесты не покрыты этим свидетельством. |
| 2.12, сопряжение 2.11 | Ранее отмеченный quota/undo-риск снят для проверенного сценария | Прошли пять режимов импорта, preview/confirmation, отмена, ошибки и явная граница Publish. При quota failure проверены прежний граф, выделение, камера и реально работающий undo. Сохранение explicit ports после reload покрыто отдельным сценарием 2.4, не выдаётся за проверку импорта ненулевых ports. |

**Почему R1 не закрыт вместе с остальными.** Текущий [R1 E2E:469](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/tests/graphs-acceptance-20260924.spec.ts:469) проверяет обычный узел в (-100000,-100000). Успешный тест не проверяет пустой диапазон ограничений круга шириной >900 у положительной границы. Повторный вызов handlePointerMove из точного hash `49504cc...` для NW (-1,0) снова дал `width=height=900, x=100100`. В [resize:5233](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/public/graph-workspace/index.html:5233) minimum=1000 больше maximum=900; исходный узел допускается schema и normalizeGraph. Подробный воспроизводимый пример и критерий закрытия сохранены ниже. Это один ограниченный Medium, не оставшийся High.

### Проверенные артефакты

- Прочитан [итоговый desktop-лог](/tmp/dpms-graphs-final-desktop.log:117): **95 passed (30.0s)**, `chromium-desktop`, четыре workers. Critic не перезапускал этот suite; проверен результат запуска main и соответствующие тестовые assertions.
- Прочитан [итоговый mobile-лог](/tmp/dpms-graphs-final-mobile.log:76): **18 passed (7.3s), 36 skipped**, проекты `webkit-iphone-13` и `webkit-iphone-13-landscape`. Запущены только `graphs-integration.spec.ts` и `graphs-theme-20260924.spec.ts`; acceptance/import specs в эту команду не входят. Exit 0 сообщён main; завершение без failed подтверждено логом.
- Команда, зафиксированная в заголовке лога: `playwright test --config playwright.graphs.config.ts --project chromium-desktop --output=/tmp/dpms-graphs-final-desktop --reporter=line`. Config не читался. Main указал запуск на **http://localhost:55177/graphs**.
- Read-only HTTP GET публичного `http://localhost:55177/graph-workspace/index.html` вернул **200** и SHA-256 `49504cc276b38e82412c0544ec371dc334985b66bf46cf56ba365d0dae8a3ee8`, совпадающий с файлом repo. Таким образом, текущий локальный сервер действительно отдаёт проверенный исходник; это не утверждение о неизменности сервера во всё время прошедшего запуска.
- Визуально просмотрены именно артефакты финального output, а не старые `frontend/test-results`: [20 портов](/tmp/dpms-graphs-final-desktop/graphs-acceptance-20260924-dad92-preserve-the-opposite-edges-chromium-desktop/2.4-twenty-ports.png), [live snapped preview](/tmp/dpms-graphs-final-desktop/graphs-acceptance-20260924-3ab41--release-outside-the-target-chromium-desktop/2.6-live-snapped-preview.png), [семь пунктов после reload](/tmp/dpms-graphs-final-desktop/graphs-acceptance-20260924-1f985-out-clipping-or-an-ellipsis-chromium-desktop/2.7-seven-items-after-reload.png). Изображения согласуются с указанными состояниями, но не заменяют assertions геометрии.
- Проверены assertions [quota/undo:560](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/tests/graphs-import-20260924.spec.ts:560): тест не ограничивается enabled-кнопкой, а выполняет undo и сравнивает nodes/edges/views/groups исходного графа; cloud PUT отсутствует. Соответствующий тест прошёл в строке 115 лога. Прежнее предположение о потере истории при этом отказе больше не является активным замечанием.

### Свидетельства main и оставшиеся границы

По итоговому сообщению main: **knowledge 14/14** на host через `/tmp/dpms-graphs-backend-venv/bin/python`; **backend API/schema 13/13** в container с изолированным aiosqlite; локальная БД на **097 head**, статья `graphs-hierarchy-guide` опубликована, body **16827 символов**. Это отдельные свидетельства main: critic БД/container не открывал и SQL/migration не запускал. Точная host-команда сохранена ниже; отсутствие `/docs` в backend-only context не исправлялось.

Отдельный mobile-прогон завершён. Его 18 pass покрывают smoke и theme-контракт на WebKit portrait/landscape; 36 skip соответствуют явным desktop-only guards в integration-spec, например [dense canvas:923](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/tests/graphs-integration.spec.ts:923) и [pointer magnetism:1138](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/tests/graphs-integration.spec.ts:1138). Поэтому полный touch-сценарий resize, порты/магнит, импорт и storage не объявляются проверенными на mobile. Физический iPhone/трекпад не использовался critic. Сохранность открытого диалога, canvas-выделения и операций undo/redo именно при смене темы отдельно в проверенном theme-spec не утверждается; подтверждены iframe identity и незавершённый graphTitle. Это границы покрытия, не новые воспроизведённые дефекты.

По последнему сообщению main остаётся правка lint для fixture callback `use` у Singer. Critic её не выполнял и результат lint не подтверждал. Это отдельный quality-gate тестового кода, не новый дефект runtime и не основание обесценивать уже завершённые прогоны. Hash runtime index повторно проверен на 12:34:22 и не изменился.

Финальная позиция critic: проверенные desktop-сценарии и ограниченный mobile smoke/theme приняты как пройденные; для безусловного approval остаётся **исправить либо явно принять residual R1**. Нельзя приравнивать это к полному touch-покрытию или green lint. Новых High/Critical по переданному scope не найдено. Пункт 3.2 остаётся в бэклоге; дополнительные layout-изменения не запрашиваются. Critic завершает работу на текущем runtime, не ожидает и не запускает новые прогоны.

### Отпечатки итоговых свидетельств

| Артефакт | SHA-256 |
| --- | --- |
| index.html repo и HTTP 55177 | 49504cc276b38e82412c0544ec371dc334985b66bf46cf56ba365d0dae8a3ee8 |
| /tmp/dpms-graphs-final-desktop.log | 19f9f15e2267ed81ec253f5bcf6e14f16ca32b5ed38d986ab2b1feef094e00b3 |
| /tmp/dpms-graphs-final-mobile.log | ce9b79ca43c31ec419f4a396c364d4d4f4340eafeeb52daa5636a4f53e921a64 |
| frontend/tests/graphs-acceptance-20260924.spec.ts | 7afcbba92c1b0ce9b1d943b04755f9293289abd8b529f89924b617ca2454ec2c |
| frontend/tests/graphs-import-20260924.spec.ts, срез 12:29:21 | 7d72fabbe7631a25e05de67ddf6fcd597826b9eb76610bc6c099cffce7491d1e |
| frontend/tests/graphs-import-20260924.spec.ts, срез 12:34:22, fixture-правки main продолжаются | bcc5080d79ab75aa2d2ed18ba813aad7cefb2ee0cf3869a51bc32ab863b8cf2b |
| frontend/tests/graphs-theme-20260924.spec.ts | ad0ce9564c188ce7a5272b9c20a81fd57e6d33f4b703e8d9c33eb674e18bde7f |

Исходники не изменены. Единственная запись critic: этот отчёт. Внешние модели, production, secrets и конфигурация не исследовались.

## Повторная проверка R1-R5: история на 12:26:41

Раздел ниже сохраняет состояние до получения итогового лога 95/95. Формулировки «результаты ожидаются» относятся к этому прошлому срезу; актуальные статусы приведены выше.

Повторный проход ограничен исправленными участками resize, размеров DOM, attachment, connectionTarget/pointerup и тестами темы. Импорт 2.12 и wheel 2.8 заново не ревьюились; их первичные ограничения ниже остаются историей проверенного объёма. Пункт 3.2 по-прежнему вне scope.

### Текущие статусы

| ID | Статус после исправлений main | Свидетельство и граница вывода |
| --- | --- | --- |
| R1 | Частично закрыт; остаток **Medium** | 2400 синтетических resize обычных фигур прошли; legacy/imported circle с width > 900 всё ещё может выйти за +100000. Подробности ниже. |
| R2 | Исходный дефект закрыт в изолированном DOM-тесте | 36 комбинаций списка: DOM width/height совпали с nodeSize; 360 проверок видимых портов, максимальная ошибка 0,025 px. |
| R3 | Исходный дефект закрыт в тесте функции | Восемь cardinal-проверок attachment для circle и semantic-compact сохраняют нулевые компоненты нормали. |
| R4 | Исходные случаи закрыты в тесте функций | Угол circle не захватывается; фактический hit B побеждает соседний порт A; DOM-стек, скрытая цель и пересчёт на pointerup проверены с синтетическим окружением. Реальный hit-testing приложения этим не заменён. |
| R5 | Несоответствие старого локатора закрыто | Smoke теперь меняет тему оболочки, проверяет iframe и отсутствие themeButton. Новый theme-spec проверяет identity iframe и незавершённый ввод; его итоговый результат ещё ожидается. |

### R1 residual. Medium: пустой допустимый интервал resize импортированного круга

Пункты: **2.4/2.11**. Источники: [ограничения resize:5233](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/public/graph-workspace/index.html:5233), [пересчёт координат:5240](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/public/graph-workspace/index.html:5240), [normalizeGraph:2878](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/public/graph-workspace/index.html:2878), [GraphNode:51](/Users/bogdanov/Code/dpms-graphs-interactions/backend/app/schemas/graph.py:51).

Допустимый schema узел: `shape=circle, autoSize=false, width=1000, height=900, x=100000, y=0`. Контракт ограничивает width и height независимо; normalizeGraph не приводит такой круг к диаметру <=900. Внешний вид использует width как диаметр.

Вызов текущего handlePointerMove для доступного **NW-handle**, scale=1, delta=(-1,0) даёт `width=900, height=900, x=100100, y=0`. При фиксированной правой границе 101000 получаются `minimum=1000` и `maximum=900`; clamp не распознаёт пустой интервал и возвращает 900. Затем x становится недопустимым. Это не только искусственная ветка западного handle, отсутствующего у круга: результат отдельно подтверждён для NW.

Следствие: resize ранее допустимого импортированного/сохранённого узла может создать payload, отвергаемый backend, а reload нормализует координату с изменением положения. Исходный массовый дефект у обычных фигур исправлен, поэтому остаточная severity снижена с High до Medium. Это не замечание к автоукладке 3.2.

Критерий закрытия: явно обработать несовместимые ограничения, не допуская координаты вне контракта; проверить импортированный круг width=1000/1200 у +100000, NW/SW, commit, undo и reload. Возможны отказ от такого resize или отдельное согласование legacy-геометрии, но не сохранение недопустимого результата.

### Собственные проверки повторного прохода

1. Node vm, функции извлечены из текущего index.html: 2400 resize-комбинаций обычных rounded/circle размером 200; координаты -100000/-99950/0/99950/100000, восемь направлений, scale 0.24/1/2.6, смещения +/-1000 world units. Границы координат, размеры и фиксированные противоположные стороны соблюдены. Восемь направлений проверяют вычислительные ветки; не все handles доступны у круга в UI. Отдельно воспроизведён residual R1 через NW. Допустимость исходного legacy-узла проверена изолированным импортом GraphNode без загрузки приложения/settings.
2. Headless Chromium с текущими CSS, renderNodes и updateListPreview: 1/20/200 длинных строк, autoSize true/false, full/semantic-compact, node.scale 0.5/1/2. Все 36 размеров совпали с моделью. На выбранной карточке в полном режиме проверены все 20 портов в каждой комбинации: 360 проверок, ошибка <=0,025 px. При ручных высотах 138/360/900 видимы соответственно 0/4/16 из 20 длинных пунктов. Числа зависят от fixture и шрифта; проверено увеличение вместимости и отсутствие прежнего роста autoSize DOM. Источники: [renderNodes:4606](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/public/graph-workspace/index.html:4606), [порты:4617](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/public/graph-workspace/index.html:4617), [updateListPreview:4649](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/public/graph-workspace/index.html:4649). Сеть заблокирована; рабочая страница и пользовательское хранилище не открывались. CSS scale узла проверен, преобразование камеры в этой DOM-пробе не применялось.
3. [attachment:3473](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/public/graph-workspace/index.html:3473): верх/низ/лево/право для circle и compact. Исходная подмена nx=0 на 1 отсутствует.
4. [connectionTarget:5296](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/public/graph-workspace/index.html:5296): circle corner (5,5), соседние A/B при указателе (201,100), смена порядка элементов перекрытия и исключение скрытого узла. [pointerup:5373](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/public/graph-workspace/index.html:5373) создаёт связь с B при устаревшем snap на A. elementsFromPoint здесь подставлен тестом: это доказательство приоритетов алгоритма, не браузерной доставки событий.
5. Статически проверен обновлённый [smoke:308](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/tests/graphs-integration.spec.ts:308). Новый [theme-spec:145](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/tests/graphs-theme-20260924.spec.ts:145) проверяет DOM observer и настоящий control ThemeProvider, неизменность src/element/window/document, фокус, незавершённый graphTitle, persisted graph и отсутствие cloud writes. Dispatch события без blur полезен для проверки draft, но не равен обычному пользовательскому клику.

Исходные запуски новых E2E этим critic не выполнялись; дополнительные test/artifact-файлы не создавались. БД, миграции, secrets, production и внешние модели не использовались.

### Внешние свидетельства и оставшиеся gates

- **По сообщению main**, existing desktop suite: **19/19 pass**, backend storage: **13/13 pass**. Логи этих запусков critic не проверял и за собственный результат их не выдаёт.
- Новые acceptance/theme-тесты на момент запроса ещё выполнялись. В acceptance-spec появились отдельные случаи [R1:457](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/tests/graphs-acceptance-20260924.spec.ts:457), [R2:491](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/tests/graphs-acceptance-20260924.spec.ts:491), [R4:522](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/tests/graphs-acceptance-20260924.spec.ts:522). Наличие теста не заменяет его результат.
- Для 3.1 остаются неподтверждёнными открытый диалог, выделение и работоспособность undo/redo после смены темы. Тест незавершённого graphTitle и identity iframe заметно усиливает покрытие, но ещё не доказывает эти отдельные состояния.
- Ожидаются окончательные новые E2E-результаты на согласованном локальном контуре, закрытие residual R1 и интеграционная проверка camera/ports/hit-testing. Импорт, wheel и cloud round-trip заново не запускались; отсутствие новых findings по ним в этом проходе не является approval.

### Точный interpreter для knowledge 14 tests

Первоначальные **14/14 pass** пункта 2.3 получены на host, с полным checkout. Рабочая директория: `/Users/bogdanov/Code/dpms-graphs-interactions/backend`.

```sh
/tmp/dpms-graphs-backend-venv/bin/python -B -m unittest discover -s tests -p test_graphs_hierarchy_knowledge.py -v
```

Точный `sys.executable`, повторно проверенный в этом проходе: `/private/tmp/dpms-graphs-backend-venv/bin/python` (`/tmp` разрешается в `/private/tmp`). Его underlying binary: `/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14`. Запускать команду следует через **venv**, не заменять её на underlying binary.

В повторном critic-проходе проверен путь interpreter, а не повторены 14 тестов. По сообщению пользователя, backend-only container дал 13 pass и одну ошибку отсутствующего `/docs`; это ожидаемое отличие build context. Изменений ради container не внесено. Alembic 097 уже применён пользователем локально; critic миграции не запускал.

### Отпечатки повторного среза

SHA-256 на 12:26:41 +0300; выводы относятся к этому срезу, поскольку main продолжает работу.

| Файл | SHA-256 |
| --- | --- |
| frontend/public/graph-workspace/index.html | 49504cc276b38e82412c0544ec371dc334985b66bf46cf56ba365d0dae8a3ee8 |
| frontend/tests/graphs-integration.spec.ts | ae43691aa2b6a9668f7824319e37ed8cbc9feddefe00867143a7b0db6aa4f228 |
| frontend/tests/graphs-acceptance-20260924.spec.ts | 7afcbba92c1b0ce9b1d943b04755f9293289abd8b529f89924b617ca2454ec2c |
| frontend/tests/graphs-theme-20260924.spec.ts | ad0ce9564c188ce7a5272b9c20a81fd57e6d33f4b703e8d9c33eb674e18bde7f |
| frontend/src/pages/GraphsPage.tsx | cfa17832281728d510c7072280f7019166cdb6abf13244d0320b96f83359b91a |
| backend/app/schemas/graph.py | fcc72e7c922e78a72a54f72951a97145bbfc34bcca8fc5d0258f5142ad1a9b4d |

## Первичный срез: история замечаний

Далее сохранён отчёт на 12:03:48, включая исходную severity и тогдашние пробелы проверки. Это **история**, а не повторное предъявление уже исправленных R2-R5; актуальные статусы и residual R1 приведены выше. Номера строк ниже относятся к первичному срезу.

### R1. High: resize с северной/западной стороны нарушает границы сохраняемого графа

Пункты: **2.4**, сохранение результата **2.11**.

Источники: [index.html:5226](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/public/graph-workspace/index.html:5226), [GraphNode:56](/Users/bogdanov/Code/dpms-graphs-interactions/backend/app/schemas/graph.py:56). Контрольные функции: ветка node-resize в handlePointerMove, normalizeGraph.

Новые западные и северные handles пересчитывают x/y через разницу размеров, но не ограничивают итоговую координату. Для узла x=-100000, width=200 перенос западного handle на 40 единиц наружу даёт width=240, x=-100040. Это получено вызовом текущего обработчика с синтетическим событием. GraphNode отвергает такую координату; аналогичен северный край y.

Следствие: локально успешный resize может сделать граф непубликуемым. При следующей нормализации координата зажимается обратно к -100000, так что результат не сохраняет точное положение после перезагрузки. Это проверка границ ручного resize, не требование дорабатывать автоукладку 3.2.

Минимальное направление исправления: ограничивать изменение размеров с учётом зафиксированной противоположной стороны и допустимых x/y; нельзя сохранять недопустимое промежуточное состояние как окончательное.

Проверка перед закрытием: север, запад, NW у -100000; разные масштабы холста; undo/redo; reload; валидация полного payload и публикация через штатный тестовый API. Один только clamp ширины/высоты недостаточен.

### R2. Medium: авторазмер списка расходится с геометрией его границы и портов

Пункты: **2.7**, сопряжение с **2.4/2.6**.

Источники: [CSS списка:882](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/public/graph-workspace/index.html:882), [nodeSize:3416](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/public/graph-workspace/index.html:3416), [renderNodes:4610](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/public/graph-workspace/index.html:4610), [updateListPreview:4645](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/public/graph-workspace/index.html:4645).

Теперь в DOM выводятся все пункты, а видимость определяется измерением списка. Для ручной фиксированной высоты это раскрывает дополнительные строки при растяжении. Однако у autoSize=true отсутствует фиксированная высота DOM-карточки: grid растёт по всем строкам. nodeSize при этом по-прежнему возвращает для не-круга базовые 224 на 108, умноженные на масштаб.

Изолированная Chromium-проба с текущим CSS, тем же устройством article и настоящей updateListPreview, 20 пунктами с переносами и масштабом 1 дала:
- ручная высота 138: 0 полностью помещающихся пунктов, «+20 ещё»;
- ручная высота 360: 7 пунктов, «+13 ещё»;
- без фиксированной высоты: около 782 px, все 20 пунктов; модель геометрии по-прежнему исходит из 108 px.

Это не утверждение о точной высоте любого реального списка: она зависит от текста, ширины и шрифта. Подтверждён сам существенный разрыв между DOM и расчётной геометрией. В результате концы связей и магнит ищут границу в верхней части длинной карточки, а не на её визуальном крае. Новая отрисовка всего списка усиливает расхождение по сравнению с ограниченным предпросмотром.

Минимальное направление исправления: согласовать высоту DOM и nodeSize для autoSize-списка, сохранив раскрытие пунктов при ручном растяжении. Это исправление размера карточки и подключения стрелок, не пересмотр раскладки 3.2.

Проверка перед закрытием: 1/20/200 пунктов, длинные строки, уменьшение и увеличение ширины/высоты, переключение autoSize, semantic zoom, связь с нижним портом. Сравнивать getBoundingClientRect с координатами attachment, а не только число li.

### R3. Medium: вертикальная нормаль круга ошибочно становится диагональной

Пункты: **2.4/2.5**, также preview в **2.6**.

Источник: [attachment:3473](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/public/graph-workspace/index.html:3473). Сам routeEdge принимает нормали извне: [edge-routing.mjs:57](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/public/graph-workspace/edge-routing.mjs:57).

Выражение nx: dx / length || 1 заменяет корректный ноль на единицу. Для верхней точки круга диаметром 200 с центром (100,100), toward=(100,-100), attachment возвращает точку (100,0), но нормаль (1,-1) вместо (0,-1). Нижняя точка получает аналогичную лишнюю X-компоненту. Ветка общая для настоящих кругов и semantic-compact отображения.

Следствие: routeEdge строит терминальный участок под 45 градусами к вертикальной границе; наконечник и preview подходят не по радиусу. Изолированный вызов текущей attachment воспроизвёл результат. Прошедшие тесты routeEdge не исключают дефект: в них нормали подаются уже рассчитанными, attachment из index.html не вызывается.

Минимальное направление исправления: выбирать запасной вектор только при нулевой длине всего вектора, сохраняя нулевую X-компоненту ненулевой вертикальной нормали.

Проверка перед закрытием: верх/низ/лево/право круга и semantic-compact узла; preview и сохранённая связь; curve/orthogonal/straight; обе стороны направленной связи.

### R4. Medium: магнит выбирает bounding box и соседний порт вместо фактической цели

Пункт: **2.6**.

Источники: [поиск цели:5270](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/public/graph-workspace/index.html:5270), [fallback по box:5284](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/public/graph-workspace/index.html:5284), [приоритет snap на отпускании:5343](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/public/graph-workspace/index.html:5343).

Подтверждены два сценария текущего алгоритма:
- Круг с box=(0,0,200,200): указатель (5,5) находится вне окружности, примерно в 34.35 px от границы при scale=1. Несмотря на радиус магнита 18 px, fallback попадания в прямоугольник назначает круг целью.
- Два прямоугольника 200 на 200: A начинается в x=0, B в x=180; указатель (201,100) находится внутри B и в 1 px снаружи A. Поиск выбирает e:2 узла A, хотя указатель над B. На pointerup snapTargetId имеет приоритет над elementFromPoint, поэтому связь закрепляется за A.

Проверка выполнялась на реальной функции handlePointerMove с синтетическим состоянием, не в рабочем графе. DOM-порядок и визуальное перекрытие для полноценного пользовательского сценария нужно проверить отдельно.

Минимальное направление исправления: различать фактическое попадание в видимую фигуру и слабое притяжение к её внешним портам; учитывать круговую границу и приоритет узла под указателем. При отпускании подтверждать актуальную цель, а не безусловно предпочитать предыдущий snap.

Проверка перед закрытием: углы bounding box круга вне 18 px, перекрывающиеся узлы, крупная карточка рядом с чужим портом, удалённый/скрытый узел, масштаб 0.24/1/2.6, совпадение подсвеченной цели и реально созданного ребра.

### R5. Medium: desktop smoke по-прежнему нажимает удалённую кнопку темы

Пункт: **3.1**, достоверность общей приёмки.

Источник: [graphs-integration.spec.ts:308](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/tests/graphs-integration.spec.ts:308). Новая передача темы: [GraphsPage.tsx:50](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/src/pages/GraphsPage.tsx:50), [GraphsPage.tsx:168](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/src/pages/GraphsPage.tsx:168).

Первый desktop-сценарий ищет внутри iframe кнопку «Включить тёмную тему». В текущем index.html отдельная кнопка и её обработчик удалены по требованию пользователя; тема поступает от оболочки. Этот шаг больше не соответствует интерфейсу и не может доказать работоспособность нового механизма. Полный E2E-прогон этим review не запускался; это статически подтверждённое несоответствие локатора, а не выдуманный лог упавшего запуска.

Минимальное направление исправления: переключать тему через оболочку и проверять iframe. Не возвращать удалённую кнопку ради старого теста.

Проверка перед закрытием: light/dark/rose без изменения src и пересоздания iframe; сохранение выбранного графа, выделения, незавершённого inline-ввода, открытого диалога и undo-стека; отсутствие публикации на сервер при переключении темы. Успех проверки одного data-theme без проверки состояния недостаточен.

## Что подтверждено и что ещё не одобрено

### 2.4: порты и контракт backend

connection-ports.mjs задаёт 20 стабильных ID, по пять на сторону. В schema добавлены необязательные sourcePort/targetPort со значением null по умолчанию и ограничением n/e/s/w:0..4. Изолированные Pydantic-пробы успешно проверили round-trip всех 20 ID, отсутствие поля, null и отклонение четырёх некорректных ID. Приложение и его конфигурация при этом не импортировались.

Указанные в ранней фазе review неправильный знак NW resize круга и диаметр больше лимита height=900 уже исправлены параллельной работой main. Повторный вызов актуального обработчика подтвердил: NW на (-40,-40) превращает 200 в 240 и переносит начало в (-40,-40); максимальная высота круга ограничена 900. Боковые e/s-handles круга также возвращены. Это не изменения critic и не активные замечания R1-R5.

Не проверен рабочий cloud round-trip через приложение. Backend API-тесты не запускались, чтобы не загружать app/deps/settings в этой ограниченной роли.

### 2.8: wheel

Актуальный обработчик делает zoom без обязательного Shift/Ctrl, нормализует deltaMode, использует инверсию и передаёт координаты указателя в setZoom. Изолированно прошли направления колеса, инверсия, исключение для Ctrl/pinch, line/page deltaMode, горизонтальная deltaX и передача координат якоря.

Открытый gate: реальная мышь/трекпад, сохранение настройки после reload, физическая неподвижность точки под курсором, Space+drag и браузерные жесты. Отдельного подтверждённого дефекта в проверенной арифметике wheel не найдено.

### 3.1: сохранение состояния при смене темы

У GraphsPage initialTheme фиксирует параметр src до явного reload. postMessage обновляет тему, а applyTheme меняет DOM-тему/цвета маркеров без render/resetGraphSession. В обработчике проверяются origin, source и version. Это подходящая основа для сохранения состояния; подтверждённого reload на каждую смену темы в текущем коде нет.

Но сохранность незавершённого редактирования, диалога и истории в реальном React/iframe-сценарии не проверена. Пока R5 и этот gate не закрыты, approval для 3.1 отсутствует.

### 2.12: импорт в появившемся диалоге

К финальному срезу уже подключены native/cubes/tree/records/edges, ручной mapping, предпросмотр с замечаниями и явное «Создать граф локально». Обработчики находятся в [previewImport:6013](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/public/graph-workspace/index.html:6013) и [confirmImport:6041](/Users/bogdanov/Code/dpms-graphs-interactions/frontend/public/graph-workspace/index.html:6041).

Чистые преобразователи ограничивают объём/глубину, не исполняют getters/toJSON, сохраняют JSON Pointer, различают типы ID и возвращают замечания об обрезке описаний/самоссылках/повторах. При чтении текущего модуля дополнительный подтверждённый блокирующий дефект не найден. Дубли и самоссылки не должны превращаться в незаметную потерю данных: UI уже выводит issues, но видимость и понятность этого сообщения ещё надо проверить.

Подтверждение импорта уже добавляется main в существующие native-сценарии; устаревшее ожидание мгновенного импорта не включено в активные замечания.

Открытые gates: все пять режимов через UI; отмена без изменения workspace; пустой/битый JSON; ошибка после успешного preview; смена mapping инвалидирует candidate; конкурирующие чтения файлов и закрытие диалога; localStorage quota error сохраняет предыдущий граф и его состояние; imported ports и линза сохраняются; до явной публикации нет cloud put. Особенно проверить историю текущего графа при отказе saveGraph: confirmImport вызывает resetGraphSession ещё до окончательного успеха записи. Этот риск rollback отмечен для динамической проверки; в данном review он не воспроизводился.

## Выполненные проверки

1. Прочитаны AGENTS.md, scoped git diff и новые модули. Secrets, production, credential-bearing files и конфигурация подключения к БД не исследовались.
2. Из корня репозитория выполнено:

```sh
node --test --test-reporter=tap frontend/scripts/test-graph-routing.mjs frontend/scripts/test-graph-imports.mjs
```

Результат: **77 tests, 77 pass, 0 fail, 0 skipped**. Это проверки чистых модулей, не приёмка интерфейса.

3. В Node vm выполнены извлечённые из текущего index.html функции геометрии и handlePointerMove с синтетическими узлами. Воспроизведены R1, R3 и оба сценария R4. Параллельные исправления направления и ограничения круга перепроверены отдельно.
4. В отдельном headless Chromium выполнена DOM/CSS-проба списка с текущим CSS и updateListPreview; сеть заблокирована, рабочая страница и пользовательский localStorage не открывались. Воспроизведён R2; обычное раскрытие ручного списка при увеличении высоты также подтверждено.
5. Изолированно проверена арифметика wheel. Сам граф, его камера и persistence в браузере этим тестом не проверялись.
6. GraphEdge/GraphNode загружены непосредственно из файла схемы через importlib с отключённой записью bytecode. Проверены портовые поля и отказ на x=-100040/height=1000. Рабочая БД, миграции и seed не запускались.

Полный graphs-integration.spec.ts, backend storage API suite, сборка, smoke работающего приложения и production deploy **не выполнялись**. Скриншоты и дополнительные тестовые файлы не создавались. Изолированные пробы не подменяют эти gates.

## Критерий повторного review

Закрыть R1-R5, обновить и прогнать соответствующие тесты. Проверку работающей системы проводить только на **http://localhost:55177/graphs**, по исходному решению пункта 1. Не менять URL и не включать пункт 3.2 в объём исправлений.

Повторный critic должен проверить актуальный diff после интеграции всех workers: файлы менялись во время текущего прохода, поэтому выводы относятся к зафиксированному срезу, а не к будущим правкам. До интеграционного подтверждения статусы «принято»/«одобрено» не ставить.

## Отпечатки среза

SHA-256 на 12:03:48 +0300:

| Файл | SHA-256 |
| --- | --- |
| frontend/public/graph-workspace/index.html | 7abcaa827f9a982e6fe2dd7e89aadab014d22d36e39af6e69eb28fe7aa10ff83 |
| frontend/public/graph-workspace/connection-ports.mjs | cf70f9c878b1dc7810cfcafe0b0f35798a61f294a987bcecb5881b11bb1e4044 |
| frontend/public/graph-workspace/edge-routing.mjs | 88fb04d43f6abfa9188b51f49c1d7e61cd351b4ef78fd09a77625d0b3674930c |
| frontend/public/graph-workspace/import-adapters.mjs | abeb35b25f40fecc7b9101e5e6682fec53225cd6ac6da89e9104a4a2a47114d8 |
| frontend/src/pages/GraphsPage.tsx | cfa17832281728d510c7072280f7019166cdb6abf13244d0320b96f83359b91a |
| backend/app/schemas/graph.py | fcc72e7c922e78a72a54f72951a97145bbfc34bcca8fc5d0258f5142ad1a9b4d |
| frontend/tests/graphs-integration.spec.ts | 013eccf063cf798cef0f3e7751eab75c220df9015bd347ee3dafb7a4ca54174d |

Номера строк относятся к этому срезу; при дальнейшем сдвиге ориентироваться также на имена функций.
