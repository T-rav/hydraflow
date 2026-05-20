"""s37 — PlanPhase recovery via touchpoint-expander on first PlanReviewer reject (ADR-0063 W3b).

Drives the W3b recovery branch end-to-end: the first PlanReviewer pass returns
blocking HIGH findings (scripted gaps); ``PlanPhase._maybe_expand_touchpoints``
dispatches the touchpoint-expander, enriches the plan with the expander's
context block, and re-runs PlanReviewer; the second pass approves with no
findings, the cache records the accepting review, and the READY-stage gate
advances the issue toward implement+review+merged — no human escalation.

The scripted scenario uses the ``script_plan_review`` FakeLLM hook added in
PR #9038. Without that hook the only achievable s37 was happy-path-transparent
(no rejection to recover from).
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s37_plan_touchpoint_expander_recovery"
DESCRIPTION = (
    "PlanReviewer: first pass rejects (+gaps), touchpoint-expander dispatched, "
    "second pass accepts → issue reaches merged without HITL."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        repos=[("owner/repo", "/workspace/repo")],
        issues=[
            {
                "number": 2,
                "title": "Add feature Y",
                "body": "Implement feature Y in src/feature_y.py",
                "labels": ["hydraflow-ready"],
            },
        ],
        scripts={
            "plan": {2: [{"success": True, "task_count": 1}]},
            "implement": {2: [{"success": True, "branch": "hf/issue-2"}]},
            "review": {2: [{"verdict": "approve", "comments": []}]},
        },
        # ADR-0063 W3b: drive PlanReviewer's two-call sequence inside
        # _maybe_expand_touchpoints. Call 1 (first review) rejects with
        # scripted gaps so the touchpoint-expander fires; call 2 (re-review
        # against enriched plan) accepts and the cache records the clean
        # second review.
        phase_scripts={
            "plan_review": {
                2: [
                    {
                        "verdict": "reject",
                        "gaps": [
                            "missing test_strategy for affected module",
                            "no reproduction steps for the bug path",
                        ],
                    },
                    {"verdict": "accept"},
                ],
            },
        },
        cycles_to_run=8,
    )


async def assert_outcome(api, page) -> None:
    """Verify the issue reaches merged AND no HITL escalation was filed.

    Only a successful touchpoint-expander recovery + subsequent phases can
    produce a merged outcome here: without W3b, the route-back-with-gaps
    path would loop until cap, then escalate.
    """
    _ = page

    def _has_merged(payload: dict) -> bool:
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return False
        for item in items:
            if not isinstance(item, dict) or item.get("issue_number") != 2:
                continue
            outcome = item.get("outcome") or {}
            if isinstance(outcome, dict) and outcome.get("outcome") == "merged":
                return True
        return False

    await api.wait_until(
        "/api/issues/history?limit=500",
        _has_merged,
        timeout=90.0,
    )
