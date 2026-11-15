// Management report: the three-day execution picture as charts. Text is kept to labels and numbers.
/* global d3 */

import * as api from "./api.js";
import { prepareJobs } from "./floor-logic.js";
import { classify, curves, kpis, perDay, utilization, worstDelays } from "./report-logic.js";

const $ = (id) => document.getElementById(id);
const MIN = 60_000;
const HOUR = 3_600_000;

let plan = null;
let skew = 0;

const offset = () => plan.utc_offset_minutes;
const nowMs = () => Date.now() + skew;
/** Plant time drawn on a UTC axis: shift by the plan's offset. */
const px = (ms) => new Date(ms + offset() * MIN);
const fmtHour = (h) => (Number.isInteger(h) ? `${h}` : h.toFixed(1));
const dayLabel = d3.utcFormat("%a %-d");

function svgIn(container, height, label) {
  const width = Math.max(280, container.clientWidth || 320);
  container.replaceChildren();
  return {
    width,
    svg: d3.select(container).append("svg").attr("viewBox", `0 0 ${width} ${height}`).attr("width", "100%")
      .attr("role", "img").attr("aria-label", label),
  };
}

// --- KPI row -----------------------------------------------------------------------------------

function ring(svg, ratio, cls) {
  const r = 26;
  const g = svg.append("g").attr("transform", "translate(32,32)");
  g.append("circle").attr("r", r).attr("fill", "none").attr("stroke-width", 8).attr("class", "ring-bg");
  g.append("circle").attr("r", r).attr("fill", "none").attr("stroke-width", 8).attr("class", `ring-fg ${cls}`)
    .attr("stroke-linecap", "round").attr("transform", "rotate(-90)")
    .attr("stroke-dasharray", `${2 * Math.PI * r * Math.min(1, ratio)} ${2 * Math.PI * r}`);
}

function kpiTile(parent, { value, caption, ratio, cls, tone }) {
  const tile = d3.select(parent).append("div").attr("class", "kpi");
  if (tone) tile.attr("data-tone", tone);
  if (ratio != null) ring(tile.append("svg").attr("width", 64).attr("height", 64), ratio, cls ?? "");
  const text = tile.append("div");
  text.append("div").attr("class", "num").text(value);
  text.append("div").attr("class", "cap").text(caption);
}

function renderKpis(jobs) {
  const k = kpis(jobs, nowMs());
  const root = $("kpis");
  root.replaceChildren();
  kpiTile(root, { value: `${Math.round(k.onTimeRate * 100)}%`, caption: "On time", ratio: k.onTimeRate, tone: k.onTimeRate >= 0.9 ? "ok" : undefined });
  kpiTile(root, { value: `${k.done}/${k.total}`, caption: "Finished", ratio: k.doneRate, cls: "blue" });
  kpiTile(root, { value: String(k.late), caption: "Late or overdue", tone: k.late ? "bad" : "ok" });
  kpiTile(root, { value: `${fmtHour(Math.round(k.meanDelayHours * 10) / 10)} h`, caption: "Mean delay", tone: k.meanDelayHours > 0 ? "bad" : "ok" });
}

// --- per-day stacked bars ---------------------------------------------------------------------

function renderDays(jobs) {
  const days = perDay(jobs, nowMs(), offset());
  const h = 40 + days.length * 54;
  const { svg, width } = svgIn($("chart-days"), h, "Orders per due day by outcome");
  const m = { left: 64, right: 16, top: 6 };
  const x = d3.scaleLinear().domain([0, 1]).range([m.left, width - m.right]);
  days.forEach((d, i) => {
    const y = m.top + i * 54;
    const g = svg.append("g").attr("transform", `translate(0,${y})`);
    g.append("text").attr("x", m.left - 10).attr("y", 20).attr("text-anchor", "end").attr("class", "val")
      .text(dayLabel(new Date(`${d.day}T00:00:00Z`)));
    let acc = 0;
    for (const cls of ["ontime", "late", "overdue", "open"]) {
      if (!d[cls]) continue;
      const w = (d[cls] / d.total) * (width - m.right - m.left);
      g.append("rect").attr("class", cls).attr("x", x(0) + acc).attr("y", 4).attr("width", Math.max(0, w - 2)).attr("height", 30).attr("rx", 4)
        .append("title").text(`${cls}: ${d[cls]}`);
      if (w > 26) g.append("text").attr("x", x(0) + acc + w / 2 - 1).attr("y", 24).attr("text-anchor", "middle")
        .attr("fill", "#fff").style("fill", "#fff").style("font-weight", 600).text(d[cls]);
      acc += w;
    }
  });
}

// --- cumulative curves ------------------------------------------------------------------------

function renderCurve(jobs) {
  const c = curves(jobs, nowMs());
  const { svg, width } = svgIn($("chart-curve"), 240, "Cumulative orders due, planned and finished");
  const m = { left: 36, right: 34, top: 10, bottom: 26 };
  const t0 = d3.min(jobs, (j) => j.plannedStartMs);
  const t1 = d3.max([...jobs.map((j) => j.dueMs), ...jobs.map((j) => j.plannedEndMs)]);
  const x = d3.scaleUtc().domain([px(t0), px(t1)]).range([m.left, width - m.right]);
  const y = d3.scaleLinear().domain([0, jobs.length]).range([240 - m.bottom, m.top]);
  const line = d3.line().curve(d3.curveStepAfter).x((d) => x(px(d[0]))).y((d) => y(d[1]));
  svg.append("g").attr("class", "axis").attr("transform", `translate(0,${240 - m.bottom})`).call(d3.axisBottom(x).ticks(d3.utcDay.every(1)).tickFormat(dayLabel).tickSizeOuter(0));
  svg.append("g").attr("class", "axis").attr("transform", `translate(${m.left},0)`).call(d3.axisLeft(y).ticks(5).tickSizeOuter(0));
  const path = (cls, data, until) => svg.append("path").attr("class", cls).attr("d", line([[t0, 0], ...data, ...(until ? [[until, data.length]] : [])]));
  path("curve-due", c.due);
  path("curve-plan", c.plan);
  path("curve-actual", c.actual, Math.min(nowMs(), t1));
  const now = nowMs();
  if (now >= t0 && now <= t1) svg.append("line").attr("class", "now-line").attr("x1", x(px(now))).attr("x2", x(px(now))).attr("y1", m.top).attr("y2", 240 - m.bottom);
  const key = [["curve-due", "Due"], ["curve-plan", "Plan"], ["curve-actual", "Actual"]];
  key.forEach(([cls, label], i) => {
    const kx = m.left + 8 + i * 70;
    svg.append("line").attr("class", cls).attr("x1", kx).attr("x2", kx + 16).attr("y1", m.top + 8).attr("y2", m.top + 8);
    svg.append("text").attr("x", kx + 20).attr("y", m.top + 12).text(label);
  });
}

// --- plan vs actual per line ------------------------------------------------------------------

function renderGantt(jobs) {
  const now = nowMs();
  const rowH = 44;
  const m = { left: 64, right: 34, top: 26, bottom: 6 };
  const lines = plan.lines;
  const h = m.top + lines.length * rowH + m.bottom;
  const { svg, width } = svgIn($("chart-gantt"), h, "Planned and actual work per line");
  const t0 = d3.min(jobs, (j) => j.plannedStartMs);
  const t1 = Math.max(d3.max(jobs, (j) => j.dueMs), d3.max(jobs, (j) => j.plannedEndMs), d3.max(jobs, (j) => j.actualEndMs ?? 0));
  const x = d3.scaleUtc().domain([px(t0), px(t1)]).range([m.left, width - m.right]);
  const hours = d3.utcHour.every(6);
  svg.append("g").attr("class", "axis").attr("transform", `translate(0,${m.top - 4})`).call(d3.axisTop(x).ticks(hours).tickFormat((d) => (d.getUTCHours() === 0 ? dayLabel(d) : "")).tickSize(0));
  for (const tick of x.ticks(d3.utcDay.every(1))) {
    svg.append("line").attr("class", "grid").attr("x1", x(tick)).attr("x2", x(tick)).attr("y1", m.top).attr("y2", h - m.bottom).style("stroke-width", 1.5);
  }
  lines.forEach((line, i) => {
    const y = m.top + i * rowH;
    svg.append("text").attr("x", m.left - 10).attr("y", y + 26).attr("text-anchor", "end").attr("class", "val").text(line.id);
    svg.append("line").attr("class", "grid").attr("x1", m.left).attr("x2", width - m.right).attr("y1", y + rowH).attr("y2", y + rowH);
    for (const job of jobs.filter((j) => j.lines.includes(line.id))) {
      const bx = (ms) => x(px(ms));
      svg.append("rect").attr("class", "plan-bar").attr("x", bx(job.plannedStartMs)).attr("y", y + 6)
        .attr("width", Math.max(2, bx(job.plannedEndMs) - bx(job.plannedStartMs))).attr("height", 9).attr("rx", 2);
      if (job.actualStartMs != null) {
        const end = job.actualEndMs ?? now;
        const cls = job.status === "done" ? classify(job, now) : end > job.dueMs ? "overdue" : "open";
        svg.append("rect").attr("class", cls).attr("x", bx(job.actualStartMs)).attr("y", y + 19)
          .attr("width", Math.max(2, bx(end) - bx(job.actualStartMs))).attr("height", 15).attr("rx", 3)
          .append("title").text(job.name);
      }
    }
  });
  if (now >= t0 && now <= t1) svg.append("line").attr("class", "now-line").attr("x1", x(px(now))).attr("x2", x(px(now))).attr("y1", m.top).attr("y2", h - m.bottom);
}

// --- worst delays and line hours --------------------------------------------------------------

function renderLate(jobs) {
  const items = worstDelays(jobs, nowMs(), 8);
  const rowH = 28;
  const { svg, width } = svgIn($("chart-late"), Math.max(60, items.length * rowH + 10), "Orders furthest past due");
  if (!items.length) {
    svg.append("text").attr("x", 8).attr("y", 30).style("font-size", "28px").style("fill", "var(--good)").text("✓");
    return;
  }
  const m = { left: 96, right: 44 };
  const x = d3.scaleLinear().domain([0, d3.max(items, (d) => d.hours)]).range([0, width - m.left - m.right]);
  items.forEach((d, i) => {
    const y = 4 + i * rowH;
    svg.append("text").attr("x", m.left - 8).attr("y", y + 16).attr("text-anchor", "end").text(d.name.replace("MaskOPCOrder", "OPC"));
    svg.append("rect").attr("class", d.finished ? "late" : "overdue").attr("x", m.left).attr("y", y + 3).attr("width", Math.max(2, x(d.hours))).attr("height", 18).attr("rx", 3);
    svg.append("text").attr("class", "val").attr("x", m.left + x(d.hours) + 6).attr("y", y + 16).text(fmtHour(Math.round(d.hours * 10) / 10));
  });
}

function renderHours() {
  const rows = utilization(plan.lines, jobsAll, nowMs());
  const rowH = 38;
  const { svg, width } = svgIn($("chart-hours"), rows.length * rowH + 10, "Planned and actual hours per line");
  const m = { left: 36, right: 44 };
  const max = d3.max(rows, (r) => Math.max(r.planned, r.actual)) || 1;
  const x = d3.scaleLinear().domain([0, max]).range([0, width - m.left - m.right]);
  rows.forEach((r, i) => {
    const y = 4 + i * rowH;
    svg.append("text").attr("class", "val").attr("x", m.left - 10).attr("y", y + 20).attr("text-anchor", "end").text(r.id);
    svg.append("rect").attr("class", "plan-bar").attr("x", m.left).attr("y", y + 2).attr("width", Math.max(1, x(r.planned))).attr("height", 12).attr("rx", 2);
    svg.append("rect").attr("class", "ontime").attr("x", m.left).attr("y", y + 17).attr("width", Math.max(1, x(r.actual))).attr("height", 14).attr("rx", 3);
    svg.append("text").attr("x", m.left + Math.max(x(r.planned), x(r.actual)) + 6).attr("y", y + 22).text(`${fmtHour(Math.round(r.actual))}/${fmtHour(Math.round(r.planned))}`);
  });
}

// --- loading ----------------------------------------------------------------------------------

let jobsAll = [];

function render() {
  jobsAll = prepareJobs(plan.jobs);
  const fmt = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "UTC" });
  $("asof").textContent = fmt.format(px(nowMs()));
  renderKpis(jobsAll);
  renderDays(jobsAll);
  renderCurve(jobsAll);
  renderGantt(jobsAll);
  renderLate(jobsAll);
  renderHours();
}

async function refresh() {
  try {
    const data = await api.getActivePlan();
    $("alert").hidden = true;
    if (!data) throw Object.assign(new Error("no plan"), { status: 404 });
    plan = data;
    skew = Date.parse(data.server_time) - Date.now();
    $("no-plan").hidden = true;
    $("board").hidden = false;
    render();
  } catch (error) {
    if (error.status === 404) {
      $("board").hidden = true;
      $("no-plan").hidden = false;
    } else {
      $("alert").textContent = `${error.message} Showing the last data received.`;
      $("alert").hidden = false;
    }
  }
}

const themeButton = $("theme-btn");
const currentTheme = () => document.documentElement.dataset.theme ?? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
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
$("print-btn").addEventListener("click", () => window.print());

let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => plan && render(), 150);
});
setInterval(() => !document.hidden && refresh(), 60_000);
refresh();
