import test from 'node:test';
import assert from 'node:assert/strict';
import { performance } from 'node:perf_hooks';
import { findVacantPosition } from '../public/graph-workspace/insertion-geometry.mjs';

const rect = (id, x = 0, y = 0, width = 10, height = 10) => ({ id, x, y, width, height });
const clear = (item, obstacles, point, gap) => obstacles.every((obstacle) => obstacle.id === item.id
  || point.x + item.width + gap <= obstacle.x
  || obstacle.x + obstacle.width + gap <= point.x
  || point.y + item.height + gap <= obstacle.y
  || obstacle.y + obstacle.height + gap <= point.y);
const validPosition = (item, obstacles, point, { gap = 24, limit = 100000 } = {}) => {
  assert.ok(point, 'Expected a vacant position');
  assert.ok(Number.isFinite(point.x) && Number.isFinite(point.y));
  assert.ok(Math.abs(point.x) <= limit && Math.abs(point.y) <= limit);
  assert.ok(clear(item, obstacles, point, gap), `Insufficient gap at ${JSON.stringify(point)}`);
};

test('empty obstacles and an already-clear preferred position stay unchanged', () => {
  const item = rect('new', -73, 42, 60, 30);
  assert.deepEqual(findVacantPosition(item, []), { x: -73, y: 42 });
  assert.deepEqual(findVacantPosition(item, [rect('far', 500, -300)]), { x: -73, y: 42 });
  const result = findVacantPosition(item, []);
  assert.notEqual(result, item);
  result.x = 100;
  assert.equal(item.x, -73);
});

for (const [direction, expected] of [
  ['right', { x: 34, y: 0 }], ['down', { x: 0, y: 34 }],
  ['left', { x: -34, y: 0 }], ['up', { x: 0, y: -34 }],
]) {
  test(`equal-distance cardinal placement favors ${direction}`, () => {
    const item = rect('new');
    const obstacles = [rect('existing')];
    const result = findVacantPosition(item, obstacles, { direction });
    assert.deepEqual(result, expected);
    validPosition(item, obstacles, result);
  });
}

test('distance takes priority over direction, avoiding long rows when a nearby vacancy exists', () => {
  const item = rect('new', 50, 0, 10, 10);
  const obstacles = [rect('wide', 0, 0, 1000, 10)];
  const result = findVacantPosition(item, obstacles, { direction: 'right', gap: 4 });
  assert.deepEqual(result, { x: 50, y: 14 });
  validPosition(item, obstacles, result, { gap: 4 });
});

for (const [direction, x, y, expected] of [
  ['right', 10, 0, { x: 10, y: 2 }], ['down', 0, 10, { x: -2, y: 10 }],
  ['left', -10, 0, { x: -10, y: -2 }], ['up', 0, -10, { x: 2, y: -10 }],
]) {
  test(`near limit: ${direction} falls back clockwise without leaving the origin bounds`, () => {
    const item = rect('new', x, y, 2, 2);
    const obstacles = [rect('existing', x, y, 2, 2)];
    const result = findVacantPosition(item, obstacles, { direction, gap: 0, limit: 10 });
    assert.deepEqual(result, expected);
    validPosition(item, obstacles, result, { gap: 0, limit: 10 });
  });
}

test('preferred origins outside bounds clamp to the closest in-bounds point', () => {
  for (const [x, y, expected] of [
    [90, -90, { x: 20, y: -20 }], [-90, 90, { x: -20, y: 20 }],
    [5, -90, { x: 5, y: -20 }], [90, 5, { x: 20, y: 5 }],
  ]) {
    assert.deepEqual(findVacantPosition(rect('new', x, y, 200, 100), [], { limit: 20 }), expected);
  }
  const item = rect('new', 100, 100, 2, 2);
  const obstacles = [rect('corner', 9, 9, 4, 4)];
  const result = findVacantPosition(item, obstacles, { gap: 0, limit: 10 });
  assert.deepEqual(result, { x: 7, y: 10 });
  validPosition(item, obstacles, result, { gap: 0, limit: 10 });
});

test('own ID is ignored, including zero, but numeric and string IDs remain distinct', () => {
  assert.deepEqual(findVacantPosition(rect(0), [rect(0, -1000, -1000, 2000, 2000)]), { x: 0, y: 0 });
  const item = rect('new');
  const obstacles = [rect('new', -1000, -1000, 2000, 2000), rect('other')];
  assert.deepEqual(findVacantPosition(item, obstacles), { x: 34, y: 0 });
  assert.deepEqual(findVacantPosition(rect(0), [rect('0')]), { x: 34, y: 0 });
});

test('exact gap contact and zero-gap touching are clear on all sides', () => {
  for (const gap of [0, 7, 24]) {
    for (const [x, y] of [[10 + gap, 0], [-10 - gap, 0], [0, 10 + gap], [0, -10 - gap]]) {
      const item = rect('new', x, y);
      const obstacles = [rect('existing')];
      assert.deepEqual(findVacantPosition(item, obstacles, { gap }), { x, y });
      validPosition(item, obstacles, { x, y }, { gap });
    }
  }
});

test('gap is enforced even when rectangle interiors do not overlap', () => {
  const item = rect('new', 12, 0);
  const obstacles = [rect('existing')];
  const result = findVacantPosition(item, obstacles, { gap: 7 });
  assert.deepEqual(result, { x: 17, y: 0 });
  validPosition(item, obstacles, result, { gap: 7 });
});

test('diagonal vacancy is found when all four straight rays are blocked', () => {
  const item = rect('new', 0, 0, 2, 2);
  const obstacles = [rect('vertical', -1, -20, 2, 40), rect('horizontal', -20, -1, 40, 2)];
  const result = findVacantPosition(item, obstacles, { gap: 0, limit: 10 });
  assert.deepEqual(result, { x: 1, y: 1 });
  validPosition(item, obstacles, result, { gap: 0, limit: 10 });
});

test('an isolated vacancy fitting the rectangle and gap exactly is not merged away', () => {
  const item = rect('new', 0, 0, 4, 6);
  const obstacles = [
    rect('left', -100, -100, 103, 200), rect('right', 11, -100, 100, 200),
    rect('top', -100, -100, 200, 105), rect('bottom', -100, 15, 200, 100),
  ];
  const result = findVacantPosition(item, obstacles, { gap: 2, limit: 20 });
  assert.deepEqual(result, { x: 5, y: 7 });
  validPosition(item, obstacles, result, { gap: 2, limit: 20 });
});

test('mixed-size cluster, negative coordinates, nested rectangles and all metadata are obstacles', () => {
  const item = rect('new', -90, -40, 70, 35);
  const obstacles = [
    { ...rect('pinned', -100, -50, 120, 80), pinned: true },
    { ...rect('hidden', -160, -110, 80, 150), hidden: true },
    rect('small', -20, -20, 10, 10), rect('wide', -50, 70, 180, 20),
    rect('tall', 70, -130, 30, 160), rect('nested', -80, -30, 10, 10),
  ];
  const result = findVacantPosition(item, obstacles, { gap: 13 });
  validPosition(item, obstacles, result, { gap: 13 });
  assert.deepEqual(result, findVacantPosition(item, obstacles.map(({ pinned, hidden, ...geometry }) => geometry), { gap: 13 }));
  assert.ok(Math.hypot(result.x - item.x, result.y - item.y) < 200);
});

test('overlapping, repeated and enclosing obstacles never mask a smaller active obstacle', () => {
  const item = rect('new', 0, 0, 2, 2);
  const obstacles = [rect('wide', -10, -2, 20, 4), rect('wide', -10, -2, 20, 4), rect('tall', -2, -10, 4, 20)];
  const result = findVacantPosition(item, obstacles, { gap: 1 });
  assert.deepEqual(result, { x: 3, y: 3 });
  validPosition(item, obstacles, result, { gap: 1 });
});

test('fully impossible areas return null, including coverage by several obstacles', () => {
  const item = rect('new', 0, 0, 4, 6);
  assert.equal(findVacantPosition(item, [rect('full', -100, -100, 200, 200)], { limit: 20 }), null);
  const walls = [rect('left', -100, -100, 101, 200), rect('right', 0, -100, 100, 200)];
  assert.equal(findVacantPosition(item, walls, { gap: 0, limit: 20 }), null);
});

test('a vacancy only on the search boundary is found, and extents may exceed limit', () => {
  const item = rect('new', 0, 0, 20, 30);
  const obstacles = [rect('wall', -100, -100, 110, 200)];
  const result = findVacantPosition(item, obstacles, { limit: 10, gap: 0 });
  assert.deepEqual(result, { x: 10, y: 0 });
  validPosition(item, obstacles, result, { limit: 10, gap: 0 });
  assert.ok(result.x + item.width > 10);
});

test('fractional geometry never accepts a gap smaller than requested', () => {
  assert.deepEqual(findVacantPosition(rect('new', 0, 0, 0.4, 10), [rect('existing', 0.7, 0)], { gap: 0.3 }), { x: 0, y: 0 });
  for (const direction of ['right', 'down', 'left', 'up']) {
    for (const [x, y, width, height, gap] of [
      [0.1, -0.3, 0.2, 0.7, 0.1], [-1.1, 2.7, 4.3, 0.6, 0.2],
      [100000.1, -100000.3, 0.1, 0.7, 0.3],
    ]) {
      const item = rect('new', x, y, width, height);
      const obstacles = [rect('existing', x, y, width, height)];
      const result = findVacantPosition(item, obstacles, { direction, gap, limit: 200000 });
      validPosition(item, obstacles, result, { gap, limit: 200000 });
    }
  }
});

test('deterministic output is independent of obstacle order and repeated calls', () => {
  const item = rect('new', -5, -5, 10, 10);
  const obstacles = [rect('a', -10, -10, 20, 20), rect('b', -100, 24, 200, 30), rect('c', 24, -100, 30, 200)];
  for (const direction of ['right', 'down', 'left', 'up']) {
    const expected = findVacantPosition(item, obstacles, { direction });
    for (let i = 0; i < obstacles.length; i += 1) {
      const reordered = [...obstacles.slice(i), ...obstacles.slice(0, i)].reverse();
      assert.deepEqual(findVacantPosition(item, reordered, { direction }), expected);
      assert.deepEqual(findVacantPosition(item, obstacles, { direction }), expected);
    }
  }
});

test('deeply frozen inputs and options remain untouched; returned positions do not alias', () => {
  const item = Object.freeze(rect('new'));
  const obstacles = Object.freeze([Object.freeze({ ...rect('a'), pinned: true }), Object.freeze(rect('b', 15, 12, 50, 30))]);
  const options = Object.freeze({ gap: 3, direction: 'down', limit: 100 });
  const before = JSON.stringify({ item, obstacles, options });
  const first = findVacantPosition(item, obstacles, options);
  const second = findVacantPosition(item, obstacles, options);
  assert.deepEqual(first, second);
  assert.notEqual(first, second);
  first.x = 12345;
  assert.notEqual(second.x, first.x);
  assert.equal(JSON.stringify({ item, obstacles, options }), before);
});

test('integer fixtures agree with an exhaustive closest-vacancy oracle', () => {
  const limit = 6;
  for (let seed = 0; seed < 100; seed += 1) {
    const item = rect('new', seed % 11 - 5, seed * 3 % 11 - 5, 1 + seed % 3, 1 + seed % 2);
    const gap = seed % 2;
    const obstacles = Array.from({ length: 1 + seed % 10 }, (_, i) => rect(i,
      (seed * 17 + i * 7) % 17 - 8, (seed * 13 + i * 11) % 17 - 8,
      1 + (seed + i * 3) % 8, 1 + (seed + i * 7) % 8));
    const result = findVacantPosition(item, obstacles, { gap, limit, direction: ['right', 'down', 'left', 'up'][seed % 4] });
    let distance = Infinity;
    for (let y = -limit; y <= limit; y += 1) {
      for (let x = -limit; x <= limit; x += 1) {
        if (clear(item, obstacles, { x, y }, gap)) distance = Math.min(distance, Math.hypot(x - item.x, y - item.y));
      }
    }
    if (distance === Infinity) assert.equal(result, null, `seed ${seed}`);
    else {
      validPosition(item, obstacles, result, { gap, limit });
      assert.equal(Math.hypot(result.x - item.x, result.y - item.y), distance, `seed ${seed}`);
    }
  }
});

test('1500 mixed-size obstacles: deterministic, collision-free, bounded runtime', (t) => {
  const obstacles = Array.from({ length: 1500 }, (_, i) => Object.freeze({
    ...rect(i, (i % 50) * 20 - 500, Math.floor(i / 50) * 25 - 375, 10 + i % 11, 12 + i % 15),
    pinned: i % 2 === 0,
  }));
  Object.freeze(obstacles);
  const item = Object.freeze(rect('new', -10, -10, 35, 45));
  const start = performance.now();
  const result = findVacantPosition(item, obstacles);
  validPosition(item, obstacles, result);
  assert.deepEqual(findVacantPosition(item, [...obstacles].reverse()), result);
  const elapsed = performance.now() - start;
  t.diagnostic(`1500 mixed-size obstacles, two searches: ${elapsed.toFixed(1)} ms`);
  assert.ok(elapsed < 2500, `Search took ${elapsed} ms`);
});

test('1500 overlapping stripes: bounded exhaustive search of a fully covered area', (t) => {
  const obstacles = Array.from({ length: 1500 }, (_, i) => rect(i, -1200, -1100 + i * 1.5, 2400, 3));
  const item = rect('new', 0, 0, 10, 10);
  const start = performance.now();
  assert.equal(findVacantPosition(item, obstacles, { gap: 1, limit: 1000 }), null);
  const elapsed = performance.now() - start;
  t.diagnostic(`1500 stripes, impossible area: ${elapsed.toFixed(1)} ms`);
  assert.ok(elapsed < 2500, `Search took ${elapsed} ms`);
});

test('explicit origin bounds override the square, stay immutable, and preserve clear origins', () => {
  const originBounds = Object.freeze({ minX: -100026, maxX: -99900, minY: 4, maxY: 11 });
  const options = Object.freeze({ originBounds, limit: 10, gap: 0 });
  const item = Object.freeze(rect('new', -100020, 8, 80, 40));
  assert.deepEqual(findVacantPosition(item, [], options), { x: -100020, y: 8 });
  assert.deepEqual(findVacantPosition(rect('new', 100000, -200000), [], options), { x: -99900, y: 4 });
  assert.deepEqual(originBounds, { minX: -100026, maxX: -99900, minY: 4, maxY: 11 });
});

test('explicit origin bounds find edge contacts on a single horizontal or vertical line', () => {
  const item = rect('new', 100000, -100026, 132, 200092);
  const obstacles = [rect('pin', 100000, 0, 80, 40)];
  const originBounds = { minX: -100026, maxX: 99974, minY: -100026, maxY: -100026 };
  const result = findVacantPosition(item, obstacles, { gap: 48, originBounds });
  assert.deepEqual(result, { x: 99820, y: -100026 });
  assert.ok(clear(item, obstacles, result, 48));
  const swap = (node) => rect(node.id, node.y, node.x, node.height, node.width);
  const vertical = findVacantPosition(swap(item), obstacles.map(swap), { gap: 48,
    originBounds: { minX: -100026, maxX: -100026, minY: -100026, maxY: 99974 } });
  assert.deepEqual(vertical, { x: -100026, y: 99820 });
  assert.ok(clear(swap(item), obstacles.map(swap), vertical, 48));
});

test('explicit single-point domains preserve contact but reject true obstruction', () => {
  const item = rect('new', 0, 0, 4, 6);
  const originBounds = { minX: 5, maxX: 5, minY: 7, maxY: 7 };
  assert.deepEqual(findVacantPosition(item, [], { originBounds }), { x: 5, y: 7 });
  assert.deepEqual(findVacantPosition(item, [rect('right', 11, 7)], { gap: 2, originBounds }), { x: 5, y: 7 });
  assert.equal(findVacantPosition(item, [rect('inside', 8, 7)], { gap: 2, originBounds }), null);
});

test('asymmetric bounded sweeps agree with an exhaustive nearest-vacancy oracle', () => {
  for (let seed = 0; seed < 100; seed += 1) {
    const originBounds = { minX: -8, maxX: -2 + seed % 5, minY: 2, maxY: 2 + seed % 7 };
    const item = rect('new', seed % 13 - 8, seed % 11, 1 + seed % 3, 1 + seed % 2);
    const gap = seed % 2;
    const obstacles = Array.from({ length: 1 + seed % 7 }, (_, i) => rect(i,
      (seed * 17 + i * 7) % 13 - 10, (seed * 13 + i * 11) % 11,
      1 + (seed + i) % 7, 1 + (seed + i * 3) % 5));
    const result = findVacantPosition(item, obstacles, { gap, originBounds });
    let distance = Infinity;
    for (let y = originBounds.minY; y <= originBounds.maxY; y += 1) {
      for (let x = originBounds.minX; x <= originBounds.maxX; x += 1) {
        if (clear(item, obstacles, { x, y }, gap)) distance = Math.min(distance, Math.hypot(x - item.x, y - item.y));
      }
    }
    if (distance === Infinity) assert.equal(result, null, `seed ${seed}`);
    else {
      assert.ok(result && clear(item, obstacles, result, gap), `seed ${seed}`);
      assert.ok(result.x >= originBounds.minX && result.x <= originBounds.maxX);
      assert.ok(result.y >= originBounds.minY && result.y <= originBounds.maxY);
      assert.equal(Math.hypot(result.x - item.x, result.y - item.y), distance, `seed ${seed}`);
    }
  }
});

test('invalid explicit origin bounds fail before any placement', () => {
  for (const originBounds of [[], 1, {}, { minX: 0, maxX: 1, minY: 0 },
    { minX: NaN, maxX: 1, minY: 0, maxY: 1 }, { minX: 0, maxX: Infinity, minY: 0, maxY: 1 }]) {
    assert.throws(() => findVacantPosition(rect('new'), [], { originBounds }), TypeError);
  }
  for (const originBounds of [
    { minX: 2, maxX: 1, minY: 0, maxY: 1 }, { minX: 0, maxX: 1, minY: 2, maxY: 1 },
    { minX: -Number.MAX_VALUE, maxX: Number.MAX_VALUE, minY: 0, maxY: 1 },
  ]) assert.throws(() => findVacantPosition(rect('new'), [], { originBounds }), RangeError);
});

test('invalid rectangle types, nonfinite fields, nonpositive sizes and IDs are rejected', () => {
  for (const invalid of [null, undefined, [], {}, rect(undefined), rect(NaN), rect({})]) {
    assert.throws(() => findVacantPosition(invalid, []), TypeError);
    assert.throws(() => findVacantPosition(rect('new'), [invalid]), TypeError);
  }
  for (const field of ['x', 'y', 'width', 'height']) {
    for (const value of [NaN, Infinity, -Infinity, '1', null, undefined]) {
      const invalid = { ...rect('same'), [field]: value };
      assert.throws(() => findVacantPosition(invalid, []), TypeError);
      assert.throws(() => findVacantPosition(rect('same'), [invalid]), TypeError);
    }
  }
  for (const field of ['width', 'height']) {
    for (const value of [0, -1]) {
      const invalid = { ...rect('same'), [field]: value };
      assert.throws(() => findVacantPosition(invalid, []), RangeError);
      assert.throws(() => findVacantPosition(rect('same'), [invalid]), RangeError);
    }
  }
  for (const obstacles of [null, {}, 'obstacles']) assert.throws(() => findVacantPosition(rect('new'), obstacles), TypeError);
});

test('invalid options and arithmetic overflow fail explicitly without nonfinite outputs', () => {
  for (const options of [null, [], 1]) assert.throws(() => findVacantPosition(rect('new'), [], options), TypeError);
  for (const options of [{ gap: -1 }, { limit: 0 }, { limit: -1 }, { direction: 'diagonal' }, { direction: null }]) {
    assert.throws(() => findVacantPosition(rect('new'), [], options), RangeError);
  }
  for (const field of ['gap', 'limit']) {
    for (const value of [Infinity, NaN, '2', null]) assert.throws(() => findVacantPosition(rect('new'), [], { [field]: value }), TypeError);
  }
  const huge = Number.MAX_VALUE;
  assert.throws(() => findVacantPosition(rect('new', huge, 0, huge), []), RangeError);
  assert.throws(() => findVacantPosition(rect('new'), [], { limit: huge }), RangeError);
  assert.throws(() => findVacantPosition(rect('new', 0, 0, huge), [rect('far', -huge, 0)]), RangeError);
  assert.throws(() => findVacantPosition(rect('new'), [rect('far', huge, 0, huge)]), RangeError);
});
