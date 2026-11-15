# Scheduling model

This document states the optimization problem solved by `scheduler.engine`. Everything here is a
generic textbook formulation (unrelated parallel machines with availability windows, minimizing
total weighted tardiness). All data is synthetic.

## Problem

Time is discrete: integer units counted from 0 (default 1 unit = 60 minutes) over a horizon `H`.
All intervals are half-open, `[start, end)`.

**Resources** `r ∈ R` each have a set of availability windows `W_r` (disjoint intervals inside
`[0, H)`). Outside them the resource is closed.

**Jobs** `j ∈ J` have: duration `p_j ≥ 1`, release time `a_j ≥ 0`, due time `d_j`, priority
`w_j ∈ {1..5}` (higher = more important) and a non-empty set of eligible resources `E_j ⊆ R`.

A schedule assigns each job one resource and a start time `s_j`. A job is non-preemptive: it
runs on one resource without interruption, so it must lie inside a single availability window.

## Model (CP-SAT)

Variables:

- `x[j,r] ∈ {0,1}` for `r ∈ E_j`: job `j` runs on resource `r`.
- `s_j ∈ [a_j, H − p_j]`: start time.
- `I[j,r]`: optional interval `[s_j, s_j + p_j)`, present iff `x[j,r] = 1`.
- `T_j ≥ 0`: tardiness.

Constraints:

1. `Σ_{r ∈ E_j} x[j,r] = 1` for every job.
2. For every resource, `NoOverlap` over its optional intervals together with one fixed interval
   per closed period. Because each job is a single interval, this forces it inside one window.
3. `T_j ≥ s_j + p_j − d_j`.

Objective: minimize `Σ_j w_j · T_j` (priority-weighted tardiness), or `Σ_j T_j` when the weighted
option is switched off.

## Result reporting

| Status | Meaning |
|---|---|
| OPTIMAL | The solver proved no better schedule exists. |
| FEASIBLE | A valid schedule was found, optimality not proven (a gap is reported). |
| INFEASIBLE | The solver proved no schedule exists. |
| UNKNOWN | Nothing was found within the time limit. |

A feasible result is never reported as optimal. Before a schedule is returned, an independent
verifier re-checks eligibility, release times, window containment and non-overlap and
recomputes the objective; a mismatch raises `ScheduleVerificationError`.

## Metrics

- On-time rate: share of jobs with `T_j = 0`.
- Total and weighted tardiness.
- Makespan: latest job end.
- Utilization per resource: busy units / available units.

## Reproducibility

Runs record the solver seed, worker count, time limit and a hash of the input. Results are
deterministic for a fixed seed with one worker; with several workers CP-SAT may return different
(equally good) schedules, and with a short time limit the status may differ between runs.

## Assumptions and limitations

- Single-resource jobs only; no precedence, setup times, or multi-resource jobs.
- Deterministic durations; no disruption or rescheduling model.
- Solving is synchronous inside the request (bounded by `MAX_TIME_LIMIT_S`); there is no job queue.
- Large instances may return FEASIBLE or UNKNOWN within the time limit.
- No authentication: the API is meant for a demo, not for multi-tenant use.
