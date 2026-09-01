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

from retro_findings import GateFinding
from retrospective import RetrospectiveCollector, RetrospectiveEntry
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

    async def test_empty_queue_publishes_every_counter_at_zero(self, tmp_path) -> None:
        """An idle tick reports the FULL counter vocabulary, all at zero.

        This asserted a three-key dict and so pinned the #11890 defect in
        place: the empty-queue exit dropped `findings_dropped` and
        `signals_seen`, and a reader of the published details cannot tell
        "counted zero" from "never counted" when a key is simply absent. The
        empty-queue path is the one an idle factory takes on nearly every tick.

        This is the layer that should have caught it. It did not, because it
        asserted the shape the code produced rather than the shape the loop
        declares — so the defect reached the sandbox suite, which is advisory
        on staging and required on main, and failed a promotion PR instead.

        Compared against `_RESULT_COUNTERS` rather than a literal, so a counter
        added later cannot pass here while being absent from what a reader of
        the running system actually gets.

        queue.load() is sync on RetrospectiveQueue so a plain MagicMock works.
        """
        from retrospective_loop import _RESULT_COUNTERS

        world = MockWorld(tmp_path)

        fake_queue = MagicMock()
        fake_queue.load.return_value = []
        _seed_ports(world, retrospective_queue=fake_queue)

        stats = await world.run_with_loops(["retrospective"], cycles=1)

        assert stats["retrospective"] == dict.fromkeys(_RESULT_COUNTERS, 0)
        for counter in ("findings_dropped", "signals_seen"):
            assert counter in stats["retrospective"], (
                f"{counter} absent from an idle tick published through the "
                "loop framework (#11890)"
            )
        fake_queue.load.assert_called_once()

    async def test_retro_patterns_item_processed_and_acknowledged(
        self, tmp_path
    ) -> None:
        """A RETRO_PATTERNS queue item causes _handle_retro_patterns to run.

        The retrospective collector's _load_recent and analyze_evidence are
        called.  The item id is acknowledged and processed count == 1.
        """
        from retrospective_queue import QueueItem, QueueKind  # noqa: PLC0415

        world = MockWorld(tmp_path)

        item = QueueItem(kind=QueueKind.RETRO_PATTERNS, issue_number=77, pr_number=88)

        fake_queue = MagicMock()
        fake_queue.load.return_value = [item]

        fake_retro = MagicMock()
        fake_retro._load_recent.return_value = []
        fake_retro.analyze_evidence = AsyncMock(
            return_value={
                "signals": 0,
                "filed": 0,
                "policy": 0,
                "dropped": 0,
                "errors": 0,
            }
        )

        _seed_ports(
            world,
            retrospective_queue=fake_queue,
            retrospective=fake_retro,
        )

        stats = await world.run_with_loops(["retrospective"], cycles=1)

        assert stats["retrospective"]["processed"] == 1
        fake_queue.acknowledge.assert_called_once_with([item.id])
        fake_retro._load_recent.assert_called_once()

    async def test_trace_evidence_becomes_one_class_issue(self, tmp_path) -> None:
        """A repeated tool error in the traces becomes ONE hydraflow-find issue.

        Drives the real RetrospectiveCollector against FakeGitHub with a real
        seeded trace tree; only the finder's model call is stubbed. Two ticks
        over the same evidence must fold, not file twice — the finding is
        pattern-shaped by construction, so siblings belong on one class issue.
        """
        import json  # noqa: PLC0415
        from unittest.mock import patch  # noqa: PLC0415

        from retrospective_queue import QueueItem, QueueKind  # noqa: PLC0415

        world = MockWorld(tmp_path)
        config = world._harness.config

        # A failed Bash call, twice, in two different issues' traces.
        for issue in (301, 302):
            run_dir = config.data_root / "traces" / str(issue) / "implement" / "run-1"
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "subprocess-0.json").write_text(
                json.dumps(
                    {
                        "issue_number": issue,
                        "phase": "implement",
                        "source": "implementer",
                        "run_id": 1,
                        "subprocess_idx": 0,
                        "backend": "claude",
                        "started_at": "2026-08-31T00:00:00+00:00",
                        "ended_at": "2026-08-31T00:01:00+00:00",
                        "success": False,
                        "crashed": False,
                        "error": None,
                        "tokens": {
                            "prompt_tokens": 1,
                            "completion_tokens": 1,
                            "cache_read_tokens": 0,
                            "cache_creation_tokens": 0,
                            "cache_hit_rate": 0.0,
                        },
                        "tools": {
                            "tool_counts": {"Bash": 1},
                            "tool_errors": {"Bash": 1},
                            "total_invocations": 1,
                        },
                        "tool_calls": [
                            {
                                "tool_name": "Bash",
                                "started_at": "2026-08-31T00:00:01+00:00",
                                "duration_ms": 10,
                                "input_summary": "make quality",
                                "succeeded": False,
                                "error": "make: *** [quality] Error 1",
                                "tool_use_id": "t1",
                            }
                        ],
                        "skill_results": [],
                        "turn_count": 1,
                        "inference_count": 1,
                    }
                )
            )

        entries = [
            RetrospectiveEntry(
                issue_number=n,
                pr_number=n + 100,
                timestamp="2026-08-31T00:00:00+00:00",
            )
            for n in (301, 302)
        ]

        fake_queue = MagicMock()
        fake_queue.load.return_value = [QueueItem(kind=QueueKind.RETRO_PATTERNS)]

        collector = RetrospectiveCollector(config, MagicMock(), world._github)
        collector._load_recent = MagicMock(return_value=entries)

        _seed_ports(world, retrospective_queue=fake_queue, retrospective=collector)

        def _propose(signals, **_kwargs):
            return [
                GateFinding(
                    kind="gate",
                    signal_id=signals[0].id,
                    title="Guard the recurring make quality failure",
                    guard_path="tests/architecture/test_quality_signal.py",
                    observed=f"{signals[0].count} occurrences",
                )
            ]

        with patch(
            "retro_finder.RetroFinder.find",
            new=AsyncMock(side_effect=_propose),
        ):
            await world.run_with_loops(["retrospective"], cycles=1)
            fake_queue.load.return_value = [QueueItem(kind=QueueKind.RETRO_PATTERNS)]
            await world.run_with_loops(["retrospective"], cycles=1)

        find_issues = [
            issue
            for issue in world._github._issues.values()
            if "hydraflow-find" in (issue.labels or [])
        ]
        assert len(find_issues) == 1, (
            "a pattern-shaped finding must fold onto one class issue, got "
            f"{[i.number for i in find_issues]}"
        )
        assert "make: *** [quality] Error 1" in (find_issues[0].body or "")

    async def test_unparseable_findings_reach_the_published_drop_counter(
        self, tmp_path
    ) -> None:
        """#11983: a tick that parsed nothing must not look like a clean tick.

        The unit tests assert `analyze_evidence` returns the right counts. This
        is the layer that says the number survives the trip to what a reader of
        the running system actually sees: `findings_dropped` is threaded from
        `counts["dropped"]` through `_do_work`, and before this change
        `unparseable` was computed in the collector and surfaced nowhere — so a
        confabulating tick published `findings_dropped: 0`, identical to a tick
        that found nothing wrong.
        """
        import json  # noqa: PLC0415
        from unittest.mock import patch  # noqa: PLC0415

        from retrospective_queue import QueueItem, QueueKind  # noqa: PLC0415

        world = MockWorld(tmp_path)
        config = world._harness.config

        run_dir = config.data_root / "traces" / "401" / "implement" / "run-1"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "subprocess-0.json").write_text(
            json.dumps(
                {
                    "issue_number": 401,
                    "phase": "implement",
                    "source": "implementer",
                    "run_id": 1,
                    "subprocess_idx": 0,
                    "backend": "claude",
                    "started_at": "2026-08-31T00:00:00+00:00",
                    "ended_at": "2026-08-31T00:01:00+00:00",
                    "success": False,
                    "crashed": False,
                    "error": None,
                    "tokens": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "cache_read_tokens": 0,
                        "cache_creation_tokens": 0,
                        "cache_hit_rate": 0.0,
                    },
                    "tools": {
                        "tool_counts": {"Bash": 1},
                        "tool_errors": {"Bash": 1},
                        "total_invocations": 1,
                    },
                    "tool_calls": [
                        {
                            "tool_name": "Bash",
                            "started_at": "2026-08-31T00:00:01+00:00",
                            "duration_ms": 10,
                            "input_summary": "make quality",
                            "succeeded": False,
                            "error": "make: *** [quality] Error 1",
                            "tool_use_id": "t1",
                        }
                    ],
                    "skill_results": [],
                    "turn_count": 1,
                    "inference_count": 1,
                }
            )
        )

        fake_queue = MagicMock()
        fake_queue.load.return_value = [QueueItem(kind=QueueKind.RETRO_PATTERNS)]

        collector = RetrospectiveCollector(config, MagicMock(), world._github)
        collector._load_recent = MagicMock(
            return_value=[
                RetrospectiveEntry(
                    issue_number=401,
                    pr_number=501,
                    timestamp="2026-08-31T00:00:00+00:00",
                )
            ]
        )
        _seed_ports(world, retrospective_queue=fake_queue, retrospective=collector)

        async def _all_items_unparseable(*_args, **_kwargs):
            # What the finder does when the model answers with something it
            # cannot turn into a Finding: it counts them and returns nothing.
            collector._finder.unparseable = 3
            return []

        with patch("retro_finder.RetroFinder.find", new=_all_items_unparseable):
            stats = await world.run_with_loops(["retrospective"], cycles=1)

        assert stats["retrospective"]["findings_dropped"] == 3, (
            "a tick whose every finding failed to parse published "
            f"findings_dropped={stats['retrospective']['findings_dropped']}, "
            "which a reader cannot tell from a clean tick"
        )

    async def test_stale_insight_dedup_across_ticks(self, tmp_path) -> None:
        """Issue #8988 / #9227: ``RetrospectiveLoop`` must not file duplicate
        ``[Review Insight] Persistent finding:`` issues on repeated stale ticks.

        Drives the real loop against FakeGitHub for three ticks of the same
        stale category and asserts the FakeGitHub issue count caps at 1 and
        that subsequent ticks skip silently (no comment spam — the factory is
        already working the routed find-queue issue).
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

        # Snapshot FakeGitHub routed-issue title count.
        insight_title = "[Review Insight] Persistent finding: Missing test coverage"

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
            # Tick 1: file the routed find-queue issue
            with patch("retrospective_loop._now_utc", return_value=base):
                await world.run_with_loops(["retrospective"], cycles=1)
            # Tick 2: skip (issue already open — factory is working it)
            with patch(
                "retrospective_loop._now_utc",
                return_value=base + timedelta(hours=2),
            ):
                await world.run_with_loops(["retrospective"], cycles=1)
            # Tick 3: skip
            with patch(
                "retrospective_loop._now_utc",
                return_value=base + timedelta(hours=4),
            ):
                await world.run_with_loops(["retrospective"], cycles=1)

        insight_issues = [
            issue
            for issue in world._github._issues.values()
            if issue.title == insight_title
        ]
        assert len(insight_issues) == 1, (
            f"expected 1 routed issue, got {len(insight_issues)}: "
            f"{[i.number for i in insight_issues]}"
        )
        # No comment spam: subsequent ticks skip the open issue silently
        # (the routed find-queue issue is already in the factory pipeline).
        assert len(insight_issues[0].comments) == 0, (
            f"expected 0 follow-up comments, got {len(insight_issues[0].comments)}"
        )


# ---------------------------------------------------------------------------
# L12: Epic Sweeper verifies done-epic children closed
# ---------------------------------------------------------------------------


class TestL12EpicSweeperLoop:
    """L12: epic_sweeper_loop sweeps open epics and auto-closes completed ones."""

    async def test_no_epics_returns_zero_counts(self, tmp_path) -> None:
        """When no open epics exist, the loop reports zero checked and swept.

        IssueFetcherPort.fetch_issues_by_labels is async so we need AsyncMock.
        """
        world = MockWorld(tmp_path)

        fake_fetcher = AsyncMock()
        fake_fetcher.fetch_issues_by_labels.return_value = []
        fake_state = MagicMock()
        fake_state.get_epic_state.return_value = None
        _seed_ports(
            world,
            issue_fetcher=fake_fetcher,
            epic_sweeper_state=fake_state,
        )

        stats = await world.run_with_loops(["epic_sweeper"], cycles=1)

        assert stats["epic_sweeper"] is not None
        assert stats["epic_sweeper"]["checked"] == 0
        assert stats["epic_sweeper"]["swept"] == 0
        assert stats["epic_sweeper"]["total_open_epics"] == 0

    async def test_epic_with_all_closed_sub_issues_is_swept(self, tmp_path) -> None:
        """An epic whose sub-issues are all closed gets auto-closed by the sweeper.

        The epic body contains a checkbox reference to issue #200.  Issue #200
        is closed.  After one cycle: epic closed, comment posted via FakeGitHub.
        """
        from models import GitHubIssue  # noqa: PLC0415

        world = MockWorld(tmp_path)

        # Epic issue with a checkbox ref to sub-issue #200
        epic_body = "## Tasks\n- [x] #200 — implement feature\n"
        epic = GitHubIssue(
            number=100,
            title="Epic: Implement feature",
            body=epic_body,
            state="open",
            labels=["hydraflow-epic"],
        )

        # Sub-issue that is already closed
        sub_issue = GitHubIssue(
            number=200,
            title="Implement feature",
            body="",
            state="closed",
            labels=[],
        )

        # Pre-seed FakeGitHub so close_issue / post_comment have a real target
        world.github.add_issue(100, epic.title, epic.body, labels=epic.labels)
        world.github.add_issue(200, sub_issue.title, sub_issue.body, labels=[])
        world.github.issue(200).state = "closed"

        fake_fetcher = AsyncMock()
        fake_fetcher.fetch_issues_by_labels.return_value = [epic]
        fake_fetcher.fetch_issue_by_number.return_value = sub_issue

        fake_state = MagicMock()
        fake_state.get_epic_state.return_value = None  # no formal EpicState children

        _seed_ports(
            world,
            issue_fetcher=fake_fetcher,
            epic_sweeper_state=fake_state,
        )

        stats = await world.run_with_loops(["epic_sweeper"], cycles=1)

        assert stats["epic_sweeper"]["swept"] == 1
        assert stats["epic_sweeper"]["checked"] == 1
        # FakeGitHub close_issue should have been called
        assert world.github.issue(100).state == "closed"


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
            state=MagicMock(),
            deps=loop_deps,
        )
        result = await loop._do_work()

        assert result is None
