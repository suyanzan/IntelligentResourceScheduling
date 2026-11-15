// Side-by-side comparison of two runs: verdict, KPI table, two Gantt charts on a shared time
// range, line utilization and a list of the jobs that changed. All differences are B minus A.

import * as api from "./api.js";
import { fmtDuration, fmtNumber, fmtPercent, fmtWhen, runLabel } from "./format.js";
import { createGantt } from "./gantt.js";
import { icon } from "./panels.js";

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

const DURATION_KEYS = new Set(["total_tardiness", "makespan"]);

const KPI_ROWS = [
  { key: "on_time_rate", label: "Jobs on time", better: "higher" },
  { key: "total_tardiness", label: "Total tardiness", better: "lower" },
  { key: "weighted_tardiness", label: "Weighted tardiness", better: "lower" },
  { key: "makespan", label: "Last job ends", better: "lower" },
  { key: "objective", label: "Objective", better: "lower" },
];

function sign(n) {
  return n > 0 ? "+" : n < 0 ? "−" : "";
}

/** The value of a KPI as text. Durations use the time unit of the run they belong to. */
function valueText(key, value, minutes) {
  if (value == null) return "–";
  if (key === "on_time_rate") return fmtPercent(value);
  if (DURATION_KEYS.has(key)) return fmtDuration(value, minutes);
  return fmtNumber(value);
}

/** B minus A as { text, diff } (null diff when either run has no value). */
function changeOf(key, delta, minutesA, minutesB) {
  if (delta.a == null || delta.b == null) return { text: "–", diff: null };
  const diff = DURATION_KEYS.has(key) ? delta.b * minutesB - delta.a * minutesA : delta.b - delta.a;
  if (key === "on_time_rate") {
    const points = Math.round(Math.abs(diff) * 100);
    return { text: points === 0 ? "no change" : `${sign(diff)}${points} pp`, diff: points === 0 ? 0 : diff };
  }
  if (diff === 0) return { text: "no change", diff: 0 };
  const size = DURATION_KEYS.has(key) ? fmtDuration(Math.abs(diff), 1) : fmtNumber(Math.abs(diff), 1);
  return { text: `${sign(diff)}${size}`, diff };
}

function verdictWord(diff, better) {
  if (diff == null || diff === 0) return null;
  return (better === "lower" ? diff < 0 : diff > 0) ? "better" : "worse";
}

function emptyMessage(run) {
  return run.status === "INFEASIBLE"
    ? "No schedule fits: the solver proved it."
    : "The solver found no schedule for this run.";
}

export function createCompareView(root, tooltip, { run }) {
  const $ = (id) => root.querySelector(`#${id}`);
  const ganttA = createGantt($("cmp-gantt-a"), tooltip);
  const ganttB = createGantt($("cmp-gantt-b"), tooltip);

  const scenarios = new Map(); // id -> scenario detail
  let token = 0;
  let current = null; // { a, b, cmp, sa, sb }

  async function scenarioOf(id) {
    if (!scenarios.has(id)) scenarios.set(id, await api.getScenario(id));
    return scenarios.get(id);
  }

  // --- selection -----------------------------------------------------------------------------

  function fill(select, groups, selectedId) {
    select.replaceChildren();
    for (const { scenario, runs } of groups) {
      const group = document.createElement("optgroup");
      group.label = scenario.name;
      for (const r of runs) {
        const option = document.createElement("option");
        option.value = String(r.id);
        option.textContent = runLabel(r);
        option.selected = r.id === selectedId;
        group.append(option);
      }
      select.append(group);
    }
  }

  /** Reload the list of runs and pick sensible defaults (the two latest of the current scenario). */
  async function open(scenarioList, currentScenarioId) {
    scenarios.clear();
    const groups = [];
    for (const scenario of scenarioList) {
      const runs = await api.listRuns(scenario.id);
      if (runs.length) groups.push({ scenario, runs });
    }
    const all = groups.flatMap((g) => g.runs);
    const own = groups.find((g) => g.scenario.id === currentScenarioId)?.runs ?? [];
    const pool = own.length >= 2 ? own : all;
    const [newer, older] = pool; // runs are listed newest first
    fill($("cmp-a"), groups, older?.id);
    fill($("cmp-b"), groups, newer?.id);
    $("cmp-controls").hidden = all.length === 0;
    $("cmp-hint").hidden = all.length >= 2;
    $("cmp-result").hidden = true;
    if (all.length >= 2) await show();
  }

  // --- rendering -----------------------------------------------------------------------------

  function renderVerdict({ cmp, a, b }) {
    const root = $("cmp-verdict");
    root.replaceChildren();
    const objective = a.weighted ? "priority-weighted tardiness" : "total tardiness";
    const o = cmp.metrics.objective;
    const badge = el("span", "badge");
    let text;
    if (cmp.better === "a" || cmp.better === "b") {
      const aWins = cmp.better === "a";
      const letter = cmp.better.toUpperCase();
      badge.dataset.tone = "good";
      badge.append(icon("check"), document.createTextNode(`Run ${letter} is better`));
      text = `Run ${letter} (run ${(aWins ? a : b).id}) has the lower ${objective}: ${fmtNumber(aWins ? o.a : o.b)} instead of ${fmtNumber(aWins ? o.b : o.a)}.`;
    } else if (cmp.better === "tie") {
      badge.dataset.tone = "neutral";
      badge.append(icon("help"), document.createTextNode("Same objective"));
      text = `Both runs reach ${objective} ${fmtNumber(o.a)}.`;
    } else {
      badge.dataset.tone = "neutral";
      badge.append(icon("help"), document.createTextNode("No winner named"));
      text = "The objective values cannot be ranked for these runs. The key figures below still show the differences.";
    }
    root.append(badge, el("span", "status-text", text));

    const notes = $("cmp-notes");
    notes.replaceChildren();
    for (const note of cmp.notes) notes.append(el("li", "", note));
    notes.hidden = cmp.notes.length === 0;
  }

  function renderKpis({ cmp, a, b }) {
    const body = $("cmp-kpis").querySelector("tbody");
    body.replaceChildren();
    for (const row of KPI_ROWS) {
      const delta = cmp.metrics[row.key];
      const change = changeOf(row.key, delta, a.time_unit_minutes, b.time_unit_minutes);
      const ranked = row.key !== "objective" || cmp.objective_comparable;
      const word = ranked ? verdictWord(change.diff, row.better) : null;

      const tr = el("tr");
      const changeCell = el("td", "num", change.text);
      if (word) {
        const tag = el("span", "delta", word);
        tag.dataset.tone = word === "better" ? "good" : "bad";
        changeCell.append(" ", tag);
      }
      tr.append(
        el("th", "", row.label),
        el("td", "num", valueText(row.key, delta.a, a.time_unit_minutes)),
        el("td", "num", valueText(row.key, delta.b, b.time_unit_minutes)),
        changeCell,
      );
      tr.firstChild.scope = "row";
      body.append(tr);
    }
  }

  function renderGantts({ a, b, sa, sb }) {
    const endMinutes = (run) => Math.max(0, ...run.assignments.map((x) => x.end)) * run.time_unit_minutes;
    const shared = Math.max(endMinutes(a), endMinutes(b));
    const draw = (gantt, run, scenario) =>
      gantt.update({
        horizonStart: scenario.horizon_start,
        minutes: scenario.time_unit_minutes,
        horizon: scenario.instance.horizon,
        resources: scenario.instance.resources,
        assignments: run.assignments,
        emptyMessage: emptyMessage(run),
        fitTo: shared > 0 ? shared / scenario.time_unit_minutes : null,
      });
    $("cmp-a-title").textContent = `Run A – ${sa.name}, ${runLabel(a)}`;
    $("cmp-b-title").textContent = `Run B – ${sb.name}, ${runLabel(b)}`;
    draw(ganttA, a, sa);
    draw(ganttB, b, sb);
  }

  function lineNames(sa, sb) {
    const names = new Map();
    for (const s of [sa, sb]) for (const r of s.instance.resources) names.set(r.id, r.name);
    return names;
  }

  function renderUtilization({ cmp, sa, sb }) {
    const body = $("cmp-util").querySelector("tbody");
    body.replaceChildren();
    const names = lineNames(sa, sb);
    for (const [id, delta] of Object.entries(cmp.utilization)) {
      const points = delta.change == null ? null : Math.round(delta.change * 100);
      const tr = el("tr");
      tr.append(
        el("th", "", names.get(id) ?? id),
        el("td", "num", delta.a == null ? "–" : fmtPercent(delta.a)),
        el("td", "num", delta.b == null ? "–" : fmtPercent(delta.b)),
        el("td", "num", points == null ? "–" : points === 0 ? "no change" : `${sign(points)}${Math.abs(points)} pp`),
      );
      tr.firstChild.scope = "row";
      body.append(tr);
    }
    $("cmp-util").hidden = body.children.length === 0;
  }

  function describeChange(job, names, minutesA, minutesB) {
    if (!job.a) return "Only scheduled in run B";
    if (!job.b) return "Only scheduled in run A";
    if (job.a.resource_id !== job.b.resource_id) {
      return `Moved from ${names.get(job.a.resource_id) ?? job.a.resource_id} to ${names.get(job.b.resource_id) ?? job.b.resource_id}`;
    }
    const shift = job.b.start * minutesB - job.a.start * minutesA;
    if (shift === 0) return "Unchanged";
    return `Starts ${fmtDuration(Math.abs(shift), 1)} ${shift > 0 ? "later" : "earlier"}`;
  }

  function renderJobs() {
    if (!current) return;
    const { cmp, a, b, sa, sb } = current;
    const showAll = $("cmp-all").checked;
    const names = lineNames(sa, sb);
    const ma = { horizonStart: sa.horizon_start, minutes: sa.time_unit_minutes };
    const mb = { horizonStart: sb.horizon_start, minutes: sb.time_unit_minutes };

    const place = (p, model) =>
      p ? `${names.get(p.resource_id) ?? p.resource_id}, ${fmtWhen(model, p.start)}${p.tardiness ? ` (late ${fmtDuration(p.tardiness, model.minutes)})` : ""}` : "–";

    // Change in lateness in minutes (runs may use different time units).
    const lateness = (j) => (j.a && j.b ? j.b.tardiness * mb.minutes - j.a.tardiness * ma.minutes : null);
    const rows = cmp.jobs.filter((j) => showAll || j.moved || !j.a || !j.b || lateness(j) !== 0);
    const body = $("cmp-jobs").querySelector("tbody");
    body.replaceChildren();
    for (const job of rows) {
      const tardy = lateness(job);
      const tr = el("tr");
      const name = el("th", "", job.job_name);
      name.scope = "row";
      name.append(" ", el("span", "code", job.job_id));
      const tardyCell = el("td", "num", tardy == null ? "–" : tardy === 0 ? "no change" : `${sign(tardy)}${fmtDuration(Math.abs(tardy), 1)}`);
      if (tardy) {
        const tag = el("span", "delta", tardy < 0 ? "better" : "worse");
        tag.dataset.tone = tardy < 0 ? "good" : "bad";
        tardyCell.append(" ", tag);
      }
      tr.append(
        name,
        el("td", "", place(job.a, ma)),
        el("td", "", place(job.b, mb)),
        el("td", "", describeChange(job, names, ma.minutes, mb.minutes)),
        tardyCell,
      );
      body.append(tr);
    }
    $("cmp-jobs-empty").hidden = rows.length > 0;
    $("cmp-jobs-count").textContent = `${cmp.moved_jobs} of ${cmp.jobs.length} jobs moved`;
  }

  async function show() {
    const idA = Number($("cmp-a").value);
    const idB = Number($("cmp-b").value);
    if (!idA || !idB) return;
    const mine = ++token;
    const [a, b, cmp] = await Promise.all([api.getRun(idA), api.getRun(idB), api.compare(idA, idB)]);
    const [sa, sb] = await Promise.all([scenarioOf(a.scenario_id), scenarioOf(b.scenario_id)]);
    if (mine !== token) return; // a newer selection superseded this one
    current = { a, b, cmp, sa, sb };
    $("cmp-result").hidden = false;
    renderVerdict(current);
    renderKpis(current);
    renderGantts(current);
    renderUtilization(current);
    renderJobs();
  }

  // --- events --------------------------------------------------------------------------------

  for (const id of ["cmp-a", "cmp-b"]) $(id).addEventListener("change", () => run(show));
  $("cmp-swap").addEventListener("click", () => {
    const a = $("cmp-a").value;
    $("cmp-a").value = $("cmp-b").value;
    $("cmp-b").value = a;
    run(show);
  });
  $("cmp-all").addEventListener("change", renderJobs);

  // Hovering a bar in one chart marks the same job in the other.
  for (const [host, other, self] of [["cmp-gantt-a", ganttB, ganttA], ["cmp-gantt-b", ganttA, ganttB]]) {
    $(host).addEventListener("pointerover", (event) => {
      const id = event.target.closest?.(".job")?.dataset.job ?? null;
      self.highlight(id);
      other.highlight(id);
    });
    $(host).addEventListener("pointerleave", () => {
      self.highlight(null);
      other.highlight(null);
    });
  }

  return { open, refit: () => { ganttA.fit(); ganttB.fit(); } };
}
