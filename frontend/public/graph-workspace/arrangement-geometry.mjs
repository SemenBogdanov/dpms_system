/**
 * Pure graph arrangement helpers. Rectangles have unique string/finite-number IDs,
 * finite coordinates and nonnegative finite dimensions (zero-size is supported).
 * Inputs are never mutated. Invalid shapes/types/nonfinite numbers throw TypeError;
 * invalid domains/options, unknown references and arithmetic overflow throw RangeError.
 * Returned Maps retain input order. Hidden/pinned nodes and rigid groups are caller-owned.
 */
const DIMENSIONS = {
  x: { size: 'width', other: 'y', otherSize: 'height' },
  y: { size: 'height', other: 'x', otherSize: 'width' },
};
const ALIGNMENTS = {
  left: ['x', 0], center: ['x', 0.5], right: ['x', 1],
  top: ['y', 0], middle: ['y', 0.5], bottom: ['y', 1],
};

function finite(value, name) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new TypeError(`${name} must be a finite number`);
  }
  return value;
}

function checked(value) {
  if (!Number.isFinite(value)) throw new RangeError('Geometry arithmetic overflow');
  return value === 0 ? 0 : value;
}

function nonnegative(value, name) {
  finite(value, name);
  if (value < 0) throw new RangeError(`${name} must be nonnegative`);
  return value;
}

function positive(value, name) {
  finite(value, name);
  if (value <= 0) throw new RangeError(`${name} must be positive`);
  return value;
}

function record(value, name) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
}

function validateRectangles(rects) {
  if (!Array.isArray(rects)) throw new TypeError('rects must be an array');
  const ids = new Set();
  for (const rect of rects) {
    record(rect, 'rectangle');
    if (typeof rect.id !== 'string' && !(typeof rect.id === 'number' && Number.isFinite(rect.id))) {
      throw new TypeError('Rectangle ID must be a string or finite number');
    }
    if (ids.has(rect.id)) throw new RangeError('Rectangle IDs must be unique');
    ids.add(rect.id);
    finite(rect.x, 'x');
    finite(rect.y, 'y');
    nonnegative(rect.width, 'width');
    nonnegative(rect.height, 'height');
    checked(rect.x + rect.width);
    checked(rect.y + rect.height);
  }
}

function boundsOf(rects) {
  if (!rects.length) return null;
  let x = Infinity;
  let y = Infinity;
  let right = -Infinity;
  let bottom = -Infinity;
  for (const rect of rects) {
    x = Math.min(x, rect.x);
    y = Math.min(y, rect.y);
    right = Math.max(right, rect.x + rect.width);
    bottom = Math.max(bottom, rect.y + rect.height);
  }
  return { x, y, width: checked(right - x), height: checked(bottom - y) };
}

function positionsOf(rects) {
  return new Map(rects.map(({ id, x, y }) => [id, { x, y }]));
}

function finishPositions(rects, positions) {
  for (const rect of rects) {
    const point = positions.get(rect.id);
    checked(point.x);
    checked(point.y);
    checked(point.x + rect.width);
    checked(point.y + rect.height);
  }
  return positions;
}

function validateAxis(axis) {
  if (axis !== 'x' && axis !== 'y') throw new RangeError('axis must be x or y');
}

function spatialOrder(rects, axis, secondary = null) {
  return rects.map((rect, index) => ({ rect, index })).sort((a, b) =>
    a.rect[axis] - b.rect[axis]
    || (secondary ? a.rect[secondary] - b.rect[secondary] : 0)
    || a.index - b.index).map(({ rect }) => rect);
}

export function rectangleBounds(rects) {
  validateRectangles(rects);
  return boundsOf(rects);
}

/** A reference must belong to rects; it remains at its original position. */
export function alignRectangles(rects, mode, options = {}) {
  validateRectangles(rects);
  record(options, 'options');
  if (!Object.hasOwn(ALIGNMENTS, mode)) throw new RangeError('Unknown alignment mode');
  const { referenceId = null } = options;
  const reference = referenceId === null ? boundsOf(rects) : rects.find((rect) => rect.id === referenceId);
  if (referenceId !== null && !reference) throw new RangeError('Unknown referenceId');
  const positions = positionsOf(rects);
  if (!reference || rects.length < 2) return positions;
  const [axis, fraction] = ALIGNMENTS[mode];
  const { size } = DIMENSIONS[axis];
  const target = checked(reference[axis] + reference[size] * fraction);
  for (const rect of rects) {
    if (rect.id !== referenceId) positions.get(rect.id)[axis] = checked(target - rect[size] * fraction);
  }
  return finishPositions(rects, positions);
}

/**
 * Default: keep the first/last origins in stable axis order and equalize edge gaps.
 * Fewer than three rectangles is a no-op; insufficient space returns null.
 * An explicit nonnegative gap works with two rectangles and fixes only the first.
 */
export function distributeRectangles(rects, axis, options = {}) {
  validateRectangles(rects);
  validateAxis(axis);
  record(options, 'options');
  const { gap = null } = options;
  if (gap !== null) nonnegative(gap, 'gap');
  const positions = positionsOf(rects);
  if (rects.length < (gap === null ? 3 : 2)) return positions;
  const sorted = spatialOrder(rects, axis);
  const { size } = DIMENSIONS[axis];
  let spacing = gap;
  if (spacing === null) {
    const occupied = sorted.slice(0, -1).reduce((sum, rect) => checked(sum + rect[size]), 0);
    spacing = checked(checked(sorted.at(-1)[axis] - sorted[0][axis]) - occupied) / (sorted.length - 1);
    if (spacing < 0) return null;
  }
  let cursor = sorted[0][axis];
  for (let index = 1; index < sorted.length; index += 1) {
    cursor = checked(checked(cursor + sorted[index - 1][size]) + spacing);
    positions.get(sorted[index].id)[axis] = gap === null && index === sorted.length - 1
      ? sorted[index][axis] : cursor;
  }
  return finishPositions(rects, positions);
}

/**
 * Row-major order is y, then x, then original index. Auto columns = ceil(sqrt(n)).
 * Column widths/row heights use their largest item; every item is top-left aligned.
 * columns: 1 gives one column; columns >= n gives one row.
 */
export function gridRectangles(rects, options = {}) {
  validateRectangles(rects);
  record(options, 'options');
  const { columns = 0, gapX = 32, gapY = 32 } = options;
  nonnegative(columns, 'columns');
  if (!Number.isSafeInteger(columns)) throw new RangeError('columns must be a safe integer');
  nonnegative(gapX, 'gapX');
  nonnegative(gapY, 'gapY');
  const positions = positionsOf(rects);
  if (rects.length < 2) return positions;
  const bounds = boundsOf(rects);
  const sorted = spatialOrder(rects, 'y', 'x');
  const count = Math.min(columns || Math.ceil(Math.sqrt(rects.length)), rects.length);
  const widths = Array(count).fill(0);
  const heights = Array(Math.ceil(rects.length / count)).fill(0);
  sorted.forEach((rect, index) => {
    widths[index % count] = Math.max(widths[index % count], rect.width);
    heights[Math.floor(index / count)] = Math.max(heights[Math.floor(index / count)], rect.height);
  });
  const offsets = (sizes, origin, gap) => {
    const result = [origin];
    for (let index = 1; index < sizes.length; index += 1) {
      result.push(checked(checked(result[index - 1] + sizes[index - 1]) + gap));
    }
    return result;
  };
  const xs = offsets(widths, bounds.x, gapX);
  const ys = offsets(heights, bounds.y, gapY);
  sorted.forEach((rect, index) => positions.set(rect.id, { x: xs[index % count], y: ys[Math.floor(index / count)] }));
  return finishPositions(rects, positions);
}

function translated(rect, dx, dy) {
  const x = checked(rect.x + dx);
  const y = checked(rect.y + dy);
  checked(x + rect.width);
  checked(y + rect.height);
  return { ...rect, x, y };
}

function anchors(rect, axis) {
  const size = rect[DIMENSIONS[axis].size];
  return [rect[axis], checked(rect[axis] + size / 2), checked(rect[axis] + size)];
}

function overlaps(a, b) {
  return a.x < b.x + b.width && b.x < a.x + a.width
    && a.y < b.y + b.height && b.y < a.y + a.height;
}

function commonStrip(rects, axis) {
  const { other, otherSize } = DIMENSIONS[axis];
  const from = Math.max(...rects.map((rect) => rect[other]));
  const to = Math.min(...rects.map((rect) => rect[other] + rect[otherSize]));
  return { from, to };
}

function gapIsValid(candidate, rect, stationary, axis) {
  const strip = commonStrip([rect, ...candidate.neighbors], axis);
  return strip.to > strip.from && !stationary.some((other) => overlaps(rect, other));
}

function nearest(current, candidate, threshold) {
  const distance = Math.abs(candidate.correction);
  // Iteration order breaks exact ties; alignment candidates are considered first.
  return Number.isFinite(distance) && distance <= threshold
    && (!current || distance < Math.abs(current.correction)) ? candidate : current;
}

function candidatesFor(moving, stationary, axis, threshold) {
  let alignment = null;
  moving.forEach((rect, movingIndex) => {
    for (const other of stationary) {
      for (const origin of anchors(rect, axis)) {
        for (const target of anchors(other, axis)) {
          alignment = nearest(alignment, {
            type: 'alignment', correction: target - origin, movingIndex, other, target,
          }, threshold);
        }
      }
    }
  });
  let best = alignment;
  const { size } = DIMENSIONS[axis];
  moving.forEach((rect, movingIndex) => {
    const neighbors = spatialOrder(stationary.filter((item) => {
      const strip = commonStrip([rect, item], axis);
      return strip.to > strip.from;
    }), axis);
    for (let index = 1; index < neighbors.length; index += 1) {
      const first = neighbors[index - 1];
      const second = neighbors[index];
      const gap = second[axis] - (first[axis] + first[size]);
      if (!Number.isFinite(gap) || gap < 0) continue;
      const targets = [];
      if (gap >= rect[size]) targets.push(first[axis] + first[size] + (gap - rect[size]) / 2);
      targets.push(first[axis] - gap - rect[size], second[axis] + second[size] + gap);
      for (const target of targets) {
        const candidate = { type: 'gap', correction: target - rect[axis], movingIndex, neighbors: [first, second] };
        const next = nearest(best, candidate, threshold);
        if (next === best) continue;
        if (!Number.isFinite(target) || !Number.isFinite(target + rect[size])) continue;
        const proposed = { ...rect, [axis]: target };
        if (gapIsValid(candidate, proposed, stationary, axis)) best = candidate;
      }
    }
  });
  return { best, alignment };
}

function guidesFor(candidate, moving, axis) {
  if (!candidate) return [];
  const rect = moving[candidate.movingIndex];
  const { size, other, otherSize } = DIMENSIONS[axis];
  if (candidate.type === 'alignment') {
    return [{
      axis, type: 'alignment', position: candidate.target,
      from: Math.min(rect[other], candidate.other[other]),
      to: Math.max(rect[other] + rect[otherSize], candidate.other[other] + candidate.other[otherSize]),
    }];
  }
  const triplet = spatialOrder([rect, ...candidate.neighbors], axis);
  const { from, to } = commonStrip(triplet, axis);
  return triplet.slice(1).map((item, index) => {
    const end = checked(triplet[index][axis] + triplet[index][size]);
    const label = checked(item[axis] - end);
    return { axis, type: 'gap', position: checked(end + label / 2), from, to, label };
  });
}

/**
 * Object tolerance is in screen pixels (divided by scale); axes snap independently.
 * Exact ties: alignment before equal-gap, then original moving/stationary order,
 * then start/center/end anchors. Gap ties use spatial neighbor order, then between,
 * before, after. Equal-gap snapping requires a shared perpendicular interior strip
 * and a collision-free moving rectangle; it uses consecutive stationary neighbors.
 * Gap guides sit at gap midpoints, span that common strip, and label world distances.
 * Grid fallback rounds only the translated selection origin, is not tolerance-gated,
 * and has no guides. Object snapping wins per axis. Locked axes never snap.
 * Empty moving selections return the axis-constrained delta without snapping.
 */
export function snapTranslation(movingRects, stationaryRects, delta, options = {}) {
  validateRectangles(movingRects);
  validateRectangles(stationaryRects);
  record(delta, 'delta');
  finite(delta.x, 'delta.x');
  finite(delta.y, 'delta.y');
  record(options, 'options');
  const {
    scale = 1, tolerance = 6, snapToObjects = true, snapToGrid = false,
    gridSize = 20, axis = null,
  } = options;
  positive(scale, 'scale');
  nonnegative(tolerance, 'tolerance');
  positive(gridSize, 'gridSize');
  if (typeof snapToObjects !== 'boolean' || typeof snapToGrid !== 'boolean') {
    throw new TypeError('Snap flags must be boolean');
  }
  if (axis !== null) validateAxis(axis);
  const threshold = checked(tolerance / scale);
  const initial = { x: axis === 'y' ? 0 : checked(delta.x), y: axis === 'x' ? 0 : checked(delta.y) };
  const result = { dx: initial.x, dy: initial.y, guides: [], snappedX: false, snappedY: false };
  if (!movingRects.length) return result;
  const movingIds = new Set(movingRects.map((rect) => rect.id));
  const stationary = stationaryRects.filter((rect) => !movingIds.has(rect.id));
  const moved = movingRects.map((rect) => translated(rect, initial.x, initial.y));
  const origin = snapToGrid ? boundsOf(moved) : null;
  const activeAxes = axis === null ? ['x', 'y'] : [axis];
  const choices = {};
  const fallbacks = {};
  const shifts = { ...initial };
  for (const current of activeAxes) {
    const candidates = snapToObjects ? candidatesFor(moved, stationary, current, threshold) : {};
    choices[current] = candidates.best ?? null;
    fallbacks[current] = candidates.alignment ?? null;
  }
  const updateShift = (current) => {
    const choice = choices[current];
    shifts[current] = choice ? checked(initial[current] + choice.correction) : initial[current];
    if (!choice && snapToGrid) {
      const target = checked(Math.round(origin[current] / gridSize) * gridSize);
      shifts[current] = checked(initial[current] + checked(target - origin[current]));
    }
  };
  activeAxes.forEach(updateShift);
  // A perpendicular snap can invalidate a gap's shared strip or introduce a collision.
  // Each axis can fall back only once, so this loop performs at most two fallbacks.
  let changed;
  do {
    changed = false;
    for (const current of activeAxes) {
      const choice = choices[current];
      if (choice?.type !== 'gap') continue;
      const finalRects = movingRects.map((rect) => translated(rect, shifts.x, shifts.y));
      if (!gapIsValid(choice, finalRects[choice.movingIndex], stationary, current)) {
        choices[current] = fallbacks[current];
        updateShift(current);
        changed = true;
      }
    }
  } while (changed);
  const finalRects = movingRects.map((rect) => translated(rect, shifts.x, shifts.y));
  result.dx = shifts.x;
  result.dy = shifts.y;
  for (const current of activeAxes) {
    result[current === 'x' ? 'snappedX' : 'snappedY'] = Boolean(choices[current]) || snapToGrid;
    result.guides.push(...guidesFor(choices[current], finalRects, current));
  }
  return result;
}
