function positiveInteger(value, fallback = 1) {
  const normalized = Math.floor(Number(value));
  return Number.isFinite(normalized) && normalized > 0 ? normalized : fallback;
}

export function fullRowPageSize(target, columns, {
  min = 1,
  max = Number.POSITIVE_INFINITY,
  bias = 'lower'
} = {}) {
  const normalizedTarget = positiveInteger(target);
  const normalizedColumns = positiveInteger(columns);
  const normalizedMin = positiveInteger(min);
  const normalizedMax = Number.isFinite(Number(max))
    ? Math.max(normalizedMin, positiveInteger(max, normalizedMin))
    : Number.POSITIVE_INFINITY;

  const firstMultiple = Math.ceil(normalizedMin / normalizedColumns) * normalizedColumns;
  const lastMultiple = Number.isFinite(normalizedMax)
    ? Math.floor(normalizedMax / normalizedColumns) * normalizedColumns
    : Number.POSITIVE_INFINITY;

  if (firstMultiple > lastMultiple) {
    return Math.min(Math.max(normalizedTarget, normalizedMin), normalizedMax);
  }

  const lower = Math.max(
    firstMultiple,
    Math.floor(normalizedTarget / normalizedColumns) * normalizedColumns
  );
  const upper = Math.min(
    lastMultiple,
    Math.ceil(normalizedTarget / normalizedColumns) * normalizedColumns
  );
  const lowerDistance = Math.abs(normalizedTarget - lower);
  const upperDistance = Math.abs(upper - normalizedTarget);

  if (upperDistance < lowerDistance) return upper;
  if (lowerDistance < upperDistance) return lower;
  return bias === 'higher' ? upper : lower;
}

export function countGridTemplateColumns(template) {
  const value = String(template || '').trim();
  if (!value || value === 'none') return 0;

  const repeatMatch = value.match(/^repeat\(\s*(\d+)\s*,/i);
  if (repeatMatch) return positiveInteger(repeatMatch[1], 0);

  let depth = 0;
  let columns = 0;
  let inTrack = false;
  for (const character of value) {
    if (character === '(') depth += 1;
    if (character === ')') depth = Math.max(0, depth - 1);
    if (/\s/.test(character) && depth === 0) {
      if (inTrack) columns += 1;
      inTrack = false;
    } else {
      inTrack = true;
    }
  }
  return columns + (inTrack ? 1 : 0);
}
