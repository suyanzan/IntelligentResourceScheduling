import assert from "node:assert/strict";
import test from "node:test";
import { prepareJobs } from "../js/floor-logic.js";
import { classify, curves, delayHours, kpis, perDay, utilization, worstDelays } from "../js/report-logic.js";

const OFFSET = 480;
const t = (s) => Date.parse(s);
const make = (id, over) => prepareJobs([{
  id, name: `Order ${id}`, lines: ["A"], status: "planned", after: null,
  due_at: "2026-11-15T16:00:00Z", planned_start_at: "2026-11-15T00:00:00Z", planned_end_at: "2026-11-15T04:00:00Z",
  actual_start_at: null, actual_end_at: null, ...over,
}])[0];

const NOW = t("2026-11-15T20:00:00Z");
const jobs = [
  make("a", { status: "done", actual_start_at: "2026-11-15T01:00:00Z", actual_end_at: "2026-11-15T05:00:00Z" }),
  make("b", { status: "done", actual_start_at: "2026-11-15T01:00:00Z", actual_end_at: "2026-11-15T18:00:00Z" }),
  make("c", { status: "running", actual_start_at: "2026-11-15T10:00:00Z" }),
  make("d", { due_at: "2026-11-17T16:00:00Z" }),
];

test("classification", () => {
  assert.deepEqual(jobs.map((j) => classify(j, NOW)), ["ontime", "late", "overdue", "open"]);
});

test("delay hours count from the finish, or from now while open", () => {
  assert.equal(delayHours(jobs[1], NOW), 2);
  assert.equal(delayHours(jobs[2], NOW), 4);
  assert.equal(delayHours(jobs[0], NOW), 0);
});

test("headline figures", () => {
  const k = kpis(jobs, NOW);
  assert.equal(k.total, 4);
  assert.equal(k.done, 2);
  assert.equal(k.onTimeRate, 0.25);
  assert.equal(k.late, 2);
  assert.equal(k.meanDelayHours, 1.5);
});

test("per-day counts use the due day", () => {
  const days = perDay(jobs, NOW, OFFSET);
  assert.deepEqual(days.map((d) => d.day), ["2026-11-15", "2026-11-17"]);
  assert.equal(days[0].total, 3);
  assert.equal(days[1].open, 1);
});

test("curves are cumulative", () => {
  const c = curves(jobs, NOW);
  assert.equal(c.actual.at(-1)[1], 2);
  assert.equal(c.due.at(-1)[1], 4);
});

test("utilization sums planned and actual hours per line", () => {
  const [a] = utilization([{ id: "A", name: "Line A" }], jobs, NOW);
  assert.equal(a.planned, 16);
  assert.equal(a.actual, 4 + 17 + 10);
});

test("worst delays are ranked", () => {
  assert.deepEqual(worstDelays(jobs, NOW).map((d) => d.id), ["c", "b"]);
});
