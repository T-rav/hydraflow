"""s40 — ImplementPhase two-stage spec-compliance gap-feed recovery (ADR-0063 W5).

Drives the W5 recovery branch end-to-end: the first implement attempt fails
with commits but a red gate (a committed-but-failed build);
``ImplementPhase._run_spec_compliance_review`` dispatches the scripted
spec-compliance reviewer which returns ``compliant=False`` with explicit gaps;
the gaps are persisted to ``WorkerResultMeta.spec_review_gaps`` and surface as
the next attempt's ``prior_failure`` anchor; the second implement attempt
succeeds, the issue advances through review and merges — no human escalation.

Since #11568 a ZERO-commit first attempt no longer takes this path: it routes
to diagnose on the first result (``zero-commit-abort``), so the W5 gap-feed is
driven here with a committed failure — the retry shape W5 still owns.

The scripted scenario uses the ``script_implement_spec_review`` FakeLLM hook
added in PR #9038. Without that hook the only achievable s40 was
happy-path-transparent (no failed attempt to recover from).
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s40_implement_two_stage_review_gap_feed"
DESCRIPTION = (
    "ImplementPhase: first attempt commits but fails its gate, spec-compliance "
    "reviewer surfaces gaps, second attempt succeeds → issue reaches merged."
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
            # Attempt 1 commits but fails its quality gate (triggers
            # _run_spec_compliance_review on the committed-failure route —
            # a zero-commit attempt would route to diagnose instead, #11568);
            # attempt 2 succeeds with one commit on the implementation branch.
            "implement": {
                4: [
                    {
                        "success": False,
                        "branch": "hf/issue-4",
                        "commits": 1,
                        "error": "make quality failed: tests/test_feature_w.py",
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
                            "src/feature_w.py does not implement the W entry point",
                            "no acceptance test covers feature W",
                        ],
                        "reasoning": (
                            "The implementation branch commits a stub that fails "
                            "its own tests; the spec required the working module."
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
    failed first attempt would either re-dispatch with only the raw gate
    error as prior_failure (potentially looping until the attempt cap) or
    escalate.
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
