"""MockWorld scenario: branch-ref lifecycle observability (#11227).

``FakeGitHub`` previously modeled PRs but had no branch-ref state, so any
loop behaviour keyed on "does the head ref still exist" (post-merge orphan
detection, RC retention sweep, branch GC) had no observable surface at the
MockWorld tier. These scenarios drive the two real consumers —
``StagingPromotionLoop`` and ``StaleIssueLoop``'s branch-GC reconciler —
against a real ``FakeGitHub`` and assert directly through the new
``branch_tip()``/``branch_tips()`` seam: FakeGitHub only, no subprocess/gh/
real git.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from mockworld.fakes.fake_github import FakeGitHub
from staging_promotion_loop import StagingPromotionLoop
from stale_issue_loop import StaleIssueLoop
from state import StateTracker

pytestmark = pytest.mark.scenario_loops


class TestRcBranchLifecycle:
    """StagingPromotionLoop against a real FakeGitHub: cut -> merge -> sweep."""

    def _make_loop(self, tmp_path, fake, **config_overrides) -> StagingPromotionLoop:
        config = HydraFlowConfig(
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            data_root=tmp_path / "data",
            **config_overrides,
        )

        async def _sleep(_s: float) -> None:
            return None

        deps = LoopDeps(
            event_bus=EventBus(),
            stop_event=asyncio.Event(),
            status_cb=MagicMock(),
            enabled_cb=lambda _name: True,
            sleep_fn=_sleep,
        )
        return StagingPromotionLoop(config=config, prs=fake, deps=deps)

    async def test_cutting_then_merging_rc_leaves_no_ref_behind(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tick 1 cuts an RC (tip observable); tick 2 promotes it, which
        emulates ``gh pr merge --delete-branch`` — the tip is gone."""
        monkeypatch.setenv("HYDRAFLOW_STAGING_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_EVIDENCE_PACK_ENABLED", "false")
        monkeypatch.setenv("HYDRAFLOW_MERGE_POLICY_ENABLED", "false")
        fake = FakeGitHub()
        loop = self._make_loop(tmp_path, fake)

        first = await loop._do_work()
        assert first is not None
        assert first["status"] == "opened"
        rc_branch = first["rc_branch"]
        assert fake.branch_tip(rc_branch) is not None

        second = await loop._do_work()

        assert second is not None
        assert second["status"] == "promoted"
        assert fake.branch_tip(rc_branch) is None

    async def test_retention_sweep_deletes_only_stale_rc_refs_and_keeps_newest(
        self, tmp_path
    ) -> None:
        fake = FakeGitHub()
        loop = self._make_loop(tmp_path, fake, staging_rc_retention_days=7)

        old_iso = (
            (datetime.now(UTC) - timedelta(days=30)).isoformat().replace("+00:00", "Z")
        )
        new_iso = (
            (datetime.now(UTC) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
        )
        fake.seed_branch("rc/2026-01-01-0000")
        fake._rc_branches["rc/2026-01-01-0000"] = old_iso
        fake.seed_branch("rc/2026-08-01-0000")
        fake._rc_branches["rc/2026-08-01-0000"] = new_iso

        deleted = await loop._sweep_stale_rc_branches()

        assert deleted == 1
        assert fake.branch_tip("rc/2026-01-01-0000") is None
        assert fake.branch_tip("rc/2026-08-01-0000") is not None


_STALE_BRANCH_REPO = "test-org/test-repo"
_STALE_BRANCH = "agent/issue-4242"


class TestStaleAgentBranchLifecycle:
    """StaleIssueLoop's branch-GC reconciler against a real FakeGitHub."""

    def _make_loop_and_github(
        self,
        tmp_path,
        *,
        delete_enabled: bool,
        has_open_pr: bool = False,
        commit_age_days: int = 30,
    ) -> tuple[StaleIssueLoop, FakeGitHub]:
        commit_iso = (
            (datetime.now(UTC) - timedelta(days=commit_age_days))
            .isoformat()
            .replace("+00:00", "Z")
        )
        # Fresh updated_at keeps issue #4242 out of _do_work's unrelated
        # general stale-issue auto-close sweep, which runs before branch-GC
        # in the same tick.
        fresh_updated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")

        fake = FakeGitHub()
        fake._repo = _STALE_BRANCH_REPO
        fake.seed_branch(
            _STALE_BRANCH,
            last_commit_at=commit_iso,
            commit_messages=["auto-agent commit"],
        )
        fake.add_issue(4242, "Some fix", "body", updated_at=fresh_updated_at)
        if has_open_pr:
            fake.add_pr(number=77, issue_number=4242, branch=_STALE_BRANCH)

        config = HydraFlowConfig(
            data_root=tmp_path / "data",
            repo_root=tmp_path / "repo",
            repo=_STALE_BRANCH_REPO,
            branch_gc_delete_enabled=delete_enabled,
        )
        deps = LoopDeps(
            event_bus=EventBus(),
            stop_event=asyncio.Event(),
            status_cb=MagicMock(),
            enabled_cb=lambda _name: True,
        )
        state = StateTracker(state_file=tmp_path / "data" / "state.json")
        loop = StaleIssueLoop(config=config, prs=fake, state=state, deps=deps)
        return loop, fake

    async def test_stale_agent_branch_gets_one_comment_ref_intact(
        self, tmp_path
    ) -> None:
        loop, fake = self._make_loop_and_github(tmp_path, delete_enabled=False)

        result = await loop._do_work()

        assert result["branch_gc_commented"] == 1
        assert fake.branch_tip(_STALE_BRANCH) is not None

    async def test_deletion_enabled_removes_ref_on_the_delete_tick(
        self, tmp_path
    ) -> None:
        loop, fake = self._make_loop_and_github(tmp_path, delete_enabled=True)
        # Simulate the truth comment having been posted on a prior tick —
        # the spec never comments and deletes in the same cycle.
        loop._branch_gc_dedup.add(_STALE_BRANCH)

        result = await loop._do_work()

        assert result["branch_gc_deleted"] == 1
        assert fake.branch_tip(_STALE_BRANCH) is None

    async def test_open_pr_keeps_ref_and_draws_no_comment(self, tmp_path) -> None:
        loop, fake = self._make_loop_and_github(
            tmp_path, delete_enabled=False, has_open_pr=True
        )

        result = await loop._do_work()

        assert result["branch_gc_commented"] == 0
        assert fake.issue(4242).comments == []
        assert fake.branch_tip(_STALE_BRANCH) is not None
