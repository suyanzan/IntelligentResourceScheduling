// Watch board: a live-style view of a solved schedule. A "now" clock (slider or play) shows which
// orders are done, running, waiting or not yet arrived, and what every line is doing. Jobs are
// listed by due date. All dynamic text uses textContent.

import { fmtDuration, fmtNumber, fmtPercent, fmtSigned, fmtWhen } from "./format.js";
import { icon } from "./panels.js";

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// --- pure helpers (no DOM) ---------------------------------------------------------------------

/** One entry per job with its planned placement, in the order the board lists them (due date). */
export function buildJobs(scenario, run) {
  const placed = new Map();
  for (const a of run?.assignments ?? []) {
    if (!placed.has(a.job_id)) placed.set(a.job_id, []);
    placed.get(a.job_id).push(a);
  }
  const endOf = new Map([...placed].map(([id, rows]) => [id, rows[0].end]));
  const jobs = scenario.instance.jobs.map((job) => {
    const rows = placed.get(job.id);
    const first = rows?.[0];
    const release = job.release ?? 0;
    const available = job.after && endOf.has(job.after) ? Math.max(release, endOf.get(job.after)) : release;
    return {
      id: job.id,
      name: job.name,
      layer: job.layer ?? "",
      due: job.due,
      priority: job.priority,
      release,
      available,
      after: job.after ?? null,
      work: job.work ?? null,
      cycleLimit: job.cycle_limit ?? null,
      scheduled: Boolean(first),
      start: first?.start ?? null,
      end: first?.end ?? null,
      lines: rows ? rows.map((r) => r.resource_id) : [],
    };
  });
  return jobs.sort((a, b) => a.due - b.due || b.priority - a.priority || a.name.localeCompare(b.name, undefined, { numeric: true }));
}

/** done | running | waiting (arrived, not started) | pending (not arrived yet) | unscheduled. */
export function jobStatus(job, now) {
  if (!job.scheduled) return "unscheduled";
  if (now >= job.end) return "done";
  if (now >= job.start) return "running";
  if (now >= job.available) return "waiting";
  return "pending";
}

/** Counts of jobs by status at `now`, plus how many are late or will be late. */
export function summarize(jobs, now) {
  const counts = { done: 0, running: 0, waiting: 0, pending: 0, unscheduled: 0, late: 0 };
  for (const job of jobs) {
    counts[jobStatus(job, now)] += 1;
    if (job.scheduled && job.end > job.due) counts.late += 1;
  }
  return counts;
}

/** What each line is doing at `now`: running a job, idle, or not available (with the time it frees). */
export function lineStates(scenario, jobs, now) {
  return scenario.instance.resources.map((resource) => {
    const open = resource.windows.some((w) => now >= w.start && now < w.end);
    const onLine = jobs.filter((j) => j.scheduled && j.lines.includes(resource.id)).sort((a, b) => a.start - b.start);
    const current = onLine.find((j) => now >= j.start && now < j.end) ?? null;
    const upcoming = onLine.filter((j) => j.start > now);
    const freeAt = open ? null : Math.min(...resource.windows.filter((w) => w.start > now).map((w) => w.start), Infinity);
    const waitingForIt = jobs.some((j) => jobStatus(j, now) === "waiting" && j.lines.length && j.start > now);
    return {
      id: resource.id,
      name: resource.name,
      capacity: resource.capacity ?? 1,
      status: current ? "running" : open ? "idle" : "unavailable",
      current,
      upcoming,
      doneCount: onLine.filter((j) => j.end <= now).length,
      freeAt: Number.isFinite(freeAt) ? freeAt : null,
      idleWhileWaiting: !current && open && waitingForIt,
    };
  });
}

// --- view --------------------------------------------------------------------------------------

const STATUS_VIEW = {
  done: { tone: "ok", icon: "check", label: "Done" },
  running: { tone: "run", icon: "play", label: "Running" },
  waiting: { tone: "wait", icon: "clock", label: "Waiting" },
  pending: { tone: "none", icon: "clock", label: "Not arrived" },
  unscheduled: { tone: "none", icon: "help", label: "Not scheduled" },
};

const SPEEDS = [
  { hours: 1, label: "1 h per second" },
  { hours: 6, label: "6 h per second" },
  { hours: 24, label: "1 day per second" },
];

/** Build the board inside `root`, which holds the elements created by index.html. */
export function createWatchBoard(root) {
  const $ = (selector) => root.querySelector(selector);
  const slider = $("#watch-now");
  const playButton = $("#watch-play");
  const speedSelect = $("#watch-speed");
  const filterSelect = $("#watch-filter");

  for (const [index, speed] of SPEEDS.entries()) {
    const option = el("option", undefined, speed.label);
    option.value = String(index);
    speedSelect.append(option);
  }
  speedSelect.value = "1";

  let scenario = null;
  let run = null;
  let jobs = [];
  let model = { horizonStart: null, minutes: 60 };
  let now = 0;
  let last = 0;
  let timer = null;

  const unitsPerHour = () => 60 / model.minutes;

  function stop() {
    if (timer) clearInterval(timer);
    timer = null;
    playButton.textContent = "Play";
    playButton.setAttribute("aria-pressed", "false");
  }

  function setNow(value) {
    now = Math.max(0, Math.min(last, Math.round(value)));
    slider.value = String(now);
    draw();
  }

  function start() {
    if (now >= last) now = 0;
    playButton.textContent = "Pause";
    playButton.setAttribute("aria-pressed", "true");
    timer = setInterval(() => {
      const step = (SPEEDS[Number(speedSelect.value)].hours * unitsPerHour()) / 4;
      setNow(now + Math.max(1, step));
      if (now >= last) stop();
    }, 250);
  }

  playButton.addEventListener("click", () => (timer ? stop() : start()));
  slider.addEventListener("input", () => {
    stop();
    setNow(Number(slider.value));
  });
  $("#watch-start").addEventListener("click", () => {
    stop();
    setNow(0);
  });
  $("#watch-end").addEventListener("click", () => {
    stop();
    setNow(last);
  });
  filterSelect.addEventListener("change", drawJobs);

  function drawClock() {
    $("#watch-clock").textContent = fmtWhen(model, now);
    $("#watch-elapsed").textContent = now === 0 ? "start of plan" : `${fmtDuration(now, model.minutes)} into the plan`;
  }

  function drawKpis(counts) {
    const root2 = $("#watch-kpis");
    root2.replaceChildren();
    const tile = (label, value, tone) => {
      const t = el("div", "tile");
      if (tone) t.dataset.tone = tone;
      t.append(el("div", "label", label), el("div", "value", String(value)));
      return t;
    };
    const lines = lineStates(scenario, jobs, now);
    const busy = lines.filter((l) => l.status === "running").length;
    root2.append(
      tile("Lines running", `${busy} of ${lines.length}`),
      tile("Running", counts.running, "run"),
      tile("Waiting", counts.waiting, "wait"),
      tile("Not arrived", counts.pending),
      tile("Done", counts.done, "ok"),
      tile("Late (planned)", counts.late, counts.late ? "late" : undefined),
    );
  }

  function drawLines() {
    const list = $("#watch-lines");
    list.replaceChildren();
    for (const line of lineStates(scenario, jobs, now)) {
      const card = el("li", "line-card");
      card.dataset.status = line.status;
      const head = el("div", "line-head");
      head.append(el("strong", undefined, line.name), el("span", "line-cpu", `${fmtNumber(line.capacity)} CPU`));
      const state = el("span", "state");
      const view =
        line.status === "running"
          ? { tone: "run", icon: "play", text: "Running" }
          : line.status === "idle"
            ? { tone: line.idleWhileWaiting ? "late" : "none", icon: line.idleWhileWaiting ? "alert" : "clock", text: line.idleWhileWaiting ? "Idle while orders wait" : "Idle" }
            : { tone: "none", icon: "clock", text: line.freeAt != null ? `Busy until ${fmtWhen(model, line.freeAt)}` : "Not available" };
      state.dataset.tone = view.tone;
      state.append(icon(view.icon), document.createTextNode(view.text));
      head.append(state);
      card.append(head);

      if (line.current) {
        const job = line.current;
        const body = el("div", "line-now");
        const title = el("div", "line-job", job.name);
        if (job.layer) title.append(el("span", "layer-tag", job.layer));
        body.append(title);
        const total = job.end - job.start;
        const ratio = (now - job.start) / total;
        const bar = el("div", "progress");
        bar.setAttribute("role", "progressbar");
        bar.setAttribute("aria-valuemin", "0");
        bar.setAttribute("aria-valuemax", "100");
        bar.setAttribute("aria-valuenow", String(Math.round(ratio * 100)));
        bar.setAttribute("aria-label", `${job.name} progress`);
        const fill = el("div", "progress-fill");
        fill.style.width = `${(ratio * 100).toFixed(1)}%`;
        if (job.end > job.due) fill.dataset.tone = "late";
        bar.append(fill);
        body.append(bar);
        const merged = job.lines.length > 1 ? ` · merged with ${job.lines.filter((id) => id !== line.id).join(" + ")}` : "";
        body.append(
          el("div", "note", `${fmtPercent(ratio)} · ends ${fmtWhen(model, job.end)} (${fmtDuration(job.end - now, model.minutes)} left)${merged}`),
        );
        card.append(body);
      } else {
        card.append(el("div", "line-now note", line.status === "idle" ? "Nothing running." : "Not running anything yet."));
      }

      const next = line.upcoming.slice(0, 3);
      const queue = el("div", "line-queue");
      queue.append(el("span", "label", next.length ? "Next" : "Next: nothing planned"));
      for (const job of next) {
        queue.append(el("span", "queue-item", `${job.name} · ${fmtWhen(model, job.start)}`));
      }
      card.append(queue, el("div", "note", `${line.doneCount} done on this line`));
      list.append(card);
    }
  }

  function jobMatches(job, status, filter) {
    if (filter === "all") return true;
    if (filter === "late") return job.scheduled && job.end > job.due;
    if (filter === "active") return status === "running" || status === "waiting";
    return status === filter;
  }

  function drawJobs() {
    const body = $("#watch-jobs");
    body.replaceChildren();
    const filter = filterSelect.value;
    let shown = 0;
    for (const job of jobs) {
      const status = jobStatus(job, now);
      if (!jobMatches(job, status, filter)) continue;
      shown += 1;
      const tr = body.insertRow();
      tr.dataset.status = status;
      const name = el("td", undefined, job.name);
      name.append(el("span", "job-id", job.id));
      if (job.layer) name.append(el("span", "layer-tag", job.layer));
      const view = STATUS_VIEW[status];
      const state = el("span", "state");
      state.dataset.tone = view.tone;
      state.append(icon(view.icon), document.createTextNode(view.label));
      if (status === "running") {
        state.append(document.createTextNode(` ${fmtPercent((now - job.start) / (job.end - job.start))}`));
      }
      const statusCell = tr.insertCell();
      statusCell.append(state);

      let outlook = "-";
      let tone = "none";
      if (job.scheduled) {
        const delay = job.end - job.due;
        outlook = delay > 0 ? `Late by ${fmtDuration(delay, model.minutes)}` : `${fmtDuration(-delay, model.minutes)} to spare`;
        tone = delay > 0 ? "late" : "ok";
        if (status === "done") outlook = delay > 0 ? `Finished late by ${fmtDuration(delay, model.minutes)}` : "Finished on time";
      }
      const outlookState = el("span", "state");
      outlookState.dataset.tone = tone;
      if (tone !== "none") outlookState.append(icon(tone === "late" ? "alert" : "check"));
      outlookState.append(document.createTextNode(outlook));

      tr.prepend(el("td", undefined, fmtWhen(model, job.due)));
      tr.cells[0].classList.add("due-cell");
      tr.insertBefore(name, tr.cells[1]);
      const lineNames = job.lines.length
        ? job.lines.map((id) => scenario.instance.resources.find((r) => r.id === id)?.name ?? id).join(" + ")
        : "-";
      tr.append(
        el("td", undefined, lineNames),
        el("td", undefined, job.scheduled ? fmtWhen(model, job.start) : "-"),
        el("td", undefined, job.scheduled ? fmtWhen(model, job.end) : "-"),
        el("td", "num", String(job.priority)),
      );
      tr.insertCell().append(outlookState);
    }
    $("#watch-empty").hidden = shown > 0;
  }

  function draw() {
    if (!scenario || !run?.assignments?.length) return;
    drawClock();
    drawKpis(summarize(jobs, now));
    drawLines();
    drawJobs();
  }

  return {
    update(nextScenario, nextRun) {
      const changed = nextRun?.id !== run?.id || nextScenario?.id !== scenario?.id;
      scenario = nextScenario;
      run = nextRun;
      const ready = Boolean(scenario && run?.assignments?.length);
      $("#watch-body").hidden = !ready;
      $("#watch-none").hidden = ready;
      if (!ready) {
        stop();
        return;
      }
      model = { horizonStart: scenario.horizon_start, minutes: scenario.time_unit_minutes };
      jobs = buildJobs(scenario, run);
      last = Math.max(...jobs.filter((j) => j.scheduled).map((j) => j.end));
      slider.max = String(last);
      if (changed) {
        stop();
        now = 0;
      }
      setNow(now);
    },
    stop,
  };
}
