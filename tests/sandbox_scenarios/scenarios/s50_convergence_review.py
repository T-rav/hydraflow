"""s50 — convergence gate: REQUEST_CHANGES loops back, APPROVE merges; ledger converged.

Exercises the end-to-end convergence gate path (``convergence_gate_enabled=True``,
enabled via ``HYDRAFLOW_CONVERGENCE_GATE_ENABLED=true`` in the hydraflow service
environment — see docker-compose.sandbox.yml):

1. Gate ON — the convergence ``HybridGate`` routes the review reject/advance decision.
2. First review returns REQUEST_CHANGES → gate records LOOP_BACK, ledger lap 1 closed,
   issue transitions back to hydraflow-ready.
3. Second review returns APPROVE → gate's deterministic check is GREEN, gate records
   ADVANCE, ``recompute_converged`` sets ``converged=True`` on the ledger.
4. PR is merged; ``/api/issues/history`` shows ``outcome=="merged"`` for issue #1.
5. ``/api/state`` shows the ``convergence_ledgers`` entry with ``laps >= 1`` and
   ``converged: true`` after the approve pass.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

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
                    # Pass 2: APPROVE → gate records ADVANCE, converged=True, merge
                    {"verdict": "approve"},
                ]
            },
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

    # --- 2. /api/state shows convergence_ledgers with laps >= 1 and converged=True ---
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
            if entry.get("converged") is True and entry.get("laps", 0) >= 1:
                return True
        return False

    await api.wait_until(
        "/api/state",
        _ledger_converged,
        timeout=30.0,
    )
