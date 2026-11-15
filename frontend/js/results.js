// Sortable job results table. Rows link to the Gantt chart: hovering a row highlights its bar.

import { icon } from "./panels.js";
import { fmtDuration, fmtNumber, fmtSigned, fmtWhen } from "./format.js";

const COLUMNS = [
  { key: "name", label: "Job", num: false, value: (r) => r.name },
  { key: "line", label: "Lines", num: false, value: (r) => r.line ?? "" },
  { key: "work", label: "CPU-hours", num: true, value: (r) => r.work ?? -1 },
  { key: "arrives", label: "Arrives", num: false, value: (r) => r.release },
  { key: "start", label: "Starts", num: false, value: (r) => r.start ?? Infinity },
  { key: "end", label: "Ends", num: false, value: (r) => r.end ?? Infinity },
  { key: "duration", label: "Duration", num: true, value: (r) => r.duration },
  { key: "due", label: "Due", num: false, value: (r) => r.due },
  { key: "priority", label: "Priority", num: true, value: (r) => r.priority },
  { key: "delay", label: "Delay", num: true, value: (r) => r.delay ?? -Infinity },
];

function cell(tag, text, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = text;
  return node;
}

/** Combine the scenario's jobs with a run's assignments into table rows. */
export function buildRows(scenario, run) {
  // A job that merges several lines has one assignment per line, all with the same span.
  const placed = new Map();
  for (const a of run?.assignments ?? []) {
    if (!placed.has(a.job_id)) placed.set(a.job_id, []);
    placed.get(a.job_id).push(a);
  }
  const lines = new Map(scenario.instance.resources.map((r) => [r.id, r.name]));
  return scenario.instance.jobs.map((job) => {
    const rows = placed.get(job.id);
    const a = rows?.[0];
    return {
      id: job.id,
      name: job.name,
      line: rows ? rows.map((r) => lines.get(r.resource_id) ?? r.resource_id).join(" + ") : null,
      merged: (rows?.length ?? 0) > 1,
      work: job.work ?? null,
      release: job.release ?? 0,
      layer: job.layer ?? "",
      cycleLimit: job.cycle_limit ?? null,
      overCycle: a?.over_cycle ?? false,
      cycleUsed: a && job.cycle_limit != null ? a.end - (job.release ?? 0) : null,
      after: job.after ?? null,
      start: a?.start ?? null,
      end: a?.end ?? null,
      duration: a ? a.end - a.start : job.work != null ? null : job.duration,
      due: job.due,
      priority: job.priority,
      tardiness: a ? a.tardiness : null,
      delay: a ? a.delay : null,
    };
  });
}

export function createResultsTable(root, { onHover }) {
  let rows = [];
  let model = { horizonStart: null, minutes: 60 };
  let sort = { key: "start", dir: 1 };
  let lateOnly = false;

  function sorted() {
    const col = COLUMNS.find((c) => c.key === sort.key);
    const visible = lateOnly ? rows.filter((r) => (r.tardiness ?? 0) > 0) : rows;
    return [...visible].sort((a, b) => {
      const x = col.value(a);
      const y = col.value(b);
      const order = typeof x === "string" ? x.localeCompare(y, undefined, { numeric: true }) : x - y;
      return (order || a.name.localeCompare(b.name, undefined, { numeric: true })) * sort.dir;
    });
  }

  function render() {
    root.replaceChildren();
    const data = sorted();
    if (!data.length) {
      const p = document.createElement("p");
      p.className = "table-empty";
      p.textContent = lateOnly ? "No late jobs in this schedule." : "This scenario has no jobs.";
      root.append(p);
      return;
    }
    const table = document.createElement("table");
    const caption = document.createElement("caption");
    caption.className = "sr-only";
    caption.textContent = "Jobs with their scheduled times and delay (end minus due; negative means early)";
    const head = table.createTHead().insertRow();
    for (const col of COLUMNS) {
      const th = document.createElement("th");
      th.scope = "col";
      if (col.num) th.className = "num";
      th.setAttribute("aria-sort", sort.key === col.key ? (sort.dir === 1 ? "ascending" : "descending") : "none");
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = col.label;
      button.addEventListener("click", () => {
        sort = { key: col.key, dir: sort.key === col.key ? -sort.dir : 1 };
        render();
      });
      th.append(button);
      head.append(th);
    }
    head.append(Object.assign(document.createElement("th"), { scope: "col", textContent: "Status" }));

    const body = table.createTBody();
    for (const r of data) {
      const tr = body.insertRow();
      tr.dataset.job = r.id;
      tr.addEventListener("pointerenter", () => onHover(r.id));
      tr.addEventListener("pointerleave", () => onHover(null));
      const name = cell("td", r.name);
      name.append(cell("span", r.id, "job-id"));
      if (r.layer) name.append(cell("span", r.layer, "layer-tag"));
      tr.append(
        name,
        cell("td", r.line ?? "Not scheduled"),
        cell("td", r.work == null ? "-" : fmtNumber(r.work), "num"),
        cell("td", r.release > 0 ? fmtWhen(model, r.release) : r.after ? `after ${r.after}` : "-"),
        cell("td", r.start == null ? "-" : fmtWhen(model, r.start)),
        cell("td", r.end == null ? "-" : fmtWhen(model, r.end)),
        cell("td", r.duration == null ? "-" : fmtDuration(r.duration, model.minutes), "num"),
        cell("td", fmtWhen(model, r.due)),
        cell("td", String(r.priority), "num"),
        cell("td", r.delay == null ? "-" : fmtSigned(r.delay, model.minutes), "num"),
      );
      const state = document.createElement("span");
      state.className = "state";
      if (r.tardiness == null) {
        state.dataset.tone = "none";
        state.textContent = "Not scheduled";
      } else if (r.tardiness > 0) {
        state.dataset.tone = "late";
        state.append(icon("alert"), document.createTextNode(`Late by ${fmtDuration(r.tardiness, model.minutes)}`));
      } else {
        state.dataset.tone = "ok";
        state.append(icon("check"), document.createTextNode("On time"));
      }
      tr.insertCell().append(state);
      if (r.cycleLimit != null && r.cycleUsed != null) {
        const cycle = document.createElement("span");
        cycle.className = "state cycle";
        cycle.dataset.tone = r.overCycle ? "late" : "ok";
        const used = fmtDuration(r.cycleUsed, model.minutes);
        const limit = fmtDuration(r.cycleLimit, model.minutes);
        cycle.append(
          icon(r.overCycle ? "alert" : "check"),
          document.createTextNode(r.overCycle ? `Cycle ${used} > ${limit}: 1 point` : `Cycle ${used} \u2264 ${limit}`),
        );
        tr.cells[tr.cells.length - 1].append(cycle);
      }
    }
    table.prepend(caption);
    root.append(table);
  }

  return {
    update(nextRows, nextModel) {
      rows = nextRows;
      model = nextModel;
      render();
    },
    setLateOnly(value) {
      lateOnly = value;
      render();
    },
    highlight(jobId) {
      for (const tr of root.querySelectorAll("tbody tr")) tr.classList.toggle("is-linked", tr.dataset.job === jobId);
    },
  };
}
