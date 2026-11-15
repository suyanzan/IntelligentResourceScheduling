// Gantt chart: one row per resource, one bar per job. A job that finishes after its due date is
// drawn blue up to the due date and red from the due date on, so lateness is visible as a tail.
// Closed periods (nights, weekends, maintenance) are shaded. Drag to pan, buttons or Ctrl+wheel
// to zoom.

import { closedPeriods, fmtDay, fmtDue, fmtDuration, fmtNumber, fmtWhen } from "./format.js";

const ROW_H = 54;
const BAR_H = 22;
const GAP = 2; // surface gap between touching bars
const MARGIN = { top: 34, right: 16, bottom: 10, left: 140 };
const CHAR_W = 6.6;

/** Path for a rectangle with individually rounded corners (4px at the data ends). */
function roundedRect(x, y, w, h, r, { left = true, right = true } = {}) {
  const rl = left ? Math.min(r, w / 2) : 0;
  const rr = right ? Math.min(r, w / 2) : 0;
  return (
    `M${x + rl},${y} H${x + w - rr} ` +
    (rr ? `Q${x + w},${y} ${x + w},${y + rr} V${y + h - rr} Q${x + w},${y + h} ${x + w - rr},${y + h} ` : `V${y + h} `) +
    `H${x + rl} ` +
    (rl ? `Q${x},${y + h} ${x},${y + h - rl} V${y + rl} Q${x},${y} ${x + rl},${y} ` : `V${y} `) +
    "Z"
  );
}

export function createGantt(root, tooltip) {
  const svg = d3.select(root).append("svg").attr("class", "gantt").attr("role", "group");
  const content = svg.append("g");
  const clipId = `clip-${Math.random().toString(36).slice(2, 8)}`;
  const clip = svg.append("defs").append("clipPath").attr("id", clipId).append("rect");

  let model = null;
  let width = 0;
  let height = 0;
  let base = null;
  let transform = d3.zoomIdentity;

  const zoom = d3
    .zoom()
    .scaleExtent([1, 24])
    .filter((event) => (event.type === "wheel" ? event.ctrlKey || event.metaKey : !event.button))
    .on("zoom", (event) => {
      transform = event.transform;
      render();
    });
  svg.call(zoom).on("dblclick.zoom", null);

  // "Fit schedule" shows everything up to the last job, or up to `model.fitTo` when set (so two
  // charts being compared can share one time range).
  function fitEnd() {
    const last = model.fitTo ?? (model.assignments.length ? d3.max(model.assignments, (a) => a.end) : null);
    if (last == null) return model.horizon;
    return Math.min(model.horizon, Math.ceil(last * 1.03 + 2));
  }

  function layout() {
    width = Math.max(320, root.clientWidth || 900);
    height = MARGIN.top + model.resources.length * ROW_H + MARGIN.bottom;
    svg.attr("width", width).attr("height", height).attr("viewBox", `0 0 ${width} ${height}`);
    clip.attr("x", MARGIN.left).attr("y", 0).attr("width", width - MARGIN.left - MARGIN.right).attr("height", height);
    base = d3.scaleLinear().domain([0, model.horizon]).range([MARGIN.left, width - MARGIN.right]);
    const extent = [[MARGIN.left, 0], [width - MARGIN.right, height]];
    zoom.extent(extent).translateExtent(extent);
  }

  function fitTransform() {
    const k = Math.max(1, model.horizon / fitEnd());
    return d3.zoomIdentity.translate(MARGIN.left * (1 - k), 0).scale(k);
  }

  function dayTicks(x) {
    const [d0, d1] = x.domain();
    const perDay = model.horizonStart ? 1440 / model.minutes : null;
    if (perDay && Number.isInteger(perDay)) {
      const pxPerDay = Math.abs(x(perDay) - x(0));
      const step = Math.max(1, Math.ceil(52 / pxPerDay));
      const narrow = pxPerDay * step < 78;
      const out = [];
      for (let d = Math.ceil(d0 / perDay); d * perDay <= d1; d += 1) {
        if (d % step === 0) out.push({ unit: d * perDay, label: fmtDay(model, d * perDay, narrow) });
      }
      return out;
    }
    return x.ticks(Math.max(4, Math.floor(width / 90))).map((unit) => ({ unit, label: String(unit) }));
  }

  function tooltipContent(a) {
    const late = a.tardiness > 0;
    // A job that merges lines has one bar per line; the tooltip lists them all.
    const lines = model.assignments.filter((x) => x.job_id === a.job_id).map((x) => x.resource_name);
    return {
      title: `${a.job_name} (${a.job_id})`,
      rows: [
        [lines.length > 1 ? "Lines (merged)" : "Line", lines.join(" + ")],
        ...(a.work != null ? [["CPU-hours", fmtNumber(a.work)]] : []),
        ["Starts", fmtWhen(model, a.start)],
        ["Ends", fmtWhen(model, a.end)],
        ["Duration", fmtDuration(a.end - a.start, model.minutes)],
        ["Due", fmtDue(model, a.due)],
        ["Priority", String(a.priority)],
        late
          ? ["Status", `Late by ${fmtDuration(a.tardiness, model.minutes)}`, "late"]
          : ["Status", "On time"],
      ],
    };
  }

  function render() {
    if (!model) return;
    const x = transform.rescaleX(base);
    content.selectAll("*").remove();
    const [left, right] = [MARGIN.left, width - MARGIN.right];

    // Time axis and vertical grid.
    const axis = content.append("g");
    for (const tick of dayTicks(x)) {
      const px = x(tick.unit);
      if (px < left - 1 || px > right + 1) continue;
      axis.append("line").attr("class", "grid").attr("x1", px).attr("x2", px).attr("y1", MARGIN.top - 6).attr("y2", height - MARGIN.bottom);
      if (px + 4 + tick.label.length * 6.4 <= width - 4) {
        axis.append("text").attr("class", "tick-label").attr("x", px + 4).attr("y", MARGIN.top - 12).text(tick.label);
      }
    }

    const plot = content.append("g").attr("clip-path", `url(#${clipId})`);
    const byResource = d3.group(model.assignments, (a) => a.resource_id);

    model.resources.forEach((resource, i) => {
      const top = MARGIN.top + i * ROW_H;
      const barY = top + (ROW_H - BAR_H) / 2;

      for (const c of closedPeriods(resource.windows, model.horizon)) {
        const x0 = Math.max(left, x(c.start));
        const x1 = Math.min(right, x(c.end));
        if (x1 > x0) plot.append("rect").attr("class", "closed").attr("x", x0).attr("y", top + 1).attr("width", x1 - x0).attr("height", ROW_H - 1);
      }
      content.append("line").attr("class", "rule").attr("x1", 0).attr("x2", right).attr("y1", top + ROW_H).attr("y2", top + ROW_H);

      const label = content.append("text").attr("x", left - 12).attr("text-anchor", "end");
      label.append("tspan").attr("class", "row-name").attr("x", left - 12).attr("y", top + ROW_H / 2 - 2).text(resource.name);
      if (resource.daily_capacity_units != null) {
        label
          .append("tspan")
          .attr("class", "row-sub")
          .attr("x", left - 12)
          .attr("dy", 15)
          .text(
            resource.capacity > 1
              ? `${fmtNumber(resource.capacity)} CPU`
              : `up to ${fmtDuration(resource.daily_capacity_units, model.minutes)} a day`,
          );
      }

      for (const a of byResource.get(resource.id) ?? []) {
        const x0 = x(a.start) + GAP / 2;
        const x1 = x(a.end) - GAP / 2;
        const w = x1 - x0;
        if (x1 < left || x0 > right || w <= 0) continue;
        const dueX = Math.min(Math.max(x(a.due), x0), x1);
        const lateStart = a.tardiness > 0 ? Math.max(dueX, x0) : x1;

        const g = plot
          .append("g")
          .attr("class", "job")
          .attr("data-job", a.job_id)
          .attr("tabindex", 0)
          .attr("role", "img")
          .attr(
            "aria-label",
            `${a.job_name} on ${a.resource_name}, ${fmtWhen(model, a.start)} to ${fmtWhen(model, a.end)}, ` +
              (a.tardiness > 0 ? `late by ${fmtDuration(a.tardiness, model.minutes)}` : "on time"),
          );

        const hasLate = a.tardiness > 0;
        if (lateStart > x0) {
          g.append("path").attr("class", "bar-ok").attr("d", roundedRect(x0, barY, lateStart - x0, BAR_H, 4, { left: true, right: !hasLate }));
        }
        if (hasLate && x1 > lateStart) {
          g.append("path").attr("class", "bar-late").attr("d", roundedRect(lateStart, barY, x1 - lateStart, BAR_H, 4, { left: lateStart <= x0, right: true }));
        }
        const text = a.job_id;
        if (w >= text.length * CHAR_W + 12) {
          g.append("text")
            .attr("class", `bar-text ${hasLate && lateStart - x0 < w / 2 ? "on-late" : "on-ok"}`)
            .attr("x", x0 + 7)
            .attr("y", barY + BAR_H / 2 + 4)
            .text(text);
        }
        g.append("rect").attr("class", "hit").attr("x", x0 - 2).attr("y", top).attr("width", w + 4).attr("height", ROW_H);

        g.on("pointermove", (event) => tooltip.showAt(event.clientX, event.clientY, tooltipContent(a)))
          .on("pointerleave", () => tooltip.hide())
          .on("focus", (event) => tooltip.showFor(event.currentTarget, tooltipContent(a)))
          .on("blur", () => tooltip.hide());
      }
    });

    if (!model.assignments.length) {
      content
        .append("text")
        .attr("class", "empty-note")
        .attr("x", (left + right) / 2)
        .attr("y", MARGIN.top + (model.resources.length * ROW_H) / 2)
        .text(model.emptyMessage);
    }
  }

  function apply(t) {
    svg.call(zoom.transform, t);
  }

  const observer = new ResizeObserver(() => {
    if (!model) return;
    const w = Math.max(320, root.clientWidth || 900);
    if (w === width) return;
    layout();
    apply(fitTransform());
  });
  observer.observe(root);

  return {
    update(next) {
      model = next;
      svg.attr(
        "aria-label",
        `Schedule with ${model.resources.length} lines and ${model.assignments.length} scheduled jobs`,
      );
      layout();
      apply(fitTransform());
    },
    fit: () => model && apply(fitTransform()),
    full: () => model && apply(d3.zoomIdentity),
    zoomBy: (factor) => model && svg.transition().duration(150).call(zoom.scaleBy, factor, [(MARGIN.left + width - MARGIN.right) / 2, 0]),
    highlight(jobId) {
      svg.selectAll(".job").classed("is-linked", function () {
        return jobId != null && this.dataset.job === jobId;
      });
    },
  };
}
