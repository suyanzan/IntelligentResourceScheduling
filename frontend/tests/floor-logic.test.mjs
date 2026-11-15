import assert from "node:assert/strict";
import test from "node:test";
import { groupJobs, groupOf, isDayEnd, lineStates, plantDay, prepareJobs, span, summarize, variance } from "../js/floor-logic.js";

const OFFSET = 480;
const t = (s) => Date.parse(s);
const job = (over) => prepareJobs([{
  id: "a", name: "Order A", lines: ["A"], status: "planned", after: null,
  due_at: "2026-11-15T15:59:59Z", planned_start_at: "2026-11-15T01:00:00Z", planned_end_at: "2026-11-15T05:00:00Z",
  actual_start_at: null, actual_end_at: null, ...over,
}])[0];

test("span reads naturally", () => {
  assert.equal(span(45 * 60_000), "45 min");
  assert.equal(span(190 * 60_000), "3 h 10 min");
  assert.equal(span(-3 * 3600_000), "3 h");
  assert.equal(span(60 * 3600_000), "2 d 12 h");
});

test("plant day uses the plan offset", () => {
  assert.equal(plantDay(t("2026-11-15T20:00:00Z"), OFFSET), "2026-11-16");
  assert.equal(plantDay(t("2026-11-15T15:59:00Z"), OFFSET), "2026-11-15");
});

test("unfinished orders from earlier days are carried over; finished ones are not", () => {
  const now = t("2026-11-16T01:00:00Z");
  assert.equal(groupOf(job({}), now, OFFSET), "carry");
  assert.equal(groupOf(job({ status: "done", actual_start_at: "2026-11-15T02:00:00Z", actual_end_at: "2026-11-15T06:00:00Z" }), now, OFFSET), "earlier");
});

test("orders fall into today, tomorrow and the day after by due day", () => {
  const now = t("2026-11-15T01:00:00Z");
  const jobs = prepareJobs([
    { ...job({}), id: "t", due_at: "2026-11-15T15:59:59Z" },
    { ...job({}), id: "m", due_at: "2026-11-16T15:59:59Z" },
    { ...job({}), id: "d", due_at: "2026-11-17T15:59:59Z" },
  ].map((j) => ({ ...j, due_at: j.due_at, planned_start_at: "2026-11-15T01:00:00Z", planned_end_at: "2026-11-15T05:00:00Z" })));
  const groups = groupJobs(jobs, now, OFFSET);
  assert.deepEqual(groups.map((g) => g.key), ["today", "tomorrow", "dayAfter"]);
});

test("variance for a planned order", () => {
  assert.equal(variance(job({}), t("2026-11-14T23:00:00Z")).text, "Starts in 2 h");
  assert.equal(variance(job({}), t("2026-11-15T01:05:00Z")).text, "Due to start now");
  const late = variance(job({}), t("2026-11-15T02:00:00Z"));
  assert.equal(late.tone, "warn");
  assert.match(late.text, /Should have started 1 h ago/);
});

test("variance for running and done orders", () => {
  const running = job({ status: "running", actual_start_at: "2026-11-15T02:00:00Z" });
  assert.match(variance(running, t("2026-11-15T03:00:00Z")).text, /started 1 h late/);
  const over = variance(running, t("2026-11-15T06:00:00Z"));
  assert.equal(over.tone, "bad");
  assert.match(over.text, /overrunning plan by 1 h/);
  const early = job({ status: "done", actual_start_at: "2026-11-15T01:00:00Z", actual_end_at: "2026-11-15T03:00:00Z" });
  assert.equal(variance(early, t("2026-11-15T04:00:00Z")).text, "Finished 2 h early");
  const pastDue = job({ status: "done", actual_start_at: "2026-11-15T01:00:00Z", actual_end_at: "2026-11-15T17:00:00Z" });
  assert.equal(variance(pastDue, t("2026-11-15T18:00:00Z")).tone, "bad");
});

test("summary counts", () => {
  const now = t("2026-11-15T06:00:00Z");
  const jobs = [job({}), job({ id: "b", status: "done", actual_start_at: "2026-11-15T01:00:00Z", actual_end_at: "2026-11-15T05:00:00Z" })];
  assert.deepEqual(summarize(jobs, now), { total: 2, done: 1, running: 0, behind: 1, pastDue: 0 });
});

test("line states flag late starts, overruns and waiting follow-ups", () => {
  const lines = [{ id: "A", name: "Line A" }];
  const now = t("2026-11-15T06:00:00Z");
  const waiting = lineStates(lines, [job({ id: "x", name: "Follow-up", after: "p" }), job({ id: "p", name: "Parent", lines: ["B"], status: "running", actual_start_at: "2026-11-15T01:00:00Z" })], now)[0];
  assert.equal(waiting.level, "behind");
  assert.match(waiting.issues[0], /waits for Parent/);
  const over = lineStates(lines, [job({ status: "running", actual_start_at: "2026-11-15T01:00:00Z" })], now)[0];
  assert.equal(over.level, "attention");
  const fine = lineStates(lines, [job({ status: "running", actual_start_at: "2026-11-15T01:00:00Z", planned_end_at: "2026-11-15T09:00:00Z" })], now)[0];
  assert.equal(fine.level, "ok");
});

test("starting out of sequence is flagged", () => {
  const lines = [{ id: "A", name: "Line A" }];
  const jobs = [
    job({ id: "first", name: "First", planned_start_at: "2026-11-15T01:00:00Z", planned_end_at: "2026-11-15T03:00:00Z" }),
    job({ id: "second", name: "Second", status: "running", actual_start_at: "2026-11-15T01:00:00Z", planned_start_at: "2026-11-15T03:00:00Z", planned_end_at: "2026-11-15T09:00:00Z" }),
  ];
  const state = lineStates(lines, jobs, t("2026-11-15T02:00:00Z"))[0];
  assert.match(state.issues.join(" "), /started ahead of First/);
});

test("a due time at midnight belongs to the day that just ended", () => {
  const now = t("2026-11-15T01:00:00Z");
  const endOfToday = job({ due_at: "2026-11-15T16:00:00Z" }); // 00:00 on 16 Nov, plant time
  assert.equal(groupOf(endOfToday, now, OFFSET), "today");
  assert.equal(isDayEnd(endOfToday.dueMs, OFFSET), true);
  assert.equal(isDayEnd(t("2026-11-15T15:59:00Z"), OFFSET), false);
  const tomorrowEnd = job({ due_at: "2026-11-16T16:00:00Z" });
  assert.equal(groupOf(tomorrowEnd, now, OFFSET), "tomorrow");
});
