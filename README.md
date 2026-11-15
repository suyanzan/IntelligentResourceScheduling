# Intelligent Resource Scheduling Platform

A generic resource scheduling and optimization platform built on Google OR-Tools CP-SAT,
with a FastAPI backend and a D3.js dashboard.

> **Independent project.** It uses only publicly documented scheduling techniques and fully
> synthetic, fictional data. It contains no proprietary algorithms, business rules, parameters
> or data from any existing industrial scheduling system.

**Status:** Phase 6 done (engine, seeded synthetic data, PostgreSQL persistence, REST API and a
D3 dashboard served at `/`). Scenario comparison and packaging are next.

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

## Roadmap

Phases 0-8 are described in the planning document: skeleton, engine models and validation,
CP-SAT model, synthetic data, database, API, frontend, scenario comparison, packaging.
