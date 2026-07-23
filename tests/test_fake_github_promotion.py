"""FakeGitHub RC-promotion fidelity (#10309).

The Staging/RC promotion PRPort block historically stubbed the read side:
``find_open_promotion_pr`` always returned ``None`` and the two listing
methods returned ``[]``, so :class:`StagingPromotionLoop` could *cut* an RC
in MockWorld but never *see* it again to monitor/merge it — the RC path was
untestable end-to-end in the sandbox. These tests pin the upgraded fake:
reads are backed by real ``FakePR``/branch state, mirroring the real
``PRManager`` semantics (open PRs whose head starts with ``rc/``, targeting
main; ``GhPromotionPR``-shaped listing entries).
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from base_background_loop import LoopDeps
from events import EventBus
from mockworld.fakes import FakeGitHub
from staging_promotion_loop import StagingPromotionLoop

if TYPE_CHECKING:
    from ports import PRPort


class TestFindOpenPromotionPr:
    @pytest.mark.asyncio
    async def test_returns_none_when_only_agent_prs_exist(self) -> None:
        gh = FakeGitHub()
        gh.add_pr(number=100, issue_number=1, branch="hf/issue-1")

        assert await gh.find_open_promotion_pr() is None

    @pytest.mark.asyncio
    async def test_returns_created_promotion_pr(self) -> None:
        gh = FakeGitHub()
        num = await gh.create_promotion_pr(
            rc_branch="rc/2026-07-22-0400", title="Promote", body="b"
        )

        info = await gh.find_open_promotion_pr()

        assert info is not None
        assert info.number == num
        assert info.branch == "rc/2026-07-22-0400"
        assert info.issue_number == 0

    @pytest.mark.asyncio
    async def test_merged_promotion_pr_is_no_longer_open(self) -> None:
        gh = FakeGitHub()
        num = await gh.create_promotion_pr(
            rc_branch="rc/2026-07-22-0400", title="Promote", body="b"
        )
        await gh.merge_promotion_pr(num)

        assert await gh.find_open_promotion_pr() is None

    @pytest.mark.asyncio
    async def test_closed_promotion_pr_is_no_longer_open(self) -> None:
        gh = FakeGitHub()
        num = await gh.create_promotion_pr(
            rc_branch="rc/2026-07-22-0400", title="Promote", body="b"
        )
        await gh.close_issue(num)

        assert await gh.find_open_promotion_pr() is None


class TestListRecentPromotionPrs:
    @pytest.mark.asyncio
    async def test_merged_promotion_pr_listed_with_contract_shape(self) -> None:
        """Entries carry the GhPromotionPR projection keys exactly."""
        gh = FakeGitHub()
        num = await gh.create_promotion_pr(
            rc_branch="rc/2026-07-22-0400", title="Promote", body="b"
        )
        await gh.merge_promotion_pr(num)

        recent = await gh.list_recent_promotion_prs(days=7)

        assert len(recent) == 1
        entry = recent[0]
        assert set(entry) == {"number", "branch", "merged", "closed_at", "url"}
        assert entry["number"] == num
        assert entry["branch"] == "rc/2026-07-22-0400"
        assert entry["merged"] is True

    @pytest.mark.asyncio
    async def test_open_promotion_pr_and_agent_prs_excluded(self) -> None:
        gh = FakeGitHub()
        await gh.create_promotion_pr(
            rc_branch="rc/2026-07-22-0400", title="Promote", body="b"
        )  # open — excluded
        gh.add_pr(number=100, issue_number=1, branch="hf/issue-1", merged=True)

        assert await gh.list_recent_promotion_prs(days=7) == []


class TestListRcBranches:
    @pytest.mark.asyncio
    async def test_created_rc_branch_listed_with_parseable_date(self) -> None:
        gh = FakeGitHub()
        await gh.create_rc_branch("rc/2026-07-22-0400")

        branches = await gh.list_rc_branches()

        assert len(branches) == 1
        branch, iso = branches[0]
        assert branch == "rc/2026-07-22-0400"
        datetime.fromisoformat(iso.replace("Z", "+00:00"))  # must parse

    @pytest.mark.asyncio
    async def test_delete_branch_removes_rc_branch(self) -> None:
        gh = FakeGitHub()
        await gh.create_rc_branch("rc/2026-07-22-0400")

        assert await gh.delete_branch("rc/2026-07-22-0400") is True

        assert await gh.list_rc_branches() == []


class TestStagingPromotionLoopAgainstFake:
    """The real loop against the real fake — the s82 sandbox path at unit tier.

    Tick 1 cuts an RC (no cadence marker on first boot → cut immediately);
    tick 2 finds its own open promotion PR via the upgraded fake read side,
    sees green CI, and merges it. This is the exact two-tick sequence the
    s82 sandbox scenario asserts through /api/staging-promotion/status.
    """

    @pytest.mark.asyncio
    async def test_two_ticks_cut_then_promote(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_STAGING_ENABLED", "true")
        # Keep the CH-4 evidence machinery (raw gh + compiler) off the
        # network — same override the air-gapped sandbox applies.
        monkeypatch.setenv("HYDRAFLOW_EVIDENCE_PACK_ENABLED", "false")
        monkeypatch.setenv("HYDRAFLOW_MERGE_POLICY_ENABLED", "false")
        from config import HydraFlowConfig  # noqa: PLC0415

        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            data_root=tmp_path / "data",
        )

        async def _sleep(_s: float) -> None:
            return None

        deps = LoopDeps(
            event_bus=EventBus(),
            stop_event=asyncio.Event(),
            status_cb=MagicMock(),
            enabled_cb=lambda _n: True,
            sleep_fn=_sleep,
        )
        gh = FakeGitHub()
        # Same cast sandbox_main uses — the fake's issue-listing surface is
        # narrower than strict PRPort; the promotion surface is complete.
        loop = StagingPromotionLoop(config=cfg, prs=cast("PRPort", gh), deps=deps)

        first = await loop._do_work()
        assert first is not None
        assert first["status"] == "opened"
        rc_pr = first["pr"]

        second = await loop._do_work()
        assert second is not None
        assert second["status"] == "promoted"
        assert second["pr"] == rc_pr
        assert gh._prs[rc_pr].merged is True
