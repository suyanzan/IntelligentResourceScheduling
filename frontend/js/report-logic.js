// Pure figures for the management report: no DOM, so they are unit-tested with `node --test`.
// Orders are the prepared jobs of floor-logic.js (times in epoch milliseconds).

import { plantDay } from "./floor-logic.js";

const HOUR = 3_600_000;

/** "ontime", "late" (finished after due), "overdue" (open and past due) or "open". */
export function classify(job, nowMs) {
  if (job.status === "done") return job.actualEndMs <= job.dueMs ? "ontime" : "late";
  return nowMs > job.dueMs ? "overdue" : "open";
}

/** Not done and its planned finish has passed (by more than the grace), though not yet past due. */
export function isBehind(job, nowMs) {
  return job.status !== "done" && nowMs <= job.dueMs && nowMs > job.plannedEndMs + 15 * 60_000;
}

/**
 * One dial per due day: every order is a segment, in planned-finish order.
 * `kind` is "done-ontime", "done-late", "todo-overdue", "todo-behind" or "todo-open".
 */
export function dayDials(jobs, nowMs, offsetMinutes) {
  const days = new Map();
  for (const job of jobs) {
    const day = plantDay(job.dueMs - 1, offsetMinutes);
    if (!days.has(day)) days.set(day, []);
    days.get(day).push(job);
  }
  const kindOf = (job) => {
    const c = classify(job, nowMs);
    if (c === "ontime") return "done-ontime";
    if (c === "late") return "done-late";
    if (c === "overdue") return "todo-overdue";
    return isBehind(job, nowMs) ? "todo-behind" : "todo-open";
  };
  return [...days.keys()].sort().map((day) => {
    const items = days.get(day).sort((a, b) => a.plannedEndMs - b.plannedEndMs || a.id.localeCompare(b.id)).map((j) => ({ id: j.id, name: j.name, kind: kindOf(j) }));
    const done = items.filter((i) => i.kind.startsWith("done")).length;
    return { day, items, done, total: items.length };
  });
}

export const CLASSES = ["ontime", "late", "overdue", "open"];

function counts(jobs, nowMs) {
  const out = { ontime: 0, late: 0, overdue: 0, open: 0 };
  for (const job of jobs) out[classify(job, nowMs)] += 1;
  return out;
}

/** Hours an order is (or ended up) past its due time; 0 when on time. */
export function delayHours(job, nowMs) {
  const end = job.status === "done" ? job.actualEndMs : nowMs;
  return Math.max(0, (end - job.dueMs) / HOUR);
}

export function kpis(jobs, nowMs) {
  const c = counts(jobs, nowMs);
  const total = jobs.length;
  const done = c.ontime + c.late;
  return {
    total,
    done,
    counts: c,
    onTimeRate: total ? c.ontime / total : 0,
    doneRate: total ? done / total : 0,
    meanDelayHours: total ? jobs.reduce((sum, j) => sum + delayHours(j, nowMs), 0) / total : 0,
    late: c.late + c.overdue,
    behind: jobs.filter((j) => isBehind(j, nowMs)).length,
  };
}

/** One entry per due day (plant time), oldest first, with the four class counts. */
export function perDay(jobs, nowMs, offsetMinutes) {
  const days = new Map();
  for (const job of jobs) {
    const day = plantDay(job.dueMs - 1, offsetMinutes); // an end-of-day due belongs to that day
    if (!days.has(day)) days.set(day, []);
    days.get(day).push(job);
  }
  return [...days.keys()].sort().map((day) => ({ day, total: days.get(day).length, ...counts(days.get(day), nowMs) }));
}

/** Cumulative step curves: how many orders were due, planned to finish, and really finished by each time. */
export function curves(jobs, nowMs) {
  const steps = (times) => times.sort((a, b) => a - b).map((t, i) => [t, i + 1]);
  return {
    due: steps(jobs.map((j) => j.dueMs)),
    plan: steps(jobs.map((j) => j.plannedEndMs)),
    actual: steps(jobs.filter((j) => j.status === "done" && j.actualEndMs <= nowMs).map((j) => j.actualEndMs)),
  };
}

/** Hours of work planned and really done per line. Orders on several lines count on each. */
export function utilization(lines, jobs, nowMs) {
  return lines.map((line) => {
    let planned = 0;
    let actual = 0;
    for (const job of jobs) {
      if (!job.lines.includes(line.id)) continue;
      planned += (job.plannedEndMs - job.plannedStartMs) / HOUR;
      if (job.actualStartMs != null) actual += ((job.actualEndMs ?? nowMs) - job.actualStartMs) / HOUR;
    }
    return { id: line.id, name: line.name, planned, actual };
  });
}

/** The orders furthest past due, worst first. */
export function worstDelays(jobs, nowMs, limit = 8) {
  return jobs
    .map((j) => ({ id: j.id, name: j.name, hours: delayHours(j, nowMs), finished: j.status === "done" }))
    .filter((d) => d.hours > 0)
    .sort((a, b) => b.hours - a.hours)
    .slice(0, limit);
}
