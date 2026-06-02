"""s09 — dependabot PR with green CI → auto-merged."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s09_dependabot_auto_merge"
DESCRIPTION = "Dependabot PR + green CI → DependabotMergeLoop merges without human."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        prs=[
            {
                "number": 100,
                "issue_number": 0,
                "branch": "dependabot/npm/foo-1.2.3",
                "ci_status": "pass",
                "merged": False,
                "labels": ["dependencies"],
                # DependabotMergeLoop only merges PRs authored by a configured
                # bot (default authors include "dependabot[bot]"). Without this
                # the loop skips the PR (not a bot author).
                "author": "dependabot[bot]",
            }
        ],
        # github_cache must run too: DependabotMergeLoop reads open PRs from the
        # GitHubDataCache (cache.get_all_open_prs()), warmed only by the
        # github_cache loop. The bot PR carries only the GitHub-native
        # "dependencies" label, so it is absent from the workflow-label-filtered
        # snapshot — get_all_open_prs (label-agnostic) is what surfaces it.
        loops_enabled=["dependabot_merge", "github_cache"],
        cycles_to_run=3,
    )


async def assert_outcome(api, page) -> None:
    # /api/prs lists only OPEN PRs, and the workflow-label-filtered cache never
    # carried this "dependencies"-labeled PR anyway, so a merged dependabot PR
    # cannot be observed there. Verify the merge via the dependabot_merge
    # worker-status event, whose details carry the merged count
    # (DependabotMergeLoop._do_work → {"merged": N}).
    # dependabot_merge reads the github_cache all-open-PRs snapshot, so it can
    # only merge once that cache is warm. On the first orchestrator tick the
    # two caretakers race and dependabot often polls just before github_cache's
    # first poll (seeing an empty cache → merged=0). Sandbox caretakers poll on
    # a 60s cadence, so the timeout must span at least one more dependabot poll
    # after the cache is warm.
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
