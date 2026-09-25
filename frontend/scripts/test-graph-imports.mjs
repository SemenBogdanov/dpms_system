import assert from 'node:assert/strict';
import test from 'node:test';
import { convertStructuredJson, detectJsonMode } from '../public/graph-workspace/import-adapters.mjs';

function graphContract({ graph, issues }) {
  assert.equal(graph.version, 3);
  assert.match(graph.id, /^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$/);
  const text = (value, min, max) => {
    assert.equal(typeof value, 'string');
    assert.ok(value.length >= min && value.length <= max, `Нарушение длины ${min}..${max}: ${value.length}`);
  };
  const number = (value, min, max) => {
    assert.ok(Number.isFinite(value) && value >= min && value <= max, `Число за границами: ${value}`);
  };
  const position = (value) => {
    number(value.x, -100000, 100000);
    number(value.y, -100000, 100000);
  };
  const viewport = (value) => {
    position(value);
    number(value.scale, 0.24, 2.6);
  };
  text(graph.title, 1, 80);
  assert.ok(Number.isFinite(Date.parse(graph.createdAt)));
  assert.ok(Number.isFinite(Date.parse(graph.updatedAt)));
  viewport(graph.viewport);
  assert.ok(graph.nodes.length <= 1500);
  assert.ok(graph.edges.length <= 3000);
  const nodes = new Set(graph.nodes.map((node) => node.id));
  assert.equal(nodes.size, graph.nodes.length);
  for (const node of graph.nodes) {
    assert.deepEqual(Object.keys(node).sort(), ['id', 'type', 'title', 'customTypeLabel', 'sourceRef', 'description', 'shape', 'radius', 'scale', 'autoSize', 'width', 'height', 'items', 'pinned', 'color', 'x', 'y'].sort());
    text(node.id, 1, 100);
    text(node.title, 1, 180);
    text(node.customTypeLabel, 0, 60);
    text(node.sourceRef, 0, 300);
    text(node.description, 0, 2000);
    assert.equal(node.type, 'custom');
    assert.ok(['square', 'rounded', 'circle'].includes(node.shape));
    assert.match(node.color, /^#[0-9a-f]{6}$/i);
    number(node.radius, 0, 36);
    number(node.scale, 0.5, 2);
    number(node.width, 96, 1200);
    number(node.height, 64, 900);
    assert.equal(typeof node.autoSize, 'boolean');
    assert.equal(typeof node.pinned, 'boolean');
    assert.deepEqual(node.items, []);
    position(node);
  }
  const edges = new Set();
  const pairs = new Set();
  for (const edge of graph.edges) {
    assert.deepEqual(Object.keys(edge).sort(), ['id', 'source', 'target', 'label', 'routing', 'points'].sort());
    text(edge.id, 1, 100);
    text(edge.source, 1, 100);
    text(edge.target, 1, 100);
    text(edge.label, 1, 80);
    assert.ok(!edges.has(edge.id));
    edges.add(edge.id);
    assert.ok(nodes.has(edge.source) && nodes.has(edge.target));
    assert.notEqual(edge.source, edge.target);
    const pair = JSON.stringify([edge.source, edge.target]);
    assert.ok(!pairs.has(pair));
    pairs.add(pair);
    assert.ok(['curve', 'orthogonal', 'straight'].includes(edge.routing));
    assert.deepEqual(edge.points, []);
  }
  assert.deepEqual(graph.groups, []);
  assert.deepEqual(graph.audit, []);
  assert.equal(graph.views.length, 1);
  assert.equal(graph.activeViewId, graph.views[0].id);
  const view = graph.views[0];
  text(view.id, 1, 100);
  text(view.name, 1, 60);
  assert.ok(['hierarchy', 'compact', 'radial'].includes(view.layout));
  assert.equal(view.focusNodeId, null);
  assert.equal(view.focusDepth, 0);
  assert.equal(view.connectionLensEnabled, false);
  viewport(view.viewport);
  assert.deepEqual(new Set(Object.keys(view.positions)), nodes);
  for (const node of graph.nodes) assert.deepEqual(view.positions[node.id], { x: node.x, y: node.y });
  assert.ok(Array.isArray(issues) && issues.every((issue) => typeof issue === 'string' && /[А-Яа-яЁё]/u.test(issue)));
  return graph;
}

function convert(input, options, name) {
  const result = convertStructuredJson(input, options, name);
  graphContract(result);
  return result;
}

function fails(input, options, message) {
  assert.throws(() => convertStructuredJson(input, options), (error) => {
    assert.ok(error instanceof Error && !(error instanceof RangeError));
    assert.match(error.message, /[А-Яа-яЁё]/u);
    assert.match(error.message, message);
    return true;
  });
}

function freezeJson(input) {
  const stack = [input];
  while (stack.length) {
    const item = stack.pop();
    if (item === null || typeof item !== 'object') continue;
    stack.push(...Object.values(item));
    Object.freeze(item);
  }
  return input;
}

test('2.12: detection preserves native/cubes precedence and does not claim schema validation', () => {
  assert.equal(detectJsonMode({ nodes: [], edges: [], cubes: [] }), 'native');
  assert.equal(detectJsonMode({ nodes: [], edges: [] }), 'native');
  assert.equal(detectJsonMode({ cubes: [] }), 'cubes');
  assert.equal(detectJsonMode({ nodes: 'not an array', edges: [] }), 'tree');
  assert.equal(detectJsonMode({ cubes: 'not an array' }), 'tree');
  assert.equal(detectJsonMode([{ id: 1, title: 'Запись' }]), 'records');
  for (const row of [{ source: 'a', target: 'b' }, { from: 0, to: false }, { sourceId: 1, targetId: 2 }, { source_id: 1, target_id: 2 }]) {
    assert.equal(detectJsonMode([row]), 'edges');
    assert.equal(convert([row]).graph.edges.length, 1);
  }
  for (const input of [[], [1, {}], [[{}]], null, 0, false, 'text', { data: [{ id: 1 }] }]) assert.equal(detectJsonMode(input), 'tree');
  fails({ nodes: [], edges: [] }, {}, /adaptImportedGraph/);
  fails({ cubes: [] }, {}, /adaptImportedGraph/);
  assert.equal(convert({ nodes: [], edges: [] }, { mode: 'tree' }).graph.nodes.length, 3);
});

test('2.12: every root JSON scalar, including a string resembling JSON, is preserved', () => {
  for (const input of [0, false, null, true, 42, '', 'hello', '{"id":1}', '😀', -0]) {
    const { graph, issues } = convert(input);
    assert.equal(graph.nodes.length, 1);
    assert.equal(graph.edges.length, 0);
    assert.equal(graph.nodes[0].sourceRef, '');
    assert.equal(graph.nodes[0].description, JSON.stringify(input));
    assert.ok(graph.nodes[0].title.startsWith('$: '));
    assert.deepEqual(issues, []);
  }
});

test('2.12: tree produces property/value hierarchy for nested arrays and empty containers', () => {
  const data = [0, false, null, [1, { name: 'Nested' }], {}, []];
  const { graph } = convert(data, { mode: 'tree' });
  assert.equal(graph.nodes.length, 10);
  assert.equal(graph.edges.length, 9);
  assert.deepEqual(graph.nodes.map((node) => node.sourceRef), ['', '/0', '/1', '/2', '/3', '/3/0', '/3/1', '/3/1/name', '/4', '/5']);
});

test('2.12: tree edges point from each actual parent to its child', () => {
  const { graph } = convert({ a: [0, { b: false }], z: null });
  const byId = new Map(graph.nodes.map((node) => [node.id, node.sourceRef]));
  assert.deepEqual(graph.edges.map((edge) => [byId.get(edge.source), byId.get(edge.target)]), [
    ['', '/a'], ['/a', '/a/0'], ['/a', '/a/1'], ['/a/1', '/a/1/b'], ['', '/z']
  ]);
  assert.deepEqual(JSON.parse(graph.nodes[0].description), { a: [0, { b: false }], z: null });
});

test('2.12: JSON Pointer escapes / and ~ without changing keys or empty tokens', () => {
  const input = { 'a/b': { '~x': [{ id: 1, title: 'Name' }] }, '': null, '~1': true };
  const tree = convert(input, { mode: 'tree' }).graph;
  assert.ok(tree.nodes.some((node) => node.sourceRef === '/a~1b/~0x/0/title'));
  assert.ok(tree.nodes.some((node) => node.sourceRef === '/'));
  assert.ok(tree.nodes.some((node) => node.sourceRef === '/~01'));
  const result = convert(input, { mode: 'records', recordPath: '/a~1b/~0x' });
  assert.equal(result.graph.nodes[0].sourceRef, '/a~1b/~0x/0');
  assert.match(result.issues[0], /только массив/);
  assert.equal(convert({ '': [{ id: 1 }] }, { recordPath: '/' }).graph.nodes.length, 1);
});

test('2.12: invalid pointers never traverse prototypes or array pseudo-properties', () => {
  for (const path of ['data', '#/data', '/~2', '/~', '/missing', '/constructor', '/toString']) fails({ data: [] }, { mode: 'records', recordPath: path }, /Pointer/);
  for (const path of ['/00', '/01', '/-1', '/-', '/1e0', '/length', '/1']) fails([[]], { mode: 'records', recordPath: path }, /Pointer/);
  fails({ data: 0 }, { mode: 'records', recordPath: '/data' }, /массив/);
  fails({ data: [] }, { mode: 'tree', recordPath: '/data' }, /только к records\/edges/);
});

test('2.12: records autodetect fields, retain attributes and connect later parents', () => {
  const data = [{ id: 2, name: 'Child', parentId: 0, active: false, weight: 0, extra: null }, { id: 0, name: 'Root', parentId: null }];
  const { graph, issues } = convert(data);
  assert.deepEqual(graph.nodes.map((node) => node.title), ['Child', 'Root']);
  assert.equal(graph.edges[0].source, graph.nodes[1].id);
  assert.equal(graph.edges[0].target, graph.nodes[0].id);
  graph.nodes.forEach((node, index) => assert.deepEqual(JSON.parse(node.description), data[index]));
  assert.deepEqual(issues, []);
  const snake = convert([{ _id: false, title: false, parent_id: null }, { _id: 0, title: 0, parent_id: false }]).graph;
  assert.deepEqual(snake.nodes.map((node) => node.title), ['false', '0']);
  assert.equal(snake.edges.length, 1);
});

test('2.12: explicit mapping uses literal fields, not dotted paths or executable expressions', () => {
  const data = { payload: [{ 'a.id': 'x', '/name~': 'Root', 'parent/key': null }, { 'a.id': 'y', '/name~': 'Child', 'parent/key': 'x' }] };
  const options = { mode: 'records', recordPath: '/payload', idField: 'a.id', titleField: '/name~', parentField: 'parent/key' };
  const { graph } = convert(data, options);
  assert.deepEqual(graph.nodes.map((node) => node.title), ['Root', 'Child']);
  assert.equal(graph.edges.length, 1);
  fails(data, { ...options, idField: 'payload.a.id' }, /не найдено/);
});

test('2.12: absent record IDs are positional only when no ID field exists', () => {
  const { graph, issues } = convert([{ name: 'One' }, { name: 'Two' }]);
  assert.equal(graph.nodes.length, 2);
  assert.match(issues.join('\n'), /позициям строк/);
  fails([{ id: 1 }, { name: 'Missing' }], {}, /отсутствует ID/);
  for (const id of [null, '', '  ', [], {}]) fails([{ id }], { mode: 'records' }, /ID/);
  fails([{ id: 1 }, { id: 1 }], {}, /Повторяющийся ID.*\/1.*\/0/);
  fails([{ id: false }, { id: false }], {}, /Повторяющийся ID/);
  assert.equal(convert([{ id: 1 }, { id: '1' }, { id: false }, { id: 'false' }]).graph.nodes.length, 4);
  fails([{ id: Number.MAX_SAFE_INTEGER + 1 }], {}, /потери точности/);
  assert.equal(convert([{ id: '9007199254740993' }]).graph.nodes.length, 1);
  fails([{ name: 'No ID', parentId: 1 }], {}, /Для parentField/);
});

test('2.12: dangling parents reject all data; self parents are disclosed, cycles remain actual edges', () => {
  fails([{ id: 0, parentId: 5 }], {}, /родитель.*не найден/);
  fails([{ id: 1, parentId: '1' }], {}, /Типы ID/);
  fails([{ id: 1, parentId: [] }], {}, /ID должен/);
  const self = convert([{ id: 1, parentId: 1 }]);
  assert.equal(self.graph.nodes.length, 1);
  assert.equal(self.graph.edges.length, 0);
  assert.match(self.issues.join('\n'), /Самоссылка.*ребро не добавлено/);
  assert.equal(JSON.parse(self.graph.nodes[0].description).parentId, 1);
  assert.equal(convert([{ id: 1, parentId: 2 }, { id: 2, parentId: 1 }]).graph.edges.length, 2);
});

test('2.12: missing titles have disclosed fallbacks; nonscalar titles reject', () => {
  const result = convert([{ id: 1, title: '' }, { id: 2 }, { id: 3, title: null }]);
  assert.deepEqual(result.graph.nodes.map((node) => node.title), ['1', '2', '3']);
  assert.equal(result.issues.length, 3);
  fails([{ id: 1, title: {} }], {}, /скалярное/);
  assert.deepEqual(convert([{ id: 1, name: 'One' }], { idField: '', titleField: '' }).issues, []);
});

test('2.12: edge entities reuse repeated endpoints with type-sensitive identity', () => {
  const data = [{ source: 0, target: false, label: 0, meta: { active: false } }, { source: false, target: '0', label: false }, { source: '0', target: 0 }];
  const { graph, issues } = convert(data);
  assert.equal(graph.nodes.length, 3);
  assert.equal(graph.edges.length, 3);
  assert.deepEqual(graph.edges.map((edge) => edge.label), ['0', 'false', 'связано с']);
  assert.equal(graph.edges[0].target, graph.edges[1].source);
  assert.equal(graph.edges[2].target, graph.edges[0].source);
  assert.equal(graph.nodes[0].sourceRef, '/0/source');
  assert.ok(graph.nodes[0].description.includes(JSON.stringify(data[0])));
  assert.deepEqual(issues, []);
});

test('2.12: edge duplicates keep first label and report each omitted row, self references are not edges', () => {
  const data = [{ source: 'A', target: 'B', label: 'first' }, { source: 'A', target: 'B', label: 'second' }, { source: 'B', target: 'A', label: 'reverse' }, { source: 'A', target: 'A', memo: 'self' }];
  const { graph, issues } = convert(data);
  assert.equal(graph.nodes.length, 2);
  assert.equal(graph.edges.length, 2);
  assert.deepEqual(graph.edges.map((edge) => edge.label), ['first', 'reverse']);
  assert.equal(issues.length, 2);
  assert.match(issues[0], /Повторная.*\/1.*\/0/);
  assert.match(issues[1], /Самоссылка.*\/3.*ребро не добавлено/);
  assert.ok(graph.nodes[0].description.includes(JSON.stringify(data[1])));
  assert.ok(graph.nodes[0].description.includes(JSON.stringify(data[3])));
  const single = convert([{ source: false, target: false }]);
  assert.equal(single.graph.nodes.length, 1);
  assert.equal(single.graph.edges.length, 0);
  assert.match(single.issues[0], /Самоссылка/);
});

test('2.12: mapped edges preserve row metadata and reject missing/invalid endpoints', () => {
  const result = convert({ links: [{ left: 'A', right: 'B', verb: 'uses', cost: 12 }] }, { mode: 'edges', recordPath: '/links', sourceField: 'left', targetField: 'right', labelField: 'verb' });
  assert.equal(result.graph.edges[0].label, 'uses');
  assert.ok(result.graph.nodes.every((node) => node.description.includes('"cost":12')));
  for (const value of [null, '', {}, []]) fails([{ source: value, target: 'A' }], { mode: 'edges' }, /ID/);
  fails([{ source: 'A', target: 'B' }, { source: 'C' }], { mode: 'edges' }, /\/1.*target.*отсутствует ID/);
  fails([{ x: 1, y: 2 }], { mode: 'edges' }, /sourceField/);
  fails([{ source: 1, target: 2, label: {} }], { mode: 'edges' }, /скалярное/);
  fails([{ source: Number.MAX_SAFE_INTEGER + 1, target: 0 }], { mode: 'edges' }, /потери точности/);
  fails([{ source: 1, target: 2 }], { mode: 'edges', targetField: 'missing' }, /не найдено/);
});

test('2.12: empty arrays, forced records/edges and invalid row shapes are explicit', () => {
  assert.equal(convert([]).graph.nodes.length, 1);
  for (const mode of ['records', 'edges']) {
    const result = convert([], { mode });
    assert.equal(result.graph.nodes.length, 0);
    assert.match(result.issues[0], /пустой массив/);
    for (const data of [[0], [false], [null], [[]], [{} , null]]) fails(data, { mode }, /только объекты/);
    fails({}, { mode }, /ожидался массив/);
  }
});

test('2.12: unsafe keys are ordinary data in trees, mappings and JSON Pointers', () => {
  const data = JSON.parse('{"__proto__":{"polluted":true},"constructor":{"prototype":{"x":1}},"prototype":[{"id":1}],"toString":false}');
  const before = Object.getOwnPropertyDescriptors(Object.prototype);
  const { graph } = convert(data);
  assert.deepEqual(JSON.parse(graph.nodes[0].description), data);
  assert.ok(graph.nodes.some((node) => node.sourceRef === '/__proto__/polluted'));
  assert.equal(convert(data, { mode: 'records', recordPath: '/prototype' }).graph.nodes.length, 1);
  const rows = JSON.parse('[{"__proto__":"a","constructor":"First"},{"__proto__":"b","constructor":"Second"}]');
  assert.deepEqual(convert(rows, { mode: 'records', idField: '__proto__', titleField: 'constructor' }).graph.nodes.map((node) => node.title), ['First', 'Second']);
  fails(JSON.parse('[{"__proto__":"a"},{}]'), { mode: 'records', idField: '__proto__' }, /отсутствует ID/);
  const endpoints = JSON.parse('[{"source":"__proto__","target":"constructor"},{"source":"constructor","target":"prototype"}]');
  assert.equal(convert(endpoints).graph.nodes.length, 3);
  assert.deepEqual(Object.getOwnPropertyDescriptors(Object.prototype), before);
  assert.equal({}.polluted, undefined);
});

test('2.12: markup is preserved as inert text, never evaluated or assigned to DOM', () => {
  const title = '<img src=x onerror="globalThis.__jsonImportExecuted=1">';
  const data = [{ id: 'javascript:alert(1)', title, html: '</script><script>globalThis.__jsonImportExecuted=2</script>' }];
  const { graph } = convert(data, {}, '<svg onload=alert(1)>.json');
  assert.equal(graph.nodes[0].title, title);
  assert.deepEqual(JSON.parse(graph.nodes[0].description), data[0]);
  assert.match(graph.nodes[0].id, /^json-node-\d+$/);
  assert.equal(graph.title, '<svg onload=alert(1)>');
  assert.equal(globalThis.__jsonImportExecuted, undefined);
});

test('2.12: JavaScript-only values, custom prototypes and nonfinite numbers reject without coercion', () => {
  for (const value of [undefined, NaN, Infinity, -Infinity, 1n, Symbol('x'), () => {}, new Date(), new Map(), new Set(), new Number(1), Object.create({ id: 1 })]) {
    fails(value, {}, /JSON/);
    fails({ nested: value }, {}, /JSON/);
    assert.throws(() => detectJsonMode(value), /JSON/);
  }
  fails({ nested: [undefined] }, {}, /JSON/);
  fails(new Array(3), {}, /Разреженный/);
  const extra = [1]; extra.extra = 2;
  fails(extra, {}, /дополнительные/);
  fails({ [Symbol('hidden')]: 1 }, {}, /Symbol/);
  fails(Object.defineProperty({}, 'hidden', { value: 1 }), {}, /Неперечисляемые/);
  class ArraySubclass extends Array {}
  fails(new ArraySubclass(), {}, /прототипов/);
});

test('2.12: getters and toJSON never execute, and cyclic references fail without stack overflow', () => {
  let calls = 0;
  const getter = Object.defineProperty({}, 'id', { enumerable: true, get() { calls += 1; return 1; } });
  fails(getter, {}, /Геттеры/);
  assert.throws(() => detectJsonMode(getter), /Геттеры/);
  fails({ toJSON() { calls += 1; return {}; } }, {}, /JSON/);
  fails({}, Object.defineProperty({}, 'mode', { get() { calls += 1; return 'tree'; } }), /геттеры/);
  assert.equal(calls, 0);
  const cyclic = {}; cyclic.child = [cyclic];
  fails(cyclic, {}, /циклическую/);
  const shared = { a: 1 };
  assert.equal(convert({ first: shared, second: shared }).graph.nodes.length, 5);
  const plain = Object.create(null); plain.id = 1;
  assert.equal(convert([plain]).graph.nodes.length, 1);
});

test('2.12: options are validated, including misspellings and inappropriate types', () => {
  for (const options of [null, [], false, 'tree', { mode: 'native' }, { mode: 'unknown' }, { recordPath: 0 }, { idField: null }, { typo: 'id' }, { [Symbol('mode')]: 'tree' }]) fails({}, options, /импорта|Параметр|режим/);
  assert.throws(() => convertStructuredJson({}, {}, null), /Имя JSON-файла/);
});

test('2.12: inputs and options stay frozen; output does not alias input or prior results', () => {
  for (const [data, options] of [
    [{ a: [0, false, null] }, { mode: 'tree' }],
    [[{ id: 0, name: 'Root' }, { id: 1, name: 'Child', parentId: 0 }], { mode: 'records' }],
    [[{ source: 0, target: false, meta: { enabled: true } }], { mode: 'edges' }]
  ]) {
    const snapshot = JSON.stringify(data);
    freezeJson(data); freezeJson(options);
    const first = convert(data, options);
    const second = convert(data, options);
    assert.deepEqual(first, second);
    first.graph.nodes[0].title = 'Changed';
    first.graph.views[0].positions[first.graph.nodes[0].id].x = 123;
    first.issues.push('Changed');
    assert.equal(JSON.stringify(data), snapshot);
    assert.deepEqual(convert(data, options), second);
  }
});

test('2.12: text truncation is disclosed and never truncates sourceRef silently', () => {
  const data = [{ id: 1, title: 'Ж'.repeat(200), text: '😀'.repeat(2000) }];
  const result = convert(data, {}, 'Ф'.repeat(90) + '.json');
  assert.match(result.issues.join('\n'), /Заголовок.*сокращён/);
  assert.match(result.issues.join('\n'), /Описание.*сокращено/);
  assert.match(result.issues.join('\n'), /Название графа.*сокращён/);
  assert.match(result.graph.nodes[0].description, /Описание сокращено/);
  assert.ok(!/[\uD800-\uDBFF]$/.test(result.graph.nodes[0].description.split('\n')[0]));
  const edge = convert([{ source: 'a', target: 'b', label: 'x'.repeat(100), detail: 'v'.repeat(2500) }]);
  assert.equal(edge.graph.edges[0].label.length, 80);
  assert.match(edge.issues.join('\n'), /Подпись связи.*сокращён/);
  assert.ok(edge.graph.nodes.every((node) => node.description.includes('Описание сокращено')));
  const boundary = convert({ ['a'.repeat(299)]: 1 }, { mode: 'tree' });
  assert.equal(boundary.graph.nodes[1].sourceRef.length, 300);
  fails({ ['a'.repeat(300)]: 1 }, { mode: 'tree' }, /sourceRef.*нельзя обрезать/);
});

test('2.12: node budget accepts exactly 1500 and rejects 1501 without partial results', () => {
  const records = Array.from({ length: 1500 }, (_, id) => ({ id }));
  assert.equal(convert(records).graph.nodes.length, 1500);
  fails([...records, { id: 1500 }], {}, /1500/);
  assert.equal(convert(Array.from({ length: 1499 }, () => 0), { mode: 'tree' }).graph.nodes.length, 1500);
  fails(Array.from({ length: 1500 }, () => 0), { mode: 'tree' }, /1500/);
  const edges = Array.from({ length: 1499 }, (_, id) => ({ source: 0, target: id + 1 }));
  assert.equal(convert(edges).graph.nodes.length, 1500);
  fails([...edges, { source: 0, target: 1500 }], { mode: 'edges' }, /1500/);
});

test('2.12: edge budget accepts 3000 directed pairs and rejects even duplicate input over budget', () => {
  const rows = Array.from({ length: 3000 }, (_, index) => ({ source: Math.floor(index / 60), target: 60 + index % 60 }));
  const result = convert(rows);
  assert.equal(result.graph.edges.length, 3000);
  assert.equal(result.graph.nodes.length, 110);
  fails([...rows, rows[0]], { mode: 'edges' }, /3000.*до удаления повторов/);
  fails(Array.from({ length: 3001 }, () => ({ source: 1, target: 1 })), { mode: 'edges' }, /3000/);
});

test('2.12: huge depths fail explicitly, supported depth and sourceRef boundary work iteratively', () => {
  let deep = 0;
  for (let index = 0; index < 20000; index += 1) deep = [deep];
  fails(deep, { mode: 'tree' }, /Глубина JSON превышает 512/);
  let pointerBoundary = 0;
  for (let index = 0; index < 150; index += 1) pointerBoundary = { a: pointerBoundary };
  assert.equal(convert(pointerBoundary, { mode: 'tree' }).graph.nodes.length, 151);
  fails({ a: pointerBoundary }, { mode: 'tree' }, /sourceRef/);
  let payload = 0;
  for (let index = 0; index < 500; index += 1) payload = [payload];
  assert.equal(convert([{ id: 1, payload }]).graph.nodes.length, 1);
});

test('2.12: JSON budget is UTF-8 bytes and validates even unselected branches', () => {
  fails('x'.repeat(5 * 1024 * 1024), {}, /5 МБ/);
  fails('€'.repeat(Math.ceil(5 * 1024 * 1024 / 3)), {}, /5 МБ.*UTF-8/);
  fails({ rows: [{ id: 1 }], ignored: NaN }, { mode: 'records', recordPath: '/rows' }, /не конечное число/);
  assert.equal(convert('x'.repeat(5 * 1024 * 1024 - 2)).graph.nodes.length, 1);
});

test('2.12: expanded graph size rejects the whole candidate, not a silent subset of descriptions', () => {
  const data = Array.from({ length: 1490 }, (_, id) => ({ id, title: '😀'.repeat(90), detail: '😀'.repeat(730) }));
  assert.ok(new TextEncoder().encode(JSON.stringify(data)).byteLength < 5 * 1024 * 1024);
  fails(data, { mode: 'records' }, /Полученный граф превышает лимит 5 МБ/);
});
