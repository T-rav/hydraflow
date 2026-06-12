"""Regression test for the #9422-#9428 stuck-bot-PR pile.

Bug: UL edge/evidence/proposer PRs (authored by ``hydraflow-ul-bot``) commit
``docs/arch/generated/`` artifacts. When ``staging`` advances, every OTHER open
bot PR's committed generated artifacts go stale — even files the PR never
touched — and the ``arch-check`` job (+ ``test_curated_generated_is_in_sync_
with_source``) fails with "docs/arch/generated/ is stale relative to source".

``DependabotMergeLoop`` saw CI failed → applied ``failure_strategy`` (default
``skip``) → left the PR open forever. ``MergeStateWatcherLoop`` only auto-rebases
DIRTY (conflict) PRs, and a GitHub-API rebase does not run ``arch-regen``, so
nothing could heal the staleness. Result: bot PRs piled up after any busy day.
Confirmed live on #9422-#9428 (all six failed identically on the curated-drift
test).

Fix: before applying ``failure_strategy``, ``DependabotMergeLoop`` detects an
arch-staleness CI failure and self-heals it — merges ``origin/<base>`` into the
PR head in an ephemeral worktree, re-runs ``arch-regen``, commits, and pushes,
re-triggering CI. Bounded by ``dependabot_arch_autoheal_max_attempts`` (default
2; 0 = kill switch) so a real (non-arch) failure eventually falls through to
``failure_strategy``.

These tests pin the CORRECT post-fix behavior: an arch-stale bot PR gets
regen-rebased (refresh attempted) instead of skipped, and a real failure does
NOT trigger the refresh.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from dependabot_merge_loop import _is_arch_staleness_failure
from models import DependabotMergeSettings, PRListItem
from tests.helpers import make_bg_loop_deps


def _bot_pr(pr: int, branch: str) -> PRListItem:
    return PRListItem(
        pr=pr,
        author="hydraflow-ul-bot",
        title="UL: add edge candidate",
        branch=branch,
        url=f"https://github.com/o/r/pull/{pr}",
    )


def _make_loop(
    tmp_path: Path,
    *,
    open_prs: list[PRListItem],
    ci_summary: str,
    failure_strategy: str = "skip",
    refresh_result: bool = True,
    prior_attempts: dict[int, int] | None = None,
):
    from dependabot_merge_loop import DependabotMergeLoop

    deps = make_bg_loop_deps(tmp_path, dependabot_merge_interval=60)

    cache = MagicMock()
    cache.get_open_prs.return_value = open_prs
    cache.get_all_open_prs.return_value = open_prs

    prs = MagicMock()
    prs.wait_for_ci = AsyncMock(return_value=(False, ci_summary))
    prs.submit_review = AsyncMock(return_value=True)
    prs.merge_pr = AsyncMock(return_value=True)
    prs.add_labels = AsyncMock()
    prs.post_comment = AsyncMock()
    prs.close_issue = AsyncMock()
    prs.refresh_pr_branch_with_arch_regen = AsyncMock(return_value=refresh_result)

    counter: dict[int, int] = dict(prior_attempts or {})
    state = MagicMock()
    state.get_dependabot_merge_settings.return_value = DependabotMergeSettings(
        authors=["hydraflow-ul-bot"], failure_strategy=failure_strategy
    )
    state.get_dependabot_merge_processed.return_value = set()
    state.get_dependabot_arch_refresh_attempts.side_effect = lambda n: counter.get(n, 0)

    def _bump(n: int) -> int:
        counter[n] = counter.get(n, 0) + 1
        return counter[n]

    state.bump_dependabot_arch_refresh_attempts.side_effect = _bump

    loop = DependabotMergeLoop(
        config=deps.config, cache=cache, prs=prs, state=state, deps=deps.loop_deps
    )
    return loop, prs, state


def test_curated_drift_summary_is_classified_as_arch_staleness() -> None:
    # The exact CI check names emitted on the #9422-#9428 failures.
    assert _is_arch_staleness_failure("Failed checks: arch-check")
    assert _is_arch_staleness_failure("Failed checks: Architecture Check")
    assert _is_arch_staleness_failure(
        "test_curated_generated_is_in_sync_with_source failed"
    )
    # A genuine non-arch failure is NOT misclassified.
    assert not _is_arch_staleness_failure("Failed checks: lint, test")


@pytest.mark.asyncio
async def test_arch_stale_bot_pr_is_regen_rebased_not_skipped(tmp_path: Path) -> None:
    loop, prs, state = _make_loop(
        tmp_path,
        open_prs=[_bot_pr(9422, "ul-edge-9422")],
        ci_summary="Failed checks: arch-check",
        failure_strategy="skip",
    )

    result = await loop._do_work()

    # The PR is refreshed (merge base + arch-regen + push), NOT silently left
    # open by the skip strategy.
    prs.refresh_pr_branch_with_arch_regen.assert_awaited_once_with(9422, "ul-edge-9422")
    state.bump_dependabot_arch_refresh_attempts.assert_called_once_with(9422)
    assert result["skipped"] == 1  # held open for the next tick to re-evaluate


@pytest.mark.asyncio
async def test_real_failure_is_not_arch_refreshed(tmp_path: Path) -> None:
    loop, prs, _ = _make_loop(
        tmp_path,
        open_prs=[_bot_pr(9428, "ul-edge-9428")],
        ci_summary="Failed checks: lint, test",
        failure_strategy="skip",
    )

    await loop._do_work()

    prs.refresh_pr_branch_with_arch_regen.assert_not_awaited()
