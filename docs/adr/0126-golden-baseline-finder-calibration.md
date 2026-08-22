# ADR-0126: Golden-baseline finder calibration — measuring a generative finder's noise floor

- **Status:** Proposed
- **Date:** 2026-08-02
- **Related:** [ADR-0120](0120-stillness-control-architecture.md) (The stillness control architecture — setpoint regulators + innovation-filtered sensing) — this is the sensor-noise-covariance ("R") that layer needs before it can trust any generative finder as a sensor; [ADR-0125](0125-mutation-gauntlet-gate-sensitivity.md) (Mutation gauntlet — gate sensitivity) — the sibling instrument, same pure-core + injected-seam + append-only-ledger shape, measuring the *other* half (gate sensitivity vs finder noise); the sampled re-audit's Shewhart rate governor (#10370, `src/audit/governance.py`) and the judge-independence c-chart (`src/judge_independence.py:shewhart_c_chart_ucl`) — the existing control-limit machinery this evaluates for reuse
- **Enforcement:** enforced
- **Enforced by:** `pytest:tests/test_finder_calibration.py`
- **Binds:** factory
- **Addresses:** #10821 (golden-baseline finder calibration — the stillness keystone); feeds the setpoint band conversion (#10824) and the noise-floor faceplate band (#10826)

> **This is a Proposed ADR — a design ruling for decision, not an accepted commitment.** It records the methodology and, deliberately, what is *real today* (this first slice) versus *deferred* to later phases. The instrument is a pure engine + ledger, not a background loop, and it does not run real finders. Accept, amend, or reject.

## Context

A *generative* finder has no natural zero. An LLM asked to "find erosion," "propose depends_on edges," or "flag ADR drift" against a repository will always find *something* — the ask itself manufactures output. So a finder's output against a **known-clean baseline** — a hand-vetted sha where, for a given signal class, the honest answer is "nothing to find" — is not signal. It *is* that finder's **false-positive floor**: its sensor noise.

Today the stillness program (ADR-0120) wants to treat these finders as sensors and regulate the factory's response to them, but it has no measure of how noisy each sensor is. Without that, every threshold is guessed, and a finder whose actuation threshold sits *below* its own noise floor will fire forever on nothing — a self-feeding source of factory churn (the maintenance-flux failure mode). The missing instrument is the one that measures the noise floor and sets thresholds *above* it.

This is the control-theory notion of **R, the measurement-noise covariance**: a Kalman filter must know how noisy a sensor is before it can weight it. For an LLM finder there is no datasheet R — but the floor's `(mean, sigma)` over repeated runs against the clean baseline *is* R, measured empirically. It must be *measured*, not assumed: a Poisson prior (variance = mean) under-states it, because LLM-finder noise is over-dispersed — mostly zero with a heavy tail.

This is distinct from `src/detector_calibration_loop.py`, which is a *retrospective, churn-based* recalibration of detectors from live outcomes. This instrument is *proactive*: it manufactures a known-clean condition and measures the finder's response to it directly.

## Decision

Introduce **golden-baseline finder calibration**: a pure engine that measures each generative finder's noise floor against a vetted-clean baseline, sets a Shewhart actuation threshold above it, flags when live output is statistically indistinguishable from that floor, and **proposes** (never applies) gain changes.

### Ruling 1 — the noise floor is the measured `(mean, sigma)`, the finder's R

`src/finder_calibration.py:measure_floor` takes repeated `NoiseSample`s (flagged-counts against the clean baseline) and returns `(mean, sigma)` where sigma is the *empirical* sample standard deviation — the measured noise covariance. Below two samples an empirical sigma is undefined; the floor is marked low-confidence and sigma falls back to the Poisson prior `sqrt(mean)` (a deliberately wider stand-in), never a crash.

### Ruling 2 — actuation threshold = the Shewhart UCL, above the floor

`src/finder_calibration.py:threshold_above_floor` returns `ceil(mean + k·sigma)` (k = 3, floored at 0). `src/finder_calibration.py:indistinguishable_from_floor` returns true when a live count sits at or below that UCL — inside the control limits ⇒ the finder is producing noise ⇒ trigger review. Only a count strictly above the UCL is distinguishable signal.

### Ruling 3 — read-only: the engine only ever *proposes*

The engine's sole actuation output is an inert `src/finder_calibration.py:GainProposal`. `src/finder_calibration.py:propose_gain` recommends raising a finder's threshold (turning gain *down*) when it sits at or below the measured floor, and returns `None` for a low-confidence floor or a threshold already above the floor. It mutates nothing — not the floor, not any finder, not any finding, not config. This is asserted in the test suite (frozen models + input-unchanged + proposal-only). Applying a proposal is a separate, human/loop-gated step.

### Ruling 4 — Shewhart reuse, honestly scoped

The repo already carries two control-limit helpers, and neither computes the chart this instrument needs. `src/audit/governance.py:upper_control_limit` is a **p-chart** anchored to a *fixed target proportion* (disagreement rate), not an empirical count floor. `src/judge_independence.py:shewhart_c_chart_ucl` is a **c-chart** that *assumes Poisson dispersion* (`cbar + 3·sqrt(cbar)`), which is exactly the assumption this instrument rejects on the confident path. So the confident-path UCL — an individuals chart over the *measured* sigma — is implemented fresh. The c-chart helper *is* reused, genuinely, for the low-confidence (<2 sample) fallback where an empirical sigma cannot be measured and the Poisson prior is the only principled choice. Consolidating all three into one shared `shewhart` module is a documented follow-up, not this slice.

### Ruling 5 — a curated generative-finder catalog + an injected measurement seam

`src/finder_calibration.py:GENERATIVE_FINDERS` is a small curated catalog (data), each entry mapping a `finder_id` to the `signal_class` it generates. The measurement seam is the `src/finder_calibration.py:FinderRunner` protocol — `run_against_baseline(finder_id, baseline) -> int`. Real finders are expensive and non-deterministic, so this slice **does not run them**: the pure core + ledger consume counts, and tests inject a fake runner returning known counts. Wiring a real finder-loop invocation against a checked-out sha is the deferred Phase-2 seam.

### Ruling 6 — an engine + append-only ledger, not a loop

The floors persist append-only to `<data_root>/calibration/finder_floors.jsonl` (floor, threshold, `last_calibrated`, per-finder drift), reusing `src/jsonl_ledger.py:AppendOnlyJsonlLedger`; last write wins per finder. A stale baseline silently miscalibrates everything, so `src/finder_calibration.py:is_baseline_stale` is a hard guardrail alongside the temporal `src/finder_calibration.py:drift_since` recalibration clock. This is an engine, like the mutation gauntlet's core — **not** a background loop: no seven-checkpoint wiring, no MockWorld shim. A calibration loop that runs on cadence is Phase 2.

| Finder (`finder_id`) | `signal_class` | Owning loop |
|---|---|---|
| `erosion_metrics` | `erosion` | ErosionMetricsLoop |
| `edge_proposer` | `edges` | EdgeProposerLoop |
| `entry_evidence` | `wiki-evidence` | EntryEvidenceLoop |
| `term_proposer` | `glossary-terms` | TermProposerLoop |
| `wiki_rot` | `wiki-rot` | WikiRotDetectorLoop |

> **Amended 2026-08-22 (#11600).** The catalog was six; it is five. The
> `adr_drift` / `adr-drift` entry stood for `AdrTouchpointAuditorLoop`, which
> [ADR-0136](0136-adr-drift-enforcement-deterministic-citation-gate.md) deleted.
> A finder floor measures a *generative* loop's residual output against a clean
> baseline; with no loop there is nothing generative to calibrate, and its
> deterministic stand-in detector (unresolved ADR citations) is a CI invariant
> the Tests lane already enforces on every PR, not LLM noise. The row, its
> `DETERMINISTIC_DETECTORS` detector, and its `finder_faceplate` worker join
> are removed; the rest of the catalog is unchanged.

## What is real today (this first slice) vs deferred

**Real:** the pure core (`GoldenBaseline`, `NoiseSample`, `FinderFloor`, `GainProposal`, `measure_floor`, `threshold_above_floor`, `indistinguishable_from_floor`, `calibrate_finder`, `propose_gain`, `is_baseline_stale`, `drift_since`); the curated finder catalog (six at authoring time, five since #11600); the injected `FinderRunner` seam + `collect_samples`; the append-only `CalibrationLedger`; and the full unit suite pinning the statistics on known distributions, the read-only-proposal guardrail (frozen models, input unchanged), the low-confidence and zero-floor edge cases, and the ledger round-trip.

**Deferred (honestly):**

- **Phase 2** — the real measurement seam: check out a golden baseline sha and invoke the actual finder loops against it (expensive, non-deterministic; excluded here on purpose). Broaden the catalog beyond the seed set.
- **Phase 2** — a slow-cadence calibration *loop* that re-measures floors on a schedule, watches `drift_since` / `mean_drift`, and files a `hydraflow-find` when a finder's live mix goes indistinguishable from its floor. This slice only *produces* the floor substrate; it does not watch it.
- **Follow-up** — consolidate `upper_control_limit`, `shewhart_c_chart_ucl`, and this engine's individuals chart into one shared `shewhart` module.
- No scenario / sandbox-e2e layer is added in this slice, and that is deliberate, not skipped: there is no new loop, no label transition, and no UI/docker wiring to exercise — the deliverable is a pure engine + ledger, whose whole contract is covered by fast unit tests. Those layers become load-bearing when the Phase-2 calibration loop lands.

## Consequences

- **Positive:** every generative finder gains a *measured* noise floor and an actuation threshold provably above it, so a finder can no longer be quietly configured to fire on its own noise. The floor is exactly the sensor covariance the stillness setpoint layer (#10824) and the noise-floor faceplate band (#10826) need. The read-only contract means the instrument can be trusted to run anywhere without risk of it silently retuning a finder.
- **Cost:** the floor is only as trustworthy as the golden baseline's vetting; a mis-vetted or stale baseline miscalibrates everything measured against it — hence the mandatory staleness guardrail and the low-confidence marking on thin samples.
- **Negative / watch:** the confident-path chart duplicates control-limit math that also lives in two other modules; the reuse of `shewhart_c_chart_ucl` for the degenerate case keeps the duplication honest and bounded, and the consolidation follow-up is the guard against three-way drift. Until the Phase-2 real runner lands, no floor is measured from live finder behaviour — the engine is proven against injected counts only, and that boundary is stated rather than blurred.
