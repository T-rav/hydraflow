# ADR-0120: The stillness control architecture — setpoint regulators, an optimization layer, and innovation-filtered sensing

- **Status:** Proposed
- **Date:** 2026-08-01
- **Related:** [ADR-0101](0101-disturbance-dampener.md) (the disturbance dampener — the reference regulator), [ADR-0029](0029-caretaker-loop-pattern.md) (loops are reflexes)
- **Addresses:** #10824 (setpoint conversion), #10827 (optimization layer), #10825 (innovation-filtered sensing) — the Phase-1 design rulings of the stillness program (#10819)

> **This is a Proposed ADR — a design ruling for decision, not an accepted commitment.** It records the target architecture and, deliberately, what is *real today* versus *unbuilt* for each rung, so the build order is chosen on evidence. Accept, amend, or reject.

## Context

Over the hands-off fortnight (2026-07-14→28) factory flux *grew* as real work shrank — a limit cycle. The Phase-0 measurement (this session) established three grounded facts:

- **Fleet-level, not per-item** (#10820): 0 per-item convergence escalations while flux ran.
- **The factory cannot measure its own wake** (#10820): work origin is unrecorded and most churn is filed unlabelled, so the self-sourced signal is blind.
- **Concentration + contention have a single worst object** (#10840/#10823): `config.py` is both the top god-file (157 dependents) *and* a top contested surface; the phase logic (`review_phase`, `plan_phase`, `shape`) is the fix-as-disturbance epicentre.

The diagnosis (#10819, Janert): ~70 finding-driven loops on one plant, each optimizing without an objective. A finding-driven loop has no rest state ("find problems" never reaches zero); an error-driven regulator does (PV at setpoint ⇒ error≈0 ⇒ no action is correct). This ADR is the structural response.

## Decision

Adopt the process-control **pyramid** as the factory's control architecture, built bottom-up, lowest-cost-first, each rung justified by measurement rather than assumed.

### Ruling 1 — Setpoint conversion (#10824): finding-driven loops become error-driven regulators *where a natural PV+target exists*

**Rule:** a loop with a measurable process variable and a human-signed target is converted to `error = PV − setpoint`, with deadband + hysteresis, and files/actuates only on a breach. A loop with no natural zero (a generative appetite) stays finding-driven but is bounded by a **rate budget** (a meta-setpoint on its output frequency), not converted.

**Grounded (real exemplars + precedents, verified):**
- **Coverage floor** — setpoint 70% lives in `Makefile:223` (`TEST_COVERAGE_DEFAULT`) + `ci.yml:396` (`--cov-fail-under=70`); *not* a config field (a candidate cleanup: promote it to config so the setpoint is one authoritative value).
- **Disturbance dampener** (ADR-0101) — the canonical regulator: baseline=setpoint (`disturbance/baseline.py`), new violations=error (`diff()` → `RatchetResult.new`), burn-down=control action (`burndown.select_units` → `DisturbanceDampenerLoop`).
- **Already error-driven** (cite as done, not candidates): `FailOpenMonitorLoop` (Shewhart c-chart), `RCBudgetLoop` (1.5×median), `FlakeTrackerLoop`, `ErosionMetricsLoop` (baseline), `SecondOrderVitalsLoop` (per-series Shewhart UCL, `vitals/control.py`), `CostBudgetWatcherLoop` (setpoint→throttle/kill — the closest thing to a real fast regulator today).
- **True conversion candidates** (a PV with a target, currently pattern-finding): `GateHealthLoop` (PV = per-check pass-rate → regulate to a pass-rate floor), `SampledAuditLoop` (PV = re-review disagreement rate → a statistical escape bound).
- **Irreducibly exploratory** (stay finding-driven + rate-budget): `MemoryBacklogLoop`, `WikiRotDetectorLoop`, `PrinciplesAuditLoop`, `RetrospectiveLoop`, `ReportIssueLoop`, the ADR-drift loops, etc.

The concentration/contention sensors (#10840/#10823) are themselves error-driven regulators (baseline=setpoint, new god-file / new contention=error) — the pattern generalises.

### Ruling 2 — The optimization layer (#10827): a slow objective pass that moves setpoints, never code

**Rule:** ~95% fast regulators (Ruling 1) hold human-signed setpoints; a slow supervisory/optimization pass runs on a long cadence with an *explicit* objective and **proposes setpoint changes — human-signed — never touching the plant directly.** The optimizer writes setpoints down to the regulators; it never edits code or files fix-PRs.

**Grounded (objective feasibility, verified):**
- **Erosion trend** — REAL, durable (`erosion/trends.py`, `erosion_trends.jsonl`).
- **Escape rate** — REAL, durable (`escape/metrics.py::escapes_per_100_merges`).
- **Intervention rate** — REAL, durable (`intervention/metrics.py::interventions_per_100_merges`).
- **Cost per merge** — **NOT a standing series.** Cost (per-phase/per-loop/rolling) and merge-volume exist separately; there is no per-merge cost attribution. `dashboard_routes/_cost_merge.py` is cross-repo roll-*merging*, a naming false-friend. Composing it is new plumbing.

**Honest gap (flag hard):** the fast-regulator rung is **a library, not a running system.** `PidController`/`AimdController` exist and are tested (`signal_control/controllers.py`) but are instantiated *nowhere* in production `src/`; the module concedes "wiring to a real actuator happens in later stages." Only Shewhart *sensing* (vitals) and `CostBudgetWatcher` *actuation* run today. **The pyramid cannot be built top-down: the optimizer has almost no regulators to write setpoints to.** Build order is therefore forced: convert/wire a handful of real regulators (Ruling 1) *before* an optimization layer is anything but a proposal generator.

### Ruling 3 — Innovation-filtered sensing (#10825): respond to innovation, not measurement

**Rule (target):** sensors respond to `innovation = actual − model_prediction` (pure surprise), so a loop does not read its own actuation as disturbance.

**Honest premise-check (flag hard — the issue's premise is FALSE):** #10825 claims "the convergence pipeline already produces per-change expectations; the footprint is in the exhaust waiting to be used." **It does not.** Verified: the exhaust contains verdicts, opaque finding signatures, prose acceptance criteria, and a file-*path* plan-vs-actual diff (`DeltaReport`/`verify_delta`) — all qualitative. A repo-wide grep for `expected_delta`/`predicted_coverage`/`expected_movement` is empty in `src/`. The *actual*-movement stores are rich (the minuend is free); the *expected* term (per-change predicted metric deltas) is entirely unbuilt.

So the fix ladder's rungs cost very differently than the issue assumed:
- **Rung 1 — settling windows (crude, cheap, buildable now):** do not measure an area for a window after actuating there. Discards information but needs no prediction. This is the only cheap rung, and it directly damps the mechanism-2 wake-reading on the noisy loops.
- **Rung 2 — expected-footprint discounting (a real build, not a surfacing):** requires *building* a per-change footprint predictor (which metrics move, how much) and measuring its prediction quality (predicted vs actual is a free calibration series once it exists). Substantial; do not cite it as "in the exhaust."
- **Rung 3 — full innovation/Kalman sensing:** the principled target, gated on rung 2's predictor being calibrated.

**Recommendation:** build rung 1 (settling windows) as part of the damper set; treat rung 2 as a measured experiment, not a surfacing task; do not build rung 3 until rung 2's predictor is calibrated.

## Consequences

- **Build order is forced and cheap-first:** damper-0a cadence alignment (#10843, config only) → settling windows (rung 1) → convert the 2 real regulator candidates (GateHealth, SampledAudit) + wire one `signal_control` controller to a live actuator → *then* an optimization layer over the three real objectives. An optimizer built before regulators has nothing to steer.
- **No instrument ships alone** (#10840): every setpoint gets its coupled counter-metric (the erosion.spread ↔ erosion.concentration pair, shipped this session, is the template).
- **Honesty as a first-class output:** two load-bearing premises were false-or-aspirational (the #10825 footprint; the running-regulator rung). Recording that here prevents building on them.

## Open decisions (yours)

1. Promote the coverage-floor setpoint (70%) from Makefile/CI into a single config field?
2. Convert `GateHealthLoop`/`SampledAuditLoop` to regulators now, or wait for more Phase-0 evidence?
3. Rung-1 settling windows: which loops, and what window per loop (needs the #10843 measurement-window declarations)?
4. Is cost-per-merge worth the new per-merge cost-attribution plumbing, or drop it as an optimizer objective in favour of the three that exist?
