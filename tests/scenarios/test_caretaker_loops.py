"""Caretaker loop scenarios L9–L13 — covers loops beyond L1–L8 in test_loops.py.

Each scenario seeds a MockWorld, runs one real BaseBackgroundLoop subclass via
``run_with_loops()``, and asserts on the observable result or mock call counts.

Because the inner delegates (adr_reviewer, memory_sync, etc.) are injected as
AsyncMock / MagicMock objects through ``world._loop_ports``, the loops exercise
their full _do_work() dispatch path without touching real I/O.

Strategy for injecting port mocks before the catalog creates its defaults:
    world._loop_ports is initialised lazily on the first run_with_loops() call.
    We pre-seed it ourselves so the catalog's ``ports.get(key) or MagicMock()``
    finds our mock and uses it instead of creating a bare MagicMock().
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


# ---------------------------------------------------------------------------
# L9: ADR Reviewer loop invokes reviewer delegate
# ---------------------------------------------------------------------------


class TestL9ADRReviewerLoop:
    """L9: adr_reviewer_loop calls review_proposed_adrs on its delegate."""

    async def test_adr_reviewer_loop_invokes_reviewer(self, tmp_path) -> None:
        """ADRReviewerLoop._do_work delegates entirely to adr_reviewer.review_proposed_adrs.

        We inject an AsyncMock as the adr_reviewer port before the catalog
        builds the loop, so the await inside _do_work succeeds.  The return
        value propagates back as the loop's stats dict.
        """
        world = MockWorld(tmp_path)

        fake_reviewer = AsyncMock()
        fake_reviewer.review_proposed_adrs.return_value = {
            "reviewed": 2,
            "accepted": 1,
            "deferred": 1,
        }
        _seed_ports(world, adr_reviewer=fake_reviewer)

        stats = await world.run_with_loops(["adr_reviewer"], cycles=1)

        assert stats["adr_reviewer"] is not None
        assert stats["adr_reviewer"]["reviewed"] == 2
        assert stats["adr_reviewer"]["accepted"] == 1
        fake_reviewer.review_proposed_adrs.assert_called_once()

    async def test_adr_reviewer_loop_returns_none_passthrough(self, tmp_path) -> None:
        """ADRReviewerLoop passes through None if reviewer returns None.

        Verifies the loop does not wrap or mutate a None result.
        """
        world = MockWorld(tmp_path)

        fake_reviewer = AsyncMock()
        fake_reviewer.review_proposed_adrs.return_value = None
        _seed_ports(world, adr_reviewer=fake_reviewer)

        stats = await world.run_with_loops(["adr_reviewer"], cycles=1)

        assert stats["adr_reviewer"] is None
        fake_reviewer.review_proposed_adrs.assert_called_once()


# ---------------------------------------------------------------------------
# L11: Retrospective loop processes queue items
# ---------------------------------------------------------------------------


class TestL11RetrospectiveLoop:
    """L11: retrospective_loop drains its queue and records stats."""

    async def test_empty_queue_returns_zero_processed(self, tmp_path) -> None:
        """With an empty queue, the loop returns zero processed/patterns/stale.

        queue.load() is sync on RetrospectiveQueue so a plain MagicMock works.
        We configure it to return [] to exercise the early-return branch.
        """
        world = MockWorld(tmp_path)

        fake_queue = MagicMock()
        fake_queue.load.return_value = []
        _seed_ports(world, retrospective_queue=fake_queue)

        stats = await world.run_with_loops(["retrospective"], cycles=1)

        assert stats["retrospective"] == {
            "processed": 0,
            "patterns_filed": 0,
            "stale_proposals": 0,
        }
        fake_queue.load.assert_called_once()

    async def test_retro_patterns_item_processed_and_acknowledged(
        self, tmp_path
    ) -> None:
        """A RETRO_PATTERNS queue item causes _handle_retro_patterns to run.

        The retrospective collector's _load_recent and _detect_patterns are
        called.  The item id is acknowledged and processed count == 1.
        """
        from retrospective_queue import QueueItem, QueueKind  # noqa: PLC0415

        world = MockWorld(tmp_path)

        item = QueueItem(kind=QueueKind.RETRO_PATTERNS, issue_number=77, pr_number=88)

        fake_queue = MagicMock()
        fake_queue.load.return_value = [item]

        fake_retro = MagicMock()
        fake_retro._load_recent.return_value = []
        fake_retro._detect_patterns = AsyncMock(return_value=None)

        _seed_ports(
            world,
            retrospective_queue=fake_queue,
            retrospective=fake_retro,
        )

        stats = await world.run_with_loops(["retrospective"], cycles=1)

        assert stats["retrospective"]["processed"] == 1
        fake_queue.acknowledge.assert_called_once_with([item.id])
        fake_retro._load_recent.assert_called_once()

    async def test_stale_hitl_dedup_across_ticks(self, tmp_path) -> None:
        """Issue #8988: ``RetrospectiveLoop`` must not file duplicate
        ``[HITL] Stale review insight:`` issues on repeated stale ticks.

        Drives the real loop against FakeGitHub for three ticks of the
        same stale category and asserts the FakeGitHub issue count caps
        at 1 with follow-up comments on the existing issue.
        """
        from datetime import UTC, datetime, timedelta
        from unittest.mock import patch  # noqa: PLC0415

        from retrospective_queue import QueueItem, QueueKind  # noqa: PLC0415

        world = MockWorld(tmp_path)

        fake_queue = MagicMock()
        fake_queue.load.return_value = [QueueItem(kind=QueueKind.VERIFY_PROPOSALS)]
        fake_queue.acknowledge = MagicMock()

        fake_insights = MagicMock()
        fake_insights.load_recent.return_value = []
        fake_insights.get_proposed_categories.return_value = set()

        _seed_ports(
            world,
            retrospective_queue=fake_queue,
            insights=fake_insights,
        )

        # Snapshot FakeGitHub HITL title count.
        hitl_title = "[HITL] Stale review insight: Missing test coverage"

        with (
            patch(
                "review_insights.verify_proposals",
                return_value=["missing_tests"],
            ),
            patch(
                "review_insights.CATEGORY_DESCRIPTIONS",
                {"missing_tests": "Missing test coverage"},
            ),
            patch("review_insights._PROPOSAL_STALE_DAYS", 30),
        ):
            base = datetime(2026, 5, 19, 0, 0, 0, tzinfo=UTC)
            # Tick 1: file
            with patch("retrospective_loop._now_utc", return_value=base):
                await world.run_with_loops(["retrospective"], cycles=1)
            # Tick 2: comment
            with patch(
                "retrospective_loop._now_utc",
                return_value=base + timedelta(hours=2),
            ):
                await world.run_with_loops(["retrospective"], cycles=1)
            # Tick 3: comment
            with patch(
                "retrospective_loop._now_utc",
                return_value=base + timedelta(hours=4),
            ):
                await world.run_with_loops(["retrospective"], cycles=1)

        hitl_issues = [
            issue
            for issue in world._github._issues.values()
            if issue.title == hitl_title
        ]
        assert len(hitl_issues) == 1, (
            f"expected 1 HITL issue, got {len(hitl_issues)}: "
            f"{[i.number for i in hitl_issues]}"
        )
        # And the loop should have posted 2 follow-up comments on the
        # one open HITL issue.
        assert len(hitl_issues[0].comments) == 2, (
            f"expected 2 follow-up comments, got {len(hitl_issues[0].comments)}"
        )


# ---------------------------------------------------------------------------
# L12: Epic Monitor includes completed-epic sweep stats
# ---------------------------------------------------------------------------


class TestL12EpicMonitorSweep:
    async def test_no_epics_returns_zero_counts(self, tmp_path) -> None:
        world = MockWorld(tmp_path)

        epic_mgr = MagicMock()
        epic_mgr.check_stale_epics = AsyncMock(return_value=[])
        epic_mgr.sweep_completed_epics = AsyncMock(
            return_value={"checked": 0, "swept": 0, "total_open_epics": 0}
        )
        epic_mgr.refresh_cache = AsyncMock(return_value=None)
        epic_mgr.get_all_progress.return_value = []
        _seed_ports(world, epic_manager=epic_mgr)

        stats = await world.run_with_loops(["epic_monitor"], cycles=1)

        assert stats["epic_monitor"] is not None
        assert stats["epic_monitor"]["checked"] == 0
        assert stats["epic_monitor"]["swept"] == 0
        assert stats["epic_monitor"]["total_open_epics"] == 0

    async def test_epic_with_all_closed_sub_issues_is_swept(self, tmp_path) -> None:
        world = MockWorld(tmp_path)

        epic_mgr = MagicMock()
        epic_mgr.check_stale_epics = AsyncMock(return_value=[])
        epic_mgr.sweep_completed_epics = AsyncMock(
            return_value={"checked": 1, "swept": 1, "total_open_epics": 1}
        )
        epic_mgr.refresh_cache = AsyncMock(return_value=None)
        epic_mgr.get_all_progress.return_value = []
        _seed_ports(world, epic_manager=epic_mgr)

        stats = await world.run_with_loops(["epic_monitor"], cycles=1)

        assert stats["epic_monitor"]["swept"] == 1
        assert stats["epic_monitor"]["checked"] == 1
        epic_mgr.sweep_completed_epics.assert_awaited_once()


# ---------------------------------------------------------------------------
# L13: Security Patch loop files issues from Dependabot alerts
# ---------------------------------------------------------------------------


class TestL13SecurityPatchLoop:
    """L13: security_patch_loop creates patch issues from dependabot alerts."""

    async def test_no_alerts_returns_zero_filed(self, tmp_path) -> None:
        """When Dependabot returns no alerts, filed == 0 and no issues created.

        FakeGitHub.get_dependabot_alerts returns [] by default, so no extra
        setup is required.
        """
        world = MockWorld(tmp_path)

        stats = await world.run_with_loops(["security_patch"], cycles=1)

        assert stats["security_patch"] is not None
        assert stats["security_patch"]["filed"] == 0
        assert stats["security_patch"]["total_alerts"] == 0

    async def test_fixable_high_severity_alert_files_issue(self, tmp_path) -> None:
        """A fixable, high-severity alert causes the loop to file a GitHub issue.

        We monkeypatch FakeGitHub.get_dependabot_alerts to return one alert
        matching the default severity threshold (high).  After one cycle the
        loop should have filed exactly one issue.
        """
        world = MockWorld(tmp_path)

        alert = {
            "number": 1,
            "security_vulnerability": {
                "package": {"name": "requests"},
                "severity": "high",
                "first_patched_version": {"identifier": "2.32.0"},
            },
            "security_advisory": {
                "summary": "SSRF vulnerability in requests",
            },
        }

        async def _fake_alerts(**_kw):
            return [alert]

        world.github.get_dependabot_alerts = _fake_alerts

        initial_issue_count = len(world.github._issues)

        stats = await world.run_with_loops(["security_patch"], cycles=1)

        assert stats["security_patch"]["filed"] == 1
        assert stats["security_patch"]["total_alerts"] == 1
        assert stats["security_patch"]["skipped_dedup"] == 0
        assert len(world.github._issues) == initial_issue_count + 1

    async def test_dry_run_skips_all_alerts(self, tmp_path) -> None:
        """When dry_run=True, the loop returns None without filing any issues.

        We instantiate SecurityPatchLoop directly with a dry-run config rather
        than going through run_with_loops, which cannot pass dry_run=True.
        """
        from base_background_loop import LoopDeps  # noqa: PLC0415
        from security_patch_loop import SecurityPatchLoop  # noqa: PLC0415
        from tests.helpers import make_bg_loop_deps  # noqa: PLC0415

        world = MockWorld(tmp_path)

        alert = {
            "number": 2,
            "security_vulnerability": {
                "package": {"name": "urllib3"},
                "severity": "critical",
                "first_patched_version": {"identifier": "2.2.0"},
            },
            "security_advisory": {"summary": "Critical vuln"},
        }

        async def _fake_alerts(**_kw):
            return [alert]

        world.github.get_dependabot_alerts = _fake_alerts

        bg = make_bg_loop_deps(tmp_path, dry_run=True)
        loop_deps = LoopDeps(
            event_bus=bg.bus,
            stop_event=bg.stop_event,
            status_cb=bg.status_cb,
            enabled_cb=bg.enabled_cb,
            sleep_fn=bg.sleep_fn,
        )

        loop = SecurityPatchLoop(
            config=bg.config,
            pr_manager=world.github,
            deps=loop_deps,
        )
        result = await loop._do_work()

        assert result is None
