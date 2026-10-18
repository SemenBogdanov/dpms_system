const DIRECTIONS = ['right', 'down', 'left', 'up'];

function finite(value, name) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new TypeError(`${name} must be a finite number`);
  }
  return value;
}

function checked(value) {
  if (!Number.isFinite(value)) throw new RangeError('Insertion geometry arithmetic overflow');
  return value === 0 ? 0 : value;
}

function record(value, name) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
}

function validateRectangle(rect) {
  record(rect, 'rectangle');
  if (typeof rect.id !== 'string' && !(typeof rect.id === 'number' && Number.isFinite(rect.id))) {
    throw new TypeError('Rectangle ID must be a string or finite number');
  }
  for (const field of ['x', 'y', 'width', 'height']) finite(rect[field], field);
  if (rect.width <= 0 || rect.height <= 0) throw new RangeError('Rectangle dimensions must be positive');
  checked(rect.x + rect.width);
  checked(rect.y + rect.height);
}

const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

function precedingOrigin(start, size, gap) {
  let origin = checked(checked(start - size) - gap);
  if (checked(checked(origin + size) + gap) <= start) return origin;
  // Round outward only when cancellation would otherwise put a contact inside the gap.
  const step = Math.max(Number.MIN_VALUE, Math.abs(start) * Number.EPSILON,
    Math.abs(origin) * Number.EPSILON, size * Number.EPSILON, gap * Number.EPSILON);
  origin = checked(origin - step);
  if (checked(checked(origin + size) + gap) > start) {
    throw new RangeError('Cannot represent a safe insertion boundary');
  }
  return origin;
}

/**
 * Return the nearest vacant origin, or null when the bounded area is fully blocked.
 * Distance is Euclidean from rect.x/y. Equal-distance ties favor direction, then
 * clockwise directions; diagonal ties belong to either adjacent direction. Remaining
 * ties use y, then x. A clear preferred position is preserved, including exact contact.
 * Origins (not entire rectangles) lie within [-limit, limit] on both axes unless
 * originBounds: {minX, maxX, minY, maxY} overrides that square. Bounds are inclusive;
 * a single line/point is allowed, so rigid-member limits need not bound padding.
 * Gap means axis-aligned separation: at least gap on x OR y for every obstacle.
 * All obstacles count equally, regardless of pinned/hidden metadata; own ID is ignored.
 * Inputs are untouched, and the result is always a fresh object.
 *
 * Coordinates and IDs (string or number) must be finite where numeric; dimensions and
 * limit must be positive, gap nonnegative, explicit bounds finite and ordered.
 * Invalid types/nonfinite inputs throw TypeError;
 * invalid domains/direction or arithmetic overflow throw RangeError, even on ignored IDs.
 * Floating contact boundaries round outward when needed, never accepting a smaller gap.
 *
 * A sweep of forbidden-origin rectangles examines at most 2n + 3 horizontal lines,
 * scanning n sorted intervals per line: O(n^2 + n log n) time, O(n) space. There is no
 * step-size search, recursion or retry budget that can miss a diagonal/isolated vacancy.
 */
export function findVacantPosition(rect, obstacles, options = {}) {
  validateRectangle(rect);
  if (!Array.isArray(obstacles)) throw new TypeError('obstacles must be an array');
  record(options, 'options');
  const { gap = 24, direction = 'right', limit = 100000, originBounds = null } = options;
  finite(gap, 'gap');
  finite(limit, 'limit');
  if (gap < 0) throw new RangeError('gap must be nonnegative');
  if (limit <= 0) throw new RangeError('limit must be positive');
  const directionIndex = DIRECTIONS.indexOf(direction);
  if (directionIndex === -1) throw new RangeError('Unknown insertion direction');
  if (originBounds !== null) record(originBounds, 'originBounds');
  const { minX, maxX, minY, maxY } = originBounds ?? { minX: -limit, maxX: limit, minY: -limit, maxY: limit };
  for (const [name, value] of Object.entries({ minX, maxX, minY, maxY })) finite(value, name);
  if (minX > maxX || minY > maxY) throw new RangeError('Origin bounds must be ordered');
  checked(maxX - minX);
  checked(maxY - minY);
  checked(checked(maxX + rect.width) + gap);
  checked(checked(maxY + rect.height) + gap);

  const boxes = [];
  for (const obstacle of obstacles) {
    validateRectangle(obstacle);
    if (obstacle.id === rect.id) continue;
    // An origin strictly inside this open box collides; its boundary is usable.
    const box = {
      left: precedingOrigin(obstacle.x, rect.width, gap),
      right: checked(checked(obstacle.x + obstacle.width) + gap),
      top: precedingOrigin(obstacle.y, rect.height, gap),
      bottom: checked(checked(obstacle.y + obstacle.height) + gap),
    };
    if (box.right > minX && box.left < maxX && box.bottom > minY && box.top < maxY) {
      boxes.push(box);
    }
  }
  const origin = { x: clamp(rect.x, minX, maxX), y: clamp(rect.y, minY, maxY) };
  const clear = obstacles.every((obstacle) => obstacle.id === rect.id
    || origin.x + rect.width + gap <= obstacle.x
    || obstacle.x + obstacle.width + gap <= origin.x
    || origin.y + rect.height + gap <= obstacle.y
    || obstacle.y + obstacle.height + gap <= origin.y);
  if (clear) return { x: checked(origin.x), y: checked(origin.y) };

  boxes.sort((a, b) => a.left - b.left || a.right - b.right || a.top - b.top || a.bottom - b.bottom);
  const rows = new Set([origin.y, minY, maxY]);
  for (const box of boxes) {
    if (box.top >= minY && box.top <= maxY) rows.add(box.top);
    if (box.bottom >= minY && box.bottom <= maxY) rows.add(box.bottom);
  }
  const orderedRows = [...rows].sort((a, b) => Math.abs(a - origin.y) - Math.abs(b - origin.y) || a - b);
  let best = null;
  let bestDistance = Infinity;
  let bestRank = Infinity;
  const consider = (x, y) => {
    const dx = checked(x - rect.x);
    const dy = checked(y - rect.y);
    const distance = checked(Math.hypot(dx, dy));
    if (distance > bestDistance) return;
    const projections = [dx, dy, -dx, -dy];
    let rank = 0;
    for (; rank < DIRECTIONS.length; rank += 1) {
      const index = (directionIndex + rank) % DIRECTIONS.length;
      if (projections[index] > 0 && projections[index] >= Math.abs(projections[(index + 1) % DIRECTIONS.length])) break;
    }
    if (!best || distance < bestDistance || rank < bestRank
      || (rank === bestRank && (y < best.y || (y === best.y && x < best.x)))) {
      best = { x: checked(x), y: checked(y) };
      bestDistance = distance;
      bestRank = rank;
    }
  };

  for (const y of orderedRows) {
    if (Math.abs(checked(y - rect.y)) > bestDistance) break;
    let cursor = minX;
    for (const box of boxes) {
      if (y <= box.top || y >= box.bottom || box.right <= cursor) continue;
      if (box.left >= cursor) consider(clamp(origin.x, cursor, Math.min(maxX, box.left)), y);
      cursor = Math.max(cursor, box.right);
      if (cursor > maxX) break;
    }
    if (cursor <= maxX) consider(clamp(origin.x, cursor, maxX), y);
  }
  return best;
}
