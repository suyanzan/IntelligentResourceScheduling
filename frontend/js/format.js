// Formatting helpers. A "model" is { horizonStart: "YYYY-MM-DD" | null, minutes: number }.

const dayFormat = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short" });
const dayShortFormat = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric" });
const whenFormat = new Intl.DateTimeFormat("en-GB", {
  weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});

/** The Date at which `unit` begins (wall-clock, no time zone), or null without a start date. */
export function unitDate(model, unit) {
  if (!model.horizonStart) return null;
  const [y, m, d] = model.horizonStart.split("-").map(Number);
  return new Date(y, m - 1, d, 0, unit * model.minutes);
}

export function fmtWhen(model, unit) {
  const date = unitDate(model, unit);
  return date ? whenFormat.format(date) : `unit ${unit}`;
}

export function fmtDay(model, unit, narrow) {
  const date = unitDate(model, unit);
  if (!date) return String(unit);
  return (narrow ? dayShortFormat : dayFormat).format(date);
}

/** A length of `units` time units as "3 h" or "45 min" (never days, so columns stay comparable). */
export function fmtDuration(units, minutes) {
  const total = units * minutes;
  if (total === 0) return "0 h";
  if (total % 60 === 0) return `${fmtNumber(total / 60)} h`;
  return `${fmtNumber(total)} min`;
}

export function fmtPercent(ratio, digits = 0) {
  return `${(ratio * 100).toFixed(digits)}%`;
}

export function fmtNumber(value, digits = 0) {
  return value.toLocaleString("en-GB", { maximumFractionDigits: digits });
}

/** Number of calendar units inside `windows` over [0, upto). */
export function availableUnits(windows, upto) {
  return windows.reduce((sum, w) => sum + Math.max(0, Math.min(w.end, upto) - Math.max(w.start, 0)), 0);
}

/** Closed periods of a resource within [0, horizon), as {start, end} pairs. */
export function closedPeriods(windows, horizon) {
  const sorted = [...windows].sort((a, b) => a.start - b.start);
  const out = [];
  let cursor = 0;
  for (const w of sorted) {
    if (w.start > cursor) out.push({ start: cursor, end: w.start });
    cursor = Math.max(cursor, w.end);
  }
  if (cursor < horizon) out.push({ start: cursor, end: horizon });
  return out;
}
