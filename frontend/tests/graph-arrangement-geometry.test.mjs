import test from 'node:test';
import assert from 'node:assert/strict';
import {
  rectangleBounds,
  alignRectangles,
  distributeRectangles,
  gridRectangles,
  snapTranslation,
} from '../public/graph-workspace/arrangement-geometry.mjs';

const rect = (id, x = 0, y = 0, width = 10, height = 10) => ({ id, x, y, width, height });
const positions = (rects) => new Map(rects.map(({ id, x, y }) => [id, { x, y }]));
const placed = (rects, result) => rects.map((item) => ({ ...item, ...result.get(item.id) }));
const translated = (rects, result) => rects.map((item) => ({ ...item, x: item.x + result.dx, y: item.y + result.dy }));
const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-9, `${actual} != ${expected}`);
const noOverlap = (rects) => {
  for (let i = 0; i < rects.length; i += 1) {
    for (let j = i + 1; j < rects.length; j += 1) {
      const a = rects[i];
      const b = rects[j];
      assert.ok(a.x + a.width <= b.x || b.x + b.width <= a.x
        || a.y + a.height <= b.y || b.y + b.height <= a.y, `${a.id} overlaps ${b.id}`);
    }
  }
};
const finiteResult = (value) => {
  if (typeof value === 'number') assert.ok(Number.isFinite(value));
  else if (value instanceof Map) [...value.values()].forEach(finiteResult);
  else if (value && typeof value === 'object') Object.values(value).forEach(finiteResult);
};

test('bounds: empty, singleton, negative coordinates, mixed sizes, zero-size', () => {
  assert.equal(rectangleBounds([]), null);
  assert.deepEqual(rectangleBounds([rect('a', -40, -20, 60, 30)]), { x: -40, y: -20, width: 60, height: 30 });
  assert.deepEqual(rectangleBounds([rect('a', -40, 10, 60, 30), rect('b', 10, -20, 50, 80)]), {
    x: -40, y: -20, width: 100, height: 80,
  });
  assert.deepEqual(rectangleBounds([rect('point', -5, 3, 0, 0)]), { x: -5, y: 3, width: 0, height: 0 });
});

const mixed = [rect('a', -40, -20, 20, 10), rect('b', 10, 40, 60, 30), rect('c', 100, 100, 10, 60)];
for (const [mode, axis, fraction] of [
  ['left', 'x', 0], ['center', 'x', 0.5], ['right', 'x', 1],
  ['top', 'y', 0], ['middle', 'y', 0.5], ['bottom', 'y', 1],
]) {
  test(`align ${mode}: selection bounds and fixed reference with mixed sizes`, () => {
    const size = axis === 'x' ? 'width' : 'height';
    const other = axis === 'x' ? 'y' : 'x';
    for (const referenceId of [null, 'b']) {
      const result = alignRectangles(mixed, mode, { referenceId });
      const reference = referenceId === null ? rectangleBounds(mixed) : mixed[1];
      for (const item of mixed) {
        close(result.get(item.id)[axis] + item[size] * fraction, reference[axis] + reference[size] * fraction);
        assert.equal(result.get(item.id)[other], item[other]);
      }
      assert.deepEqual([...result.keys()], ['a', 'b', 'c']);
      if (referenceId !== null) assert.deepEqual(result.get('b'), { x: 10, y: 40 });
    }
    assert.deepEqual(alignRectangles([], mode), new Map());
    assert.deepEqual(alignRectangles([mixed[0]], mode), positions([mixed[0]]));
  });
}

test('align: numeric ID including zero is a fixed reference', () => {
  const input = [rect(0, -10, -10, 20, 20), rect(1, 100, 100)];
  assert.deepEqual(alignRectangles(input, 'right', { referenceId: 0 }), new Map([
    [0, { x: -10, y: -10 }], [1, { x: 0, y: 100 }],
  ]));
});

for (const axis of ['x', 'y']) {
  test(`distribute ${axis}: equal edge gaps, fixed endpoints, mixed sizes`, () => {
    const input = axis === 'x'
      ? [rect('last', 200, 7, 20, 10), rect('first', -100, 17, 40, 10), rect('middle', 20, 27, 80, 10)]
      : [rect('last', 7, 200, 10, 20), rect('first', 17, -100, 10, 40), rect('middle', 27, 20, 10, 80)];
    const result = distributeRectangles(input, axis);
    assert.equal(result.get('first')[axis], -100);
    assert.equal(result.get('middle')[axis], 30);
    assert.equal(result.get('last')[axis], 200);
    const other = axis === 'x' ? 'y' : 'x';
    for (const item of input) assert.equal(result.get(item.id)[other], item[other]);
    assert.deepEqual([...result.keys()], ['last', 'first', 'middle']);
  });

  test(`distribute ${axis}: explicit gap, zero gap, two nodes, stable ties`, () => {
    const input = [rect('b', -20, -20, 30, 30), rect('a', -20, -20, 10, 10), rect('c', 5, 5, 20, 20)];
    const result = distributeRectangles(input, axis, { gap: 7 });
    assert.equal(result.get('b')[axis], -20);
    assert.equal(result.get('a')[axis], 17);
    assert.equal(result.get('c')[axis], 34);
    assert.equal(distributeRectangles(input.slice(0, 2), axis, { gap: 0 }).get('a')[axis], 10);
    assert.deepEqual(distributeRectangles(input.slice(0, 2), axis), positions(input.slice(0, 2)));
    assert.deepEqual(distributeRectangles([], axis), new Map());
    assert.deepEqual(distributeRectangles(input.slice(0, 1), axis), positions(input.slice(0, 1)));
  });

  test(`distribute ${axis}: refuses negative gaps but accepts exactly touching`, () => {
    const input = [rect('a', 0, 0, 20, 20), rect('b', 10, 10, 30, 30), rect('c', 40, 40, 10, 10)];
    assert.equal(distributeRectangles(input, axis), null);
    input[2][axis] = 50;
    assert.equal(distributeRectangles(input, axis).get('b')[axis], 20);
    noOverlap(placed(input, distributeRectangles(input, axis)));
  });
}

test('distribution preserves fractional endpoint exactly', () => {
  const input = Array.from({ length: 9 }, (_, i) => rect(i, i === 8 ? 103.1 : i * 5, 0, 0.1, 10));
  const result = distributeRectangles(input, 'x');
  assert.equal(result.get(8).x, 103.1);
  const output = placed(input, result);
  const gap = output[1].x - output[0].x - output[0].width;
  output.slice(1).forEach((item, i) => close(item.x - output[i].x - output[i].width, gap));
});

test('grid: mixed dimensions, overall top-left, global column/row sizes and spatial order', () => {
  const input = [rect('d', -100, 30, 40, 25), rect('b', 50, -20, 80, 10), rect('a', 0, -20, 20, 30), rect('c', -100, 30, 60, 50)];
  const result = gridRectangles(input, { columns: 2, gapX: 7, gapY: 11 });
  assert.deepEqual(result, new Map([
    ['d', { x: -100, y: 21 }], ['b', { x: -53, y: -20 }],
    ['a', { x: -100, y: -20 }], ['c', { x: -53, y: 21 }],
  ]));
  noOverlap(placed(input, result));
  assert.deepEqual([...result.keys()], input.map((item) => item.id));
});

test('grid: auto columns, incomplete rows, one row/column, zero gaps, zero/one item', () => {
  const input = Array.from({ length: 7 }, (_, i) => rect(i, -30 + i * 3, -40 + i * 4, 10 + i * 9, 15 + i * 7));
  const auto = gridRectangles(input);
  assert.equal(new Set([...auto.values()].map((point) => point.x)).size, 3);
  assert.equal(new Set([...auto.values()].map((point) => point.y)).size, 3);
  for (const columns of [0, 1, 2, 3, 7, 100]) {
    const result = gridRectangles(input, { columns, gapX: 0, gapY: 0 });
    noOverlap(placed(input, result));
    const bounds = rectangleBounds(placed(input, result));
    assert.equal(bounds.x, -30);
    assert.equal(bounds.y, -40);
    if (columns === 1) assert.equal(new Set([...result.values()].map((point) => point.x)).size, 1);
    if (columns >= 7) assert.equal(new Set([...result.values()].map((point) => point.y)).size, 1);
  }
  assert.deepEqual(gridRectangles([]), new Map());
  assert.deepEqual(gridRectangles([mixed[0]]), positions([mixed[0]]));
});

for (const scale of [0.25, 1, 2]) {
  test(`snap: screen-pixel tolerance at scale ${scale}, inclusive boundary and outside`, () => {
    const moving = [rect('m', 0, 0, 100, 100)];
    const tolerance = 6 / scale;
    const stationary = [rect('s', 300, 400, 100, 100)];
    const result = snapTranslation(moving, stationary, { x: 200 - tolerance, y: 0 }, { scale, axis: 'x' });
    close(result.dx, 200);
    assert.equal(result.snappedX, true);
    assert.equal(result.snappedY, false);
    assert.deepEqual(result.guides, [{ axis: 'x', type: 'alignment', position: 300, from: 0, to: 500 }]);
    const outside = snapTranslation(moving, stationary, { x: 200 - tolerance - 0.01, y: 0 }, { scale, axis: 'x' });
    close(outside.dx, 200 - tolerance - 0.01);
    assert.equal(outside.snappedX, false);
    assert.deepEqual(outside.guides, []);
  });
}

test('snap: nearest edges/centers across any moving member, rigid selection offsets', () => {
  const moving = [rect('first', -100, -60, 20, 10), rect('second', 30, 45, 40, 20)];
  const stationary = [rect('s', 100, 200, 10, 10)];
  const result = snapTranslation(moving, stationary, { x: 29, y: 0 }, { axis: 'x' });
  assert.equal(result.dx, 30);
  assert.equal(result.snappedX, true);
  const output = translated(moving, result);
  assert.equal(output[1].x - output[0].x, 130);
  assert.equal(output[1].y - output[0].y, 105);
  assert.equal(result.guides[0].from, 45);
  assert.equal(result.guides[0].to, 210);
});

test('snap: center-to-center alignment and guide extents reflect both final axes', () => {
  const result = snapTranslation([rect('m', 0, 0, 20, 20)], [rect('s', 100, 100, 40, 40)], { x: 109, y: 108 });
  assert.equal(result.dx, 110);
  assert.equal(result.dy, 110);
  assert.equal(result.snappedX, true);
  assert.equal(result.snappedY, true);
  assert.deepEqual(result.guides, [
    { axis: 'x', type: 'alignment', position: 120, from: 100, to: 140 },
    { axis: 'y', type: 'alignment', position: 120, from: 100, to: 140 },
  ]);
});

test('snap: every edge/center pairing is eligible on both axes', () => {
  for (const axis of ['x', 'y']) {
    for (const from of [0, 15, 30]) {
      for (const target of [100, 125, 150]) {
        const delta = { x: 0, y: 0, [axis]: target - from - 1 };
        const result = snapTranslation([rect('m', 0, 0, 30, 30)], [rect('s', 100, 100, 50, 50)], delta, { axis, tolerance: 1 });
        assert.equal(result[axis === 'x' ? 'dx' : 'dy'], target - from);
        assert.equal(result.guides[0].position, target);
      }
    }
  }
});

test('snap: equal-distance ties use original stationary order, then moving and anchor order', () => {
  const moving = [rect('m', 10, 0, 0, 0)];
  const stationary = [rect('left', 8, 100, 0, 0), rect('right', 12, 100, 0, 0)];
  assert.equal(snapTranslation(moving, stationary, { x: 0, y: 0 }, { axis: 'x' }).dx, -2);
  assert.equal(snapTranslation(moving, stationary.toReversed(), { x: 0, y: 0 }, { axis: 'x' }).dx, 2);
  const members = [rect('first', 8, 0, 0, 0), rect('second', 12, 0, 0, 0)];
  assert.equal(snapTranslation(members, [rect('s', 10, 100, 0, 0)], { x: 0, y: 0 }, { axis: 'x' }).dx, 2);
  const anchorTie = snapTranslation([rect('m', 0, 0, 10, 10)], [rect('s', 2.5, 100, 0, 0)], { x: 0, y: 0 }, { axis: 'x' });
  assert.equal(anchorTie.dx, 2.5);
});

test('snap: axis locks suppress both motion and snapping on the locked axis', () => {
  const moving = [rect('m')];
  const stationary = [rect('s', 100, 100)];
  const x = snapTranslation(moving, stationary, { x: 89, y: 89 }, { axis: 'x', snapToGrid: true });
  assert.equal(x.dx, 90);
  assert.equal(x.dy, 0);
  assert.equal(x.snappedY, false);
  assert.ok(x.guides.every((guide) => guide.axis === 'x'));
  const y = snapTranslation(moving, stationary, { x: 89, y: 89 }, { axis: 'y', snapToGrid: true });
  assert.equal(y.dx, 0);
  assert.equal(y.dy, 90);
  assert.equal(y.snappedX, false);
  assert.ok(y.guides.every((guide) => guide.axis === 'y'));
});

test('snap: grid rounds selection origin only, preserves offsets, supports negatives', () => {
  const moving = [rect('a', -37, -13), rect('b', -12, 26)];
  const result = snapTranslation(moving, [], { x: 0, y: 0 }, { snapToGrid: true, tolerance: 0 });
  assert.deepEqual(result, { dx: -3, dy: -7, snappedX: true, snappedY: true, guides: [] });
  const output = translated(moving, result);
  assert.equal(output[1].x - output[0].x, 25);
  assert.equal(output[1].y - output[0].y, 39);
  const offset = snapTranslation(moving, [], { x: 9, y: 11 }, { snapToGrid: true, gridSize: 10 });
  assert.equal(offset.dx, 7);
  assert.equal(offset.dy, 13);
});

test('snap: objects beat a closer grid line; grid fallback is independent per axis', () => {
  const result = snapTranslation([rect('m', 0, 0, 0, 0)], [rect('s', 25, 400, 0, 0)], { x: 20, y: 31 }, { snapToGrid: true });
  assert.equal(result.dx, 25);
  assert.equal(result.dy, 40);
  assert.equal(result.guides.length, 1);
  assert.equal(result.guides[0].axis, 'x');
});

test('snap: disabled snapping, empty selections, stationary IDs in moving, zero tolerance', () => {
  const moving = [rect('same')];
  const delta = { x: 2, y: 3 };
  const expected = { dx: 2, dy: 3, guides: [], snappedX: false, snappedY: false };
  assert.deepEqual(snapTranslation(moving, [rect('s', 1, 1)], delta, { snapToObjects: false }), expected);
  assert.deepEqual(snapTranslation(moving, [rect('same', 1, 1)], delta), expected);
  assert.deepEqual(snapTranslation(moving, [], delta), expected);
  assert.deepEqual(snapTranslation([], [], delta, { snapToGrid: true }), expected);
  assert.deepEqual(snapTranslation([], [], delta, { axis: 'x' }), { ...expected, dy: 0 });
  const exact = snapTranslation(moving, [rect('s', 20, 100)], { x: 10, y: 0 }, { axis: 'x', tolerance: 0 });
  assert.equal(exact.snappedX, true);
  assert.equal(exact.dx, 10);
  assert.equal(snapTranslation(moving, [rect('s', 20, 100)], { x: 9.99, y: 0 }, { axis: 'x', tolerance: 0 }).snappedX, false);
});

for (const axis of ['x', 'y']) {
  test(`snap ${axis}: equal gaps between/before/after mixed-size neighbors`, () => {
    const swap = (item) => axis === 'x' ? item : rect(item.id, item.y, item.x, item.height, item.width);
    const stationary = [rect('first', 0, 0, 20, 30), rect('second', 100, 5, 40, 20)].map(swap);
    for (const [start, target, label] of [[49, 50, 30], [-101, -100, 80], [219, 220, 80]]) {
      const moving = [swap(rect('moving', start, 8, 20, 10))];
      const result = snapTranslation(moving, stationary, { x: 0, y: 0 }, { axis, tolerance: 2 });
      assert.equal(result[axis === 'x' ? 'dx' : 'dy'], target - start);
      assert.equal(result[axis === 'x' ? 'snappedX' : 'snappedY'], true);
      assert.equal(result.guides.length, 2);
      assert.ok(result.guides.every((guide) => guide.type === 'gap' && guide.axis === axis));
      result.guides.forEach((guide) => {
        close(guide.label, label);
        assert.equal(guide.from, 8);
        assert.equal(guide.to, 18);
      });
      noOverlap([...translated(moving, result), ...stationary]);
    }
  });
}

test('snap: gap ties favor alignment; closer gap can win', () => {
  const moving = [rect('m', 49, 8, 20, 10)];
  const neighbors = [rect('a', 0, 0, 20, 30), rect('b', 100, 5, 40, 20)];
  const tie = snapTranslation(moving, [...neighbors, rect('s', 48, 100, 0, 0)], { x: 0, y: 0 }, { axis: 'x', tolerance: 2 });
  assert.equal(tie.dx, -1);
  assert.equal(tie.guides[0].type, 'alignment');
  const nearer = snapTranslation(moving, [...neighbors, rect('s', 47, 100, 0, 0)], { x: 0, y: 0 }, { axis: 'x', tolerance: 2 });
  assert.equal(nearer.dx, 1);
  assert.equal(nearer.guides[0].type, 'gap');
});

test('snap: gap requires neighbors in a common strip and enough room, with no blockers', () => {
  const moving = [rect('m', 49, 8, 20, 10)];
  const first = rect('a', 0, 0, 20, 30);
  const second = rect('b', 100, 5, 40, 20);
  for (const stationary of [
    [first, { ...second, y: 50 }],
    [first, second, rect('blocker', 52, 8, 15, 10)],
    [rect('a', 0, 0, 110, 30), second],
  ]) {
    const result = snapTranslation(moving, stationary, { x: 0, y: 0 }, { axis: 'x', tolerance: 1 });
    assert.ok(result.guides.every((guide) => guide.type !== 'gap'));
  }
  const insufficient = snapTranslation([rect('m', 19, 8, 100, 10)], [first, second], { x: 0, y: 0 }, { axis: 'x', tolerance: 1 });
  assert.ok(insufficient.guides.every((guide) => guide.type !== 'gap'));
});

test('snap: equal-gap candidate is rechecked after perpendicular object snapping', () => {
  const moving = [rect('m', 49, 19, 20, 4)];
  const neighbors = [rect('a', 0, 0, 20, 20), rect('b', 100, 0, 40, 20)];
  const result = snapTranslation(moving, neighbors, { x: 0, y: 0 }, { tolerance: 2 });
  assert.equal(result.dy, 1);
  assert.equal(result.dx, 0);
  assert.equal(result.snappedX, false);
  assert.ok(result.guides.every((guide) => guide.type !== 'gap'));
});

test('snap: perpendicular grid fallback can invalidate an object gap snap', () => {
  const moving = [rect('m', 49, 30, 20, 2)];
  const neighbors = [rect('a', 0, 25, 20, 40), rect('b', 100, 25, 40, 40)];
  const result = snapTranslation(moving, neighbors, { x: 0, y: 0 }, { tolerance: 2, snapToGrid: true, gridSize: 100 });
  assert.deepEqual(result, { dx: -49, dy: -30, snappedX: true, snappedY: true, guides: [] });
});

test('snap: equal-gap translation preserves a multi-member selection', () => {
  const moving = [rect('a', 49, 8, 20, 10), rect('b', -200, 100, 35, 25)];
  const stationary = [rect('left', 0, 0, 20, 30), rect('right', 100, 5, 40, 20)];
  const result = snapTranslation(moving, stationary, { x: 0, y: 0 }, { axis: 'x', tolerance: 2 });
  assert.equal(result.dx, 1);
  const output = translated(moving, result);
  assert.equal(output[0].x - output[1].x, 249);
  assert.equal(output[0].y - output[1].y, -92);
});

test('all helpers leave deeply frozen inputs/options unchanged and return fresh positions', () => {
  const input = Object.freeze(mixed.map((item) => Object.freeze({ ...item })));
  const stationary = Object.freeze([Object.freeze(rect('stationary', 400, 400))]);
  const before = JSON.stringify(input);
  rectangleBounds(input);
  for (const result of [
    alignRectangles(input, 'center', Object.freeze({ referenceId: 'b' })),
    distributeRectangles(input, 'x', Object.freeze({ gap: 12 })),
    gridRectangles(input, Object.freeze({ columns: 2 })),
  ]) {
    result.get('a').x = 999;
    assert.notEqual(input[0].x, 999);
  }
  snapTranslation(input, stationary, Object.freeze({ x: 2, y: 3 }), Object.freeze({ snapToGrid: true }));
  assert.equal(JSON.stringify(input), before);
});

test('invalid rectangle types, missing IDs, duplicates, negative sizes and nonfinite input fail consistently', () => {
  const consumers = [
    (input) => rectangleBounds(input),
    (input) => alignRectangles(input, 'left'),
    (input) => distributeRectangles(input, 'x'),
    (input) => gridRectangles(input),
    (input) => snapTranslation(input, [], { x: 0, y: 0 }),
    (input) => snapTranslation([], input, { x: 0, y: 0 }),
  ];
  for (const consume of consumers) {
    for (const input of [null, {}, [null], [undefined], [rect(undefined)], [rect(NaN)], [rect({})]]) {
      assert.throws(() => consume(input), TypeError);
    }
    for (const field of ['x', 'y', 'width', 'height']) {
      for (const value of [NaN, Infinity, -Infinity, '10', undefined]) {
        assert.throws(() => consume([{ ...rect('a'), [field]: value }]), TypeError);
      }
    }
    assert.throws(() => consume([rect('a', 0, 0, -1)]), RangeError);
    assert.throws(() => consume([rect('a', 0, 0, 1, -1)]), RangeError);
    assert.throws(() => consume([rect('a'), rect('a')]), RangeError);
    assert.throws(() => consume([rect('a', Number.MAX_VALUE, 0, Number.MAX_VALUE)]), RangeError);
  }
});

test('invalid modes, axes, references, options and snap domains are rejected', () => {
  assert.throws(() => alignRectangles(mixed, 'diagonal'), RangeError);
  assert.throws(() => alignRectangles(mixed, 'constructor'), RangeError);
  assert.throws(() => alignRectangles(mixed, 'left', { referenceId: 'missing' }), RangeError);
  assert.throws(() => distributeRectangles(mixed, 'z'), RangeError);
  for (const gap of [-1, Infinity, NaN, '2']) assert.throws(() => distributeRectangles(mixed, 'x', { gap }));
  for (const columns of [-1, 1.5, Infinity, NaN, '2', Number.MAX_SAFE_INTEGER + 1]) {
    assert.throws(() => gridRectangles(mixed, { columns }));
  }
  for (const options of [{ gapX: -1 }, { gapY: NaN }, { gapX: '2' }]) assert.throws(() => gridRectangles(mixed, options));
  for (const options of [
    { scale: 0 }, { scale: -1 }, { scale: Infinity }, { tolerance: -1 }, { tolerance: NaN },
    { gridSize: 0 }, { gridSize: -1 }, { gridSize: Infinity }, { axis: 'z' },
    { snapToObjects: 1 }, { snapToGrid: null },
  ]) assert.throws(() => snapTranslation(mixed, [], { x: 0, y: 0 }, options));
  for (const delta of [null, {}, { x: NaN, y: 0 }, { x: 0, y: Infinity }, { x: '0', y: 0 }]) {
    assert.throws(() => snapTranslation([], [], delta), TypeError);
  }
  for (const options of [null, [], 3]) {
    assert.throws(() => alignRectangles([], 'left', options), TypeError);
    assert.throws(() => distributeRectangles([], 'x', options), TypeError);
    assert.throws(() => gridRectangles([], options), TypeError);
    assert.throws(() => snapTranslation([], [], { x: 0, y: 0 }, options), TypeError);
  }
});

test('overflow cannot leak NaN/Infinity into geometry, shifts or guides', () => {
  const huge = Number.MAX_VALUE;
  assert.throws(() => rectangleBounds([rect('a', -huge, 0, 0), rect('b', huge, 0, 0)]), RangeError);
  assert.throws(() => gridRectangles([rect('a', 0, 0, huge), rect('b', 0, 0, huge)], { columns: 2 }), RangeError);
  assert.throws(() => distributeRectangles([rect('a', huge, 0, 0), rect('b', huge, 0, 0)], 'x', { gap: huge }), RangeError);
  assert.throws(() => snapTranslation([rect('a', huge, 0, 0)], [], { x: huge, y: 0 }), RangeError);
  assert.throws(() => snapTranslation([], [], { x: 0, y: 0 }, { scale: Number.MIN_VALUE }), RangeError);
  assert.throws(() => snapTranslation([rect('a', huge, 0, 0)], [], { x: 0, y: 0 }, { gridSize: Number.MIN_VALUE, snapToGrid: true }), RangeError);
  finiteResult(snapTranslation([rect('a', -huge, 0, 0)], [rect('b', huge, 100, 0)], { x: 0, y: 0 }));
});

test('deterministic mixed-size sweep: grids never overlap and all returned numbers are finite', () => {
  for (let count = 2; count <= 35; count += 1) {
    const input = Array.from({ length: count }, (_, i) => rect(i, (i * 37 % 113) - 80, (i * 29 % 97) - 70, 1 + i * 17 % 73, 1 + i * 13 % 61));
    for (const columns of [0, 1, 2, 5, count]) {
      const result = gridRectangles(input, { columns, gapX: 7, gapY: 11 });
      noOverlap(placed(input, result));
      finiteResult(result);
    }
    for (const mode of Object.keys({ left: 1, center: 1, right: 1, top: 1, middle: 1, bottom: 1 })) {
      finiteResult(alignRectangles(input, mode));
    }
    finiteResult(distributeRectangles(input, 'x', { gap: 3 }));
    finiteResult(distributeRectangles(input, 'y', { gap: 3 }));
    finiteResult(snapTranslation(input.slice(0, 2), input.slice(2), { x: -4, y: 7 }, { snapToGrid: true }));
  }
});
