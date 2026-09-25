const MAX_NODES = 1500;
const MAX_EDGES = 3000;
const MAX_JSON_BYTES = 5 * 1024 * 1024;
const MAX_DEPTH = 512;
const DESCRIPTION_LIMIT = 2000;
const DESCRIPTION_SUFFIX = '\n[Описание сокращено: лимит 2000 символов. Полные данные остаются в исходном JSON.]';
const EPOCH = '1970-01-01T00:00:00.000Z';
const FIELD_NAMES = ['idField', 'titleField', 'parentField', 'sourceField', 'targetField', 'labelField'];
const ENDPOINT_PAIRS = [['source', 'target'], ['from', 'to'], ['sourceId', 'targetId'], ['source_id', 'target_id']];
const own = (object, key) => Object.hasOwn(object, key);
const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const escapePointer = (key) => String(key).replace(/~/g, '~0').replace(/\//g, '~1');
const childPointer = (path, key) => `${path}/${escapePointer(key)}`;
const location = (path) => path === '' ? 'корень (пустой JSON Pointer)' : path;

function fail(message) {
  throw new Error(message);
}

function head(text, length) {
  const end = Math.min(length, text.length);
  const last = text.charCodeAt(end - 1);
  return text.slice(0, last >= 0xd800 && last <= 0xdbff ? end - 1 : end);
}

// Serialize with descriptors and an explicit stack: no getters, toJSON or recursion.
function inspectJson(input) {
  const chunks = [];
  const spans = new WeakMap();
  const active = new WeakSet();
  const stack = [{ value: input, depth: 0, opened: false }];
  let length = 0;
  const append = (text) => {
    length += text.length;
    if (length > MAX_JSON_BYTES) fail('JSON превышает лимит 5 МБ; импорт целиком отменён.');
    chunks.push(text);
  };
  while (stack.length) {
    const frame = stack[stack.length - 1];
    const { value } = frame;
    if (!frame.opened) {
      if (frame.depth > MAX_DEPTH) fail(`Глубина JSON превышает ${MAX_DEPTH}; импорт целиком отменён.`);
      if (value === null || ['string', 'number', 'boolean'].includes(typeof value)) {
        if (typeof value === 'number' && !Number.isFinite(value)) fail('JSON содержит не конечное число (NaN или Infinity).');
        append(JSON.stringify(value));
        stack.pop();
        continue;
      }
      if (typeof value !== 'object') fail('Ожидалось разобранное JSON-значение: undefined, функции, BigInt и Symbol недопустимы.');
      if (active.has(value)) fail('JSON содержит циклическую ссылку; импорт целиком отменён.');
      const array = Array.isArray(value);
      const prototype = Object.getPrototypeOf(value);
      if (array ? prototype !== Array.prototype : prototype !== Object.prototype && prototype !== null) {
        fail('JSON должен содержать только обычные объекты и массивы, без пользовательских прототипов.');
      }
      const descriptors = Object.getOwnPropertyDescriptors(value);
      const keys = Reflect.ownKeys(descriptors);
      for (const key of keys) {
        if (typeof key !== 'string') fail('Ключи Symbol недопустимы в JSON.');
        const descriptor = descriptors[key];
        if (!own(descriptor, 'value')) fail('Геттеры и сеттеры недопустимы в JSON.');
        if (array && key === 'length') continue;
        if (!descriptor.enumerable) fail('Неперечисляемые свойства недопустимы в JSON.');
        if (array && (!/^(0|[1-9]\d*)$/.test(key) || Number(key) >= descriptors.length.value)) {
          fail('Массив JSON содержит дополнительные свойства вместо индексов.');
        }
      }
      frame.keys = array ? keys.filter((key) => key !== 'length') : keys;
      if (array && frame.keys.length !== descriptors.length.value) fail('Разреженный массив недопустим в JSON; используйте null вместо пропусков.');
      frame.descriptors = descriptors;
      frame.array = array;
      frame.index = 0;
      frame.start = length;
      frame.opened = true;
      active.add(value);
      append(array ? '[' : '{');
    }
    if (frame.index < frame.keys.length) {
      const key = frame.keys[frame.index];
      if (frame.index) append(',');
      if (!frame.array) append(`${JSON.stringify(key)}:`);
      frame.index += 1;
      stack.push({ value: frame.descriptors[key].value, depth: frame.depth + 1, opened: false });
    } else {
      append(frame.array ? ']' : '}');
      spans.set(value, [frame.start, length]);
      active.delete(value);
      stack.pop();
    }
  }
  const raw = chunks.join('');
  if (new TextEncoder().encode(raw).byteLength > MAX_JSON_BYTES) fail('JSON превышает лимит 5 МБ в UTF-8; импорт целиком отменён.');
  return {
    raw,
    snippet(value, limit = DESCRIPTION_LIMIT + 1) {
      if (value !== null && typeof value === 'object') {
        const [start, end] = spans.get(value);
        return raw.slice(start, Math.min(end, start + limit));
      }
      return JSON.stringify(value).slice(0, limit);
    }
  };
}

function detectValidated(input) {
  if (isRecord(input) && own(input, 'nodes') && own(input, 'edges') && Array.isArray(input.nodes) && Array.isArray(input.edges)) return 'native';
  if (isRecord(input) && own(input, 'cubes') && Array.isArray(input.cubes)) return 'cubes';
  if (Array.isArray(input) && input.length && input.every(isRecord)) {
    if (ENDPOINT_PAIRS.some(([source, target]) => input.some((row) => own(row, source) && own(row, target)))) return 'edges';
    return 'records';
  }
  return 'tree';
}

/** input is a parsed JSON value, never a JSON source string. Detection is not graph validation. */
export function detectJsonMode(input) {
  inspectJson(input);
  return detectValidated(input);
}

function readOptions(options) {
  if (!isRecord(options) || ![Object.prototype, null].includes(Object.getPrototypeOf(options))) fail('Параметры импорта должны быть обычным объектом.');
  const result = Object.create(null);
  for (const key of Reflect.ownKeys(options)) {
    if (!['mode', 'recordPath', ...FIELD_NAMES].includes(key)) fail('Неизвестный параметр импорта; проверьте имена полей API.');
    const descriptor = Object.getOwnPropertyDescriptor(options, key);
    if (!own(descriptor, 'value')) fail('Параметры импорта не могут содержать геттеры или сеттеры.');
    if (descriptor.value === undefined) continue;
    if (typeof descriptor.value !== 'string') fail(`Параметр ${key} должен быть строкой.`);
    result[key] = descriptor.value;
  }
  if (result.mode !== undefined && !['tree', 'records', 'edges'].includes(result.mode)) fail('Неизвестный режим: допустимы tree, records и edges. native/cubes обрабатывает основной импортёр.');
  return result;
}

function selectArray(input, path) {
  if (path !== '' && !path.startsWith('/')) fail('recordPath должен быть JSON Pointer: пустая строка для корня или путь с начальным /.');
  let value = input;
  if (path !== '') {
    for (const token of path.slice(1).split('/')) {
      if (/~(?![01])/u.test(token)) fail('В JSON Pointer допустимы только экранирования ~0 и ~1.');
      const key = token.replace(/~1/g, '/').replace(/~0/g, '~');
      if (value === null || typeof value !== 'object' || !own(value, key)) fail(`JSON Pointer ${path} не найден в исходных данных.`);
      if (Array.isArray(value) && !/^(0|[1-9]\d*)$/.test(key)) fail(`JSON Pointer ${path} содержит недопустимый индекс массива.`);
      value = value[key];
    }
  }
  if (!Array.isArray(value)) fail(`По пути ${location(path)} ожидался массив записей.`);
  if (!value.every(isRecord)) fail(`Массив ${location(path)} должен содержать только объекты; для скаляров и вложенных массивов выберите tree.`);
  return value;
}

function mappedField(options, name, rows, candidates, required = false) {
  const explicit = options[name];
  const field = explicit || candidates.find((candidate) => rows.some((row) => own(row, candidate)));
  if (explicit && rows.length && !rows.some((row) => own(row, explicit))) fail(`Поле ${name} «${explicit}» не найдено ни в одной записи.`);
  if (!field && required && rows.length) fail(`Не удалось определить ${name}; укажите имя поля явно.`);
  return field;
}

function identity(value, context) {
  if (value === undefined || value === null || (typeof value === 'string' && value.trim() === '')) fail(`${context}: отсутствует ID; допустимы непустая строка, число или boolean (включая 0 и false).`);
  if (!['string', 'number', 'boolean'].includes(typeof value)) fail(`${context}: ID должен быть строкой, числом или boolean, а не объектом или массивом.`);
  if (typeof value === 'number' && Number.isInteger(value) && !Number.isSafeInteger(value)) fail(`${context}: числовой ID вне безопасного целочисленного диапазона JavaScript; передайте ID строкой, чтобы избежать потери точности.`);
  return `${typeof value}:${JSON.stringify(value)}`;
}

function scalarText(value, context) {
  if (value !== null && typeof value === 'object') fail(`${context}: ожидалось скалярное значение, а не объект или массив.`);
  return value === null || value === undefined ? '' : String(value);
}

function hash(text) {
  let value = 2166136261;
  for (let index = 0; index < text.length; index += 1) value = Math.imul(value ^ text.charCodeAt(index), 16777619);
  return (value >>> 0).toString(16).padStart(8, '0');
}

function createBuilder(mode, fileName, inspected, options) {
  const issues = [];
  const nodes = [];
  const edges = [];
  const pairs = new Map();
  const shortened = new WeakSet();
  const boundedText = (text, limit, context) => {
    if (text.length <= limit) return text;
    issues.push(`${context}: текст сокращён до ${limit} символов; исходное значение остаётся в JSON.`);
    return `${head(text, limit - 3)}...`;
  };
  const appendDescription = (node, text) => {
    if (shortened.has(node)) return;
    const combined = node.description + text;
    if (combined.length <= DESCRIPTION_LIMIT) {
      node.description = combined;
    } else {
      node.description = head(combined, DESCRIPTION_LIMIT - DESCRIPTION_SUFFIX.length) + DESCRIPTION_SUFFIX;
      shortened.add(node);
      issues.push(`Описание узла ${node.id} (${location(node.sourceRef)}) сокращено до ${DESCRIPTION_LIMIT} символов; часть исходных данных не помещается в граф.`);
    }
  };
  const addNode = (title, path, value) => {
    if (nodes.length >= MAX_NODES) fail(`Лимит ${MAX_NODES} узлов превышен; импорт целиком отменён, данные не обрезаны.`);
    if (path.length > 300) fail('JSON Pointer узла превышает лимит sourceRef (300 символов); путь нельзя обрезать. Импорт целиком отменён.');
    const index = nodes.length;
    const node = {
      id: `json-node-${index + 1}`,
      type: 'custom',
      title: boundedText(title.trim() ? title : '(пустая строка)', 180, `Заголовок ${location(path)}`),
      customTypeLabel: mode === 'tree' ? 'JSON' : mode === 'records' ? 'Запись JSON' : 'Сущность JSON',
      sourceRef: path,
      description: '',
      shape: 'rounded', radius: 8, scale: 1, autoSize: true,
      width: 224, height: 108, items: [], pinned: false,
      color: mode === 'tree' ? '#2F6BFF' : mode === 'records' ? '#16845B' : '#0F8B8D',
      x: (index % 30) * 280, y: Math.floor(index / 30) * 160
    };
    nodes.push(node);
    appendDescription(node, inspected.snippet(value));
    return node;
  };
  const addEdge = (source, target, label, path) => {
    if (source === target) {
      issues.push(`Самоссылка ${location(path)}: ребро не добавлено, поскольку граф не поддерживает связь узла с собой. Строка отражена в описании узла с учётом возможного сокращения.`);
      return;
    }
    const pair = `${source}:${target}`;
    if (pairs.has(pair)) {
      issues.push(`Повторная направленная связь ${location(path)}: ребро не добавлено; первая строка ${location(pairs.get(pair))}. Данные строк отражены в описаниях с учётом возможного сокращения; подписи не объединяются.`);
      return;
    }
    if (edges.length >= MAX_EDGES) fail(`Лимит ${MAX_EDGES} связей превышен; импорт целиком отменён, данные не обрезаны.`);
    pairs.set(pair, path);
    edges.push({ id: `json-edge-${edges.length + 1}`, source, target, label: boundedText(label || 'связано с', 80, `Подпись связи ${location(path)}`), routing: 'curve', points: [] });
  };
  const finish = () => {
    const settings = ['mode', 'recordPath', ...FIELD_NAMES].map((key) => [key, options[key] ?? '']);
    const id = `graph-json-${hash(inspected.raw + JSON.stringify([mode, settings, fileName]))}`;
    const viewId = `${id}-view`;
    const viewport = { x: 0, y: 0, scale: 1 };
    const result = {
      graph: {
        version: 3, id,
        title: boundedText(fileName.replace(/\.json$/i, '').trim() || 'Импорт JSON', 80, 'Название графа'),
        createdAt: EPOCH, updatedAt: EPOCH, viewport,
        nodes, edges, groups: [],
        views: [{ id: viewId, name: 'Импорт JSON', layout: 'compact', positions: Object.fromEntries(nodes.map((node) => [node.id, { x: node.x, y: node.y }])), viewport: { ...viewport }, focusNodeId: null, focusDepth: 0, connectionLensEnabled: false }],
        activeViewId: viewId, audit: []
      },
      issues
    };
    if (new TextEncoder().encode(JSON.stringify(result.graph)).byteLength > MAX_JSON_BYTES) fail('Полученный граф превышает лимит 5 МБ; импорт целиком отменён. Выберите меньший массив через recordPath.');
    return result;
  };
  return { issues, addNode, addEdge, appendDescription, finish };
}

function convertTree(input, builder, inspected) {
  const stack = [{ value: input, path: '', key: '$', parent: null }];
  while (stack.length) {
    const { value, path, key, parent } = stack.pop();
    const container = value !== null && typeof value === 'object';
    const summary = container ? (Array.isArray(value) ? `массив [${value.length}]` : `объект {${Object.keys(value).length}}`) : inspected.snippet(value, 181);
    const node = builder.addNode(`${key}: ${summary}`, path, value);
    if (parent) builder.addEdge(parent, node.id, 'содержит', path);
    if (!container) continue;
    const keys = Object.keys(value);
    if (keys.length + stack.length > MAX_NODES) fail(`Лимит ${MAX_NODES} узлов превышен; импорт целиком отменён, данные не обрезаны.`);
    for (let index = keys.length - 1; index >= 0; index -= 1) {
      const child = keys[index];
      stack.push({ value: value[child], path: childPointer(path, child), key: Array.isArray(value) ? `[${child}]` : child, parent: node.id });
    }
  }
}

function convertRecords(rows, path, options, builder) {
  if (rows.length > MAX_NODES) fail(`Лимит ${MAX_NODES} записей/узлов превышен; импорт целиком отменён.`);
  const idField = mappedField(options, 'idField', rows, ['id', 'ID', '_id', 'uuid', 'code']);
  const titleField = mappedField(options, 'titleField', rows, ['title', 'name', 'label', 'displayName', 'display_name']);
  const parentField = mappedField(options, 'parentField', rows, ['parentId', 'parent_id', 'parent', 'parentID']);
  if (!idField && rows.length) builder.issues.push('Поле ID не найдено: ID узлов назначены по позициям строк. Для связей parentField необходимо указать idField.');
  if (parentField && !idField) fail('Для parentField необходимо поле ID (idField); позиционные ID не используются для поиска родителя.');
  const ids = new Map();
  const rowNodes = rows.map((row, index) => {
    const rowPath = childPointer(path, index);
    const key = idField ? identity(own(row, idField) ? row[idField] : undefined, `Запись ${rowPath}, поле ${idField}`) : null;
    if (key !== null && ids.has(key)) fail(`Повторяющийся ID в записи ${rowPath}; первая запись ${ids.get(key).path}. ID должны быть уникальными, импорт целиком отменён.`);
    const titleValue = titleField && own(row, titleField) ? row[titleField] : null;
    let title = scalarText(titleValue, `Запись ${rowPath}, поле ${titleField}`);
    if (!title.trim()) {
      title = idField ? String(row[idField]) : `Запись ${index + 1}`;
      if (titleField) builder.issues.push(`Запись ${rowPath}: пустое или отсутствующее поле ${titleField}; заголовок заменён ID или номером строки.`);
    }
    const node = builder.addNode(title, rowPath, row);
    if (key !== null) ids.set(key, { node, path: rowPath });
    return node;
  });
  if (!parentField) return;
  rows.forEach((row, index) => {
    if (!own(row, parentField) || row[parentField] === null || row[parentField] === '') return;
    const rowPath = childPointer(path, index);
    const parent = ids.get(identity(row[parentField], `Родитель записи ${rowPath}, поле ${parentField}`));
    if (!parent) fail(`Запись ${rowPath}: родитель из поля ${parentField} не найден среди ID выбранного массива. Типы ID должны совпадать (число 1 и строка "1" различаются). Импорт целиком отменён.`);
    builder.addEdge(parent.node.id, rowNodes[index].id, 'содержит', rowPath);
  });
}

function convertEdges(rows, path, options, builder, inspected) {
  if (rows.length > MAX_EDGES) fail(`Лимит ${MAX_EDGES} строк связей превышен (до удаления повторов); импорт целиком отменён.`);
  const pair = ENDPOINT_PAIRS.find(([source, target]) => rows.some((row) => own(row, source) && own(row, target))) || ENDPOINT_PAIRS[0];
  const sourceField = mappedField(options, 'sourceField', rows, [pair[0]], true);
  const targetField = mappedField(options, 'targetField', rows, [pair[1]], true);
  const labelField = mappedField(options, 'labelField', rows, ['label', 'relation', 'type', 'name']);
  const entities = new Map();
  const entity = (row, field, rowPath) => {
    const value = own(row, field) ? row[field] : undefined;
    const key = identity(value, `Связь ${rowPath}, поле ${field}`);
    if (!entities.has(key)) entities.set(key, builder.addNode(String(value), childPointer(rowPath, field), value));
    return entities.get(key);
  };
  rows.forEach((row, index) => {
    const rowPath = childPointer(path, index);
    const source = entity(row, sourceField, rowPath);
    const target = entity(row, targetField, rowPath);
    const rawRow = `\n\nСтрока ${rowPath}: ${inspected.snippet(row)}`;
    builder.appendDescription(source, rawRow);
    if (source !== target) builder.appendDescription(target, rawRow);
    const label = labelField && own(row, labelField) ? scalarText(row[labelField], `Связь ${rowPath}, поле ${labelField}`) : '';
    builder.addEdge(source.id, target.id, label.trim() ? label : 'связано с', rowPath);
  });
}

/** Pure offline conversion. Throws Russian Error messages; never mutates input/options. */
export function convertStructuredJson(input, options = {}, fileName = 'import.json') {
  const settings = readOptions(options);
  if (typeof fileName !== 'string') fail('Имя JSON-файла должно быть строкой.');
  const inspected = inspectJson(input);
  const path = settings.recordPath ?? '';
  const selected = path !== '' ? selectArray(input, path) : input;
  const mode = settings.mode ?? detectValidated(selected);
  if (mode === 'native' || mode === 'cubes') fail(`Формат ${mode} должен обрабатываться adaptImportedGraph в основном импортёре; для дерева явно укажите mode: "tree".`);
  if (mode === 'tree' && path !== '') fail('recordPath применяется только к records/edges; для tree оставьте пустой путь.');
  const builder = createBuilder(mode, fileName, inspected, settings);
  if (mode === 'tree') {
    convertTree(input, builder, inspected);
  } else {
    const rows = selectArray(input, path);
    if (!rows.length) builder.issues.push('Выбран пустой массив: создан граф без узлов и связей.');
    if (path !== '') builder.issues.push(`Импортирован только массив ${path}; остальные данные документа не включены в граф.`);
    if (mode === 'records') convertRecords(rows, path, settings, builder);
    else convertEdges(rows, path, settings, builder, inspected);
  }
  return builder.finish();
}
