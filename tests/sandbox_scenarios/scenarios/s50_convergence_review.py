"""s50 — convergence gate: REQUEST_CHANGES loops back, APPROVE converges and merges.

Exercises the end-to-end convergence gate path (``convergence_gate_enabled=True``,
enabled via ``HYDRAFLOW_CONVERGENCE_GATE_ENABLED=true`` in the hydraflow service
environment — see docker-compose.sandbox.yml):

1. Gate ON — the convergence ``HybridGate`` is wired into BOTH the REJECT path
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
6. ``/api/state`` shows the ``convergence_ledgers`` entry with ``laps >= 1``,
   ``stage_state["review"]["last_verdict"] == "ADVANCE"``, and
   ``converged == True`` — confirming the full Phase 2a gate path completed.

Advisor scripting note: the gated approve calls ``PostVerifyAdvisor`` (role
``"post_verify"``, lens ``"correctness"`` for low blast radius). The seed scripts
this via ``advisor_scripts={1: {"post_verify": [<APPROVE payload>]}}`` so the
``FakeLLM`` returns APPROVE and the gate cleanly records ``ADVANCE`` rather than
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
            # The gated approve path invokes PostVerifyAdvisor with role
            # "post_verify" (lens "correctness" for low blast radius). FakeLLM
            # pops this result via pop_advisor_result(1, "post_verify") so the
            # gate records ADVANCE and recompute_converged flips converged=True.
            1: {"post_verify": [_ADVISOR_POST_VERIFY_APPROVE]},
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

    await api.wait_until(
        "/api/issues/history?limit=500",
        _merged,
        timeout=240.0,
    )

    # --- 2. /api/state shows convergence_ledgers with full Phase 2a gate path ---
    # Phase 2a gates BOTH the REJECT and APPROVE paths. On REQUEST_CHANGES the gate
    # records LOOP_BACK and closes lap 1 via mark_lap(). On APPROVE the gate runs
    # the post_verify lens judge → records ADVANCE → recompute_converged flips
    # ledger.converged to True. Assert all three: laps >= 1, last_verdict == "ADVANCE",
    # and converged is True.
    def _ledger_converged(payload: object) -> bool:
        if not isinstance(payload, dict):
            return False
        ledgers = payload.get("convergence_ledgers")
        if not isinstance(ledgers, dict):
            return False
        # The ledger key is the repo-qualified issue key produced by
        # StateTracker._key(); in the single-repo sandbox it resolves to "1"
        # or a namespaced variant. Accept any entry whose issue_number == 1.
        for entry in ledgers.values():
            if not isinstance(entry, dict):
                continue
            if entry.get("issue_number") != 1:
                continue
            # The reject closed lap 1 — laps >= 1.
            if entry.get("laps", 0) < 1:
                continue
            # The gate recorded ADVANCE on the approve pass.
            review_stage = entry.get("stage_state", {}).get("review", {})
            if review_stage.get("last_verdict") != "ADVANCE":
                continue
            # recompute_converged flipped converged to True after ADVANCE.
            if entry.get("converged") is not True:
                continue
            return True
        return False

    await api.wait_until(
        "/api/state",
        _ledger_converged,
        timeout=30.0,
    )
