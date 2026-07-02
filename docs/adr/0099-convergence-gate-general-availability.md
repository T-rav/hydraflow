# ADR-0099: Convergence gate general availability (flag removed)

- **Status:** Accepted
- **Date:** 2026-07-01
- **Supersedes (in part):** ADR-0094, ADR-0095 (their dark-ship / flag-gated clauses)
- **Refines:** ADR-0094
- **Enforced by:** `tests/test_review_phase_core.py`, `tests/scenarios/test_convergence_review_mockworld.py`, `tests/sandbox_scenarios/scenarios/s50_convergence_review.py`

## Context

ADR-0094 introduced the convergence `HybridGate` and `ConvergenceLedger`, but shipped both behind a `convergence_gate_enabled` flag (default `False`, opt-in rollout). The legacy ungated review path (`_run_post_verify_advisor` plus `_handle_approved_merge`, bounded by the `max_review_fix_attempts` reject cap) remained the live code path while the gate was off.

ADR-0095 then gated the APPROVE path, making `ledger.converged` a real signal, still behind the same flag. The "do not coexist" principle was declared in ADR-0094, but the dark-ship hedge meant a dual code path was maintained: the legacy fork for flag-off repos and the gated fork for flag-on repos.

Phases 2b through 2d (ADR-0096, ADR-0097, ADR-0098) built on top of this foundation, adding cross-boundary verdict recording, attempt-counter migration, and the oscillation caretaker. All are production-ready. The flag and its accompanying legacy code path are maintenance debt with no remaining rationale: the gate has a tested fail-safe (degraded advisor loops back conservatively; lap budget exhaustion escalates to HITL), and keeping the legacy path in production is untested-in-prod hedging rather than a real safety net.

This ADR records the removal of the flag and the deletion of the legacy ungated review fork.

## Decision

### The `convergence_gate_enabled` flag is deleted

The config field `convergence_gate_enabled` is removed from `src/config.py`. There is no replacement flag. The gate is always on.

### The convergence HybridGate + ConvergenceLedger are the sole, always-on review/decision path

Both Review APPROVE and Review REJECT decisions route exclusively through the gated handlers:

- **APPROVE:** `_handle_approved_review_gated` calls `_convergence_decision(review_approved=True)`, which runs the deterministic check (`_approve_deterministic_check`), then runs `PostVerifyAdvisor` once per ordered lens (correctness, security, spec, scaled by blast radius via `min_review_passes_for_blast_radius`). ADVANCE merges. LOOP_BACK re-queues to ready for re-implementation. ESCALATE opens a HITL companion issue.
- **REJECT:** `_handle_rejected_review_gated` calls `_convergence_decision(review_approved=False)`. The reject deterministic signal is always red; the gate loops back unconditionally and, at the outer lap budget, escalates to HITL.

`_convergence_decision` is the single decision seam for both verdicts at the Review boundary.

### Boundary verdict recording is unconditional

`record_stage_verdict` in `src/convergence_recording.py` no longer checks `convergence_gate_enabled`. Each call at the Triage, Shape, and Plan boundaries records a verdict and finding signatures into the per-issue ledger unconditionally on every pipeline run.

### Deleted code

The following are removed and not replaced:

- The `convergence_gate_enabled` config field and its `HYDRAFLOW_CONVERGENCE_GATE_ENABLED` env override.
- `_uses_convergence_gate` (the helper that read the flag and branched dispatch).
- `_run_post_verify_advisor` (the legacy ungated review method, which ran PostVerifyAdvisor inside its own internal veto/retry `while`-loop and handed back to the executor on retry). This is the method the gate replaced; with the gate always on, the method is unreachable and deleted.
- The `post_verify_retry_budget` blast-stratified table (the per-veto retry budget that `_run_post_verify_advisor` consumed; the gate uses the `BLAST_RADIUS_RETRIES` table instead, which is retained).
- The legacy `max_review_fix_attempts` reject-cap body of `_handle_rejected_review`. The legacy handler is replaced entirely by `_handle_rejected_review_gated`; escalation at the reject boundary is now governed by `max_convergence_laps` plus oscillation detection.

### Retained: `BLAST_RADIUS_RETRIES` and `min_review_passes_for_blast_radius`

These are the gate's blast-radius-scaled lens-pass count mechanism and remain unchanged. They are not the deleted legacy retry budget.

## Rules and consequences

1. **The gate governs every real merge.** There is no flag-off path, no runtime bypass, and no legacy fallback code. An APPROVE merges only when the PostVerifyAdvisor lens judge returns a clean ADVANCE.
2. **Review-reject escalation uses `max_convergence_laps` and oscillation detection, not `max_review_fix_attempts`.** `max_review_fix_attempts` no longer bounds the review to implement to review cycle at the Review boundary. Operators who previously tuned `max_review_fix_attempts` should review `max_convergence_laps` instead.
3. **A degraded advisor loops back, not merges.** If PostVerifyAdvisor fails (non-credit, non-bug exception), the gate degrades conservatively to LOOP_BACK (unless `HYDRAFLOW_REVIEW_POSTVERIFY_FAIL_AS_VETO=false` inverts this). The gate never silently advances a degraded verdict. Credit exhaustion and likely-bug exceptions propagate via `reraise_on_credit_or_bug(exc)`.
4. **The gate goes LIVE in production on the next rc promotion to main.** The flag-off safety net is gone; confirm `max_convergence_laps` and `HYDRAFLOW_REVIEW_POSTVERIFY_FAIL_AS_VETO` are set to the intended production values before the RC is cut.
5. **`convergence_gate_enabled` in existing env configs is a no-op warning.** Any operator env file or CI secret that set this variable does nothing after deploy. Remove them to avoid confusion.
6. **Boundary recording incurs one small ledger write per boundary decision on every run.** This was previously gated behind the flag; it is now unconditional. The cost profile is unchanged from a flag-on deploy.

## Alternatives considered

1. **Keep the flag for staged rollout.** Rejected. The "do not coexist" principle (ADR-0094) was accepted at design time precisely to avoid a permanent dual code path. The gate is production-ready with tested fail-safes; staged rollout via a long-lived flag is maintenance debt and untested-in-prod hedging. Removing the flag was the declared intent when the gate was judged ready.
2. **Keep the legacy path as a runtime fallback for gate failures.** Rejected. The gate already has a fail-safe: a degraded or failing advisor loops back conservatively, and lap-budget exhaustion escalates to HITL. A separate legacy code path is not a safety net; it is a second, largely untested branch that diverges under load. The gate's own fail-open behavior is the correct response to gate failures.

## When to supersede this ADR

Supersede if: a future need for staged rollout or a runtime gate-bypass emerges (for example, a new boundary type or a dramatically different review model); the Review decision model changes such that `_convergence_decision` is no longer the sole decision seam; or Phase 3 folds Review convergence into a unified convergence runner that replaces the gated handlers.

## Source-file citations

- `src/review_phase/_phase.py`: `_handle_approved_review_gated`, `_handle_rejected_review_gated`, `_convergence_decision` (sole decision path for both APPROVE and REJECT).
- `src/convergence_recording.py`: `record_stage_verdict` (unconditional, flag check removed).
- `src/config.py`: `convergence_gate_enabled` field removed.
