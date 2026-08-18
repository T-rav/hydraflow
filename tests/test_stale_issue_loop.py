"""Tests for the StaleIssueLoop background worker."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import StaleIssueSettings
from stale_issue_loop import StaleIssueLoop
from tests.helpers import make_bg_loop_deps


def _gh_issue_json(
    number: int,
    title: str = "Some issue",
    updated_at: str | None = None,
    labels: list[str] | None = None,
) -> dict:
    """Build a dict matching ``PRPort.list_open_issues`` output (#11418)."""
    if updated_at is None:
        updated_at = (datetime.now(UTC) - timedelta(days=60)).isoformat()
    label_objs = [{"name": lbl} for lbl in (labels or [])]
    return {
        "number": number,
        "title": title,
        "body": "",
        "updated_at": updated_at,
        "labels": label_objs,
    }


def _make_state(
    *,
    staleness_days: int = 30,
    excluded_labels: list[str] | None = None,
    dry_run: bool = False,
    already_closed: set[int] | None = None,
) -> MagicMock:
    """Build a mock StateTracker with stale issue methods."""
    state = MagicMock()
    settings = StaleIssueSettings(
        staleness_days=staleness_days,
        excluded_labels=excluded_labels or [],
        dry_run=dry_run,
    )
    state.get_stale_issue_settings.return_value = settings
    state.get_stale_issue_closed.return_value = already_closed or set()
    return state


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    interval: int = 86400,
    gh_issues: list[dict] | None = None,
    staleness_days: int = 30,
    excluded_labels: list[str] | None = None,
    dry_run: bool = False,
    already_closed: set[int] | None = None,
) -> tuple[StaleIssueLoop, MagicMock, MagicMock]:
    """Build a StaleIssueLoop with test-friendly defaults.

    Returns (loop, prs_mock, state_mock).
    """
    deps = make_bg_loop_deps(tmp_path, enabled=enabled, stale_issue_interval=interval)

    prs = AsyncMock()
    prs.list_open_issues = AsyncMock(return_value=gh_issues or [])
    prs.close_issue = AsyncMock(return_value=True)
    prs.post_comment = AsyncMock()
    prs.list_branch_refs = AsyncMock(return_value=[])
    prs.list_branch_commits = AsyncMock(return_value=[])

    state = _make_state(
        staleness_days=staleness_days,
        excluded_labels=excluded_labels,
        dry_run=dry_run,
        already_closed=already_closed,
    )

    loop = StaleIssueLoop(
        config=deps.config,
        prs=prs,
        state=state,
        deps=deps.loop_deps,
    )
    return loop, prs, state


class TestStaleIssueLoopInterval:
    def test_default_interval_uses_config(self, tmp_path: Path) -> None:
        loop, *_ = _make_loop(tmp_path, interval=86400)
        assert loop._get_default_interval() == 86400


class TestStaleIssueLoopDoWork:
    @pytest.mark.asyncio
    async def test_no_issues_returns_zeroes(self, tmp_path: Path) -> None:
        """When there are no open issues, all counters are zero."""
        loop, *_ = _make_loop(tmp_path, gh_issues=[])
        result = await loop._do_work()
        assert result == {"scanned": 0, "closed": 0, "skipped": 0, "retired": 0}

    @pytest.mark.asyncio
    async def test_stale_issue_gets_closed(self, tmp_path: Path) -> None:
        """An issue with old updatedAt is commented and closed."""
        old_date = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        issues = [_gh_issue_json(42, updated_at=old_date)]
        loop, prs, state = _make_loop(tmp_path, gh_issues=issues)

        result = await loop._do_work()

        assert result is not None
        assert result["closed"] == 1
        assert result["scanned"] == 1
        prs.post_comment.assert_awaited_once()
        prs.close_issue.assert_awaited_once_with(42)
        state.add_stale_issue_closed.assert_called_once_with(42)

    @pytest.mark.asyncio
    async def test_non_stale_issue_skipped(self, tmp_path: Path) -> None:
        """An issue updated recently is not closed."""
        recent_date = (datetime.now(UTC) - timedelta(days=5)).isoformat()
        issues = [_gh_issue_json(10, updated_at=recent_date)]
        loop, prs, state = _make_loop(tmp_path, gh_issues=issues)

        result = await loop._do_work()

        assert result is not None
        assert result["closed"] == 0
        assert result["scanned"] == 1
        prs.post_comment.assert_not_awaited()
        state.add_stale_issue_closed.assert_not_called()

    @pytest.mark.asyncio
    async def test_excluded_label_skips_issue(self, tmp_path: Path) -> None:
        """Issues with excluded labels are skipped entirely."""
        old_date = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        issues = [_gh_issue_json(7, updated_at=old_date, labels=["keep-open"])]
        loop, prs, state = _make_loop(
            tmp_path,
            gh_issues=issues,
            excluded_labels=["keep-open"],
        )

        result = await loop._do_work()

        assert result is not None
        assert result["skipped"] == 1
        assert result["scanned"] == 0
        assert result["closed"] == 0
        prs.post_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_already_closed_issue_skipped(self, tmp_path: Path) -> None:
        """Issues already in the closed set are skipped."""
        old_date = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        issues = [_gh_issue_json(99, updated_at=old_date)]
        loop, prs, state = _make_loop(
            tmp_path,
            gh_issues=issues,
            already_closed={99},
        )

        result = await loop._do_work()

        assert result is not None
        assert result["skipped"] == 1
        assert result["scanned"] == 0
        assert result["closed"] == 0
        prs.post_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_dry_run_logs_but_does_not_close(self, tmp_path: Path) -> None:
        """In dry_run mode, stale issues are counted but not actually closed."""
        old_date = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        issues = [_gh_issue_json(15, updated_at=old_date)]
        loop, prs, state = _make_loop(tmp_path, gh_issues=issues, dry_run=True)

        result = await loop._do_work()

        assert result is not None
        assert result["closed"] == 1
        assert result["scanned"] == 1
        # Should NOT have called post_comment or close
        prs.post_comment.assert_not_awaited()
        prs.close_issue.assert_not_awaited()
        state.add_stale_issue_closed.assert_not_called()

    @pytest.mark.asyncio
    async def test_sentry_breadcrumb_emitted(self, tmp_path: Path) -> None:
        """When an ObservabilityPort is injected, a breadcrumb is recorded."""
        from mockworld.fakes.fake_observability import FakeObservability

        old_date = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        issues = [_gh_issue_json(5, updated_at=old_date)]
        loop, prs, state = _make_loop(tmp_path, gh_issues=issues)
        fake_obs = FakeObservability()
        loop._obs = fake_obs

        await loop._do_work()

        assert len(fake_obs.breadcrumbs) >= 1
        bc = fake_obs.breadcrumbs[0]
        assert bc["category"] == "stale_issue.cycle"
        assert "1" in bc["message"]  # scanned count

    @pytest.mark.asyncio
    async def test_gh_fetch_failure_returns_stats(self, tmp_path: Path) -> None:
        """If fetching issues fails, stats are returned with zeroes."""
        loop, prs, state = _make_loop(tmp_path)
        prs.list_open_issues = AsyncMock(side_effect=RuntimeError("network error"))

        result = await loop._do_work()

        assert result == {"scanned": 0, "closed": 0, "skipped": 0}

    @pytest.mark.asyncio
    async def test_backlog_budget_uses_list_open_issues(self, tmp_path: Path) -> None:
        """#11418: the retirement valve reads through PRPort.list_open_issues,
        not a raw ``_run_gh`` reach-around, and its issue-close goes through
        PRPort.close_issue."""
        older = (datetime.now(UTC) - timedelta(days=200)).isoformat()
        newer = (datetime.now(UTC) - timedelta(days=100)).isoformat()
        issues = [
            {
                "number": 77,
                "title": "old advisory",
                "body": "",
                "updated_at": older,
                "created_at": older,
                "labels": [{"name": "hydraflow-find"}],
            },
            {
                "number": 78,
                "title": "newer advisory",
                "body": "",
                "updated_at": newer,
                "created_at": newer,
                "labels": [{"name": "hydraflow-find"}],
            },
        ]
        loop, prs, state = _make_loop(tmp_path)
        prs.list_open_issues = AsyncMock(return_value=issues)
        loop._config.backlog_budget = 1  # 2 advisory issues > budget of 1
        loop._config.backlog_budget_min_age_days = 7

        result = await loop._scan_backlog_budget()

        assert result["retired"] == 1
        prs.close_issue.assert_awaited_once_with(77)

    @pytest.mark.asyncio
    async def test_backlog_budget_disabled_skips_fetch(self, tmp_path: Path) -> None:
        """budget <= 0 disables the valve without ever calling list_open_issues."""
        loop, prs, state = _make_loop(tmp_path)
        loop._config.backlog_budget = 0

        result = await loop._scan_backlog_budget()

        assert result == {"retired": 0}
        prs.list_open_issues.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_lifecycle_labels_excluded_by_default(
        self,
        tmp_path: Path,
    ) -> None:
        """Issues with HydraFlow lifecycle labels are skipped."""
        old_date = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        issues = [
            _gh_issue_json(1, updated_at=old_date, labels=["hydraflow-plan"]),
        ]
        loop, prs, _ = _make_loop(tmp_path, gh_issues=issues)

        result = await loop._do_work()

        assert result is not None
        assert result["skipped"] == 1
        assert result["closed"] == 0


class TestBranchGcPortWiring:
    """#11418: branch-GC reads through PRPort.list_branch_refs /
    list_branch_commits instead of the raw ``self._prs._run_gh``/``_repo``
    reach-around — so a fake backing PRPort can model both calls."""

    @pytest.mark.asyncio
    async def test_candidate_branches_queries_each_configured_prefix(
        self, tmp_path: Path
    ) -> None:
        loop, prs, _ = _make_loop(tmp_path)
        prs.list_branch_refs = AsyncMock(
            side_effect=lambda prefix: (
                [f"{prefix}1"] if prefix == "agent/issue-" else []
            )
        )

        branches = await loop._branch_gc_candidate_branches()

        assert branches == ["agent/issue-1"]
        prs.list_branch_refs.assert_any_await("agent/issue-")
        prs.list_branch_refs.assert_any_await("fix/")

    @pytest.mark.asyncio
    async def test_candidate_branches_swallows_transient_error(
        self, tmp_path: Path
    ) -> None:
        """A plain RuntimeError on one prefix is logged and skipped, not raised."""
        loop, prs, _ = _make_loop(tmp_path)

        async def _flaky(prefix: str) -> list[str]:
            if prefix == "agent/issue-":
                raise RuntimeError("gh api boom")
            return ["fix/1"]

        prs.list_branch_refs = AsyncMock(side_effect=_flaky)

        branches = await loop._branch_gc_candidate_branches()

        assert branches == ["fix/1"]

    @pytest.mark.asyncio
    async def test_candidate_branches_propagates_credit_exhaustion(
        self, tmp_path: Path
    ) -> None:
        """A CreditExhaustedError must NOT be swallowed (#11418 defensive branch)."""
        from subprocess_util import CreditExhaustedError

        loop, prs, _ = _make_loop(tmp_path)
        prs.list_branch_refs = AsyncMock(side_effect=CreditExhaustedError("no credits"))

        with pytest.raises(CreditExhaustedError):
            await loop._branch_gc_candidate_branches()

    @pytest.mark.asyncio
    async def test_commit_info_derives_last_date_and_messages(
        self, tmp_path: Path
    ) -> None:
        loop, prs, _ = _make_loop(tmp_path)
        prs.list_branch_commits = AsyncMock(
            return_value=[
                {"date": "2026-01-02T00:00:00Z", "message": "Fixes #42: thing"},
                {"date": "2026-01-01T00:00:00Z", "message": "wip"},
            ]
        )

        info = await loop._branch_gc_commit_info("agent/issue-42")

        assert info == (
            "2026-01-02T00:00:00Z",
            ["Fixes #42: thing", "wip"],
        )

    @pytest.mark.asyncio
    async def test_commit_info_returns_none_on_empty_commits(
        self, tmp_path: Path
    ) -> None:
        loop, prs, _ = _make_loop(tmp_path)
        prs.list_branch_commits = AsyncMock(return_value=[])

        info = await loop._branch_gc_commit_info("agent/issue-42")

        assert info is None

    @pytest.mark.asyncio
    async def test_commit_info_swallows_transient_error(self, tmp_path: Path) -> None:
        loop, prs, _ = _make_loop(tmp_path)
        prs.list_branch_commits = AsyncMock(side_effect=RuntimeError("gh api boom"))

        info = await loop._branch_gc_commit_info("agent/issue-42")

        assert info is None

    @pytest.mark.asyncio
    async def test_commit_info_propagates_credit_exhaustion(
        self, tmp_path: Path
    ) -> None:
        from subprocess_util import CreditExhaustedError

        loop, prs, _ = _make_loop(tmp_path)
        prs.list_branch_commits = AsyncMock(
            side_effect=CreditExhaustedError("no credits")
        )

        with pytest.raises(CreditExhaustedError):
            await loop._branch_gc_commit_info("agent/issue-42")
