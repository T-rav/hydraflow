"""s50 — convergence gate: REQUEST_CHANGES loops back, APPROVE converges and merges.

Exercises the end-to-end convergence gate path (the gate is unconditional;
no flag or env override is required):

1. The convergence ``HybridGate`` is wired into BOTH the REJECT path
   (``_handle_rejected_review`` → ``_convergence_decision``) AND the APPROVE path
   (``_handle_approved_review_gated`` → ``_convergence_decision``) in Phase 2a.
2. First review returns REQUEST_CHANGES → gate's deterministic check is RED (review
   not approved) → gate records LOOP_BACK; ledger lap 1 is closed via ``mark_lap()``;
   issue transitions back to hydraflow-ready.
3. Re-implementation runs on the re-queued issue, producing a new branch/PR.
4. Second review returns APPROVE → routed through the convergence gate
   (``_handle_approved_review_gated``): the deterministic check passes, the
   ``PostVerifyAdvisor`` lens judge (``post_verify`` role, ``correctness`` lens for
   low blast radius) returns APPROVE → gate records ``ADVANCE`` →
   ``recompute_converged(["review"])`` flips ``ledger.converged`` to ``True``.
5. PR is merged via ``_handle_approved_merge``; ``/api/issues/history`` shows
   ``outcome=="merged"`` for issue #1.
6. After the merge ``PostMergeHandler.handle_approved`` calls
   ``clear_convergence_ledger`` (commit #9693), so the ``convergence_ledgers``
   entry for issue #1 is ABSENT from ``/api/state`` once the merge completes.

**Lifecycle contract and test-layer split**: the converged=True proof (gate ran,
ADVANCE recorded, ``recompute_converged`` flipped the flag) is verified at the
unit layer (``tests/test_post_merge_handler.py::test_ledger_ordering_retrospective_reads_before_clear``)
and at the MockWorld layer (``tests/scenarios/test_convergence_review_mockworld.py::TestApproveConverges``),
where a pre-clear observer captures the ledger state before the clear fires.
This sandbox e2e confirms the merge completed AND that clear-on-merge ran in
the real orchestrator.  Do NOT try to race the pre-clear window in Docker — the
window is too narrow to be reliable.

Advisor scripting note: the gated approve calls ``PostVerifyAdvisor`` with the
lens-tagged role ``"post_verify:correctness"`` (correctness lens for low blast
radius). The seed scripts this via
``advisor_scripts={1: {"post_verify:correctness": [<APPROVE payload>]}}`` (FakeLLM
keys on the exact role string) so the gate cleanly records ``ADVANCE`` rather than
relying on the degraded fail-open path.
"""

from __future__ import annotations

import json

from mockworld.seed import MockWorldSeed

# Scripted advisor verdict for the gated approve path (Phase 2a).
# The convergence gate calls PostVerifyAdvisor (role="post_verify",
# lens="correctness" for low blast radius). Scripting APPROVE here ensures
# the FakeLLM returns a clean verdict so the gate records ADVANCE and
# recompute_converged flips ledger.converged to True.
_ADVISOR_POST_VERIFY_APPROVE: str = json.dumps(
    {
        "verdict": "APPROVE",
        "reasoning": "Re-implementation satisfies the original spec.",
        "disagreements": [],
        "suggested_fix_direction": None,
    }
)

NAME = "s50_convergence_review"
DESCRIPTION = (
    "Convergence gate ON: REQUEST_CHANGES loops issue back to ready (lap 1), "
    "APPROVE converges the ledger and merges the PR."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        issues=[
            {
                "number": 1,
                "title": "Add feature X",
                "body": "Implement X.",
                "labels": ["hydraflow-ready"],
            }
        ],
        scripts={
            "plan": {1: [{"success": True}]},
            "implement": {
                1: [
                    # First pass (before review loop-back)
                    {"success": True, "branch": "hf/issue-1"},
                    # Second pass (after loop-back to ready, re-implementation)
                    {"success": True, "branch": "hf/issue-1"},
                ]
            },
            "review": {
                1: [
                    # Pass 1: REQUEST_CHANGES → gate records LOOP_BACK, lap 1
                    {
                        "verdict": "request-changes",
                        "comments": ["needs better error handling"],
                    },
                    # Pass 2: APPROVE → routed through the convergence gate
                    # (_handle_approved_review_gated) → ADVANCE → converged=True
                    # → merge. The post_verify advisor is scripted to APPROVE via
                    # advisor_scripts below so the gate cleanly records ADVANCE.
                    {"verdict": "approve"},
                ]
            },
        },
        advisor_scripts={
            # Script the post_verify advisor for issue 1 to APPROVE.
            # The gated approve path invokes PostVerifyAdvisor with the
            # lens-tagged role "post_verify:correctness" (correctness lens for
            # low blast radius). FakeLLM pops the result keyed by the EXACT role
            # string, so the key must be "post_verify:correctness" (not the base
            # "post_verify") for the script to be load-bearing rather than
            # fail-open. The gate then records ADVANCE and recompute_converged
            # flips converged=True.
            1: {"post_verify:correctness": [_ADVISOR_POST_VERIFY_APPROVE]},
        },
        # Allow enough cycles for: triage → plan → implement → review (reject) →
        # loop-back → ready → implement (again) → review (approve) → merge.
        cycles_to_run=12,
    )


async def assert_outcome(api, page) -> None:
    # --- 1. Issue ends merged ---
    def _merged(payload: object) -> bool:
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return False
        for item in items:
            if not isinstance(item, dict) or item.get("issue_number") != 1:
                continue
            outcome = item.get("outcome") or {}
            if isinstance(outcome, dict) and outcome.get("outcome") == "merged":
                return True
        return False

    history = await api.wait_until(
        "/api/issues/history?limit=500",
        _merged,
        timeout=240.0,
    )
    # Explicit end-state assertion. Reaching outcome "merged" is the e2e proof
    # that the WHOLE gated convergence path ran in the real orchestrator:
    # REQUEST_CHANGES → gate deterministic RED → LOOP_BACK (ADR-0094 reject
    # boundary, ledger lap 1) → re-implement → APPROVE → gate ADVANCE +
    # recompute_converged (ADR-0095 approve-path gating, converged live) →
    # _handle_approved_merge. If any link in that chain regressed, issue #1
    # would never reach "merged" and this assertion fails.
    hist_items = history.get("items") if isinstance(history, dict) else None
    assert isinstance(hist_items, list), f"history payload missing items: {history!r}"
    merged_issue_1 = [
        item
        for item in hist_items
        if isinstance(item, dict)
        and item.get("issue_number") == 1
        and isinstance(item.get("outcome"), dict)
        and item["outcome"].get("outcome") == "merged"
    ]
    assert merged_issue_1, (
        f"issue #1 did not reach merged via the gated convergence path: {history!r}"
    )

    # --- 2. /api/state shows convergence_ledgers ABSENT for issue #1 ---
    # After a successful merge PostMergeHandler.handle_approved calls
    # clear_convergence_ledger (commit #9693), removing the entry entirely.
    # The converged=True proof is covered at the unit layer
    # (test_ledger_ordering_retrospective_reads_before_clear) and MockWorld layer
    # (TestApproveConverges pre-clear observer).  The sandbox asserts the
    # clear-on-merge end state: no ledger entry for issue #1 in the real
    # orchestrator's state after the merge completes.
    def _ledger_absent(payload: object) -> bool:
        if not isinstance(payload, dict):
            return False
        ledgers = payload.get("convergence_ledgers")
        if not isinstance(ledgers, dict):
            # No convergence_ledgers key at all → cleared (vacuous absence OK
            # only if the merge was already confirmed above).
            return True
        # Accept if there is no entry whose issue_number == 1.
        for entry in ledgers.values():
            if isinstance(entry, dict) and entry.get("issue_number") == 1:
                return False  # Still present — clear hasn't propagated yet.
        return True

    state = await api.wait_until(
        "/api/state",
        _ledger_absent,
        timeout=30.0,
    )
    # ADR-0094 clear-on-merge contract: PostMergeHandler.handle_approved calls
    # clear_convergence_ledger after the merge, so once the merge has completed
    # (asserted above) no convergence_ledgers entry for issue #1 must remain in
    # the real orchestrator's persisted state.
    ledgers = state.get("convergence_ledgers") if isinstance(state, dict) else None
    remaining_issue_1 = [
        entry
        for entry in (ledgers.values() if isinstance(ledgers, dict) else [])
        if isinstance(entry, dict) and entry.get("issue_number") == 1
    ]
    assert not remaining_issue_1, (
        f"convergence ledger for issue #1 not cleared after merge: {state!r}"
    )
