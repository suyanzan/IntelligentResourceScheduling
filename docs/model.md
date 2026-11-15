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

### Jobs measured in capacity-hours (merged resources)

A resource `r` can also have a processing `capacity` `c_r` (for example CPUs), and a job can carry
`work` `W_j` (for example CPU-hours) instead of a fixed duration. Such a job may run on **several
eligible resources at once**: it picks a non-empty set `S ⊆ E_j`, all resources in `S` start and
finish it together, and its duration is

`p_{j,S} = ceil(W_j / Σ_{r∈S} c_r)`.

Example: 150,000 CPU-hours on a 500-CPU line takes 300 h; on that line plus a 1,000-CPU line it
takes 100 h. While a job runs, each resource in `S` handles only that job and cannot be
interrupted. Jobs with a fixed duration keep the original single-resource behaviour. Jobs with
`work` may have at most 8 eligible resources (2^8 − 1 options).

The bundled `opc` sample is fictional: lines A–D with 500, 1,000, 1,500 and 2,000 CPUs running
around the clock (optional maintenance), and orders `MaskOPCOrder 001–020` of 1,000–150,000
CPU-hours.

## Model (CP-SAT)

Variables:

- `x[j,o] ∈ {0,1}`: job `j` uses option `o`. An option is a set of resources `S` with duration
  `p_{j,o}`; a fixed-duration job has one single-resource option per eligible resource, a job
  with `work` has one option per non-empty subset of its eligible resources.
- `s_j`, `e_j`: start and end, with `e_j = s_j + p_{j,o}` when option `o` is chosen.
- `I[j,o,r]`: optional interval `[s_j, s_j + p_{j,o})` on each resource `r` of option `o`,
  present iff `x[j,o] = 1`.
- `T_j ≥ 0`: tardiness.

Constraints:

1. `Σ_o x[j,o] = 1` for every job.
2. For every resource, `NoOverlap` over its optional intervals together with one fixed interval
   per closed period. Because each job is a single interval on each chosen resource, this forces
   it inside one window of each of them.
3. `T_j ≥ e_j − d_j`.

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
- Delay per job: `e_j − d_j`, kept signed in the report (negative means early).
- Total and weighted tardiness (only positive delays count).
- Average delay: `Σ_j max(0, e_j − d_j) / N`, where `N` is the number of all jobs, so early and
  on-time jobs count as 0 in the sum but are included in the divisor. The solver minimizes the
  priority-weighted sum; for the smallest average delay regardless of priority, solve without
  weights (the unweighted objective is `N` times the average delay).
- Makespan: latest job end.
- Utilization per resource: busy units / available units.

## Reproducibility

Runs record the solver seed, worker count, time limit and a hash of the input. Results are
deterministic for a fixed seed with one worker; with several workers CP-SAT may return different
(equally good) schedules, and with a short time limit the status may differ between runs.

## Assumptions and limitations

- A job uses its chosen resources exclusively and for its whole duration (no sharing of part of a
  resource, no changing the resource set midway); no precedence or setup times.
- Deterministic durations; no disruption or rescheduling model.
- Solving is synchronous inside the request (bounded by `MAX_TIME_LIMIT_S`); there is no job queue.
- Large instances may return FEASIBLE or UNKNOWN within the time limit.
- No authentication: the API is meant for a demo, not for multi-tenant use.

## No-idle rule

With `no_idle` on (the dashboard default), a line may not sit idle while an order it
could run is still waiting. For each line, the busy time plus any maintenance before
the latest start of an order that can use that line must fill the whole span from time 0
to that start; idle time is only allowed after that point. The rule needs every release
time to be 0 (otherwise the request is reported as MODEL_INVALID). The schedule is
re-checked by an independent verifier. It can cost objective value compared with the
unconstrained optimum, and the solver is seeded with a sequential all-lines heuristic.
