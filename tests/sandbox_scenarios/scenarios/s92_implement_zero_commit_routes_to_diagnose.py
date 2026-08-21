"""s92 — a zero-commit implement attempt routes to diagnose on its FIRST result (#11568).

Sandbox e2e for the ``zero-commit-abort`` flow node. The real ``ImplementPhase``
boots inside docker with the scripted FakeLLM agent returning one zero-commit
result; the node routes the issue to ``hydraflow-diagnose`` with the
zero-commit cause instead of re-dispatching it for attempts 2 and 3. The
sandbox's diagnostic Stage-1 bypass (``DiagnosticRunner._mockworld_fake_llm``)
returns a not-fixable diagnosis, so the DiagnosticLoop escalates straight to
``hydraflow-hitl`` and ``github_cache`` surfaces it on ``/api/hitl`` — the same
chain s05 exercises.

The assertion discriminates the pre-#11568 shape: the scripted result is
sticky-tail, so a retrying implementer would burn three zero-commit attempts
and reach the HITL tab through the attempt cap with the cause
"Implementation attempt cap exceeded …" — which this scenario rejects. Only
the first-result routing carries the "zero commits" cause.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s92_implement_zero_commit_routes_to_diagnose"
DESCRIPTION = (
    "ImplementPhase: the first zero-commit attempt routes to hydraflow-diagnose "
    "(no attempt 2); the sandbox diagnostic bypass escalates it to the HITL tab "
    "carrying the zero-commit cause, not the attempt-cap cause."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        issues=[
            {"number": 1, "title": "t", "body": "b", "labels": ["hydraflow-ready"]}
        ],
        scripts={
            "plan": {1: [{"success": True}]},
            # One zero-commit result. FakeLLM repeats the last scripted result
            # when its queue drains, so a retrying implementer would see zero
            # commits on every attempt — the attempt-cap shape this rejects.
            "implement": {
                1: [
                    {
                        "success": False,
                        "branch": "hf/issue-1",
                        "commits": 0,
                        "error": "No commits found on branch",
                    }
                ]
            },
        },
        # Same caretaker subset as s05: the diagnostic loop carries the issue
        # from diagnose to hitl; github_cache surfaces it on /api/hitl; every
        # other caretaker stays off so StaleIssueLoop cannot close issue #1
        # (FakeGitHub issues carry an ancient default updated_at).
        loops_enabled=["diagnostic", "github_cache"],
        cycles_to_run=10,
    )


async def assert_outcome(api, page) -> None:
    """Issue #1 reaches the HITL tab carrying the zero-commit cause."""
    _ = page

    def _routed_for_zero_commits(payload: object) -> bool:
        # /api/hitl returns a list at the top level.
        items = (
            payload
            if isinstance(payload, list)
            else (payload.get("items") if isinstance(payload, dict) else None)
        )
        if not isinstance(items, list):
            return False
        for item in items:
            if isinstance(item, dict) and item.get("issue") == 1:
                return "zero commits" in str(item.get("cause", "")).lower()
        return False

    await api.wait_until("/api/hitl", _routed_for_zero_commits, timeout=240.0)
