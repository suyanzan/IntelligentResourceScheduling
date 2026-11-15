// Pure rules for the production-floor dashboard: no DOM, no network, so they can be tested
// with `node --test`. Times are epoch milliseconds; "plant time" is UTC plus the plan's offset.

const MIN = 60_000;
/** A start or finish within this many minutes of the plan counts as on time. */
export const GRACE_MIN = 15;

/** Plain-language gap, "45 min", "3 h 10 min" or "2 d 4 h". */
export function span(ms) {
  const minutes = Math.round(Math.abs(ms) / MIN);
  if (minutes < 60) return `${minutes} min`;
  if (minutes < 48 * 60) {
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    return m ? `${h} h ${m} min` : `${h} h`;
  }
  const d = Math.floor(minutes / 1440);
  const h = Math.round((minutes % 1440) / 60);
  return h ? `${d} d ${h} h` : `${d} d`;
}

/** The plant-local calendar day of `ms` as "YYYY-MM-DD". */
export function plantDay(ms, offsetMinutes) {
  return new Date(ms + offsetMinutes * MIN).toISOString().slice(0, 10);
}

function shiftDay(day, days) {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

/** Convert the API's ISO strings to milliseconds and add what the board needs. */
export function prepareJobs(jobs) {
  return jobs.map((j) => ({
    ...j,
    dueMs: Date.parse(j.due_at),
    plannedStartMs: Date.parse(j.planned_start_at),
    plannedEndMs: Date.parse(j.planned_end_at),
    actualStartMs: j.actual_start_at ? Date.parse(j.actual_start_at) : null,
    actualEndMs: j.actual_end_at ? Date.parse(j.actual_end_at) : null,
  }));
}

/**
 * How one order compares with its plan right now.
 * `tone` is "ok", "warn", "bad" or "info"; `text` is one short sentence for the row.
 */
export function variance(job, nowMs) {
  const grace = GRACE_MIN * MIN;
  if (job.status === "done") {
    const end = job.actualEndMs - job.plannedEndMs;
    const pastDue = job.actualEndMs > job.dueMs;
    let text;
    if (Math.abs(end) <= grace) text = "Finished on plan";
    else text = end < 0 ? `Finished ${span(end)} early` : `Finished ${span(end)} late`;
    if (pastDue) return { tone: "bad", text: `${text} · ${span(job.actualEndMs - job.dueMs)} after due` };
    return { tone: end > grace ? "warn" : "ok", text };
  }
  if (job.status === "running") {
    const behind = job.actualStartMs - job.plannedStartMs;
    const start = Math.abs(behind) <= grace ? "" : behind > 0 ? `started ${span(behind)} late · ` : `started ${span(behind)} early · `;
    if (nowMs > job.dueMs) return { tone: "bad", text: `${start}${span(nowMs - job.dueMs)} past due` };
    if (nowMs > job.plannedEndMs + grace) return { tone: "bad", text: `${start}overrunning plan by ${span(nowMs - job.plannedEndMs)}` };
    return { tone: behind > grace ? "warn" : "ok", text: `${start}planned finish in ${span(Math.max(0, job.plannedEndMs - nowMs))}` };
  }
  if (nowMs > job.dueMs) return { tone: "bad", text: `${span(nowMs - job.dueMs)} past due, not started` };
  if (nowMs > job.plannedStartMs + grace) return { tone: "warn", text: `Should have started ${span(nowMs - job.plannedStartMs)} ago` };
  if (nowMs >= job.plannedStartMs) return { tone: "info", text: "Due to start now" };
  return { tone: "info", text: `Starts in ${span(job.plannedStartMs - nowMs)}` };
}

export const GROUPS = [
  { key: "carry", title: "Carried over", hint: "Due on an earlier day and not finished" },
  { key: "today", title: "Today", hint: "" },
  { key: "tomorrow", title: "Tomorrow", hint: "" },
  { key: "dayAfter", title: "Day after tomorrow", hint: "" },
  { key: "later", title: "Later", hint: "" },
  { key: "earlier", title: "Finished earlier", hint: "Completed orders from past days" },
];

/** Which group an order belongs to, by the plant day it is due. */
export function groupOf(job, nowMs, offsetMinutes) {
  const today = plantDay(nowMs, offsetMinutes);
  // Due times are half-open ends: "end of the day" is exactly midnight and still belongs to that day.
  const due = plantDay(job.dueMs - 1, offsetMinutes);
  if (due < today) return job.status === "done" ? "earlier" : "carry";
  if (due === today) return "today";
  if (due === shiftDay(today, 1)) return "tomorrow";
  if (due === shiftDay(today, 2)) return "dayAfter";
  return "later";
}

/** Orders sorted for the floor: running first, then by due time, then planned start. */
export function floorOrder(a, b) {
  const rank = { running: 0, planned: 1, done: 2 };
  return rank[a.status] - rank[b.status] || a.dueMs - b.dueMs || a.plannedStartMs - b.plannedStartMs;
}

/** Split orders into the groups above (only non-empty groups, in display order). */
export function groupJobs(jobs, nowMs, offsetMinutes) {
  const buckets = new Map(GROUPS.map((g) => [g.key, []]));
  for (const job of jobs) buckets.get(groupOf(job, nowMs, offsetMinutes)).push(job);
  return GROUPS.map((g) => ({ ...g, jobs: buckets.get(g.key).sort(floorOrder) })).filter((g) => g.jobs.length > 0);
}

/** Counts for one set of orders. */
export function summarize(jobs, nowMs) {
  const open = jobs.filter((j) => j.status !== "done");
  return {
    total: jobs.length,
    done: jobs.length - open.length,
    running: jobs.filter((j) => j.status === "running").length,
    behind: open.filter((j) => ["warn", "bad"].includes(variance(j, nowMs).tone)).length,
    pastDue: open.filter((j) => nowMs > j.dueMs).length,
  };
}

/**
 * Plan versus reality for each line. A line is "ok", "behind" or "attention", with the reasons
 * in plain words. Orders spanning several lines count on each of them.
 */
export function lineStates(lines, jobs, nowMs) {
  const byId = new Map(jobs.map((j) => [j.id, j]));
  return lines.map((line) => {
    const mine = jobs.filter((j) => j.lines.includes(line.id));
    const running = mine.find((j) => j.status === "running") ?? null;
    const queued = mine.filter((j) => j.status === "planned").sort((a, b) => a.plannedStartMs - b.plannedStartMs);
    const next = queued[0] ?? null;
    const issues = [];
    let level = "ok";
    const raise = (to) => { if (to === "attention" || level === "ok") level = to; };

    if (running && nowMs > running.plannedEndMs + GRACE_MIN * MIN) {
      issues.push(`${running.name} is ${span(nowMs - running.plannedEndMs)} over its planned finish`);
      raise("attention");
    }
    if (!running && next && nowMs > next.plannedStartMs + GRACE_MIN * MIN) {
      const pred = next.after ? byId.get(next.after) : null;
      if (pred && pred.status !== "done") {
        issues.push(`${next.name} waits for ${pred.name} to finish`);
        raise("behind");
      } else {
        issues.push(`${next.name} should have started ${span(nowMs - next.plannedStartMs)} ago`);
        raise("behind");
      }
    }
    if (running && queued.some((q) => q.plannedStartMs < running.plannedStartMs)) {
      const skipped = queued.find((q) => q.plannedStartMs < running.plannedStartMs);
      issues.push(`${running.name} was started ahead of ${skipped.name}, which the plan has first`);
      raise("behind");
    }
    return { line, running, next, issues, level };
  });
}

/** True when `ms` is exactly midnight plant time, which is how "end of day" due times arrive. */
export function isDayEnd(ms, offsetMinutes) {
  return (((ms + offsetMinutes * MIN) % 86_400_000) + 86_400_000) % 86_400_000 === 0;
}
