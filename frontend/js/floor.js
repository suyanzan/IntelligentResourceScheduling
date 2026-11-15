// Production-floor dashboard: the released plan against what really happened, with the actions
// line staff use to record starts and finishes. All dynamic text uses textContent.

import * as api from "./api.js";
import { groupJobs, groupOf, isDayEnd, lineStates, plantDay, prepareJobs, summarize, variance } from "./floor-logic.js";

const $ = (id) => document.getElementById(id);
const REFRESH_MS = 30_000;
const MIN = 60_000;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

const state = { plan: null, jobs: [], skew: 0, busy: false, viewDay: null };
// Which groups the viewer opened or folded, kept across refreshes.
const groupOpen = new Map();

// --- time helpers (plant time = UTC + plan offset) ---------------------------------------------

const offset = () => (state.plan ? state.plan.utc_offset_minutes : 480);
const nowMs = () => Date.now() + state.skew;
const plantFormat = (options) => new Intl.DateTimeFormat("en-GB", { ...options, timeZone: "UTC", hourCycle: "h23" });
const clockFormat = plantFormat({ hour: "2-digit", minute: "2-digit", second: "2-digit" });
const dayFormat = plantFormat({ weekday: "short", day: "numeric", month: "short" });
const whenFormat = plantFormat({ weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const timeFormat = plantFormat({ hour: "2-digit", minute: "2-digit" });
const shift = (ms) => new Date(ms + offset() * MIN);

/** "Sun 15 Nov 09:00", or just "09:00" when it falls on `sameDayAs`'s day. */
function fmtWhen(ms, sameDayAs) {
  if (sameDayAs != null && plantDay(ms, offset()) === plantDay(sameDayAs, offset())) return timeFormat.format(shift(ms));
  return whenFormat.format(shift(ms));
}

/** A due time: end-of-day deadlines read "Sun 15 Nov 24:00" instead of 00:00 on the next day. */
function fmtDue(ms) {
  if (!isDayEnd(ms, offset())) return fmtWhen(ms);
  const label = whenFormat.format(shift(ms - 1));
  return `${label.replace(/,?\s*\d{2}:\d{2}$/, "")} 24:00`;
}

/** Plant-local "YYYY-MM-DDTHH:mm" for a datetime-local field. */
const toLocalInput = (ms) => shift(ms).toISOString().slice(0, 16);
/** Back to an aware ISO string, or null when the field is empty. */
function fromLocalInput(value) {
  if (!value) return null;
  const ms = Date.parse(`${value}:00Z`) - offset() * MIN;
  return Number.isNaN(ms) ? null : new Date(ms).toISOString();
}

/** The moment the day grouping is anchored to: now, or midday of the day the viewer picked. */
const anchorMs = () => (state.viewDay ? Date.parse(`${state.viewDay}T12:00:00Z`) - offset() * MIN : nowMs());

// --- alerts, operator name, theme --------------------------------------------------------------

function showAlert(message) {
  const box = $("alert");
  box.textContent = message;
  box.hidden = !message;
}

const operator = $("operator");
try {
  operator.value = localStorage.getItem("operator") ?? "";
} catch {
  /* storage unavailable */
}
operator.addEventListener("change", () => {
  try {
    localStorage.setItem("operator", operator.value.trim());
  } catch {
    /* storage unavailable: the name lasts for this page view */
  }
});

const themeButton = $("theme-btn");
const currentTheme = () =>
  document.documentElement.dataset.theme ?? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
function syncTheme() {
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
    /* storage unavailable */
  }
  syncTheme();
});
syncTheme();

// --- loading -----------------------------------------------------------------------------------

function apply(plan) {
  state.plan = plan;
  state.skew = Date.parse(plan.server_time) - Date.now();
  state.jobs = prepareJobs(plan.jobs);
  const filter = $("line-filter");
  if (filter.options.length !== plan.lines.length + 1) {
    const keep = filter.value;
    filter.replaceChildren(new Option("All lines", ""));
    for (const line of plan.lines) filter.append(new Option(line.name, line.id));
    filter.value = plan.lines.some((l) => l.id === keep) ? keep : "";
  }
}

async function refresh() {
  if (state.busy) return;
  try {
    const plan = await api.getActivePlan();
    showAlert("");
    if (!plan) {
      state.plan = null;
      $("no-plan").hidden = false;
      $("plan").hidden = true;
      return;
    }
    apply(plan);
    if (!$("view-day").value) $("view-day").value = plantDay(nowMs(), offset());
    render();
    if ($("log").open) loadLog();
  } catch (error) {
    if (error.status === 404) {
      state.plan = null;
      $("no-plan").hidden = false;
      $("plan").hidden = true;
    } else {
      showAlert(`${error.message} Showing the last data received.`);
    }
  }
}

// --- rendering ---------------------------------------------------------------------------------

const STATUS_TEXT = { planned: "Not started", running: "Running", done: "Finished" };

function tile(label, value, sub, tone) {
  const node = el("div", "tile");
  if (tone) node.dataset.tone = tone;
  node.append(el("div", "label", label), el("div", "value", String(value)), el("div", "sub", sub));
  return node;
}

function renderHeader() {
  const plan = state.plan;
  $("plan-title").textContent = plan.scenario_name;
  const by = plan.released_by ? ` by ${plan.released_by}` : "";
  $("plan-sub").textContent = `Released ${fmtWhen(Date.parse(plan.released_at))}${by}${plan.note ? ` · ${plan.note}` : ""}`;
}

function renderTiles(visible) {
  const now = nowMs();
  const todays = visible.filter((j) => groupOf(j, anchorMs(), offset()) === "today");
  const carried = visible.filter((j) => groupOf(j, anchorMs(), offset()) === "carry");
  const t = summarize(todays, now);
  const all = summarize(visible, now);
  const tiles = $("tiles");
  tiles.replaceChildren(
    tile("Carried over", carried.length, carried.length ? "not finished on earlier days" : "nothing left from before", carried.length ? "late" : "ok"),
    tile(state.viewDay ? "Due that day" : "Due today", `${t.done} / ${t.total}`, "finished", t.total > 0 && t.done === t.total ? "ok" : undefined),
    tile("Running", all.running, "on the lines now", "run"),
    tile("Behind plan", all.behind, all.pastDue ? `${all.pastDue} already past due` : "late start or overrun", all.behind ? "late" : "ok"),
  );
}

function renderLines(visible) {
  const now = nowMs();
  const filter = $("line-filter").value;
  const box = $("lines");
  box.replaceChildren();
  for (const s of lineStates(state.plan.lines, state.jobs, now)) {
    if (filter && s.line.id !== filter) continue;
    const card = el("div", "line");
    card.dataset.level = s.level;
    const head = el("div", "line-head");
    head.append(el("strong", undefined, s.line.name), el("span", "muted", `${s.line.capacity} CPU`));
    const flag = el("span", "flag", s.level === "ok" ? "On plan" : s.level === "behind" ? "Behind plan" : "Needs attention");
    head.append(flag);
    card.append(head);
    if (s.running) {
      const v = variance(s.running, now);
      card.append(el("div", "line-now", `Running: ${s.running.name}`), el("div", `line-sub tone-${v.tone}`, v.text));
    } else {
      card.append(el("div", "line-now idle", "Idle"));
    }
    if (s.next) card.append(el("div", "line-next muted", `Next: ${s.next.name} · planned ${fmtWhen(s.next.plannedStartMs, now)}`));
    for (const issue of s.issues) card.append(el("div", "issue", issue));
    box.append(card);
  }
}

function button(label, className, onClick) {
  const b = el("button", className, label);
  b.type = "button";
  b.addEventListener("click", onClick);
  return b;
}

function row(job) {
  const now = nowMs();
  const v = variance(job, now);
  const item = el("article", "order");
  item.dataset.status = job.status;
  item.dataset.tone = v.tone;

  const head = el("div", "order-head");
  head.append(el("strong", "order-name", job.name));
  if (job.layer) head.append(el("span", "layer-tag", job.layer));
  if (job.after) head.append(el("span", "layer-tag", "follow-up"));
  head.append(el("span", "status", STATUS_TEXT[job.status]));
  item.append(head);

  const facts = el("div", "order-facts");
  facts.append(
    el("span", undefined, `Lines ${job.lines.join(" + ")}`),
    el("span", undefined, `Due ${fmtDue(job.dueMs)}`),
    el("span", undefined, `Plan ${fmtWhen(job.plannedStartMs, now)} → ${fmtWhen(job.plannedEndMs, job.plannedStartMs)}`),
  );
  if (job.cycle_limit_minutes) facts.append(el("span", undefined, `Cycle limit ${job.cycle_limit_minutes / 60} h`));
  item.append(facts);

  if (job.actualStartMs != null) {
    const end = job.actualEndMs != null ? fmtWhen(job.actualEndMs, job.actualStartMs) : "in progress";
    item.append(el("div", "order-actual", `Actual ${fmtWhen(job.actualStartMs, now)} → ${end}`));
  }
  item.append(el("div", `order-variance tone-${v.tone}`, v.text));
  if (job.note) item.append(el("div", "order-note", `Note: ${job.note}${job.updated_by ? ` — ${job.updated_by}` : ""}`));

  const actions = el("div", "order-actions");
  const active = state.plan.active;
  if (active && job.status === "planned") actions.append(button("Start", "primary", () => openDialog("start", job)));
  if (active && job.status !== "done") actions.append(button("Finish", job.status === "running" ? "primary" : "", () => openDialog("complete", job)));
  if (active && job.status !== "planned") actions.append(button("Undo", "", () => openDialog("revert", job)));
  if (active) actions.append(button("Note", "", () => openDialog("note", job)));
  item.append(actions);
  return item;
}

function renderGroups(visible) {
  const hideDone = $("hide-done").checked;
  const container = $("groups");
  container.replaceChildren();
  const groups = groupJobs(visible, anchorMs(), offset());
  if (state.viewDay) {
    // One day picked: show only the orders due that day (plus, optionally, unfinished ones from before).
    const keep = new Set(["today", ...($("with-carry").checked ? ["carry"] : [])]);
    groups.splice(0, groups.length, ...groups.filter((g) => keep.has(g.key)));
    const label = (days) => dayFormat.format(new Date(anchorMs() + offset() * MIN + days * 86_400_000));
    const titles = { today: label(0), tomorrow: label(1), dayAfter: label(2) };
    for (const g of groups) if (titles[g.key]) g.title = titles[g.key];
  }
  if (!groups.length) {
    container.append(el("p", "muted", state.viewDay ? "No orders are due on this day." : "No orders match this filter."));
  }
  for (const group of groups) {
    const shown = hideDone ? group.jobs.filter((j) => j.status !== "done") : group.jobs;
    const section = el("details", "group");
    section.dataset.key = group.key;
    // Today and carried-over orders open by default; the rest stay folded until the viewer opens them.
    const defaultOpen = group.key === "carry" || group.key === "today";
    section.open = groupOpen.has(group.key) ? groupOpen.get(group.key) : defaultOpen;
    const summary = el("summary");
    const counts = summarize(group.jobs, nowMs());
    summary.append(el("span", "group-title", group.title));
    summary.append(el("span", "group-count", `${counts.done} / ${counts.total} finished`));
    if (counts.behind) summary.append(el("span", "group-behind", `${counts.behind} behind plan`));
    if (group.hint) summary.append(el("span", "muted", group.hint));
    section.append(summary);
    if (!shown.length) section.append(el("p", "muted group-empty", hideDone ? "Everything here is finished." : "Nothing here."));
    for (const job of shown) section.append(row(job));
    section.addEventListener("toggle", () => groupOpen.set(group.key, section.open));
    container.append(section);
  }
}

function visibleJobs() {
  const line = $("line-filter").value;
  return line ? state.jobs.filter((j) => j.lines.includes(line)) : state.jobs;
}

function render() {
  if (!state.plan) return;
  $("no-plan").hidden = true;
  $("plan").hidden = false;
  const visible = visibleJobs();
  renderHeader();
  renderTiles(visible);
  renderLines(visible);
  renderGroups(visible);
  if (!state.plan.active) showAlert("This plan has been replaced by a newer release. It is shown read-only.");
}

// --- dialog ------------------------------------------------------------------------------------

const dialog = $("dialog");
let pending = null;

function show(id, visible) {
  $(id).hidden = !visible;
}

function openDialog(kind, job) {
  const now = nowMs();
  pending = { kind, job };
  $("dlg-error").hidden = true;
  $("dlg-note").value = kind === "note" ? job.note : "";
  const titles = { start: "Start order", complete: "Finish order", revert: "Undo last step", note: "Note / delay reason" };
  $("dialog-title").textContent = `${titles[kind]} — ${job.name}`;
  const subs = {
    start: `Planned start ${fmtWhen(job.plannedStartMs, now)} on ${job.lines.join(" + ")}.`,
    complete: `Planned finish ${fmtWhen(job.plannedEndMs, now)}.`,
    revert: job.status === "done" ? "The order goes back to Running; its finish time is cleared." : "The order goes back to Not started; its start time is cleared.",
    note: "Visible to everyone watching this plan.",
  };
  $("dialog-sub").textContent = subs[kind];
  const needsStart = kind === "complete" && job.actualStartMs == null;
  show("dlg-start-row", kind === "start" || needsStart);
  show("dlg-end-row", kind === "complete");
  show("dlg-note-row", kind !== "revert");
  $("dlg-start").value = toLocalInput(kind === "start" ? now : job.plannedStartMs);
  $("dlg-end").value = toLocalInput(now);
  $("dlg-ok").textContent = kind === "revert" ? "Undo" : "Save";
  dialog.showModal();
  const first = kind === "note" ? $("dlg-note") : $("dlg-ok");
  first.focus();
}

$("dlg-cancel").addEventListener("click", () => dialog.close());

$("dialog-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!pending) return;
  const { kind, job } = pending;
  const by = operator.value.trim();
  const note = $("dlg-note").value.trim();
  let body;
  if (kind === "start") {
    body = { at: fromLocalInput($("dlg-start").value), by };
    if (note) body.note = note;
  } else if (kind === "complete") {
    body = { at: fromLocalInput($("dlg-end").value), by };
    if (job.actualStartMs == null) {
      body.started_at = fromLocalInput($("dlg-start").value);
      if (!body.started_at) return fail("Enter when the order really started.");
    }
    if (note) body.note = note;
  } else if (kind === "revert") {
    body = { by };
  } else {
    body = { note, by };
  }
  if ("at" in body && !body.at) return fail("Enter a time.");
  $("dlg-ok").disabled = true;
  state.busy = true;
  try {
    const plan = await api.floorAction(state.plan.id, job.id, kind, body);
    apply(plan);
    dialog.close();
    render();
    if ($("log").open) loadLog();
  } catch (error) {
    fail(error.message);
    if (error.status === 409) setTimeout(refresh, 0);
  } finally {
    state.busy = false;
    $("dlg-ok").disabled = false;
  }
});

function fail(message) {
  const box = $("dlg-error");
  box.textContent = message;
  box.hidden = false;
}

// --- activity log ------------------------------------------------------------------------------

const ACTION_TEXT = { start: "started", complete: "finished", revert: "undid", note: "noted", release: "released the plan" };

async function loadLog() {
  if (!state.plan) return;
  try {
    const events = await api.getPlanEvents(state.plan.id);
    const list = $("log-list");
    list.replaceChildren();
    for (const e of [...events].reverse()) {
      const who = e.actor || "Someone";
      const what = e.job_name ? `${ACTION_TEXT[e.action] ?? e.action} ${e.job_name}` : ACTION_TEXT[e.action] ?? e.action;
      const at = e.effective_at ? ` (at ${fmtWhen(Date.parse(e.effective_at), nowMs())})` : "";
      const note = e.note ? ` — ${e.note}` : "";
      list.append(el("li", undefined, `${fmtWhen(Date.parse(e.recorded_at))} · ${who} ${what}${at}${note}`));
    }
    if (!events.length) list.append(el("li", "muted", "Nothing recorded yet."));
  } catch (error) {
    showAlert(error.message);
  }
}
$("log").addEventListener("toggle", () => $("log").open && loadLog());

// --- clock and wiring --------------------------------------------------------------------------

function tickClock() {
  const t = shift(nowMs());
  $("clock-time").textContent = clockFormat.format(t);
  $("clock-day").textContent = dayFormat.format(t);
}

function setViewDay(value) {
  state.viewDay = value || null;
  groupOpen.clear();
  $("view-day").value = state.viewDay ?? plantDay(nowMs(), offset());
  $("today-btn").hidden = !state.viewDay;
  $("carry-row").hidden = !state.viewDay;
  render();
}
$("view-day").addEventListener("change", () => setViewDay($("view-day").value));
$("today-btn").addEventListener("click", () => setViewDay(null));
$("line-filter").addEventListener("change", render);
$("hide-done").addEventListener("change", render);
$("with-carry").addEventListener("change", render);

tickClock();
setInterval(tickClock, 1000);
setInterval(() => {
  if (!dialog.open && !document.hidden) refresh();
}, REFRESH_MS);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && !dialog.open) refresh();
});
refresh();
