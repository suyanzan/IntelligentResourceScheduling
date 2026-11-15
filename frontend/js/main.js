// Page controller: loads data from the API and drives the components.

import * as api from "./api.js";
import { createCompareView } from "./compare.js";
import { runLabel } from "./format.js";
import { createGantt } from "./gantt.js";
import { renderKpis, renderSolver, renderStatusLine, renderUtilization } from "./panels.js";
import { buildRows, createResultsTable } from "./results.js";
import { createTooltip } from "./tooltip.js";
import { createWatchBoard } from "./watch.js";

const $ = (id) => document.getElementById(id);

const state = { scenarios: [], scenario: null, runs: [], run: null, busy: false, mode: "single" };

const tooltip = createTooltip();
const gantt = createGantt($("gantt"), tooltip);
const results = createResultsTable($("results-body"), {
  onHover(jobId) {
    gantt.highlight(jobId);
  },
});

const watch = createWatchBoard($("watch"));

const compare = createCompareView($("compare"), tooltip, { run: (work) => guarded(null, work) });

// --- helpers ---------------------------------------------------------------------------------

function showAlert(error) {
  const box = $("alert");
  box.replaceChildren();
  const message = document.createElement("div");
  message.textContent = error.message ?? String(error);
  box.append(message);
  if (error.issues?.length) {
    const list = document.createElement("ul");
    for (const issue of error.issues) {
      const li = document.createElement("li");
      li.textContent = issue;
      list.append(li);
    }
    box.append(list);
  }
  box.hidden = false;
}

function clearAlert() {
  $("alert").hidden = true;
}

function setBusy(busy, label) {
  state.busy = busy;
  document.body.classList.toggle("is-loading", busy);
  document.body.setAttribute("aria-busy", String(busy));
  for (const id of ["scenario-select", "run-select", "time-limit", "no-idle", "solve-btn", "generate-btn", "empty-generate-btn", "compare-btn", "watch-btn", "release-btn"]) {
    const needsScenario = id !== "generate-btn" && id !== "empty-generate-btn";
    const noRuns = id === "run-select" && state.runs.length === 0;
    $(id).disabled = busy || (needsScenario && !state.scenario) || noRuns;
  }
  if (!busy) syncRelease();
  $("solve-btn").textContent = busy && label ? label : "Solve";
}

async function guarded(label, work) {
  clearAlert();
  setBusy(true, label);
  try {
    await work();
  } catch (error) {
    showAlert(error);
  } finally {
    setBusy(false);
  }
}

function fillSelect(select, items, labelOf, selectedId) {
  select.replaceChildren();
  for (const item of items) {
    const option = document.createElement("option");
    option.value = String(item.id);
    option.textContent = labelOf(item);
    option.selected = item.id === selectedId;
    select.append(option);
  }
}

// --- rendering -------------------------------------------------------------------------------

function emptyMessage(run) {
  if (!run) return "No schedule yet. Choose Solve to place the jobs.";
  if (run.status === "INFEASIBLE") return "The solver proved that no schedule fits. See the solver result below.";
  return "The solver found no schedule within the time limit.";
}

function render() {
  const { scenario, run } = state;
  $("empty").hidden = Boolean(scenario);
  $("content").hidden = !scenario || state.mode !== "single";
  if (!scenario) {
    watch.update(null, null);
    return;
  }

  const model = { horizonStart: scenario.horizon_start, minutes: scenario.time_unit_minutes };
  const assignments = run?.assignments ?? [];

  renderStatusLine($("status"), run, model.minutes);
  renderKpis($("kpis"), run, model);
  gantt.update({
    ...model,
    horizon: scenario.instance.horizon,
    resources: scenario.instance.resources,
    assignments,
    emptyMessage: emptyMessage(run),
  });
  renderUtilization($("util-body"), scenario, run);
  renderSolver($("solver-body"), run);
  results.update(buildRows(scenario, run), model);
  watch.update(scenario, run);
  $("solve-btn").disabled = false;
}

// --- data flow -------------------------------------------------------------------------------

async function loadRun(runId) {
  state.run = runId == null ? null : await api.getRun(runId);
}

async function selectScenario(id, runId) {
  state.scenario = await api.getScenario(id);
  state.runs = await api.listRuns(id);
  const chosen = runId ?? state.runs[0]?.id ?? null;
  await loadRun(chosen);
  fillSelect($("scenario-select"), state.scenarios, (s) => `${s.name} (${s.job_count} jobs)`, id);
  fillSelect($("run-select"), state.runs, runLabel, chosen);
  $("run-select").disabled = state.runs.length === 0;
  $("scenario-select").disabled = false;
  render();
}

async function refreshScenarios(selectId) {
  state.scenarios = await api.listScenarios();
  if (!state.scenarios.length) {
    state.scenario = null;
    state.run = null;
    $("scenario-select").replaceChildren();
    $("run-select").replaceChildren();
    render();
    return;
  }
  await selectScenario(selectId ?? state.scenarios[0].id);
}

async function createSample() {
  const created = await api.generate($("preset-select").value);
  await refreshScenarios(created.id);
}

function setMode(mode) {
  state.mode = mode;
  const comparing = mode === "compare";
  const watching = mode === "watch";
  $("compare").hidden = !comparing;
  $("watch").hidden = !watching;
  $("content").hidden = mode !== "single" || !state.scenario;
  $("controls").inert = comparing;
  document.body.classList.toggle("is-compare", comparing);
  $("compare-btn").setAttribute("aria-pressed", String(comparing));
  $("compare-btn").textContent = comparing ? "Back to schedule" : "Compare runs";
  $("watch-btn").setAttribute("aria-pressed", String(watching));
  $("watch-btn").textContent = watching ? "Back to schedule" : "Watch board";
  if (!watching) watch.stop();
  if (comparing) compare.refit();
}

// --- events ----------------------------------------------------------------------------------

$("scenario-select").addEventListener("change", (event) =>
  guarded(null, () => selectScenario(Number(event.target.value))),
);

$("run-select").addEventListener("change", (event) =>
  guarded(null, async () => {
    await loadRun(Number(event.target.value));
    render();
  }),
);

$("controls").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!state.scenario) return;
  const limit = Math.min(60, Math.max(1, Number($("time-limit").value) || 10));
  $("time-limit").value = String(limit);
  guarded(`Solving, up to ${limit} s`, async () => {
    const run = await api.solve(state.scenario.id, limit, $("no-idle").checked);
    await selectScenario(state.scenario.id, run.id);
  });
});

// Release the selected run to the production floor.
function syncRelease() {
  const run = state.run;
  const ok = Boolean(run && run.assignments?.length && state.scenario?.horizon_start);
  $("release-btn").disabled = !ok;
  $("release-btn").title = ok
    ? "Send the selected run to the production floor"
    : "Needs a solved run on a scenario with a start date";
}

const releaseDialog = $("release-dialog");
$("release-btn").addEventListener("click", () => {
  const run = state.run;
  if (!run) return;
  $("release-sub").textContent = `${state.scenario.name} · run #${run.id} (${run.status}), ${run.assignments.length} orders.`;
  try {
    $("release-by").value = localStorage.getItem("operator") ?? "";
  } catch {
    /* storage unavailable */
  }
  $("release-note").value = "";
  releaseDialog.showModal();
});
$("release-cancel").addEventListener("click", () => releaseDialog.close());
$("release-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const by = $("release-by").value.trim();
  releaseDialog.close();
  try {
    localStorage.setItem("operator", by);
  } catch {
    /* storage unavailable */
  }
  guarded(null, async () => {
    const plan = await api.releasePlan(state.run.id, by, $("release-note").value.trim());
    const notice = $("notice");
    notice.replaceChildren(`Released ${plan.jobs.length} orders to the floor. `);
    const link = document.createElement("a");
    link.href = "floor.html";
    link.textContent = "Open the production floor";
    notice.append(link);
    notice.hidden = false;
  });
});

$("watch-btn").addEventListener("click", () => setMode(state.mode === "watch" ? "single" : "watch"));

$("compare-btn").addEventListener("click", () => {
  if (state.mode === "compare") return setMode("single");
  guarded(null, async () => {
    await compare.open(state.scenarios, state.scenario?.id);
    setMode("compare");
  });
});

for (const id of ["generate-btn", "empty-generate-btn"]) {
  $(id).addEventListener("click", () => guarded(null, createSample));
}

$("late-only").addEventListener("change", (event) => results.setLateOnly(event.target.checked));
$("zoom-fit").addEventListener("click", () => gantt.fit());
$("zoom-full").addEventListener("click", () => gantt.full());
$("zoom-in").addEventListener("click", () => gantt.zoomBy(1.6));
$("zoom-out").addEventListener("click", () => gantt.zoomBy(1 / 1.6));

// Theme: follow the system setting until the viewer picks one.
const themeButton = $("theme-btn");
function currentTheme() {
  return (
    document.documentElement.dataset.theme ?? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
  );
}
function syncThemeButton() {
  const dark = currentTheme() === "dark";
  themeButton.textContent = dark ? "Light mode" : "Dark mode";
  themeButton.setAttribute("aria-pressed", String(dark));
}
themeButton.addEventListener("click", () => {
  const next = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try {
    localStorage.setItem("theme", next);
  } catch {
    /* storage unavailable: the choice lasts for this page view */
  }
  syncThemeButton();
});
syncThemeButton();

results.highlight = results.highlight.bind(results);
$("gantt").addEventListener("pointerover", (event) => {
  const job = event.target.closest?.(".job");
  results.highlight(job ? job.dataset.job : null);
});
$("gantt").addEventListener("pointerleave", () => results.highlight(null));

guarded(null, () => refreshScenarios());
