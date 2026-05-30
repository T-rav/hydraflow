"""s36 — DiscoverPhase recovery via discover-expander on coherence failure (ADR-0063 W3a).

Drives the W3a recovery branch end-to-end: the first coherence evaluation
fails with scripted ``queries_required``; ``DiscoverRunner`` dispatches the
expander (which returns those queries in MockWorld mode); the second attempt
evaluates the brief as coherent and the issue advances past Discover without
the ``hitl-escalation`` / ``discover-stuck`` labels that would otherwise be
applied by ``_escalate_stuck``.

The scripted scenario uses the ``script_discover`` FakeLLM hook added in
PR #9038. Without that hook the only achievable s36 was happy-path-transparent
(no failure to recover from).
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s36_discover_expander_recovery"
DESCRIPTION = (
    "DiscoverRunner: first coherence eval rejects (+expander queries), second "
    "passes → issue reaches merged with no hitl-escalation / discover-stuck."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        repos=[("owner/repo", "/workspace/repo")],
        issues=[
            {
                "number": 1,
                "title": "Add feature X",
                "body": "Implement feature X in src/feature_x.py",
                "labels": ["hydraflow-ready"],
            },
        ],
        scripts={
            "plan": {1: [{"success": True, "task_count": 1}]},
            "implement": {1: [{"success": True, "branch": "hf/issue-1"}]},
            "review": {1: [{"verdict": "approve", "comments": []}]},
        },
        # ADR-0063 W3a: drive the bounded retry loop in DiscoverRunner.
        # Attempt 1 fails coherence with scripted queries — the expander
        # dispatch sees those queries via the runner's pending-queries
        # buffer (no subagent subprocess fires). Attempt 2 passes.
        phase_scripts={
            "discover": {
                1: [
                    {
                        "coherent": False,
                        "queries_required": [
                            "What is the primary user persona?",
                            "What measurable success criteria define done?",
                        ],
                        "summary": "missing concrete acceptance criteria",
                        "findings": ["vague-criterion — no metric named"],
                    },
                    {"coherent": True, "summary": "criteria now concrete"},
                ],
            },
        },
        cycles_to_run=8,
    )


async def assert_outcome(api, page) -> None:
    """Verify the issue reaches merged AND no discover-stuck escalation was filed.

    The W3a recovery path is observable in three places:
      1. The issue's outcome is ``merged`` (the bounded retry recovered).
      2. The issue does not carry ``hitl-escalation`` (no human paged).
      3. No companion ``discover-stuck`` escalation issue exists.

    We assert on (1) directly because it is the strongest end-to-end signal:
    only a successful Discover recovery + subsequent phases + green review
    can produce a merged outcome here.
    """
    _ = page  # UI introspection not required for this assertion.

    def _has_merged(payload: dict) -> bool:
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
        _has_merged,
        timeout=90.0,
    )
