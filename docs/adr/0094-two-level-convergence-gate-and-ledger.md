# ADR-0094: Two-level convergence: Gate + ConvergenceLedger

- **Status:** Accepted
- **Date:** 2026-06-30
- **Supersedes:** none
- **Related:** ADR-0001 (five concurrent async loops), ADR-0002 (labels as state machine), ADR-0029 (caretaker loop pattern), ADR-0049 (kill-switch convention), ADR-0051 (iterative production-readiness review), ADR-0059 (advisor-pattern self-repairing review)

## Context

HydraFlow's pipeline already converged in places, but unevenly, and nothing represented "this issue has converged across the whole pipeline."

Two concrete gaps motivated this work:

1. **Inner convergence was non-uniform.** Three different engines did the same job with different guarantees: `AdversarialRetryLoop` (Discover/Shape/Plan critics, with budget + oscillation detection), Implement's hand-rolled `for attempt in range(max)` loops (no oscillation detection, no concern-forwarding), and Shape's one-off evaluator retry. The review-fix retry was a flat per-stage counter.
2. **There was no outer fixpoint object.** The "outer loop" was emergent: label requeue (ADR-0002) plus a half-dozen separate per-issue counters scattered across `state/` (`review_attempts`, `auto_agent_attempts`, `sandbox_failure_fixer_attempts`, `quality_fix_attempts`, `review_blast_radii`). Cross-stage feedback was hand-wired per pair. Oscillation detection existed only inside stages, never across them, so the outer loop could ping-pong with nothing to catch it.

The target is a **two-level Ralph loop**: every stage loops until an independent referee says its goal is met (inner), and the pipeline cycles the issue until a full pass clears every gate (outer), with both levels oscillation-safe and HITL as a floor rather than a per-step clock.

This ADR records the foundation (Phase 1): the `Gate` referee, the `ConvergenceLedger`, and the wiring of both to the Review reject boundary as the proof point.

## Decision

### D1: Gate referee: hybrid, blast-radius-scaled

A uniform `Gate` abstraction (`src/convergence_gate.py`) renders one of three decisions: `ADVANCE`, `LOOP_BACK(target, feedback)`, `ESCALATE(reason)`. The concrete `HybridGate` evaluates in this order:

1. Run the deterministic check. If it is not green, return `LOOP_BACK` immediately. The judge never runs (a judge cannot wave through a red deterministic signal).
2. Otherwise run `N` independent judge passes, where `N = review_advisor.min_review_passes_for_blast_radius(blast_radius)` (low 1 / medium 2 / high 3). The blast-radius table is the single source of truth from ADR-0051; the gate does not invent a second one.
3. If all judges approve, `ADVANCE`. If any vetoes, `LOOP_BACK` while attempts remain, else `ESCALATE`.

The judge runs as an independent role (the `hydraflow-review-advisor` dispatch from ADR-0059), never the same invocation that produced the artifact, so the gate cannot rubber-stamp its own output.

### D2: Outer loop: requeue + ConvergenceLedger

The ADR-0001 independent loops and ADR-0002 label state machine are preserved. A first-class per-issue `ConvergenceLedger` (Pydantic model on `StateData`, accessed via `ConvergenceStateMixin`) becomes the single source of truth for per-issue convergence state: `laps`, `blast_radius`, `stage_state` (per-stage `attempts` + `last_verdict` + `last_finding_signatures`), `open_concerns`, `lap_signatures`, and `converged`.

**No dual-write.** Every per-issue counter has exactly one owner. Phase 1 deletes the legacy `StateData.review_attempts` and `StateData.review_blast_radii` fields and moves that state into the ledger; the public accessor names (`get_review_attempts`, `increment_review_attempts`, `reset_review_attempts`, `set/get_review_blast_radius`, `min_review_passes_required`) are preserved on `StateTracker`, delegating to the ledger, so existing call sites are unchanged.

### Storage / decision split

The "do not coexist" rule forced a clean layering that also resolves the kill-switch tension:

- **Ledger = storage layer, always on.** Plain persisted state, behind no flag.
- **Gate = decision layer, flag-gated** by `convergence_gate_enabled` (default `False`, opt-in rollout). Disabling the gate reverts the *decision* to the legacy path, which still reads attempt state from the ledger (the legacy counters are gone). The flag toggles how the verdict is computed, not where the count lives.

Consequence: the kill switch reverts the decision, not the storage. Full rollback of the storage change is a revert PR, not a flag. That is the accepted price of no-coexist.

### Outer convergence and oscillation

- **Converged (issue done):** a full lap where every visited gate returned `ADVANCE` and `open_concerns` is empty (`recompute_converged`).
- **Outer oscillation:** `detect_outer_oscillation` escalates to HITL when a finding-signature set repeats across laps, lifting `AdversarialRetryLoop`'s in-stage idea to the pipeline level.
- **Lap budget:** `max_convergence_laps` (default 3) caps outer laps; exhaustion converts a `LOOP_BACK` into `ESCALATE`.

## Rules and decisions discovered during implementation

These are load-bearing and were settled while wiring Phase 1. They are recorded here because they are non-obvious:

1. **At the Review reject boundary, escalation is governed by the outer lap budget (`max_convergence_laps`), not the legacy per-stage `max_review_fix_attempts`.** Because the reject path's deterministic signal is always red, `HybridGate` loops back unconditionally and never reaches its per-stage attempt-cap branch; the cap that bounds the review→implement→review cycle is the outer lap budget plus oscillation. A review→implement→review round-trip is a cross-stage outer lap, so this is the intended unification, not a regression. When the flag is on, `max_review_fix_attempts` is superseded at this boundary; this is documented on the `convergence_gate_enabled` config field to prevent operator surprise. Under default config the two coincide (the legacy cap of 2 and `max_convergence_laps` of 3 both escalate on the third review), so existing behavior is preserved.

2. **`ledger.converged` is a Phase-2-meaningful field.** Phase 1 wires the gate only into `_handle_rejected_review`; the APPROVE → merge path is ungated. `recompute_converged` therefore never records an `ADVANCE` for the review stage, so `converged` stays `False` throughout Phase 1. The ledger's Phase-1 value is attempt/lap tracking, oscillation detection, and the lap budget at the reject boundary. `converged` becomes meaningful when the APPROVE path is gated (Phase 2). Tests and the sandbox scenario assert what Phase 1 actually produces (loop-back recorded, `laps >= 1`, review `last_verdict == "LOOP_BACK"`), not `converged`.

3. **Failure-soft, never deadlock.** A deterministic-check infrastructure failure is treated as red (`LOOP_BACK`), since green cannot be proven. A judge-dispatch failure calls `reraise_on_credit_or_bug(exc)` first (so credit exhaustion and likely bugs propagate, never swallowed), then degrades to the documented per-gate default verdict (`APPROVE` at Review unless `HYDRAFLOW_REVIEW_POSTVERIFY_FAIL_AS_VETO=true`, matching ADR-0059).

4. **Migration is non-crashing, with an accepted transient loss.** Deleting `review_attempts`/`review_blast_radii` is safe because `StateData` ignores unknown keys: a pre-change `state.json` loads cleanly and `convergence_ledgers` defaults to empty. Issues mid-review-retry at the moment of upgrade reset their review-fix count and blast radius to defaults. This is acceptable because both drive a soft retry budget, not a correctness invariant; the worst case is one slightly more generous retry round after deploy.

## Scope (Phase 1)

The gate is wired to exactly one boundary: the Review reject decision (`_handle_rejected_review_gated`). The APPROVE → merge path and `PostVerifyAdvisor` are intentionally unchanged. Running the hybrid judge as N-passes-by-blast-radius on the APPROVE path tangles with PostVerifyAdvisor's existing veto/retry loop and is deferred to Phase 2. Phase 1 proves the gate, the ledger, the outer lap budget, and oscillation detection at a real boundary with bounded blast radius. Phase 2 rolls the gate to other boundaries and gates the APPROVE path; Phase 3 folds Implement's hand-rolled loops onto the unified engine.

## Telemetry / observability

The full `ConvergenceLedger` per issue is exposed in `/api/state` under `convergence_ledgers` (no dashboard change was required). The sandbox e2e scenario asserts against this surface. Per-decision gate event emission is deferred to a later phase.

## Consequences

- One convergence primitive and one outer-loop object replace scattered counters and ad hoc cross-stage feedback at the Review boundary.
- The kill switch makes the decision reversible by flag; the storage change is reversible only by revert.
- The feature ships dark (flag default off); enabling it changes the review-fix cap from a per-stage count to the outer lap budget, documented on the config field.
- The full test pyramid ships: unit (`tests/test_convergence_ledger.py`, `tests/test_convergence_gate.py`), MockWorld scenario (`tests/scenarios/test_convergence_review_mockworld.py`), sandbox e2e (`tests/sandbox_scenarios/scenarios/s50_convergence_review.py`).

## Alternatives considered

- **Deterministic-only or judge-only gates.** Rejected. Deterministic-only is blind to semantic quality; judge-only risks the judge grading the worker. The hybrid (deterministic must be green AND an independent judge signs off, blast-radius-scaled) is the strongest against rubber-stamping.
- **Blocking shepherd for the outer loop** (one worker walks an issue stage-to-stage in a single fixpoint). Rejected in favor of requeue + ledger to preserve the ADR-0001 concurrency model; the fixpoint is distributed across the existing loops, with the ledger as the shared truth and oscillation detection as the safety net.
- **Coexistence of legacy counters with the ledger** (dual-write). Rejected. No datum is written in two places; the ledger is the sole owner, migrated by move-not-copy.
- **Honoring `max_review_fix_attempts` as a second cap in the gated path.** Rejected. It would create a confusing interaction between two independent caps; the outer lap budget is the single, principled bound, documented on the config.

## When to supersede this ADR

Supersede when the APPROVE path is gated (making `converged` live), when the gate is rolled to boundaries beyond Review, or when the lap budget proves the wrong bound for the review-fix cycle in practice.

## Source-file citations

- `src/convergence_gate.py`: `Gate`, `GateDecision`, `GateResult`, `GateContext`, `DetResult`, `JudgeVerdict`, `HybridGate`, `build_review_gate`.
- `src/models.py`: `StageRecord`, `ConvergenceLedger`, `StateData.convergence_ledgers`.
- `src/state/_convergence.py`: `ConvergenceStateMixin` (ledger accessors + the review-attempt/blast-radius delegations).
- `src/review_phase/_phase.py`: `_uses_convergence_gate`, `_convergence_decision`, `_handle_rejected_review_gated`.
- `src/config.py`: `convergence_gate_enabled`, `max_convergence_laps`.
- `src/review_advisor.py`: `min_review_passes_for_blast_radius`, `compute_blast_radius` (reused, not duplicated).
