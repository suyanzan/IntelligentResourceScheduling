# Intelligent Resource Scheduling Platform

A generic resource scheduling and optimization platform built on Google OR-Tools CP-SAT,
with a FastAPI backend and a D3.js dashboard.

> **Independent project.** It uses only publicly documented scheduling techniques and fully
> synthetic, fictional data. It contains no proprietary algorithms, business rules, parameters
> or data from any existing industrial scheduling system.

**Status:** Phase 0 (project skeleton). No scheduling logic is implemented yet.

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

## Roadmap

Phases 0-8 are described in the planning document: skeleton, engine models and validation,
CP-SAT model, synthetic data, database, API, frontend, scenario comparison, packaging.
