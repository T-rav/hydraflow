# ADR-0096: Boundary verdict recording (Phase 2b)

- **Status:** Accepted
- **Date:** 2026-06-30
- **Refines:** ADR-0094 (two-level convergence: Gate + ConvergenceLedger)
- **Extends:** ADR-0095 (approve-path gating)

> **Superseded in part by [ADR-0100](0100-convergence-gate-general-availability.md):** the `convergence_gate_enabled` flag has been removed; the convergence gate is now the sole, always-on review path and the legacy ungated fallback is deleted. The flag-gated / dark-ship framing below is historical.

## Context

ADR-0094 wired the convergence Gate and ConvergenceLedger at the Review boundary only. Phase 2a (ADR-0095) then gated the approve path so that `ledger.converged` became a real, reachable signal. Lap accounting and `mark_lap`/`recompute_converged` are Review-owned throughout both phases.

The other pipeline boundaries (Triage, Shape, Plan) still make ADVANCE/LOOP_BACK/ESCALATE-shaped decisions inside their own engines: `AdversarialRetryLoop`-backed councils and judges (Shape, Plan), and scoring-based routing (Triage). However, the ledger has no pipeline-wide view of those decisions. That gap blocks the Phase 2d oscillation caretaker, which needs cross-boundary verdict history to detect oscillation across stage boundaries, not just within the Review boundary.

## Decision

Each pipeline boundary records a uniform verdict and finding signatures into the per-issue `ConvergenceLedger` AFTER its existing decision, via one gated helper:

```
record_stage_verdict(state, *, enabled, issue_number, stage, decision, signatures)
```

This helper lives in `src/convergence_recording.py`.

### Record, not replace (Fork 2)

The helper is a side-write, inserted immediately before an existing return site. It does NOT alter any phase's control flow, decision logic, or inner engine. Triage scoring, ShapeExpertCouncil, PlanCouncil, SpecJudge, and AssumptionSurfacer are all untouched. The boundary still makes its own decision by its own mechanism; the recording is purely observational.

### Verdict mapping per boundary

- **Triage:** outcomes `{plan, sentry_noise_closed, already_addressed, epic_decomposed, bug_not_present}` map to ADVANCE; outcomes `{discover, parked}` map to LOOP_BACK; any other outcome produces no record.
- **Shape:** finalized / selection-made / council-consensus maps to ADVANCE; waiting maps to LOOP_BACK.
- **Plan:** outcome `success` maps to ADVANCE; outcome `failed` maps to LOOP_BACK; outcome `escalated` maps to ESCALATE; an already-satisfied-closed early exit maps to ADVANCE.
- **Signatures:** Shape and Plan use `signatures_from_concerns(adv.pending_concerns)`, which extracts sorted, unique CRITICAL/HIGH concern text from the adversarial loop state. Triage uses `[]` (no adversarial concerns at that boundary).

### Lap/converged stay review-owned

The boundary recording writes only `stage_state[stage].last_verdict` and `last_finding_signatures` into the ledger. It does NOT call `mark_lap` or `recompute_converged`. Those remain the Review boundary's exclusive responsibility, preserving the Phase 1/2a lap and `converged` semantics without change.

Rationale: a single outer-lap definition anchored at Review is simpler to reason about and avoids multiplying the lap concept across boundaries. Boundary records are observability and oscillation input, not lap drivers.

## Rules and consequences

1. **Inert when disabled.** When `convergence_gate_enabled` is off, the helper is a no-op, and each phase is byte-for-byte unchanged.
2. **Verdict strings are exact.** The only legal values are `"ADVANCE"`, `"LOOP_BACK"`, and `"ESCALATE"`. No other strings are written to the ledger.
3. **Pipeline-wide history.** With recording active, the ledger accumulates a verdict history across Triage, Shape, Plan, and Review boundaries. The Phase 2d oscillation caretaker consumes this history to detect repeated LOOP_BACK patterns that span multiple stages.
4. **Cost.** One small ledger write and save per boundary decision when the flag is on. No additional LLM calls.

## Scope (Phase 2b)

This ADR covers the `record_stage_verdict` helper, its integration at the Triage, Shape, and Plan boundaries, and the MockWorld pipeline scenario that exercises the full recording flow. Out of scope: counter migration into the ledger (Phase 2c) and the `ConvergenceOscillationLoop` caretaker (Phase 2d).

## Alternatives considered

1. **Replace each boundary's engine with the Gate.** Rejected. The councils and judges are the domain logic for those phases. The Gate is a referee for convergence, not a planner or shape evaluator. Replacing the engines would conflate two distinct concerns and break the established domain decomposition.
2. **Have each boundary call `mark_lap`/`recompute_converged`.** Rejected. That would multiply the lap definition across boundaries, producing multiple conflicting lap anchors and breaking the single review-anchored outer lap established in Phases 1 and 2a.

## When to supersede this ADR

Supersede when a boundary's recording contract changes (for example, if a boundary begins driving laps), or when Phases 2c or 2d change what the ledger stores or how verdict history is structured.

## Source-file citations

- `src/convergence_recording.py`: `record_stage_verdict`, `signatures_from_concerns`.
- `src/triage_phase.py`: integration of `record_stage_verdict` at Triage decision sites.
- `src/shape_phase.py`: integration of `record_stage_verdict` at Shape decision sites.
- `src/plan_phase.py`: integration of `record_stage_verdict` at Plan decision sites.
- `tests/scenarios/test_convergence_pipeline_mockworld.py`: MockWorld pipeline scenario exercising the full cross-boundary recording flow.
