// Summary figures, utilization meters and the solver panel. All dynamic text uses textContent.

import { availableUnits, fmtDuration, fmtHours, fmtNumber, fmtPercent, fmtWhen } from "./format.js";

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

const SVG_NS = "http://www.w3.org/2000/svg";
const ICONS = {
  check: "M3 8.5l3.2 3.2L13 5",
  alert: "M8 4v5M8 11.5v.5",
  cross: "M4.5 4.5l7 7M11.5 4.5l-7 7",
  help: "M6 6.2a2 2 0 113 1.7c-.7.4-1 .8-1 1.6M8 12v.5",
};

/** A 16px status icon: a ring with a glyph. Always paired with text, never colour alone. */
export function icon(name) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.7");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  const ring = document.createElementNS(SVG_NS, "circle");
  ring.setAttribute("cx", "8");
  ring.setAttribute("cy", "8");
  ring.setAttribute("r", "6.6");
  const glyph = document.createElementNS(SVG_NS, "path");
  glyph.setAttribute("d", ICONS[name]);
  svg.append(ring, glyph);
  return svg;
}

const STATUS = {
  OPTIMAL: { tone: "good", icon: "check", label: "Proven optimal" },
  FEASIBLE: { tone: "warning", icon: "alert", label: "Feasible, not proven optimal" },
  INFEASIBLE: { tone: "critical", icon: "cross", label: "Infeasible" },
  UNKNOWN: { tone: "serious", icon: "help", label: "No schedule found" },
  MODEL_INVALID: { tone: "critical", icon: "cross", label: "Invalid model" },
};

function objectiveName(run) {
  return run.weighted ? "priority-weighted tardiness" : "total tardiness";
}

function explanation(run, minutes) {
  switch (run.status) {
    case "OPTIMAL":
      return `No schedule${run.no_idle ? " that keeps every line busy" : ""} has lower ${objectiveName(run)}. The solver proved this.`;
    case "FEASIBLE": {
      const gap = run.gap == null ? "" : ` The result is within ${fmtPercent(run.gap, 1)} of the best possible.`;
      return `This is the best schedule found within the time limit; it may not be the best that exists.${gap} A longer time limit can improve it.`;
    }
    case "INFEASIBLE":
      return "No schedule can satisfy every constraint within the planning horizon.";
    case "UNKNOWN":
      return "The solver found no schedule within the time limit. Try a longer limit.";
    default:
      return "The solver could not use this scenario.";
  }
}

export function renderStatusLine(root, run, minutes) {
  root.replaceChildren();
  if (!run) {
    const badge = el("span", "badge");
    badge.dataset.tone = "neutral";
    badge.append(icon("help"), document.createTextNode("Not solved yet"));
    root.append(badge, el("span", "status-text", "Choose Solve to place the jobs on the lines."));
    return;
  }
  const s = STATUS[run.status];
  const badge = el("span", "badge");
  badge.dataset.tone = s.tone;
  badge.append(icon(s.icon), document.createTextNode(s.label));
  root.append(badge, el("span", "status-text", explanation(run, minutes)));
}

export function renderKpis(root, run, model) {
  root.replaceChildren();
  const m = run?.metrics;
  if (!m) return;
  // A job that merges several lines has one assignment per line; count each job once.
  const jobs = new Map(run.assignments.map((a) => [a.job_id, a.tardiness]));
  const late = [...jobs.values()].filter((t) => t > 0).length;
  const total = jobs.size;

  const hero = el("div", "hero");
  hero.append(
    el("div", "value", fmtPercent(m.on_time_rate)),
    el("div", "label", "of jobs finish on time"),
    el("div", "sub", `${total - late} of ${total} jobs`),
  );

  const tile = (label, value, sub) => {
    const t = el("div", "tile");
    t.append(el("div", "label", label), el("div", "value", value), el("div", "sub", sub));
    return t;
  };
  root.append(
    hero,
    tile("Total tardiness", fmtDuration(m.total_tardiness, model.minutes), late ? `across ${late} late ${late === 1 ? "job" : "jobs"}` : "no late jobs"),
    tile("Average delay", fmtHours(m.mean_delay ?? 0, model.minutes), "late hours \u00f7 all jobs"),
    tile("Weighted tardiness", fmtNumber(m.weighted_tardiness), "tardiness times priority"),
    tile("Last job ends", fmtDuration(m.makespan, model.minutes), model.horizonStart ? fmtWhen(model, m.makespan) : "from the start"),
  );
}

export function renderUtilization(root, scenario, run) {
  root.replaceChildren();
  if (!run?.metrics) {
    root.append(el("p", "note", "Solve the scenario to see how busy each line is."));
    return;
  }
  const minutes = scenario.time_unit_minutes;
  root.append(
    el("p", "note", "Share of each line's open hours that are used, from the start until the last job ends."),
  );
  const list = el("ul", "meters");
  for (const resource of scenario.instance.resources) {
    const ratio = run.metrics.utilization[resource.id] ?? 0;
    const open = availableUnits(resource.windows, run.metrics.makespan);
    const busy = Math.round(ratio * open);

    const item = el("li", "meter");
    const name = el("span", "name", resource.name);
    name.append(el("span", "detail", `${fmtDuration(busy, minutes)} of ${fmtDuration(open, minutes)} open`));
    const track = el("span", "track");
    const fill = el("span", "fill");
    fill.style.width = `${Math.min(100, ratio * 100)}%`;
    track.append(fill);
    item.append(name, track, el("span", "figure", fmtPercent(ratio)));
    item.setAttribute("aria-label", `${resource.name}: ${fmtPercent(ratio)} utilized`);
    list.append(item);
  }
  root.append(list);
}

export function renderSolver(root, run) {
  root.replaceChildren();
  if (!run) {
    root.append(el("p", "note", "No run yet for this scenario."));
    return;
  }
  const facts = [];
  const objective = run.objective_value == null ? "none" : fmtNumber(run.objective_value);
  facts.push([`Objective (${objectiveName(run)})`, objective]);
  facts.push(["No idle lines", run.no_idle ? "on: lines stay busy while orders wait" : "off"]);
  if (run.best_bound != null) facts.push(["Best possible value", fmtNumber(run.best_bound, 1)]);
  if (run.gap != null) facts.push(["Gap to best possible", fmtPercent(run.gap, 1)]);
  facts.push(["Solve time", `${run.wall_time_s.toFixed(2)} s of ${fmtNumber(run.time_limit_s)} s allowed`]);
  facts.push(["Workers and seed", `${run.num_workers} worker${run.num_workers === 1 ? "" : "s"}, seed ${run.random_seed}`]);
  facts.push(["Solver", `OR-Tools ${run.solver_version}`]);

  const dl = el("dl", "facts");
  for (const [k, v] of facts) dl.append(el("dt", "", k), el("dd", "", v));
  const hash = el("dd", "mono", run.input_hash.slice(0, 12));
  hash.title = run.input_hash;
  dl.append(el("dt", "", "Input fingerprint"), hash);
  root.append(dl);

  if (run.messages.length) {
    const ul = el("ul", "messages");
    for (const m of run.messages) ul.append(el("li", "", m));
    root.append(ul);
  }
}
