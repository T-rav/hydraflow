# ADR-0133: Vitals methodology — widened-limit multiplicity, published MDE, and time-between-events charts

- **Status:** Proposed
- **Date:** 2026-08-09
- **Related:** [ADR-0120](0120-stillness-control-architecture.md) (Stillness control architecture — the setpoint regulators + innovation-filtered sensing this methodology makes readable as evidence); [ADR-0126](0126-golden-baseline-finder-calibration.md) (Finder calibration — measures a finder's noise floor `R`; a *per-instrument* companion to this *fleet-wide* multiplicity ruling); [ADR-0125](0125-mutation-gauntlet-gate-sensitivity.md) (Mutation gauntlet — gate sensitivity, another instrument that inherits these limits); [ADR-0129](0129-adr-checkable-assertion-density.md) (Checkable-assertion density — one of the charts governed here). Governs the existing control-limit machinery in `src/vitals/control.py` (`3.0·sigma_hat` individuals chart), `src/finder_calibration.py` (`DEFAULT_SIGMA_K = 3.0`), `src/audit/governance.py` (`upper_control_limit`), and `src/judge_independence.py` (`shewhart_c_chart_ucl`).
- **Enforcement:** enforced
- **Enforced by:** `pytest:tests/test_vitals_methodology.py`
- **Binds:** factory
- **Addresses:** #10838 (Vitals methodology: pick a multiplicity regime, publish minimum detectable effect, fix rare-event charts). Everything downstream (#10367, #10370, #10373, #10829, #10836, #10837) inherits it.

> **This is a Proposed ADR — a design ruling for decision, not an accepted commitment.** It formalizes the multiplicity regime the author already RULED in #10838 (widened limits, 2026-07-29), pins the arithmetic in an executable engine (`src/vitals_methodology.py`), and, deliberately, records what is *settled maths today* versus what is *deferred migration* (rewiring the live charts to consume it). The engine is a pure library, not a background loop, and it changes no live alarm threshold on its own. Accept, amend, or reject.

## Context

The factory now runs a fleet of vitals instruments — finder calibration (#10821), judge calibration (#10836), the judge-independence c-chart, checkable-assertion density (#10917), the escape and erosion ledgers, the second-order vitals, the sampled re-audit's rate governor. Each is an individuals or c-chart with a limit at a hardcoded **3σ**. Read one at a time, a 3σ chart is honest: an in-control process breaches it ~0.13% of the time (one-sided). Read as a **fleet of ~70 charts, each evaluated on a cadence**, the same 3σ produces a false alarm somewhere almost every cycle — and a fleet that always shows *something* adverse is a fleet nobody reads. **This determines whether the vitals mean anything, and it must be settled before any of them are cited as evidence.**

Three properties are missing, and #10838 researched each to a citable answer:

1. **A multiplicity regime.** Classical SPC does *not* treat charts as hypothesis tests — it designs by average run length, and the Shewhart/Wheeler/Deming tradition rejects the p-value framing outright. There are three legitimate answers (widened limits; per-cycle Benjamini-Hochberg FDR; online FDR), and an ARL-designed chart with a BH-adjusted alarm gives *neither* guarantee. One must be chosen and never mixed.
2. **Power.** A metric can be charted yet be incapable of detecting the effect it claims to monitor. A loop merging 30×/month at a 5% escape rate produces ~1.5 events/month; detecting a doubling on that volume takes ~7 months of pooling, so any monthly "escapes are flat" claim on it is not evidence.
3. **Rare-event handling.** Count charts degenerate at low counts; the lower limit pins at 0 and a rate *increase* cannot breach it.

## Decision

Four rulings, each with an executable anchor in `src/vitals_methodology.py` (tests in `tests/test_vitals_methodology.py`).

### 1. Multiplicity = **widened limits**, derived from the registered instrument count, decided at cycle granularity

**RULED (author, #10838, 2026-07-29): widened limits.** Benjamini-Hochberg FDR and online FDR are *not* adopted and must not be mixed in; we design by average run length and keep the Shewhart tradition the existing charts already assume.

- The per-chart sigma multiplier `L` is a function of the **registered instrument count** (`widened_sigma_multiplier(n_instruments)`), splitting a family-wise monthly false-alarm budget (default 5%) across the fleet by Bonferroni (or Šidák). At 70 charts this is ~3.4σ rather than 3σ; the classic group-chart result (10 uncorrelated streams → 3.64σ, Mortell & Runger 1995; Epprecht 2011) is recovered by the same function with the matching arguments.
- **The widening factor is never hardcoded** and never derives from a tick/evaluation count. It grows with the fleet, so the family-wise rate does not drift as instruments are added.
- **Floored at classic 3σ.** We only ever *widen*: a small fleet under a loose monthly budget would compute a limit *tighter* than 3σ (a single chart at 5% is 1.96σ), which would over-alarm charts built for 3σ. The floor holds the fleet at classic Shewhart until it is large enough (n ≳ 19 at the 5% default) to genuinely need wider limits.
- **Alarms are decided at CYCLE granularity, not tick granularity** (the #10838 blocker resolution). A chart's state is evaluated once per review cycle for alarm purposes; intermediate polls (`trust_fleet_sanity_interval` at 10 min, etc.) update data but cannot fire. Without this, the effective test count is `charts × ticks` — tens of thousands per month — and any fixed widening would leave the fleet reading permanently adverse. Cycle granularity gives an alarm the cleaner semantics of a statement about the cycle, and keeps the widening arithmetic dependent on chart count alone.

### 2. Alarm philosophy + triage budget (ISA-18.2 discipline — human cognition, **not** statistical false-alarm control)

Adopt the ANSI/ISA-18.2-2016 disciplines that are not statistical:

- **Rationalization.** Every instrument's alarm must carry a documented operator response, a priority, and a consequence of inaction, or it is removed. `AlarmDefinition.is_rationalized` / `rationalize()` encode this; an un-actionable alarm is not a low-priority alarm, it is noise.
- **Triage budget.** A review cycle carries a bounded triage budget (`TRIAGE_BUDGET_PER_CYCLE`, seeded at ISA-18.2's ~6 alarms/hour acceptable rate); `RationalizationReport.over_triage_budget` flags a fleet that exceeds it.
- Cite ISA-18.2 for cognitive load only — **never** as false-positive control (that is pillar 1's job).

### 3. Publish a minimum detectable effect (MDE) per instrument, or stop charting it

`mde_baseline_events(rate_ratio, alpha, power)` returns the baseline events per window needed to detect a rate ratio, using the variance-stabilized Poisson approximation `(z_{α/2} + z_power)² / (4·(√RR − 1)²)` — which at α=0.05, 80% power reproduces #10838's published table (RR 2.0→11, 1.5→39, 1.25→141, 1.1→824, 0.5→23, 0.75→109, 0.9→745). `can_chart(baseline_events, rate_ratio)` refuses a rate chart whose MDE the instrument cannot meet. Seeded defects (#10835) are the way out of the power trap for gate-recall metrics: injected faults are as plentiful as chosen, so recall gets tight intervals where real escapes never will.

### 4. Move scarce-event metrics to time-between-events (g/t) charts

`time_between_events_limits(mean_interval)` gives the Benneyan (2001) g/t-chart limits — centreline `0.693·mean` (the geometric median, since the distribution is badly right-skewed), `UCL = mean + 3√(mean²+mean)`, `LCL = max(0, mean − 3√(mean²+mean))`. Because the LCL pins at 0, deterioration (intervals collapsing toward 0) cannot breach a limit; `consecutive_zeros_run_limit()` supplies the Benneyan consecutive-zeros run rule so it still shows. Metrics like merges-between-escapes and days-between-escapes move to these charts.

## Consequences

- **The vitals become citable as evidence.** A widened-limit breach at cycle granularity, on an instrument whose MDE it meets, means what it says; a flat reading on a metric below its MDE is explicitly *not* evidence and is labelled so.
- **This ADR changes no live threshold by itself.** The four call sites that hardcode `3.0` (`vitals/control.py`, `finder_calibration.py`, `audit/governance.py`, `judge_independence.py`) continue to read 3σ until a **follow-up migration** rewires them through `widened_sigma_multiplier` against a real registered-instrument count. That migration is a deliberate behavior change to live alarms and gets its own PR + review; it is out of scope here so the methodology can be accepted independently of moving every chart at once.
- **Mixing regimes is now a documented violation.** Introducing a BH-adjusted or online-FDR alarm alongside these ARL-designed charts contradicts this ADR and requires a superseding one.
- Config cadences mismatched to their measurement window (#10843) reduce the effective test count directly and are a separate config change, not a statistics change.

## Alternatives considered

- **Per-cycle Benjamini-Hochberg FDR** (convert each chart to a p-value via Li, Qiu, Chatterjee & Wang 2013, then BH over "this month's review"). Defensible and auditable, but BH assumes independence or positive dependency and these series (escapes, erosion, interventions) are almost certainly correlated; Benjamini-Yekutieli handles arbitrary dependence at a log(m) cost. Rejected: mixing it with ARL-designed charts gives neither guarantee, and the author RULED against adopting it.
- **Online FDR across the stream** (LOND/LORD; SAFFRON/ADDIS) for a lifetime rather than per-month guarantee. Rejected for the same non-mixing reason, plus alpha-wealth budgeting makes quiet metrics progressively stingier — the wrong failure mode for a factory whose quiet metrics are the ones we most want to keep sensitive.
- **Tiered BH in production** (Optimizely's primary/secondary/monitoring split at ~10% FDR alongside always-valid p-values). Strong precedent, but it is the FDR regime this ADR declines; kept on record as the shape to copy *if* a future superseding ADR ever adopts FDR.
- **Leave every chart at a naive 3σ.** Rejected: that is the status quo that makes the fleet unreadable as it grows — the exact problem #10838 exists to fix.
