# ADR-0095: Approve-path gating and live convergence (Phase 2a)

- **Status:** Accepted
- **Date:** 2026-06-30
- **Refines:** ADR-0094 (two-level convergence: Gate + ConvergenceLedger)
- **Related:** ADR-0051 (blast-radius review passes), ADR-0059 (advisor-pattern self-repairing review / PostVerifyAdvisor), ADR-0049 (kill-switch convention)

> **Superseded in part by [ADR-0101](0101-convergence-gate-general-availability.md):** the `convergence_gate_enabled` flag has been removed; the convergence gate is now the sole, always-on review path and the legacy ungated fallback is deleted. The flag-gated / dark-ship framing below is historical.

## Context

ADR-0094 shipped the convergence `Gate` + `ConvergenceLedger` wired only into the Review **reject** boundary. It explicitly left two things for a later phase and named the supersession trigger: "supersede when the APPROVE path is gated (making `converged` live)." Under Phase 1, `ledger.converged` was structurally unreachable, because the reject path only ever records `LOOP_BACK`/`ESCALATE`, never `ADVANCE`.

Phase 2a closes that gap: it routes the Review APPROVE decision through the same gate, so a clean approve records `ADVANCE` and `converged` becomes a real, reachable signal. It remains behind `convergence_gate_enabled` (default off).

## Decision

### Unified decision through `_convergence_decision`

The APPROVE path now flows through the same `_convergence_decision` seam the reject path uses, with `review_approved=True`. That method is the single place the Review boundary decides ADVANCE / LOOP_BACK / ESCALATE for both verdicts:

- **Reject** (`review_approved=False`): deterministic signal is red, the gate loops back (unchanged from ADR-0094).
- **Approve** (`review_approved=True`): deterministic check runs, then the judge runs, then the gate combines.

### PostVerifyAdvisor becomes the gate's multi-lens judge (Fork 1)

On approve, the gate's judge is PostVerifyAdvisor, invoked `N = min_review_passes_for_blast_radius(blast_radius)` times (low 1 / med 2 / high 3, the ADR-0051 table). Because PostVerifyAdvisor had no way to render distinct perspectives, Phase 2a added a **lens** parameter:

- `PostVerifyInput.lens: Literal["correctness", "security", "spec"] | None`.
- `_POST_VERIFY_LENS_GUIDANCE` (module constant) prepends lens-specific guidance in `_build_prompt`.
- The runner role is tagged `f"post_verify:{lens}"` for telemetry and fake-dispatch keying.

The gate runs the ordered lenses `["correctness", "security", "spec"][:N]`, so each pass is a genuinely distinct perspective rather than N identical calls. The combine is **unanimous-across-lenses**: every lens must approve to ADVANCE; any veto loops back (or escalates at the lap budget). This is the faithful realization of "N independent judge passes scaled by blast radius."

The gate **owns the retry loop**. PostVerifyAdvisor's own veto-retry budget is not consulted on the gate path: the gated approve never enters `_run_post_verify_advisor` (its internal `while`-loop), it calls `_run_post_verify_for_surface` once per lens. Loop-back to `ready` (re-implementation) is the gate's single retry mechanism, replacing the advisor's executor-handback.

### Deterministic signal on approve

The approve deterministic check is "code-scanning clean" (`_approve_deterministic_check` over `code_scanning_alerts`): open alerts → LOOP_BACK without invoking the judge, even on an APPROVE verdict (do not merge a PR with open code-scanning alerts). CI check-status is not yet folded into the deterministic layer; that is a later refinement.

### `converged` goes live

On all-lens APPROVE + deterministic green, the gate records `ADVANCE`; `recompute_converged(["review"])` then sets `converged=True` (all visited gates ADVANCE and no open concerns) and the ledger persists it. This is reachable and proven at unit, MockWorld, and sandbox layers.

## Rules and consequences

1. **Cost.** Running PostVerifyAdvisor N times multiplies LLM cost and latency on the merge path for medium/high-blast PRs. This is the accepted price of blast-radius-scaled scrutiny: trivial diffs get one pass, high-blast diffs get three distinct-lens passes.
2. **Side-effect parity.** The gated approve escalate mirrors the gated reject escalate: it sets `EscalationContext` (including `agent_transcript`), calls `record_harness_failure`, publishes "escalating" status, escalates via `_escalate_to_hitl`, and seeds a memory suggestion via `_suggest_memory`. The two gated escalates share these side effects; the reject escalate additionally refines its cause text via `detect_outer_oscillation`, which the approve escalate does not need.
3. **Failure-soft preserved.** A judge-dispatch failure calls `reraise_on_credit_or_bug(exc)` first (credit exhaustion never swallowed), then degrades to the documented default (APPROVE unless `HYDRAFLOW_REVIEW_POSTVERIFY_FAIL_AS_VETO`).
4. **Flag-off unchanged.** With `convergence_gate_enabled` off, the approve path is byte-for-byte the legacy `_run_post_verify_advisor` + `_handle_approved_merge` flow; the gate branch is a guarded early return.
5. **Observability shift.** On gate-on repos, PostVerifyAdvisor's veto/retry metric series go quiet (the gate records decisions in the ledger instead). Dashboards watching those series should read the convergence ledger. The pre-flight prior-attempt heuristic (`_advisor_attempt`) is not bumped across gate loop-backs; the ledger `attempts` is the authoritative loop counter.

## Scope (Phase 2a)

This ADR covers the Review approve boundary only. The rest of Phase 2 follows as stacked increments: 2b rolls uniform verdict recording to the Triage / Shape / Plan boundaries (record, not replace their inner `AdversarialRetryLoop` engines), 2c migrates the remaining scattered counters into the ledger, and 2d adds a caretaker loop for pipeline-wide oscillation. Phase 3 (Implement RED/GREEN/REFACTOR convergence) remains out of scope.

## Alternatives considered

- **Single PostVerify pass + record converged** (no N-multiplication): smaller, but does not deliver the blast-radius-scaled scrutiny the design calls for. Rejected in favor of the lens infrastructure.
- **Majority of N identical passes**: cheaper than distinct lenses but only samples LLM variance rather than distinct perspectives; weaker scrutiny. Rejected in favor of genuinely distinct lenses.
- **Keep PostVerifyAdvisor's own retry loop and stack the gate on top**: two retry loops, confusing budgets. Rejected; the gate owns the single loop.

## When to supersede this ADR

Supersede when the gate is rolled to non-Review boundaries (2b) in a way that changes the recording contract, or when the deterministic layer folds in CI check-status, or when the lens set or combine rule changes.

## Source-file citations

- `src/review_advisor.py`: `PostVerifyInput.lens`, `_POST_VERIFY_LENS_GUIDANCE`, role tagging in `run`, `min_review_passes_for_blast_radius`.
- `src/review_phase/_phase.py`: `_approve_deterministic_check`, `_lenses_for`, `_post_verify_lens_judge`, `_convergence_decision` (approve branch), `_handle_approved_review_gated`, the approve decision site in `_run_post_review_actions`.
- `src/convergence_gate.py`: `HybridGate`, `build_review_gate` (reused from Phase 1).
- `src/models.py`: `ConvergenceLedger.recompute_converged` (now reachable on approve).
- Tests: `tests/test_review_advisor.py` (lens), `tests/test_review_phase_core.py` (`TestApproveConvergenceGate`), `tests/scenarios/test_convergence_review_mockworld.py` (converged True e2e), `tests/sandbox_scenarios/scenarios/s50_convergence_review.py`.
