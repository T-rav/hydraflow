# ADR-0098: Convergence oscillation caretaker (Phase 2d)

- **Status:** Accepted
- **Date:** 2026-07-01
- **Refines:** ADR-0094 (two-level convergence: Gate + ConvergenceLedger)
- **Extends:** ADR-0096 (boundary verdict recording)

## Context

Phase 2b (ADR-0096) made the ledger record LOOP_BACK/ADVANCE verdicts at each pipeline boundary (Triage, Shape, Plan, Review), giving the ledger a pipeline-wide verdict history for the first time. That history is observability data: no existing consumer acted on cross-boundary oscillation patterns.

The review phase (ADR-0094/0095) escalates to HITL when the outer lap budget (`max_convergence_laps`) is exhausted or when `detect_outer_oscillation` detects repeated finding-signature sets across review laps. Both signals are anchored at the Review boundary. Two classes of stuck issue are not caught:

1. Issues that ping-pong across Triage, Shape, and Plan without reaching the review lap cap. Each stage routes them back, but no global observer detects the pattern.
2. Issues that reach Review, trigger oscillation, but have not yet closed enough laps to exhaust the lap cap. The cap and oscillation detector are review-lap-anchored; a cross-boundary pattern that spans fewer review laps than the cap is invisible to them.

Phase 2d adds `ConvergenceOscillationLoop`, a background caretaker that consumes the cross-boundary verdict history accumulated by Phase 2b and escalates stuck issues to HITL before they exhaust the lap cap or loop forever in the pre-review stages.

## Decision

### Detection: `ConvergenceLedger.detect_cross_boundary_oscillation`

The detection method fires on EITHER of two complementary signals:

**Temporal signal (post-review oscillation):** `detect_outer_oscillation(window)` returns True when the last `window` review laps produced identical, non-empty finding-signature sets. `lap_signatures` unions all boundary findings at `mark_lap`, so this signal is cross-boundary-aware for issues that reach review. It can catch review-lap oscillation earlier than the lap cap when `window` is below `max_convergence_laps`.

**Snapshot signal (pre-review churn):** at least `min_loopback_stages` distinct stages among {triage, shape, plan} currently have `last_verdict == "LOOP_BACK"`. This catches cross-boundary churn in issues that have not yet closed a review lap, where the temporal signal has no data.

Either signal alone is sufficient to flag an issue as oscillating. Default values: `window=2`, `min_loopback_stages=2`.

### The loop: `ConvergenceOscillationLoop`

The loop (`src/convergence_oscillation_loop.py`, class `ConvergenceOscillationLoop(BaseBackgroundLoop)`, worker name `convergence_oscillation`) runs on a configurable interval and performs three steps:

1. Enumerate all per-issue ledgers via `StateTracker.iter_convergence_ledgers()`, a new public accessor added to `src/state/_convergence.py`.
2. Skip any ledger where `ledger.converged` is True or `ledger.oscillation_escalated` is True.
3. For each remaining ledger, call `detect_cross_boundary_oscillation`. If it fires, create a companion HITL issue labeled with the HITL escalation label and `convergence-oscillation`, then set `ledger.oscillation_escalated = True` and persist.

The dedup flag (`oscillation_escalated`) is set only AFTER a successful `create_issue` call, so a failed create retries on the next interval. A failed create that raises a credit or bug exception is not swallowed: `reraise_on_credit_or_bug(exc)` is called in the broad `except` block before any fallback, propagating `CreditExhaustedError` and likely-bug exceptions upward (per the dark-factory contract in `docs/wiki/dark-factory.md` section 2.2).

The loop makes no LLM calls (`LONG_LLM_CYCLE = False`). `loop_fitness` is `HOUSEKEEPING / INSUFFICIENT_DATA`: the caretaker has no clean per-item acceptance signal because escalation is a one-shot side effect, and the absence of oscillation is the healthy state.

### Read-only-except-dedup contract

The loop NEVER calls `mark_lap`, `record_gate_result`, `increment_attempts`, or `recompute_converged`. Those methods remain exclusively owned by the review phase. The loop's only ledger write is the `oscillation_escalated` dedup flag. This contract keeps boundary phases simple: each boundary records its own verdict and drives its own lap accounting; the caretaker is a read-only observer that fires a one-shot side effect when a global pattern is detected.

### Control and safety

Two-layer kill switch per ADR-0049: an in-body `_enabled_cb` callback checks the live config value, and the config field `convergence_oscillation_loop_enabled` (default True) provides operator-level control. The loop also checks `dry_run` before creating any issue: in dry-run mode, detection runs but no issues are filed.

### Configuration

All fields are env-overridable:

- `convergence_oscillation_interval` (default 3600, ge=300): polling interval in seconds.
- `convergence_oscillation_loop_enabled` (default True): operator kill switch.
- `convergence_oscillation_window` (default 2): number of review laps compared by the temporal signal.
- `convergence_oscillation_min_loopback_stages` (default 2): minimum distinct stages at LOOP_BACK required for the snapshot signal.

### Relationship to review escalation

The caretaker complements, and does not replace, the review phase's lap-cap escalation. The lap cap catches issues that exhaust their review budget regardless of oscillation pattern. The caretaker catches two cases the lap cap misses: (a) cross-boundary churn that never reaches the review lap cap, and (b) review-lap oscillation that repeats before the cap is reached. Both mechanisms can trigger on the same issue without conflict: `oscillation_escalated` prevents duplicate caretaker escalations, while the lap cap follows its own logic independently.

## Rules and consequences

1. **Read-only contract is absolute.** The loop must not call any ledger method that advances lap state or alters verdicts. The only permitted ledger write is `oscillation_escalated`. Violating this would corrupt the review phase's lap accounting.
2. **Dedup flag set after, not before, the create.** A pre-set flag would suppress retries on a failed create, leaving the issue unescalated with no way to recover without operator intervention.
3. **Credit and bug exceptions propagate.** The broad `except` block must call `reraise_on_credit_or_bug(exc)` before any fallback. Swallowing `CreditExhaustedError` silently burns attempt budget against an exhausted billing signal.
4. **Dry-run is respected.** The loop may detect oscillation in dry-run mode, but it must not create any issue. Dry-run logs the detection for observability without side effects.
5. **Config knobs are additive, not subtractive.** Tightening `convergence_oscillation_window` or `convergence_oscillation_min_loopback_stages` causes earlier escalation. Loosening them reduces sensitivity. Neither affects the review lap cap.
6. **`oscillation_escalated` is terminal.** Once set, the caretaker ignores that ledger. Clearing it to re-escalate requires operator intervention on the state file.

## Scope (Phase 2d)

This ADR covers:

- The `detect_cross_boundary_oscillation` detection method and the `oscillation_escalated` dedup flag, both on `ConvergenceLedger` (`src/models.py`).
- The `iter_convergence_ledgers` public accessor and `mark_oscillation_escalated` helper on `StateTracker` (`src/state/_convergence.py`).
- `ConvergenceOscillationLoop` and its full orchestrator and registry wiring (`src/convergence_oscillation_loop.py`).
- The full test pyramid: unit tests for detection and the loop, a MockWorld scenario, and a sandbox e2e scenario.

This completes the Phase 2 arc. Phase 2a gated the approve path. Phase 2b added cross-boundary verdict recording. Phase 2c migrated attempt counters into the ledger. Phase 2d adds the oscillation caretaker that consumes Phase 2b's verdict history. Nothing in Phase 2d is out of scope as deferred: all invariants (functional_areas.yml, scenario catalog, event reducer, orchestrator wiring, registry, AST ratchets) are addressed in Tasks 1-5.

## Alternatives considered

1. **Observability only, no auto-escalation.** Emit a metric or log when oscillation is detected, and leave escalation to a human watching a dashboard. Rejected. The whole point of the caretaker is an autonomous safety net. An operator watching a dashboard reintroduces the human-in-the-loop latency the pipeline exists to eliminate. Issues stuck in oscillation can consume resources indefinitely without an automated response.

2. **Reuse the review-lap temporal detection only, no snapshot signal.** Run `detect_outer_oscillation` across all ledgers and skip the snapshot check. Rejected. This misses the pre-review cross-boundary churn case: issues that loop between Triage, Shape, and Plan without ever closing a review lap have no lap data for the temporal signal to operate on. Those issues would loop forever under this approach.

3. **Let each boundary drive escalation inline when it detects repeated LOOP_BACK.** Each phase checks its own LOOP_BACK count and escalates when it exceeds a threshold. Rejected. This duplicates escalation logic across three boundary phases, makes the threshold a per-phase config that must be kept consistent, and produces escalation events from multiple sites for the same issue. A centralized read-only caretaker sees the full cross-boundary picture, escalates once, and keeps boundary phases responsible only for their own verdicts.

## When to supersede this ADR

Supersede when: the detection algorithm changes (for example, adding a frequency-based signal or making the window adaptive); the `oscillation_escalated` dedup strategy changes (for example, to allow re-escalation after a configurable cooldown); the loop gains LLM calls or a different fitness classification; or Phase 3 folds oscillation handling into a unified convergence runner that replaces the caretaker pattern.

## Source-file citations

- `src/models.py`: `ConvergenceLedger.detect_cross_boundary_oscillation`, `ConvergenceLedger.oscillation_escalated`.
- `src/state/_convergence.py`: `StateTracker.iter_convergence_ledgers`, `StateTracker.mark_oscillation_escalated`.
- `src/convergence_oscillation_loop.py`: `ConvergenceOscillationLoop`, worker `convergence_oscillation`.
- `tests/scenarios/test_convergence_oscillation_mockworld.py`: MockWorld scenario exercising the full caretaker flow.
- `tests/sandbox_scenarios/scenarios/s51_convergence_oscillation.py`: sandbox e2e scenario.
