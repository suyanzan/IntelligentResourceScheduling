import assert from "node:assert/strict";
import test from "node:test";
import { fmtDue } from "../js/format.js";

const model = { horizonStart: "2026-11-15", minutes: 60 };

test("an end-of-day due time is shown as 24:00 of that day", () => {
  assert.equal(fmtDue(model, 24), "Sun 15 Nov, 24:00");
  assert.equal(fmtDue(model, 72), "Tue 17 Nov, 24:00");
});

test("other due times are unchanged", () => {
  assert.match(fmtDue(model, 30), /Mon 16 Nov, 06:00/);
});
