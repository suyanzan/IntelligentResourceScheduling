# Intelligent Resource Scheduling Platform

A generic resource scheduling and optimization platform built on Google OR-Tools CP-SAT,
with a FastAPI backend and a D3.js dashboard.

> **Independent project.** It uses only publicly documented scheduling techniques and fully
> synthetic, fictional data. It contains no proprietary algorithms, business rules, parameters
> or data from any existing industrial scheduling system.

**Status:** Phases 0-8 done: engine, seeded synthetic data, PostgreSQL persistence, REST API, D3
dashboard, run comparison, Docker packaging and a Render Blueprint (not deployed by default).

## Planned scope (MVP)

- Resources with daily capacity and availability calendars; jobs with duration, due date,
  priority and eligible resources.
- CP-SAT model: one eligible resource per job, no overlap per resource, availability windows
  respected, minimizing (weighted) total tardiness.
- Explicit solver statuses (OPTIMAL, FEASIBLE, INFEASIBLE, UNKNOWN). A feasible solution is
  never reported as optimal unless the solver proves it.
- Dashboard: utilization, on-time rate, total tardiness, Gantt chart, job results.
- Seeded synthetic data and deterministic test fixtures.

## Architecture

```
frontend (D3) -> api (FastAPI) -> services -> engine (OR-Tools only)
                                     \-> db (SQLAlchemy / PostgreSQL)
```

The optimization engine (`src/scheduler/engine`) is independent of FastAPI and the database.

## Quick start (Docker)

```bash
docker compose up --build
```

Open <http://localhost:8000>. Compose starts PostgreSQL, applies the migrations and serves the
API and dashboard. The credentials in `docker-compose.yml` are for local use only.

## Deploying to Render

`render.yaml` is a Render Blueprint (a Docker web service plus a PostgreSQL database). Nothing is
deployed until you do it: in the Render dashboard choose **New > Blueprint**, select this
repository and apply. The container runs `alembic upgrade head` on every start and reads `PORT`
and `DATABASE_URL` from the environment. Free-tier services sleep when idle and free databases
expire, so use a paid plan for anything lasting. Solves run inside the request, so keep
`MAX_TIME_LIMIT_S` modest (60 s in the Blueprint).

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ruff check .
mypy
pytest
```

## Synthetic data

`scheduler.synthetic.generator` builds fully fictional instances (lines, shifts, weekends,
maintenance days, orders). The same seed always yields identical data on every platform; golden
hashes in the tests pin the presets. Presets are sized to be feasible, but arbitrary configs are
only guaranteed to be structurally valid.

```python
from scheduler.synthetic.generator import preset
from scheduler.engine.solver import solve

result = solve(preset("small"))
print(result.status, result.objective)
```

## Database

PostgreSQL via SQLAlchemy 2.x. Scenarios own their resources, jobs and calendars; each solve
stores an immutable run (status, objective, bound, gap, assignments, metrics) together with an
`input_hash` of the exact inputs. Once a scenario has runs its inputs are locked; clone it to
edit. Schema changes go through Alembic:

```bash
export DATABASE_URL=postgresql+psycopg://scheduler:scheduler@localhost:5432/scheduler
alembic upgrade head
```

Integration tests need a database: set `TEST_DATABASE_URL` (CI uses a Postgres service
container). Without it they are skipped.

## API

```bash
uvicorn scheduler.api.main:app --reload   # interactive docs at /docs
```

| Method and path | Purpose |
|---|---|
| `GET /api/health` | liveness |
| `POST /api/data/generate` | create a scenario from seeded synthetic data (`preset` or custom sizes) |
| `GET/POST /api/scenarios` | list / create scenarios |
| `GET/DELETE /api/scenarios/{id}` | read / delete a scenario |
| `POST /api/scenarios/{id}/clone` | copy inputs into a new editable scenario |
| `PUT /api/scenarios/{id}/instance` | replace resources and jobs (409 once the scenario has runs) |
| `POST /api/scenarios/{id}/solve` | solve synchronously and store a run |
| `GET /api/scenarios/{id}/runs`, `GET /api/runs/{id}` | list runs / read one with its schedule |

Errors: 404 unknown id, 409 locked inputs, 422 invalid input (engine problems are listed under
`issues`), 500 if the solver's output ever fails independent verification. A solve always returns
201 with a `status` of `OPTIMAL`, `FEASIBLE`, `INFEASIBLE` or `UNKNOWN`; only `OPTIMAL` means
optimality was proven. `time_limit_s` is capped by the server setting `MAX_TIME_LIMIT_S`
(default 60).

## Dashboard

Start the API and open `http://localhost:8000/`:

```bash
uvicorn scheduler.api.main:app
```

The page (plain HTML/CSS/JS with a vendored D3 v7, no build step, works offline) lets you add a
synthetic scenario, solve it with a time limit, and inspect the result: solver status badge
(optimal / feasible with gap / infeasible / no schedule), on-time rate, total and weighted
tardiness, line utilization, a pannable and zoomable Gantt chart that marks late jobs and closed
periods, and a sortable job table. It follows the system light/dark setting, works on phones,
and the Gantt bars can be reached with the keyboard. Set `FRONTEND_DIR` to serve the files from
another folder, or to an empty value to run the API only.

**CPU-hour jobs and merged lines.** A job can be given `work` (for example CPU-hours) instead of
a fixed duration, and lines can have a `capacity` (for example CPUs). Such a job may run on
several lines at once; its duration is `ceil(work / total capacity)`. The "OPC compute farm"
sample builds four lines (500 / 1,000 / 1,500 / 2,000 CPUs) and 20 orders of 1,000-150,000
CPU-hours. The dashboard shows each order's signed delay (early orders keep a negative value) and
the **average delay**: late hours divided by all orders. Details are in `docs/model.md`.

**Comparing runs.** The "Compare runs" button puts two stored runs side by side: key figures with
differences (B minus A), per-line utilization, two Gantt charts on a shared time axis with linked
hover, and a table of jobs that moved. A winner is named only when both runs solved the same
inputs with the same kind of objective; otherwise (a what-if with an extra line, say) the
differences are shown without ranking. The API equivalent is `GET /api/compare?run_a=&run_b=`.

## Model, assumptions and limitations

The mathematical formulation, status semantics and assumptions are in
[`docs/model.md`](docs/model.md). In short: single-resource non-preemptive jobs, discrete time,
deterministic durations, no precedence or setup times, synchronous solving without a job queue,
and no authentication (demo use). Not done: a secondary makespan objective, because it would
change what OPTIMAL means.

## Roadmap

Phases 0-8 (skeleton, engine models and validation, CP-SAT model, synthetic data, database, API,
frontend, run comparison, packaging) are complete.

### No idle lines

The dashboard has a **No idle lines** checkbox (on by default). When on, a line stays busy until no order it can run is left to start. See `docs/model.md`.

### OPC live scenario

The default sample (`opc_live`) models a day on the farm. There are five lines (A 500, B 1,000,
C 1,500, D 2,000 and E 1,500 CPUs). All lines are free when the plan starts, and orders arrive over time. Some are DIFFUSION orders that should finish within 12
hours of arriving; each one that does not earns a cycle point. Every OPC order is followed by an
AUTORP order (42% of its CPU-hours, same due date) that can start only after the OPC order ends.
Every due date is today, tomorrow or the day after (the end of that day). A job may merge lines
only up to 3000 CPUs in total. All data is fictional; see `docs/model.md`.

### Watch board

The **Watch board** button opens a monitoring view of a solved run. A "now" clock (slider, or
Play with a speed choice) shows what every line is doing (running with progress and the next
orders, idle, or busy until a given time) and where each order stands: done, running, waiting,
or not arrived yet. Orders are listed by due date and can be filtered. The Job results table
also starts sorted by due date.

## Production floor dashboard

`/floor.html` is the page for line staff. A scheduler picks a solved run and chooses **Release to floor**; the plan (three days of orders with planned lines and times, aligned to real dates) becomes the active plan. Staff then see, in plant time and refreshed every 30 s:

- a **Day** picker (default today) to look at any day: orders due that day, the day after, and unfinished earlier orders carried into it;
- orders grouped by due day: **Carried over** (earlier days, not finished), Today, Tomorrow, Day after, later, so the next shift sees what the previous one left;
- per order: planned versus actual start/finish and a plain-language variance (late start, overrun, ahead, past due);
- per line: running order, next planned order, and flags when reality departs from the plan (late start, overrun, started out of sequence, follow-up waiting for its parent);
- actions: **Start**, **Finish** (actual times editable), **Undo** (one step back), **Note** (delay reason), with an activity log.

There is no login: the operator name is free text. Do not expose the page beyond the plant network without adding authentication. Frontend rules are unit-tested with `node --test frontend/tests/*.test.mjs`.

The **OPC live** sample covers exactly three days (today, tomorrow, the day after; 72 time units). Order sizes are 1,000–15,000 CPU-hours so that the three days can be worked off even when the plan starts late in the day.

### Execution report

`/report.html` is a charts-only summary of the three-day plan for managers: on-time and finished rings, outcomes per due day, cumulative due/planned/finished curves, plan versus actual per line, the most overdue orders and hours per line. It reads the active plan, refreshes every minute and prints to PDF.

For demos the floor page has **Simulate shift (demo)**: it records a plausible, seeded duty shift (starts a little late or early, runs a little long or short, follow-ups after their parent) up to the current time, so the floor page and the report have data without anyone clicking through every order. Events are logged as "Demo engineer".
