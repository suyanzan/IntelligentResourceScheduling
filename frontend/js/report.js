// Management report: the three-day execution picture as charts. Text is kept to labels and numbers.
/* global d3 */

import * as api from "./api.js";
import { prepareJobs } from "./floor-logic.js";
import { classify, curves, dayDials, kpis, utilization, worstDelays } from "./report-logic.js";

const $ = (id) => document.getElementById(id);
const MIN = 60_000;

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

// --- hero: one dial per day, one segment per order ---------------------------------------------

const ICONS = {
  check: "M5 13.5l5 5 11-11",
  flag: "M7 22V5m0 0h12l-3 4.5L19 14H7",
  alert: "M13 6v9m0 4.5v.5",
  clock: "M13 7v6l4 2.5",
};

function icon(name, color) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 26 26");
  svg.setAttribute("aria-hidden", "true");
  const ring = document.createElementNS(svg.namespaceURI, "circle");
  for (const [k, v] of Object.entries({ cx: 13, cy: 13, r: 11.5, fill: "none", stroke: color, "stroke-opacity": 0.5, "stroke-width": 1.4 })) ring.setAttribute(k, v);
  const path = document.createElementNS(svg.namespaceURI, "path");
  for (const [k, v] of Object.entries({ d: ICONS[name], fill: "none", stroke: color, "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round" })) path.setAttribute(k, v);
  svg.append(ring, path);
  return svg;
}

function renderDials(jobs) {
  const root = $("dials");
  root.replaceChildren();
  const arc = d3.arc().innerRadius(70).outerRadius(92).padAngle(0.035).cornerRadius(2.5);
  for (const dial of dayDials(jobs, nowMs(), offset())) {
    const box = d3.select(root).append("div").attr("class", "dial");
    const svg = box.append("svg").attr("viewBox", "0 0 200 200").attr("role", "img")
      .attr("aria-label", `${dayLabel(new Date(`${dial.day}T00:00:00Z`))}: ${dial.done} of ${dial.total} finished`);
    const g = svg.append("g").attr("transform", "translate(100,100)");
    const step = (2 * Math.PI) / dial.total;
    dial.items.forEach((item, i) => {
      g.append("path").attr("class", `seg ${item.kind}`)
        .attr("d", arc({ startAngle: i * step, endAngle: (i + 1) * step }))
        .append("title").text(item.name);
    });
    g.append("text").attr("class", "big").attr("text-anchor", "middle").attr("y", 8).text(`${Math.round((dial.done / dial.total) * 100)}%`);
    g.append("text").attr("class", "small").attr("text-anchor", "middle").attr("y", 28).text(`${dial.done} / ${dial.total}`);
    box.append("div").attr("class", "day").text(dayLabel(new Date(`${dial.day}T00:00:00Z`)));
  }
}

function renderStats(jobs) {
  const k = kpis(jobs, nowMs());
  const root = $("stats");
  root.replaceChildren();
  const rows = [
    { icon: "check", color: "#5fd6a0", n: `${k.done}/${k.total}`, l: "Finished", tone: "ok" },
    { icon: "clock", color: "#f1cb52", n: String(k.behind), l: "Behind plan", tone: k.behind ? "warn" : "ok" },
    { icon: "alert", color: "#ff8a77", n: String(k.counts.overdue + k.counts.late), l: "Past due", tone: k.late ? "bad" : "ok" },
    { icon: "flag", color: "#9fbcc2", n: `${fmtHour(Math.round(k.meanDelayHours * 10) / 10)} h`, l: "Mean delay", tone: k.meanDelayHours > 0 ? "bad" : "ok" },
  ];
  for (const row of rows) {
    const stat = document.createElement("div");
    stat.className = "stat";
    stat.dataset.tone = row.tone;
    stat.append(icon(row.icon, row.color));
    const text = document.createElement("div");
    const n = document.createElement("div");
    n.className = "n";
    n.textContent = row.n;
    const l = document.createElement("div");
    l.className = "l";
    l.textContent = row.l;
    text.append(n, l);
    stat.append(text);
    root.append(stat);
  }
}

// --- cumulative curves ------------------------------------------------------------------------

function renderCurve(jobs) {
  const c = curves(jobs, nowMs());
  const H = 250;
  const { svg, width } = svgIn($("chart-curve"), H, "Cumulative orders due, planned and finished");
  const m = { left: 36, right: 34, top: 14, bottom: 26 };
  const t0 = d3.min(jobs, (j) => j.plannedStartMs);
  const t1 = d3.max([...jobs.map((j) => j.dueMs), ...jobs.map((j) => j.plannedEndMs)]);
  const x = d3.scaleUtc().domain([px(t0), px(t1)]).range([m.left, width - m.right]);
  const y = d3.scaleLinear().domain([0, jobs.length]).range([H - m.bottom, m.top]);
  const defs = svg.append("defs");
  const grad = defs.append("linearGradient").attr("id", "area-ok").attr("x1", 0).attr("x2", 0).attr("y1", 0).attr("y2", 1);
  grad.append("stop").attr("offset", "0%").attr("stop-color", "#2bb673").attr("stop-opacity", 0.35);
  grad.append("stop").attr("offset", "100%").attr("stop-color", "#2bb673").attr("stop-opacity", 0);
  svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.bottom})`).call(d3.axisBottom(x).ticks(d3.utcDay.every(1)).tickFormat(dayLabel).tickSizeOuter(0));
  svg.append("g").attr("class", "axis").attr("transform", `translate(${m.left},0)`).call(d3.axisLeft(y).ticks(4).tickSizeOuter(0).tickSize(-(width - m.left - m.right))).call((g) => g.selectAll(".tick line").attr("class", "grid")).call((g) => g.select(".domain").remove());
  const line = d3.line().curve(d3.curveStepAfter).x((d) => x(px(d[0]))).y((d) => y(d[1]));
  const until = Math.min(nowMs(), t1);
  const actual = [[t0, 0], ...c.actual, [until, c.actual.length]];
  svg.append("path").attr("fill", "url(#area-ok)").attr("d", d3.area().curve(d3.curveStepAfter).x((d) => x(px(d[0]))).y0(y(0)).y1((d) => y(d[1]))(actual));
  svg.append("path").attr("class", "curve-due").attr("d", line([[t0, 0], ...c.due]));
  svg.append("path").attr("class", "curve-plan").attr("d", line([[t0, 0], ...c.plan]));
  svg.append("path").attr("class", "curve-actual").attr("d", line(actual));
  svg.append("circle").attr("cx", x(px(until))).attr("cy", y(c.actual.length)).attr("r", 5).attr("fill", "var(--ok)").attr("stroke", "var(--surface)").attr("stroke-width", 2);
  const key = [["curve-due", "Due"], ["curve-plan", "Plan"], ["curve-actual", "Actual"]];
  key.forEach(([cls, label], i) => {
    const kx = m.left + 10 + i * 78;
    svg.append("line").attr("class", cls).attr("x1", kx).attr("x2", kx + 18).attr("y1", m.top + 8).attr("y2", m.top + 8);
    svg.append("text").attr("x", kx + 24).attr("y", m.top + 12).text(label);
  });
}

// --- plan vs actual per line ------------------------------------------------------------------

function renderGantt(jobs) {
  const now = nowMs();
  const rowH = 46;
  const m = { left: 44, right: 34, top: 28, bottom: 6 };
  const lines = plan.lines;
  const h = m.top + lines.length * rowH + m.bottom;
  const { svg, width } = svgIn($("chart-gantt"), h, "Planned and actual work per line");
  const t0 = d3.min(jobs, (j) => j.plannedStartMs);
  const t1 = Math.max(d3.max(jobs, (j) => j.dueMs), d3.max(jobs, (j) => j.plannedEndMs), d3.max(jobs, (j) => j.actualEndMs ?? 0));
  const x = d3.scaleUtc().domain([px(t0), px(t1)]).range([m.left, width - m.right]);
  const days = x.ticks(d3.utcDay.every(1));
  days.forEach((d, i) => {
    const next = days[i + 1] ?? x.domain()[1];
    if (i % 2 === 0) svg.append("rect").attr("class", "band").attr("x", x(d)).attr("y", m.top).attr("width", Math.max(0, x(next) - x(d))).attr("height", h - m.top - m.bottom);
    if (x(d) + 56 < width) svg.append("text").attr("x", x(d) + 6).attr("y", m.top - 10).text(dayLabel(d));
  });
  lines.forEach((line, i) => {
    const y = m.top + i * rowH;
    svg.append("text").attr("x", m.left - 12).attr("y", y + 28).attr("text-anchor", "end").attr("class", "val").style("font-size", "14px").text(line.id);
    const bx = (ms) => x(px(ms));
    for (const job of jobs.filter((j) => j.lines.includes(line.id))) {
      svg.append("rect").attr("class", "plan-bar").attr("x", bx(job.plannedStartMs)).attr("y", y + 7)
        .attr("width", Math.max(2, bx(job.plannedEndMs) - bx(job.plannedStartMs) - 1)).attr("height", 8).attr("rx", 3);
      if (job.actualStartMs != null) {
        const end = job.actualEndMs ?? now;
        const cls = job.status === "done" ? ({ ontime: "ok", late: "warn" })[classify(job, now)] : end > job.dueMs ? "bad" : "open";
        svg.append("rect").attr("class", cls).attr("x", bx(job.actualStartMs)).attr("y", y + 20)
          .attr("width", Math.max(2, bx(end) - bx(job.actualStartMs) - 1)).attr("height", 16).attr("rx", 4)
          .append("title").text(job.name);
      }
    }
  });
  if (now >= t0 && now <= t1) svg.append("line").attr("class", "now-line").attr("x1", x(px(now))).attr("x2", x(px(now))).attr("y1", m.top - 4).attr("y2", h - m.bottom);
}

// --- most overdue (lollipops) and hours per line (gauges) -------------------------------------

function renderLate(jobs) {
  const items = worstDelays(jobs, nowMs(), 8);
  const rowH = 30;
  const { svg, width } = svgIn($("chart-late"), Math.max(70, items.length * rowH + 10), "Orders furthest past due");
  if (!items.length) {
    const g = svg.append("g").attr("transform", "translate(30,34)");
    g.append("circle").attr("r", 20).attr("fill", "none").attr("stroke", "var(--ok)").attr("stroke-width", 2.5);
    g.append("path").attr("d", "M-8 0l6 6 11-12").attr("fill", "none").attr("stroke", "var(--ok)").attr("stroke-width", 3).attr("stroke-linecap", "round").attr("stroke-linejoin", "round");
    return;
  }
  const m = { left: 92, right: 52 };
  const x = d3.scaleLinear().domain([0, d3.max(items, (d) => d.hours)]).range([0, width - m.left - m.right]);
  items.forEach((d, i) => {
    const y = 6 + i * rowH;
    const tone = d.finished ? "warn" : "bad";
    svg.append("text").attr("x", m.left - 10).attr("y", y + 15).attr("text-anchor", "end").text(d.name.replace("MaskOPCOrder", "OPC"));
    svg.append("line").attr("class", `stem ${tone}`).attr("x1", m.left).attr("x2", m.left + Math.max(4, x(d.hours))).attr("y1", y + 11).attr("y2", y + 11);
    svg.append("circle").attr("class", `dot ${tone}`).attr("cx", m.left + Math.max(4, x(d.hours))).attr("cy", y + 11).attr("r", 6);
    svg.append("text").attr("class", "val").attr("x", m.left + Math.max(4, x(d.hours)) + 14).attr("y", y + 15).text(fmtHour(Math.round(d.hours * 10) / 10));
  });
}

function renderHours() {
  const rows = utilization(plan.lines, jobsAll, nowMs());
  const { svg, width } = svgIn($("chart-hours"), 150, "Hours worked against plan, per line");
  const cell = width / rows.length;
  const r = Math.min(34, cell / 2 - 12);
  const arc = d3.arc().innerRadius(r - 8).outerRadius(r).startAngle(0).cornerRadius(4);
  rows.forEach((row, i) => {
    const g = svg.append("g").attr("transform", `translate(${cell * i + cell / 2},58)`);
    const ratio = row.planned > 0 ? Math.min(1, row.actual / row.planned) : 0;
    g.append("path").attr("d", arc({ endAngle: 2 * Math.PI })).attr("fill", "var(--grid)");
    if (ratio > 0) g.append("path").attr("d", arc({ endAngle: 2 * Math.PI * ratio })).attr("fill", "var(--ok)");
    g.append("text").attr("class", "val").attr("text-anchor", "middle").attr("y", 6).style("font-size", "16px").text(row.id);
    g.append("text").attr("text-anchor", "middle").attr("y", r + 24).text(`${fmtHour(Math.round(row.actual))} / ${fmtHour(Math.round(row.planned))} h`);
  });
}

// --- loading ----------------------------------------------------------------------------------

let jobsAll = [];

function render() {
  jobsAll = prepareJobs(plan.jobs);
  const fmt = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "UTC" });
  $("asof").textContent = fmt.format(px(nowMs()));
  renderDials(jobsAll);
  renderStats(jobsAll);
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
