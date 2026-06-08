"""s09b — Auto-Agent PR (agent/auto-agent-N, owner-authored) + green CI → auto-merged.

Auto-Agent preflight PRs ride the ``agent/auto-agent-<N>`` branch and are opened
by the auto-agent subprocess under the ambient owner token — so they are NOT a
configured bot author and the review->merge pipeline (keyed on hydraflow-review
+ agent/issue-N) never lands them. DependabotMergeLoop must merge them by branch
prefix, otherwise they pile up green-but-unmerged.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s09b_auto_agent_auto_merge"
DESCRIPTION = (
    "Auto-Agent PR (agent/auto-agent-N, owner author) + green CI → "
    "DependabotMergeLoop merges by branch prefix without human."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        prs=[
            {
                "number": 110,
                "issue_number": 0,
                "branch": "agent/auto-agent-9291",
                "ci_status": "pass",
                "merged": False,
                # No workflow label, and the author is the owner token (NOT a
                # configured bot) — this is exactly the PR shape that fell
                # through every merge path before the branch-prefix fix.
                "labels": [],
                "author": "T-rav",
            }
        ],
        # github_cache must run too: DependabotMergeLoop reads the label-agnostic
        # all-open-PRs snapshot warmed by the github_cache loop.
        loops_enabled=["dependabot_merge", "github_cache"],
        cycles_to_run=3,
    )


async def assert_outcome(api, page) -> None:
    # The merge is observable via the dependabot_merge worker-status event whose
    # details carry the merged count (DependabotMergeLoop._do_work -> {"merged": N}).
    await api.wait_until(
        "/api/events",
        lambda p: any(
            e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "dependabot_merge"
            and e.get("data", {}).get("details", {}).get("merged", 0) >= 1
            for e in (p if isinstance(p, list) else [])
        ),
        timeout=120.0,
    )
