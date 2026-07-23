"""Tests for the DependabotMergeLoop background worker."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from dependabot_merge_loop import DependabotMergeLoop
from events import EventType
from models import DependabotMergeSettings, PRListItem
from tests.helpers import make_bg_loop_deps


def _make_pr(
    pr: int,
    author: str = "dependabot[bot]",
    title: str = "Bump foo",
    branch: str = "",
    is_bot: bool = False,
) -> PRListItem:
    """Build a minimal PRListItem for testing."""
    return PRListItem(
        pr=pr,
        author=author,
        title=title,
        branch=branch,
        is_bot=is_bot,
        url=f"https://github.com/o/r/pull/{pr}",
    )


def _make_state(
    *,
    authors: list[str] | None = None,
    failure_strategy: str = "skip",
    processed: set[int] | None = None,
    arch_refresh_attempts: dict[int, int] | None = None,
) -> MagicMock:
    """Build a mock StateTracker with bot PR methods.

    The arch-staleness self-heal counter is backed by a real dict so that
    ``get`` reflects ``bump`` within a single ``_do_work`` call (the loop reads
    the counter back after bumping for its log line).
    """
    state = MagicMock()
    settings = DependabotMergeSettings(
        authors=authors or ["dependabot[bot]"],
        failure_strategy=failure_strategy,
    )
    state.get_dependabot_merge_settings.return_value = settings
    state.get_dependabot_merge_processed.return_value = processed or set()

    counter: dict[int, int] = dict(arch_refresh_attempts or {})

    def _get_attempts(pr_number: int) -> int:
        return counter.get(pr_number, 0)

    def _bump_attempts(pr_number: int) -> int:
        counter[pr_number] = counter.get(pr_number, 0) + 1
        return counter[pr_number]

    ub_counter: dict[int, int] = {}

    def _get_ub(pr_number: int) -> int:
        return ub_counter.get(pr_number, 0)

    def _bump_ub(pr_number: int) -> int:
        ub_counter[pr_number] = ub_counter.get(pr_number, 0) + 1
        return ub_counter[pr_number]

    state.get_dependabot_update_branch_attempts.side_effect = _get_ub
    state.bump_dependabot_update_branch_attempts.side_effect = _bump_ub

    state.get_dependabot_arch_refresh_attempts.side_effect = _get_attempts
    state.bump_dependabot_arch_refresh_attempts.side_effect = _bump_attempts
    state._arch_refresh_counter = counter  # exposed for assertions
    return state


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    interval: int = 60,
    open_prs: list[PRListItem] | None = None,
    ci_result: tuple[bool, str] = (True, "All checks passed"),
    merge_result: bool = True,
    failure_strategy: str = "skip",
    processed: set[int] | None = None,
    authors: list[str] | None = None,
    arch_refresh_attempts: dict[int, int] | None = None,
    arch_refresh_result: bool = True,
    arch_autoheal_max_attempts: int | None = None,
    update_branch_max_attempts: int | None = None,
    update_branch_result: bool = True,
    mergeable: bool | None = None,
) -> tuple[DependabotMergeLoop, asyncio.Event, MagicMock, MagicMock, MagicMock]:
    """Build a DependabotMergeLoop with test-friendly defaults.

    Returns (loop, stop_event, cache_mock, prs_mock, state_mock).

    ``mergeable`` feeds ``get_pr_mergeable`` (the #9889 item-2 conflict
    corroboration read). The harness default ``None`` (= unknown) keeps the
    legacy merge-failure path in every pre-existing test; conflict-heal tests
    opt in with ``mergeable=False``.
    """
    deps = make_bg_loop_deps(
        tmp_path, enabled=enabled, dependabot_merge_interval=interval
    )
    # Isolate the conflict-comment DedupStore under tmp_path (the factory
    # config's data_root defaults to CWD, which would leak between tests).
    object.__setattr__(deps.config, "data_root", tmp_path / "data")
    if arch_autoheal_max_attempts is not None:
        object.__setattr__(
            deps.config,
            "dependabot_arch_autoheal_max_attempts",
            arch_autoheal_max_attempts,
        )
    # #9889 heal class 2 defaults OFF in this harness so failure-strategy
    # tests keep exercising the strategy path; tests opt in explicitly.
    object.__setattr__(
        deps.config,
        "dependabot_update_branch_max_attempts",
        update_branch_max_attempts if update_branch_max_attempts is not None else 0,
    )

    cache = MagicMock()
    # DependabotMergeLoop reads the label-agnostic snapshot (get_all_open_prs);
    # get_open_prs is kept in sync for any incidental reads.
    cache.get_open_prs.return_value = open_prs or []
    cache.get_all_open_prs.return_value = open_prs or []

    prs = MagicMock()
    prs.wait_for_ci = AsyncMock(return_value=ci_result)
    prs.submit_review = AsyncMock(return_value=True)
    prs.merge_pr = AsyncMock(return_value=merge_result)
    prs.update_pr_branch = AsyncMock(return_value=update_branch_result)
    prs.add_labels = AsyncMock()
    prs.post_comment = AsyncMock()
    prs.close_issue = AsyncMock()
    prs.close_pr = AsyncMock(return_value=True)
    prs.get_pr_mergeable = AsyncMock(return_value=mergeable)
    prs.refresh_pr_branch_with_arch_regen = AsyncMock(return_value=arch_refresh_result)

    state = _make_state(
        authors=authors,
        failure_strategy=failure_strategy,
        processed=processed,
        arch_refresh_attempts=arch_refresh_attempts,
    )

    loop = DependabotMergeLoop(
        config=deps.config,
        cache=cache,
        prs=prs,
        state=state,
        deps=deps.loop_deps,
    )
    return loop, deps.stop_event, cache, prs, state


class TestDependabotMergeLoopInterval:
    def test_default_interval_uses_config(self, tmp_path: Path) -> None:
        """_get_default_interval returns config.dependabot_merge_interval."""
        loop, *_ = _make_loop(tmp_path, interval=120)
        assert loop._get_default_interval() == 120


class TestDependabotMergeLoopDoWork:
    @pytest.mark.asyncio
    async def test_no_bot_prs_returns_zeros(self, tmp_path: Path) -> None:
        """When no open PRs match bot authors, all counters are zero."""
        loop, *_ = _make_loop(tmp_path, open_prs=[])
        result = await loop._do_work()
        assert result == {"merged": 0, "skipped": 0, "failed": 0}

    @pytest.mark.asyncio
    async def test_non_bot_author_ignored(self, tmp_path: Path) -> None:
        """PRs from non-bot authors are not processed."""
        loop, _, _, prs, _ = _make_loop(
            tmp_path,
            open_prs=[_make_pr(1, author="human-dev")],
        )
        result = await loop._do_work()
        assert result == {"merged": 0, "skipped": 0, "failed": 0}
        prs.wait_for_ci.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_already_processed_skipped(self, tmp_path: Path) -> None:
        """PRs already in the processed set are not re-checked."""
        loop, _, _, prs, _ = _make_loop(
            tmp_path,
            open_prs=[_make_pr(42)],
            processed={42},
        )
        result = await loop._do_work()
        assert result == {"merged": 0, "skipped": 0, "failed": 0}
        prs.wait_for_ci.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ci_green_approves_and_merges(self, tmp_path: Path) -> None:
        """When CI passes, the PR is approved and merged."""
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[_make_pr(10)],
            ci_result=(True, "All checks passed"),
        )

        result = await loop._do_work()

        assert result["merged"] == 1
        prs.submit_review.assert_awaited_once()
        prs.merge_pr.assert_awaited_once_with(10, auto_rebase=True)
        state.add_dependabot_merge_processed.assert_called_once_with(10)

    @pytest.mark.asyncio
    async def test_ci_green_merge_fails(self, tmp_path: Path) -> None:
        """When CI passes but merge fails, it counts as failed."""
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[_make_pr(10)],
            ci_result=(True, "All checks passed"),
            merge_result=False,
        )

        result = await loop._do_work()

        assert result["failed"] == 1
        assert result["merged"] == 0
        state.add_dependabot_merge_processed.assert_not_called()

    @pytest.mark.asyncio
    async def test_ci_pending_skips(self, tmp_path: Path) -> None:
        """When CI times out (still pending), the PR is skipped for retry."""
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[_make_pr(10)],
            ci_result=(False, "CI timed out after 60s"),
        )

        result = await loop._do_work()

        assert result["skipped"] == 1
        assert result["merged"] == 0
        prs.merge_pr.assert_not_awaited()
        state.add_dependabot_merge_processed.assert_not_called()

    @pytest.mark.asyncio
    async def test_ci_failed_strategy_skip(self, tmp_path: Path) -> None:
        """failure_strategy=skip leaves the PR open without tracking."""
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[_make_pr(10)],
            ci_result=(False, "2/5 checks failed: lint, test"),
            failure_strategy="skip",
        )

        result = await loop._do_work()

        assert result["skipped"] == 1
        prs.merge_pr.assert_not_awaited()
        state.add_dependabot_merge_processed.assert_not_called()

    @pytest.mark.asyncio
    async def test_ci_failed_strategy_hitl(self, tmp_path: Path) -> None:
        """failure_strategy=hitl adds labels and comments, then tracks."""
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[_make_pr(10)],
            ci_result=(False, "2/5 checks failed: lint, test"),
            failure_strategy="hitl",
        )

        result = await loop._do_work()

        assert result["failed"] == 1
        prs.add_labels.assert_awaited_once()
        prs.post_comment.assert_awaited_once()
        state.add_dependabot_merge_processed.assert_called_once_with(10)

    @pytest.mark.asyncio
    async def test_ci_failed_strategy_close(self, tmp_path: Path) -> None:
        """failure_strategy=close comments and closes the PR, then tracks."""
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[_make_pr(10)],
            ci_result=(False, "2/5 checks failed: lint, test"),
            failure_strategy="close",
        )

        result = await loop._do_work()

        assert result["failed"] == 1
        prs.post_comment.assert_awaited_once()
        prs.close_issue.assert_awaited_once_with(10)
        state.add_dependabot_merge_processed.assert_called_once_with(10)

    @pytest.mark.asyncio
    async def test_multiple_bot_prs_processed(self, tmp_path: Path) -> None:
        """Multiple bot PRs are each processed independently."""
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[_make_pr(1), _make_pr(2), _make_pr(3)],
            ci_result=(True, "All checks passed"),
        )

        result = await loop._do_work()

        assert result["merged"] == 3
        assert prs.merge_pr.await_count == 3

    @pytest.mark.asyncio
    async def test_author_matching_case_insensitive(self, tmp_path: Path) -> None:
        """Bot author matching is case-insensitive."""
        loop, _, _, prs, _ = _make_loop(
            tmp_path,
            open_prs=[_make_pr(1, author="Dependabot[bot]")],
            authors=["dependabot[bot]"],
            ci_result=(True, "All checks passed"),
        )

        result = await loop._do_work()

        assert result["merged"] == 1

    @pytest.mark.asyncio
    async def test_custom_bot_authors(self, tmp_path: Path) -> None:
        """Custom bot authors from settings are respected."""
        loop, _, _, prs, _ = _make_loop(
            tmp_path,
            open_prs=[
                _make_pr(1, author="renovate[bot]"),
                _make_pr(2, author="dependabot[bot]"),
            ],
            authors=["renovate[bot]"],
            ci_result=(True, "All checks passed"),
        )

        result = await loop._do_work()

        # Only renovate PR should match
        assert result["merged"] == 1
        prs.merge_pr.assert_awaited_once_with(1, auto_rebase=True)


class TestDependabotMergeLoopRun:
    @pytest.mark.asyncio
    async def test_run_publishes_worker_status_event(self, tmp_path: Path) -> None:
        """The loop publishes a BACKGROUND_WORKER_STATUS event on success."""
        loop, *_ = _make_loop(tmp_path)

        await loop.run()

        events = [
            e
            for e in loop._bus.get_history()
            if e.type == EventType.BACKGROUND_WORKER_STATUS
        ]
        assert len(events) >= 1
        data = events[0].data
        assert data["worker"] == "dependabot_merge"
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_run_skips_when_disabled(self, tmp_path: Path) -> None:
        """The loop skips work when the enabled callback returns False."""
        loop, *_ = _make_loop(tmp_path, enabled=False)

        await loop.run()

        loop._status_cb.assert_not_called()


class TestDependabotMergeLoopAutoAgentBranch:
    """Auto-Agent preflight PRs ride the factory-owned ``agent/auto-agent-N``
    branch and are authored by the ambient owner token (not a bot author), so
    the review->merge pipeline (keyed on hydraflow-review + agent/issue-N) never
    lands them. The loop merges them by branch prefix so they don't pile up.
    """

    @pytest.mark.asyncio
    async def test_merges_auto_agent_pr_despite_non_bot_author(
        self, tmp_path: Path
    ) -> None:
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[_make_pr(42, author="T-rav", branch="agent/auto-agent-42")],
            ci_result=(True, "All checks passed"),
        )

        result = await loop._do_work()

        assert result["merged"] == 1
        prs.merge_pr.assert_awaited_once_with(42, auto_rebase=True)
        state.add_dependabot_merge_processed.assert_called_once_with(42)

    @pytest.mark.asyncio
    async def test_does_not_merge_normal_pipeline_branch(self, tmp_path: Path) -> None:
        """agent/issue-N PRs belong to the review->merge pipeline, not this loop."""
        loop, _, _, prs, _ = _make_loop(
            tmp_path,
            open_prs=[_make_pr(42, author="T-rav", branch="agent/issue-42")],
        )

        result = await loop._do_work()

        assert result == {"merged": 0, "skipped": 0, "failed": 0}
        prs.wait_for_ci.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_does_not_merge_arbitrary_owner_branch(self, tmp_path: Path) -> None:
        """A hand-authored PR on a NON-shepherd-prefix branch must not auto-merge.

        (#9889 class 5 made human fix/-style prefixes shepherdable by design,
        so the arbitrary-branch pin uses a prefix outside that set.)
        """
        loop, _, _, prs, _ = _make_loop(
            tmp_path,
            open_prs=[_make_pr(42, author="T-rav", branch="spike-manual-thing")],
        )

        result = await loop._do_work()

        assert result == {"merged": 0, "skipped": 0, "failed": 0}
        prs.wait_for_ci.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_auto_agent_pr_failing_ci_respects_failure_strategy(
        self, tmp_path: Path
    ) -> None:
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[_make_pr(42, author="T-rav", branch="agent/auto-agent-42")],
            ci_result=(False, "2/5 checks failed: lint, test"),
            failure_strategy="skip",
        )

        result = await loop._do_work()

        assert result["skipped"] == 1
        prs.merge_pr.assert_not_awaited()
        state.add_dependabot_merge_processed.assert_not_called()


class TestIsArchStalenessFailure:
    """The pure detector that classifies a CI-failure summary as stale-arch."""

    @pytest.mark.parametrize(
        "summary",
        [
            "Failed checks: arch-check",
            "Failed checks: Architecture Check",
            "Failed checks: lint, Architecture Check, test",
            "test_curated_generated_is_in_sync_with_source failed",
            "docs/arch/generated/ is stale relative to source. Run `make arch-regen`",
        ],
    )
    def test_arch_summaries_detected(self, summary: str) -> None:
        from dependabot_merge_loop import _is_arch_staleness_failure

        assert _is_arch_staleness_failure(summary) is True

    @pytest.mark.parametrize(
        "summary",
        [
            "",
            "Failed checks: lint, test",
            "Failed checks: Type Check",
            "Failed checks: Browser Scenarios",
            "CI timed out after 60s",
        ],
    )
    def test_non_arch_summaries_rejected(self, summary: str) -> None:
        from dependabot_merge_loop import _is_arch_staleness_failure

        assert _is_arch_staleness_failure(summary) is False


class TestDependabotArchSelfHeal:
    """The stale-arch self-heal path: merge base + arch-regen + push, bounded
    by ``dependabot_arch_autoheal_max_attempts``, before failure_strategy."""

    @pytest.mark.asyncio
    async def test_arch_stale_failure_triggers_refresh_not_strategy(
        self, tmp_path: Path
    ) -> None:
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[_make_pr(9422, author="hydraflow-ul-bot", branch="ul-edge-1")],
            ci_result=(False, "Failed checks: arch-check"),
            failure_strategy="hitl",
            authors=["hydraflow-ul-bot"],
        )

        result = await loop._do_work()

        # Refresh was attempted on the PR's branch; counter bumped; PR left
        # open (skipped) for the next tick to re-evaluate.
        prs.refresh_pr_branch_with_arch_regen.assert_awaited_once_with(
            9422, "ul-edge-1"
        )
        state.bump_dependabot_arch_refresh_attempts.assert_called_once_with(9422)
        assert result["skipped"] == 1
        assert result["failed"] == 0
        # No failure_strategy side effects (hitl would label + comment + track).
        prs.add_labels.assert_not_awaited()
        prs.post_comment.assert_not_awaited()
        state.add_dependabot_merge_processed.assert_not_called()

    @pytest.mark.asyncio
    async def test_refresh_no_op_falls_through_to_strategy(
        self, tmp_path: Path
    ) -> None:
        # Refresh returns False (e.g. a real non-generated conflict) — the loop
        # must apply the failure strategy, NOT bump the counter.
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[_make_pr(9423, author="hydraflow-ul-bot", branch="ul-edge-2")],
            ci_result=(False, "Failed checks: arch-check"),
            failure_strategy="hitl",
            authors=["hydraflow-ul-bot"],
            arch_refresh_result=False,
        )

        result = await loop._do_work()

        prs.refresh_pr_branch_with_arch_regen.assert_awaited_once()
        state.bump_dependabot_arch_refresh_attempts.assert_not_called()
        # Fell through to hitl strategy.
        assert result["failed"] == 1
        prs.add_labels.assert_awaited_once()
        prs.post_comment.assert_awaited_once()
        state.add_dependabot_merge_processed.assert_called_once_with(9423)

    @pytest.mark.asyncio
    async def test_cap_reached_falls_through_to_strategy(self, tmp_path: Path) -> None:
        # Already at the cap (2 attempts) — no further refresh; apply strategy.
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[_make_pr(9424, author="hydraflow-ul-bot", branch="ul-edge-3")],
            ci_result=(False, "Failed checks: arch-check"),
            failure_strategy="skip",
            authors=["hydraflow-ul-bot"],
            arch_refresh_attempts={9424: 2},
            arch_autoheal_max_attempts=2,
        )

        result = await loop._do_work()

        prs.refresh_pr_branch_with_arch_regen.assert_not_awaited()
        assert result["skipped"] == 1  # strategy=skip
        state.add_dependabot_merge_processed.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_arch_failure_skips_refresh(self, tmp_path: Path) -> None:
        # A real (non-arch) failure must NOT trigger a refresh — strategy only.
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[_make_pr(9425, author="hydraflow-ul-bot", branch="ul-edge-4")],
            ci_result=(False, "Failed checks: lint, test"),
            failure_strategy="hitl",
            authors=["hydraflow-ul-bot"],
        )

        result = await loop._do_work()

        prs.refresh_pr_branch_with_arch_regen.assert_not_awaited()
        assert result["failed"] == 1
        prs.add_labels.assert_awaited_once()
        state.add_dependabot_merge_processed.assert_called_once_with(9425)

    @pytest.mark.asyncio
    async def test_kill_switch_zero_disables_refresh(self, tmp_path: Path) -> None:
        # max_attempts=0 is the kill switch: never refresh, even on stale-arch.
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[_make_pr(9426, author="hydraflow-ul-bot", branch="ul-edge-5")],
            ci_result=(False, "Failed checks: arch-check"),
            failure_strategy="skip",
            authors=["hydraflow-ul-bot"],
            arch_autoheal_max_attempts=0,
        )

        result = await loop._do_work()

        prs.refresh_pr_branch_with_arch_regen.assert_not_awaited()
        assert result["skipped"] == 1
        state.bump_dependabot_arch_refresh_attempts.assert_not_called()

    @pytest.mark.asyncio
    async def test_below_cap_still_refreshes(self, tmp_path: Path) -> None:
        # One prior attempt, cap=2 — a second refresh is still allowed.
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[_make_pr(9427, author="hydraflow-ul-bot", branch="ul-edge-6")],
            ci_result=(False, "Failed checks: Architecture Check"),
            failure_strategy="skip",
            authors=["hydraflow-ul-bot"],
            arch_refresh_attempts={9427: 1},
            arch_autoheal_max_attempts=2,
        )

        result = await loop._do_work()

        prs.refresh_pr_branch_with_arch_regen.assert_awaited_once_with(
            9427, "ul-edge-6"
        )
        state.bump_dependabot_arch_refresh_attempts.assert_called_once_with(9427)
        assert result["skipped"] == 1


class TestDependabotMergeLoopFactoryMaintenanceBranches:
    """UL proposer/evidence/edge + pricing-refresh PRs are opened under the
    ambient factory token (``HydraOps-T-rav`` for UL, ``T-rav`` for pricing) —
    NOT a configured bot author — and they carry workflow labels
    (``hydraflow-ul-*`` / ``pricing-refresh``) rather than ``agent/issue-N``, so
    both author-based selection and the review->merge pipeline miss them and
    they pile up. The loop merges them by their factory-owned branch prefix
    (#9843), mirroring the auto-agent prefix fix.
    """

    @pytest.mark.parametrize(
        "branch",
        [
            "ul-proposer/4e3d7b2b",
            "ul-evidence/5ebff585",
            "ul-edges/0afc892d",
            "ul-pruner/9f1c2d3e",
            "pricing-refresh-auto",
            "hydraflow/wiki-maint-20260718-1200",
        ],
    )
    @pytest.mark.asyncio
    async def test_merges_factory_maintenance_pr_despite_non_bot_author(
        self, tmp_path: Path, branch: str
    ) -> None:
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[_make_pr(50, author="HydraOps-T-rav", branch=branch)],
            ci_result=(True, "All checks passed"),
        )

        result = await loop._do_work()

        assert result["merged"] == 1
        prs.merge_pr.assert_awaited_once_with(50, auto_rebase=True)
        state.add_dependabot_merge_processed.assert_called_once_with(50)

    @pytest.mark.asyncio
    async def test_stale_arch_factory_pr_selected_and_self_heals(
        self, tmp_path: Path
    ) -> None:
        """A UL PR red purely on stale arch is now *selected* (by branch prefix)
        and rides the existing arch self-heal path — the #9838 case that
        previously never even entered the loop."""
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[
                _make_pr(9838, author="HydraOps-T-rav", branch="ul-proposer/4e3d7b2b")
            ],
            ci_result=(False, "Failed checks: arch-check"),
            failure_strategy="skip",
        )

        result = await loop._do_work()

        prs.refresh_pr_branch_with_arch_regen.assert_awaited_once_with(
            9838, "ul-proposer/4e3d7b2b"
        )
        state.bump_dependabot_arch_refresh_attempts.assert_called_once_with(9838)
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_ul_lookalike_branch_not_merged(self, tmp_path: Path) -> None:
        """Prefixes are exact: a human branch that merely starts with ``ul-``
        (e.g. ``ul-cleanup-notes``) must not auto-merge."""
        loop, _, _, prs, _ = _make_loop(
            tmp_path,
            open_prs=[_make_pr(60, author="human-dev", branch="ul-cleanup-notes")],
        )

        result = await loop._do_work()

        assert result == {"merged": 0, "skipped": 0, "failed": 0}
        prs.wait_for_ci.assert_not_awaited()


class TestIsBotDetection:
    """GitHub's ``author.is_bot`` flag (the same signal the UI uses to tag a PR
    as a bot) is the primary auto-merge selector, so Dependabot/Renovate/any App
    is picked up generically — without linking to specific account logins (#9843).
    """

    @pytest.mark.asyncio
    async def test_is_bot_pr_merges_without_author_allowlist(
        self, tmp_path: Path
    ) -> None:
        """An is_bot PR merges even when ``settings.authors`` is empty — the bot
        flag alone qualifies it (the operator's ask: don't tie detection to
        account names)."""
        loop, _, _, prs, _ = _make_loop(
            tmp_path,
            open_prs=[
                _make_pr(
                    1,
                    author="app/dependabot",
                    branch="dependabot/uv/foo",
                    is_bot=True,
                )
            ],
            authors=[],
            ci_result=(True, "All checks passed"),
        )

        result = await loop._do_work()

        assert result["merged"] == 1
        prs.merge_pr.assert_awaited_once_with(1, auto_rebase=True)

    @pytest.mark.asyncio
    async def test_non_bot_human_pr_not_merged(self, tmp_path: Path) -> None:
        """is_bot=False on an arbitrary branch stays ignored (no over-merge)."""
        loop, _, _, prs, _ = _make_loop(
            tmp_path,
            open_prs=[
                _make_pr(1, author="some-human", branch="feature/x", is_bot=False)
            ],
            authors=[],
        )

        result = await loop._do_work()

        assert result == {"merged": 0, "skipped": 0, "failed": 0}
        prs.wait_for_ci.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_draft_bot_pr_not_merged(self, tmp_path: Path) -> None:
        """A draft is never auto-merged, even from a bot author."""
        loop, _, _, prs, _ = _make_loop(
            tmp_path,
            open_prs=[
                _make_pr(1, author="app/dependabot", branch="dependabot/x", is_bot=True)
            ],
        )
        # Mark the seeded PR draft (the helper builds non-draft by default).
        loop._cache.get_all_open_prs.return_value[0].draft = True

        result = await loop._do_work()

        assert result == {"merged": 0, "skipped": 0, "failed": 0}
        prs.wait_for_ci.assert_not_awaited()


class TestAuthorNormalization:
    """gh's ``--json author`` renders a GitHub App as ``app/dependabot`` while
    ``settings.authors`` holds the ``dependabot[bot]`` form. Without normalizing
    both sides even real Dependabot PRs never match and the loop merges nothing
    (#9843)."""

    @pytest.mark.parametrize(
        "pr_author",
        ["app/dependabot", "dependabot[bot]", "Dependabot[bot]", "app/Dependabot"],
    )
    @pytest.mark.asyncio
    async def test_dependabot_app_login_matches_config(
        self, tmp_path: Path, pr_author: str
    ) -> None:
        loop, _, _, prs, _ = _make_loop(
            tmp_path,
            open_prs=[_make_pr(1, author=pr_author, branch="dependabot/uv/foo")],
            authors=["dependabot[bot]"],
            ci_result=(True, "All checks passed"),
        )

        result = await loop._do_work()

        assert result["merged"] == 1
        prs.merge_pr.assert_awaited_once_with(1, auto_rebase=True)

    @pytest.mark.parametrize(
        ("login", "expected"),
        [
            ("app/dependabot", "dependabot"),
            ("dependabot[bot]", "dependabot"),
            ("Dependabot[bot]", "dependabot"),
            ("app/renovate", "renovate"),
            ("renovate[bot]", "renovate"),
            ("T-rav", "t-rav"),
            ("HydraOps-T-rav", "hydraops-t-rav"),
            ("", ""),
        ],
    )
    def test_normalize_author(self, login: str, expected: str) -> None:
        from dependabot_merge_loop import _normalize_author

        assert _normalize_author(login) == expected


class TestMergePolicyGate:
    """CH-3 (#9731) — the policy gate at the bot-PR auto-merge seam."""

    def _fake_labels(self, monkeypatch, labels: list[str]) -> None:
        import json

        import subprocess_util

        async def _run(*cmd, **_kwargs):
            assert cmd[:3] == ("gh", "pr", "view")
            return json.dumps({"labels": [{"name": name} for name in labels]})

        monkeypatch.setattr(subprocess_util, "run_subprocess", _run)

    @pytest.mark.asyncio
    async def test_policy_deny_skips_approve_and_merge(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from events import EventType
        from tests.helpers import install_repo_merge_policy

        loop, _, _, prs, state = _make_loop(tmp_path, open_prs=[_make_pr(10)])
        install_repo_merge_policy(loop._config)
        prs.get_pr_diff_names = AsyncMock(return_value=["src/app.py"])
        self._fake_labels(monkeypatch, [])

        result = await loop._do_work()

        assert result == {"merged": 0, "skipped": 0, "failed": 1}
        prs.submit_review.assert_not_awaited()
        prs.merge_pr.assert_not_awaited()
        state.add_dependabot_merge_processed.assert_not_called()
        alerts = [
            e for e in loop._bus.get_history() if e.type == EventType.SYSTEM_ALERT
        ]
        assert len(alerts) == 1
        assert alerts[0].data["source"] == "merge_policy"

    @pytest.mark.asyncio
    async def test_default_policy_allows_ci_green_bot_merge(
        self, tmp_path: Path
    ) -> None:
        """The packaged policy accepts the loop's CI-green auto-approval."""
        loop, _, _, prs, state = _make_loop(tmp_path, open_prs=[_make_pr(10)])

        result = await loop._do_work()

        assert result["merged"] == 1
        prs.merge_pr.assert_awaited_once_with(10, auto_rebase=True)


# ---------------------------------------------------------------------------
# Class 5 (#9889): human-prefix branch shepherding
# ---------------------------------------------------------------------------


class TestHumanBranchShepherd:
    @pytest.mark.asyncio
    async def test_green_human_fix_branch_is_merged(self, tmp_path: Path) -> None:
        """Operator-approved contract: CI-green human fix/ PRs merge."""
        loop, _, _, prs, _ = _make_loop(
            tmp_path,
            open_prs=[_make_pr(42, author="T-rav", branch="fix/manual-thing")],
        )

        with patch("dependabot_merge_loop.fetch_pr_labels", AsyncMock(return_value=[])):
            result = await loop._do_work()

        assert result["merged"] == 1
        prs.merge_pr.assert_awaited_once_with(42, auto_rebase=True)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("prefix", ["perf/", "ci/", "build/"])
    async def test_green_conventional_prefix_branch_is_merged(
        self, tmp_path: Path, prefix: str
    ) -> None:
        """Every Conventional-Commit work prefix gets the shepherd merge path.

        Regression for a factory session that hand-merged a batch of green
        ``perf/`` CI-speedup PRs because ``perf/``/``ci/``/``build/`` were
        outside the shepherd prefix set — they had no merge path at all.
        """
        loop, _, _, prs, _ = _make_loop(
            tmp_path,
            open_prs=[_make_pr(42, author="T-rav", branch=f"{prefix}some-work")],
        )

        with patch("dependabot_merge_loop.fetch_pr_labels", AsyncMock(return_value=[])):
            result = await loop._do_work()

        assert result["merged"] == 1
        prs.merge_pr.assert_awaited_once_with(42, auto_rebase=True)

    @pytest.mark.asyncio
    async def test_kill_switch_restores_no_merge_path(self, tmp_path: Path) -> None:
        loop, _, _, prs, _ = _make_loop(
            tmp_path,
            open_prs=[_make_pr(42, author="T-rav", branch="fix/manual-thing")],
        )
        object.__setattr__(loop._config, "human_branch_shepherd_enabled", False)

        result = await loop._do_work()

        assert result == {"merged": 0, "skipped": 0, "failed": 0}
        prs.wait_for_ci.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_auto_merge_label_leaves_pr_to_author(
        self, tmp_path: Path
    ) -> None:
        loop, _, _, prs, _ = _make_loop(
            tmp_path,
            open_prs=[_make_pr(42, author="T-rav", branch="feat/my-feature")],
        )

        with patch(
            "dependabot_merge_loop.fetch_pr_labels",
            AsyncMock(return_value=["no-auto-merge"]),
        ):
            result = await loop._do_work()

        assert result["skipped"] == 1
        prs.merge_pr.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_bot_prs_never_pay_the_label_fetch(self, tmp_path: Path) -> None:
        """The opt-out read is a raw gh subprocess — bot lane must skip it."""
        loop, _, _, prs, _ = _make_loop(
            tmp_path,
            open_prs=[_make_pr(7, author="dependabot[bot]", is_bot=True)],
        )

        with patch("dependabot_merge_loop.fetch_pr_labels", AsyncMock()) as fetch:
            result = await loop._do_work()

        fetch.assert_not_awaited()
        assert result["merged"] == 1

    @pytest.mark.asyncio
    async def test_airgap_skips_label_fetch_when_policy_disabled(
        self, tmp_path: Path
    ) -> None:
        """#9754: with merge_policy_enabled=False (sandbox) no raw gh runs."""
        loop, _, _, prs, _ = _make_loop(
            tmp_path,
            open_prs=[_make_pr(42, author="T-rav", branch="fix/manual-thing")],
        )
        object.__setattr__(loop._config, "merge_policy_enabled", False)

        with patch("dependabot_merge_loop.fetch_pr_labels", AsyncMock()) as fetch:
            result = await loop._do_work()

        fetch.assert_not_awaited()
        assert result["merged"] == 1

    @pytest.mark.asyncio
    async def test_draft_human_pr_excluded(self, tmp_path: Path) -> None:
        pr = _make_pr(42, author="T-rav", branch="fix/manual-thing")
        pr = pr.model_copy(update={"draft": True})
        loop, _, _, prs, _ = _make_loop(tmp_path, open_prs=[pr])

        result = await loop._do_work()

        assert result == {"merged": 0, "skipped": 0, "failed": 0}
        prs.wait_for_ci.assert_not_awaited()


# ---------------------------------------------------------------------------
# Item 2 (#9889): DIRTY content-conflict auto-heal
# ---------------------------------------------------------------------------


class TestConflictHeal:
    """A CI-green PR whose merge fails on a genuine content conflict
    (``get_pr_mergeable`` reads False = CONFLICTING) is healed by class:
    factory-maintenance → close-supersede (the regenerating loop reopens a
    fresh PR, single-flight #9939); dependabot/bot → one bounded
    update-branch then the failure strategy; human shepherd-prefix → one
    dedup-bounded comment, otherwise the author's to fix."""

    @pytest.mark.asyncio
    async def test_ul_pr_conflict_closed_with_supersede_comment(
        self, tmp_path: Path
    ) -> None:
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[
                _make_pr(50, author="HydraOps-T-rav", branch="ul-proposer/4e3d7b2b")
            ],
            merge_result=False,
            mergeable=False,
        )

        result = await loop._do_work()

        prs.post_comment.assert_awaited_once()
        comment = prs.post_comment.await_args.args[1]
        assert "conflict" in comment.lower()
        assert "fresh" in comment.lower() or "supersed" in comment.lower()
        prs.close_pr.assert_awaited_once_with(50)
        state.add_dependabot_merge_processed.assert_called_once_with(50)
        prs.update_pr_branch.assert_not_awaited()
        prs.close_issue.assert_not_awaited()
        assert result["failed"] == 1
        assert result["merged"] == 0

    @pytest.mark.parametrize(
        "branch",
        [
            "ul-evidence/5ebff585",
            "ul-edges/0afc892d",
            "ul-pruner/9f1c2d3e",
            "pricing-refresh-auto",
            "hydraflow/wiki-maint-20260719-0400",
        ],
    )
    @pytest.mark.asyncio
    async def test_all_factory_maintenance_prefixes_close_supersede(
        self, tmp_path: Path, branch: str
    ) -> None:
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[_make_pr(51, author="HydraOps-T-rav", branch=branch)],
            merge_result=False,
            mergeable=False,
        )

        await loop._do_work()

        prs.close_pr.assert_awaited_once_with(51)
        state.add_dependabot_merge_processed.assert_called_once_with(51)

    @pytest.mark.asyncio
    async def test_dependabot_conflict_update_branch_once_then_retry(
        self, tmp_path: Path
    ) -> None:
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[
                _make_pr(
                    52, author="app/dependabot", branch="dependabot/uv/foo", is_bot=True
                )
            ],
            merge_result=False,
            mergeable=False,
            update_branch_max_attempts=1,
            update_branch_result=True,
        )

        result = await loop._do_work()

        prs.update_pr_branch.assert_awaited_once_with(52, method="merge")
        state.bump_dependabot_update_branch_attempts.assert_called_once_with(52)
        prs.close_pr.assert_not_awaited()
        prs.post_comment.assert_not_awaited()
        state.add_dependabot_merge_processed.assert_not_called()
        assert result["skipped"] == 1
        assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_dependabot_conflict_cap_exhausted_applies_failure_strategy(
        self, tmp_path: Path
    ) -> None:
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[
                _make_pr(
                    53, author="app/dependabot", branch="dependabot/uv/bar", is_bot=True
                )
            ],
            merge_result=False,
            mergeable=False,
            update_branch_max_attempts=1,
            failure_strategy="hitl",
        )
        state.get_dependabot_update_branch_attempts.side_effect = lambda _n: 1

        result = await loop._do_work()

        prs.update_pr_branch.assert_not_awaited()
        prs.add_labels.assert_awaited_once()
        prs.post_comment.assert_awaited_once()
        state.add_dependabot_merge_processed.assert_called_once_with(53)
        prs.close_pr.assert_not_awaited()
        assert result["failed"] == 1

    @pytest.mark.asyncio
    async def test_dependabot_conflict_update_branch_refused_falls_to_strategy(
        self, tmp_path: Path
    ) -> None:
        """update_pr_branch=False (GitHub can't rebase a real conflict) must
        not burn the attempt budget and must fall through to the strategy."""
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[
                _make_pr(
                    54, author="app/dependabot", branch="dependabot/uv/baz", is_bot=True
                )
            ],
            merge_result=False,
            mergeable=False,
            update_branch_max_attempts=1,
            update_branch_result=False,
            failure_strategy="skip",
        )

        result = await loop._do_work()

        prs.update_pr_branch.assert_awaited_once_with(54, method="merge")
        state.bump_dependabot_update_branch_attempts.assert_not_called()
        assert result["skipped"] == 1  # strategy=skip leaves it open
        state.add_dependabot_merge_processed.assert_not_called()

    @pytest.mark.asyncio
    async def test_human_pr_conflict_single_comment_never_closed(
        self, tmp_path: Path
    ) -> None:
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[_make_pr(55, author="T-rav", branch="fix/manual-thing")],
            merge_result=False,
            mergeable=False,
        )

        with patch("dependabot_merge_loop.fetch_pr_labels", AsyncMock(return_value=[])):
            first = await loop._do_work()
            second = await loop._do_work()  # PR still open + conflicting

        # Exactly ONE conflict comment across both cycles (DedupStore-bounded).
        prs.post_comment.assert_awaited_once()
        comment = prs.post_comment.await_args.args[1]
        assert "conflict" in comment.lower()
        # Never closed, never update-branched, never marked processed —
        # the author keeps full ownership.
        prs.close_pr.assert_not_awaited()
        prs.close_issue.assert_not_awaited()
        prs.update_pr_branch.assert_not_awaited()
        state.add_dependabot_merge_processed.assert_not_called()
        assert first["skipped"] == 1
        assert second["skipped"] == 1

    @pytest.mark.asyncio
    async def test_kill_switch_off_restores_legacy_give_up(
        self, tmp_path: Path
    ) -> None:
        loop, _, _, prs, state = _make_loop(
            tmp_path,
            open_prs=[
                _make_pr(56, author="HydraOps-T-rav", branch="ul-proposer/deadbeef")
            ],
            merge_result=False,
            mergeable=False,
        )
        object.__setattr__(loop._config, "dependabot_conflict_heal_enabled", False)

        result = await loop._do_work()

        prs.get_pr_mergeable.assert_not_awaited()
        prs.close_pr.assert_not_awaited()
        prs.post_comment.assert_not_awaited()
        prs.update_pr_branch.assert_not_awaited()
        state.add_dependabot_merge_processed.assert_not_called()
        assert result["failed"] == 1

    @pytest.mark.asyncio
    async def test_transient_merge_failure_is_not_treated_as_conflict(
        self, tmp_path: Path
    ) -> None:
        """mergeable=None (unknown) and True (clean) both mean the merge
        failure was NOT a content conflict — legacy give-up, no heal."""
        for status in (None, True):
            loop, _, _, prs, state = _make_loop(
                tmp_path,
                open_prs=[
                    _make_pr(57, author="HydraOps-T-rav", branch="ul-edges/cafe")
                ],
                merge_result=False,
                mergeable=status,
            )

            result = await loop._do_work()

            prs.get_pr_mergeable.assert_awaited_once_with(57)
            prs.close_pr.assert_not_awaited()
            prs.post_comment.assert_not_awaited()
            assert result["failed"] == 1
