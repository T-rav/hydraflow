"""s40 — ImplementPhase two-stage spec-compliance gap-feed recovery (ADR-0063 W5).

Drives the W5 recovery branch end-to-end: the first implement attempt fails
with zero commits (zero-diff branch); ``ImplementPhase._run_spec_compliance_review``
dispatches the scripted spec-compliance reviewer which returns ``compliant=False``
with explicit gaps; the gaps are persisted to ``WorkerResultMeta.spec_review_gaps``
and surface as the next attempt's ``prior_failure`` anchor; the second implement
attempt succeeds, the issue advances through review and merges — no human
escalation.

The scripted scenario uses the ``script_implement_spec_review`` FakeLLM hook
added in PR #9038. Without that hook the only achievable s40 was
happy-path-transparent (no failed attempt to recover from).
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s40_implement_two_stage_review_gap_feed"
DESCRIPTION = (
    "ImplementPhase: first attempt fails zero-diff, spec-compliance reviewer "
    "surfaces gaps, second attempt succeeds → issue reaches merged."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        repos=[("owner/repo", "/workspace/repo")],
        issues=[
            {
                "number": 4,
                "title": "Add feature W",
                "body": "Implement feature W in src/feature_w.py",
                "labels": ["hydraflow-ready"],
            },
        ],
        scripts={
            "plan": {4: [{"success": True, "task_count": 1}]},
            # ADR-0063 W5: drive ImplementPhase's failure-then-success path.
            # Attempt 1 produces zero commits (triggers _run_spec_compliance_review);
            # attempt 2 succeeds with one commit on the implementation branch.
            "implement": {
                4: [
                    {
                        "success": False,
                        "branch": "hf/issue-4",
                        "commits": 0,
                        "error": "No commits found on branch",
                    },
                    {"success": True, "branch": "hf/issue-4", "commits": 1},
                ],
            },
            "review": {4: [{"verdict": "approve", "comments": []}]},
        },
        # ADR-0063 W5: the spec-compliance reviewer runs once after the
        # failed attempt 1. It returns non-compliant with two gaps that
        # ImplementPhase persists into WorkerResultMeta.spec_review_gaps;
        # those gaps then prepend the next attempt's prior_failure prompt
        # anchor (verified by tests/test_implement_phase_spec_reviewer.py;
        # this sandbox scenario asserts only the end-to-end recovery
        # signal because Tier-3's contract is one tick, one signal).
        phase_scripts={
            "implement_spec_review": {
                4: [
                    {
                        "compliant": False,
                        "gaps": [
                            "src/feature_w.py is missing — branch produced no diff",
                            "no acceptance test covers feature W",
                        ],
                        "reasoning": (
                            "The implementation branch carries zero commits "
                            "against the base; the spec required the new module."
                        ),
                    },
                ],
            },
        },
        cycles_to_run=10,
    )


async def assert_outcome(api, page) -> None:
    """Verify the issue reaches merged after the two-stage gap-feed recovery.

    Only a successful spec-compliance recovery + a passing second attempt +
    subsequent phases can produce a merged outcome here. Without W5 the
    failed first attempt would either re-dispatch with an uninformative
    ``"No commits found on branch"`` prior_failure (potentially looping
    until the attempt cap) or escalate.
    """
    _ = page

    def _has_merged(payload: dict) -> bool:
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return False
        for item in items:
            if not isinstance(item, dict) or item.get("issue_number") != 4:
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
