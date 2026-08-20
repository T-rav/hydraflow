"""Tests for service_registry.py — ServiceRegistry and build_services factory."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from operator import attrgetter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig

from unittest.mock import patch

from events import EventBus, EventType, HydraFlowEvent
from service_registry import ServiceRegistry, WorkerRegistryCallbacks, build_services
from state import StateTracker
from workspace import WorkspaceManager


def _make_callbacks() -> WorkerRegistryCallbacks:
    """Create a stub WorkerRegistryCallbacks."""
    return WorkerRegistryCallbacks(
        update_status=lambda *args, **kwargs: None,
        is_enabled=lambda name: True,
        get_interval=lambda name: 60,
        get_watchdog_timeout=lambda name: 7200,
    )


class TestBuildServices:
    def test_returns_service_registry(self, config: HydraFlowConfig) -> None:
        """build_services should return a ServiceRegistry instance."""
        bus = EventBus()
        state = StateTracker(config.state_file)
        stop_event = asyncio.Event()
        callbacks = _make_callbacks()

        registry = build_services(config, bus, state, stop_event, callbacks)

        assert isinstance(registry, ServiceRegistry)
        assert isinstance(registry.workspaces, WorkspaceManager)

    def test_all_fields_are_set(self, config: HydraFlowConfig) -> None:
        """All ServiceRegistry fields should be non-None."""
        bus = EventBus()
        state = StateTracker(config.state_file)
        stop_event = asyncio.Event()
        callbacks = _make_callbacks()

        registry = build_services(config, bus, state, stop_event, callbacks)

        # hindsight is None when not configured — that's expected
        # live_corpus_replay_loop is None when shadow_corpus_enabled is off
        # (default) — see service_registry.py and #8786 Phase 2.
        optional_fields = {"hindsight", "hindsight_wal", "live_corpus_replay_loop"}
        for field_name in ServiceRegistry.__dataclass_fields__:
            if field_name in optional_fields:
                continue
            assert getattr(registry, field_name) is not None, f"{field_name} is None"

    def test_pipeline_label_listener_is_wired_to_the_store(
        self, config: HydraFlowConfig
    ) -> None:
        """#9842: label swaps must reach the in-memory pipeline immediately.

        The wiring is hasattr-gated (sandbox fakes read labels live and skip
        it), so a rename on either side would silently sever the event-driven
        card path and quietly reintroduce the 5-minute poll lag — pin it.
        """
        bus = EventBus()
        state = StateTracker(config.state_file)
        stop_event = asyncio.Event()
        callbacks = _make_callbacks()

        registry = build_services(config, bus, state, stop_event, callbacks)

        listener = registry.prs._pipeline_label_listener
        assert listener is not None, "pipeline label listener not wired"
        assert listener.__func__ is type(registry.store).apply_label_transition
        assert listener.__self__ is registry.store

    def test_agents_runner_is_shared(self, config: HydraFlowConfig) -> None:
        """Agents, planners, reviewers, and HITL runner should share the subprocess runner."""
        bus = EventBus()
        state = StateTracker(config.state_file)
        stop_event = asyncio.Event()
        callbacks = _make_callbacks()

        registry = build_services(config, bus, state, stop_event, callbacks)

        assert registry.agents._runner is registry.subprocess_runner
        assert registry.planners._runner is registry.subprocess_runner
        assert registry.reviewers._runner is registry.subprocess_runner
        # Verify the runner type matches the expected execution mode
        from docker_runner import get_docker_runner

        runner = get_docker_runner(config)
        assert type(registry.subprocess_runner) is type(runner)

    def test_store_uses_fetcher(self, config: HydraFlowConfig) -> None:
        """IssueStore should be initialized with the fetcher."""
        bus = EventBus()
        state = StateTracker(config.state_file)
        stop_event = asyncio.Event()
        callbacks = _make_callbacks()

        registry = build_services(config, bus, state, stop_event, callbacks)

        from issue_fetcher import GitHubTaskFetcher

        assert isinstance(registry.store._fetcher, GitHubTaskFetcher)
        assert registry.store._fetcher._fetcher is registry.fetcher

    def test_phase_store_is_raw_store_when_caching_disabled(
        self, config: HydraFlowConfig
    ) -> None:
        """When caching_issue_store_enabled is False, phase_store points at
        the raw IssueStore — not a wrapper."""
        # caching_issue_store_enabled defaults False (opt-in after cache
        # coverage); set it explicitly to pin the raw-store path.
        config.caching_issue_store_enabled = False  # type: ignore[misc]
        bus = EventBus()
        state = StateTracker(config.state_file)
        stop_event = asyncio.Event()
        callbacks = _make_callbacks()

        registry = build_services(config, bus, state, stop_event, callbacks)

        assert registry.phase_store is registry.store

    def test_phase_store_is_caching_decorator_when_both_flags_enabled(
        self, config: HydraFlowConfig
    ) -> None:
        """With both flags True, phase_store wraps store in
        CachingIssueStore. Catches a regression where the conditional
        always returns the raw store."""
        from caching_issue_store import CachingIssueStore

        config.issue_cache_enabled = True  # type: ignore[misc]
        config.caching_issue_store_enabled = True  # type: ignore[misc]

        bus = EventBus()
        state = StateTracker(config.state_file)
        stop_event = asyncio.Event()
        callbacks = _make_callbacks()

        registry = build_services(config, bus, state, stop_event, callbacks)

        assert isinstance(registry.phase_store, CachingIssueStore)
        # The decorator wraps the same underlying store.
        assert registry.phase_store._inner is registry.store

    def test_phase_store_raw_when_only_cache_flag_enabled(
        self, config: HydraFlowConfig
    ) -> None:
        """If issue_cache_enabled=True but caching_issue_store_enabled
        is False, phase_store stays raw — the cache flag alone is
        not enough to opt into the decorator."""
        config.issue_cache_enabled = True  # type: ignore[misc]
        config.caching_issue_store_enabled = False  # type: ignore[misc]

        bus = EventBus()
        state = StateTracker(config.state_file)
        stop_event = asyncio.Event()
        callbacks = _make_callbacks()

        registry = build_services(config, bus, state, stop_event, callbacks)

        assert registry.phase_store is registry.store

    def test_uses_get_docker_runner(self, config: HydraFlowConfig) -> None:
        """build_services should use get_docker_runner to create the subprocess runner."""
        bus = EventBus()
        state = StateTracker(config.state_file)
        stop_event = asyncio.Event()
        callbacks = _make_callbacks()

        with patch("service_registry.get_docker_runner") as mock_factory:
            from execution import get_default_runner

            mock_factory.return_value = get_default_runner()
            build_services(config, bus, state, stop_event, callbacks)

        mock_factory.assert_called_once()
        call_args = mock_factory.call_args
        assert call_args[0][0] is config  # positional: config
        assert "credentials" in call_args[1]  # keyword: credentials


class TestServiceRegistryWiring:
    """Integration checks for ServiceRegistry wiring and shared dependencies."""

    _BUS_TARGETS = [
        ("triage phase", attrgetter("triager._bus")),
        ("plan phase", attrgetter("planner_phase._bus")),
        ("review phase", attrgetter("reviewer._bus")),
        ("hitl phase", attrgetter("hitl_phase._bus")),
        ("agents runner", attrgetter("agents._bus")),
        ("planners runner", attrgetter("planners._bus")),
        ("reviewers runner", attrgetter("reviewers._bus")),
        ("hitl runner", attrgetter("hitl_runner._bus")),
        ("triage runner", attrgetter("triage._bus")),
        ("pr manager", attrgetter("prs._bus")),
        ("issue store", attrgetter("store._bus")),
        # Note: ImplementPhase is intentionally absent — it does not accept event_bus
        # in its constructor; events flow through its sub-runners (agents._bus, etc.).
    ]
    _STATE_TARGETS = [
        ("triage phase", attrgetter("triager._state")),
        ("plan phase", attrgetter("planner_phase._state")),
        ("implement phase", attrgetter("implementer._state")),
        ("review phase", attrgetter("reviewer._state")),
        ("hitl phase", attrgetter("hitl_phase._state")),
    ]
    _STOP_EVENT_TARGETS = [
        ("triage phase", attrgetter("triager._stop_event")),
        ("plan phase", attrgetter("planner_phase._stop_event")),
        ("implement phase", attrgetter("implementer._stop_event")),
        ("review phase", attrgetter("reviewer._stop_event")),
        ("hitl phase", attrgetter("hitl_phase._stop_event")),
    ]
    # Explicit list of phase objects (not runners) that can publish on the shared bus.
    # Kept separate from _BUS_TARGETS to avoid a fragile index-based slice.
    _PHASE_BUS_PUBLISHERS = [
        ("triage phase", attrgetter("triager._bus")),
        ("plan phase", attrgetter("planner_phase._bus")),
        ("review phase", attrgetter("reviewer._bus")),
        ("hitl phase", attrgetter("hitl_phase._bus")),
    ]

    @staticmethod
    def _build_registry(
        config: HydraFlowConfig,
    ) -> tuple[ServiceRegistry, EventBus, StateTracker, asyncio.Event]:
        bus = EventBus()
        state = StateTracker(config.state_file)
        stop_event = asyncio.Event()
        callbacks = _make_callbacks()
        registry = build_services(config, bus, state, stop_event, callbacks)
        return registry, bus, state, stop_event

    def test_phases_share_event_bus(self, config: HydraFlowConfig) -> None:
        registry, bus, _, _ = self._build_registry(config)

        for label, getter in self._BUS_TARGETS:
            assert getter(registry) is bus, (
                f"{label} is not using the shared EventBus instance"
            )

    def test_phases_share_state_tracker(self, config: HydraFlowConfig) -> None:
        registry, _, state, _ = self._build_registry(config)

        for label, getter in self._STATE_TARGETS:
            assert getter(registry) is state, f"{label} is not sharing StateTracker"

    def test_staging_promotion_loop_receives_state(
        self, config: HydraFlowConfig
    ) -> None:
        """StagingPromotionLoop must receive the shared StateTracker so it can
        persist last_green_rc_sha / last_rc_red_sha on promotion outcomes
        (bisect plan Task 5)."""
        registry, _, state, _ = self._build_registry(config)

        assert registry.staging_promotion_loop._state is state, (
            "staging_promotion_loop is not wired to the shared StateTracker; "
            "promotion/ci_failed paths cannot record RC attribution"
        )

    def test_phases_share_stop_event(self, config: HydraFlowConfig) -> None:
        registry, _, _, stop_event = self._build_registry(config)

        for label, getter in self._STOP_EVENT_TARGETS:
            assert getter(registry) is stop_event, f"{label} not wired to stop_event"

    async def test_event_bus_propagation(self, config: HydraFlowConfig) -> None:
        registry, bus, _, _ = self._build_registry(config)
        queue = bus.subscribe()

        try:
            for label, getter in self._PHASE_BUS_PUBLISHERS:
                event = HydraFlowEvent(
                    type=EventType.SYSTEM_ALERT, data={"source": label}
                )
                await getter(registry).publish(event)

                received = await asyncio.wait_for(queue.get(), timeout=1)
                assert received is event, f"{label} did not publish via shared EventBus"
        finally:
            bus.unsubscribe(queue)


class TestWorkerRegistryCallbacks:
    def test_has_four_fields_only(self) -> None:
        """WorkerRegistryCallbacks should expose exactly 4 focused callbacks."""
        fields = set(WorkerRegistryCallbacks.__dataclass_fields__)
        assert fields == {
            "update_status",
            "is_enabled",
            "get_interval",
            "get_watchdog_timeout",
        }

    def test_is_frozen(self) -> None:
        """WorkerRegistryCallbacks should be immutable."""
        import pytest

        cb = WorkerRegistryCallbacks(
            update_status=lambda *a, **kw: None,
            is_enabled=lambda _: True,
            get_interval=lambda _: 60,
            get_watchdog_timeout=lambda _: 7200,
        )
        with pytest.raises(AttributeError):
            cb.update_status = lambda *a, **kw: None  # type: ignore[misc]

    def test_build_services_accepts_active_issues_cb(
        self, config: HydraFlowConfig
    ) -> None:
        """build_services should accept active_issues_cb as a separate parameter."""
        bus = EventBus()
        state = StateTracker(config.state_file)
        stop_event = asyncio.Event()
        callbacks = _make_callbacks()
        called = False

        def track_active() -> None:
            nonlocal called
            called = True

        registry = build_services(
            config, bus, state, stop_event, callbacks, active_issues_cb=track_active
        )
        # Verify all three consumers received the callback
        assert registry.hitl_phase._active_issues_cb is track_active
        assert registry.implementer._active_issues_cb is track_active
        assert registry.reviewer._active_issues_cb is track_active

    def test_build_services_without_active_issues_cb(
        self, config: HydraFlowConfig
    ) -> None:
        """build_services should work when active_issues_cb is None (default)."""
        bus = EventBus()
        state = StateTracker(config.state_file)
        stop_event = asyncio.Event()
        callbacks = _make_callbacks()

        registry = build_services(config, bus, state, stop_event, callbacks)
        assert isinstance(registry, ServiceRegistry)


class TestHumanSteeringLoopActiveIssuesCb:
    """The steering sensor must widen to the full-pipeline active set.

    ``human_steering_loop.active_issues_cb`` used to read
    ``state.get_active_issue_numbers`` — the narrower implement/review/HITL
    set the orchestrator maintains via ``_sync_active_issue_numbers``. A
    ``/pause`` posted while an issue sits in triage/discover/shape/plan was
    never sensed. The cb must instead mirror the actuator's own
    enumeration: ``store.get_active_issues()`` (every active phase).
    """

    def test_cb_returns_stores_full_active_issue_numbers(
        self, config: HydraFlowConfig
    ) -> None:
        bus = EventBus()
        state = StateTracker(config.state_file)
        stop_event = asyncio.Event()
        callbacks = _make_callbacks()

        registry = build_services(config, bus, state, stop_event, callbacks)

        # Simulate issues active in phases the old, narrower cb could not
        # see (shape) alongside one it could (review).
        registry.store.mark_active(7, "shape")
        registry.store.mark_active(9, "review")

        assert sorted(registry.human_steering_loop._active_issues_cb()) == [7, 9]

    def test_cb_reflects_store_not_state_active_issue_numbers(
        self, config: HydraFlowConfig
    ) -> None:
        """Regression guard: the cb must read the store, not the narrower
        state-tracker set — even when the two disagree."""
        bus = EventBus()
        state = StateTracker(config.state_file)
        stop_event = asyncio.Event()
        callbacks = _make_callbacks()

        registry = build_services(config, bus, state, stop_event, callbacks)

        # state's narrower set has nothing; the store has a shape-phase issue
        # the old wiring would have missed entirely.
        state.set_active_issue_numbers([])
        registry.store.mark_active(7, "shape")

        assert registry.human_steering_loop._active_issues_cb() == [7]


class TestAdversarialPipelineWiring:
    """Factory wiring for the earlier-adversarial pipeline (ADR-0064).

    ADR-0107 retired the standalone Discover/Shape phases, so the adversarial
    council/surfacer wiring now lives only on the plan phase. The discover/shape
    engines are the ``DiscoverRunner`` / ``ShapeRunner`` the planner invokes on
    demand; the factory constructs them and binds their escalation deps.
    """

    @staticmethod
    def _build(config: HydraFlowConfig) -> ServiceRegistry:
        bus = EventBus()
        state = StateTracker(config.state_file)
        stop_event = asyncio.Event()
        callbacks = _make_callbacks()
        return build_services(config, bus, state, stop_event, callbacks)

    def test_discover_shape_runners_wired_with_escalation_deps(
        self, config: HydraFlowConfig
    ) -> None:
        """ADR-0107: the factory builds the discover/shape engines, binds their
        escalation deps, and hands them to the planner as on-demand helpers."""
        from discover_runner import DiscoverRunner
        from shape_runner import ShapeRunner

        registry = self._build(config)

        assert isinstance(registry.discover_runner, DiscoverRunner)
        assert isinstance(registry.shape_runner, ShapeRunner)
        # bind_escalation_deps ran at wire-up: prs + dedup are set.
        assert registry.discover_runner._prs is not None
        assert registry.discover_runner._dedup is not None
        assert registry.shape_runner._prs is not None
        assert registry.shape_runner._dedup is not None
        # The planner borrows the SAME engine instances for its decision gate.
        assert registry.planner_phase._discover_runner is registry.discover_runner
        assert registry.planner_phase._shape_runner is registry.shape_runner

    def test_plan_phase_adversarial_agents_attached(
        self, config: HydraFlowConfig
    ) -> None:
        """All four PlanPhase adversarial slots get SubprocessAgentRunner adapters."""
        from adversarial_agent_runner import SubprocessAgentRunner

        registry = self._build(config)
        plan_phase = registry.planner_phase

        assert isinstance(plan_phase._surfacer_agent, SubprocessAgentRunner)
        assert plan_phase._council_agents is not None
        assert set(plan_phase._council_agents.keys()) == {
            "builder",
            "tester",
            "risk_skeptic",
        }
        for voter in plan_phase._council_agents.values():
            assert isinstance(voter, SubprocessAgentRunner)
        assert isinstance(plan_phase._spec_ac_agent, SubprocessAgentRunner)
        assert isinstance(plan_phase._spec_judge_agent, SubprocessAgentRunner)
        assert plan_phase._surfacer_agent.config is config
        assert plan_phase._surfacer_agent.tool == config.planner_tool
        assert plan_phase._surfacer_agent.model == config.planner_model
        assert plan_phase._surfacer_agent.provider == config.planner_provider


class TestAutoTightenGhClosures:
    """Unit tests for the two gh-shelling closures the AutoTighten factory
    wiring builds: ``make_gh_coverage_fetch`` and ``make_gh_merged_pr_lister``.

    Both take an injectable ``runner`` (mirrors ``auto_pr._run_gh``'s shape)
    so these tests never shell out to the real ``gh`` CLI.
    """

    def test_coverage_fetch_picks_latest_successful_run_and_downloads_it(
        self, config: HydraFlowConfig, tmp_path: Path
    ) -> None:
        from service_registry import make_gh_coverage_fetch

        runs_json = (
            '[{"databaseId": 42, "headSha": "deadbeef", "status": "completed", '
            '"conclusion": "success"}, '
            '{"databaseId": 41, "headSha": "old", "status": "completed", '
            '"conclusion": "failure"}]'
        )
        calls = []

        def fake_runner(cmd, *, cwd):
            calls.append(cmd)
            if cmd[:3] == ["gh", "run", "list"]:
                return subprocess.CompletedProcess(cmd, 0, stdout=runs_json, stderr="")
            if cmd[:3] == ["gh", "run", "download"]:
                # Simulate `gh run download` writing coverage.json into --dir.
                download_dir = Path(cmd[cmd.index("--dir") + 1])
                (download_dir / "coverage.json").write_text(
                    '{"totals": {"percent_covered": 91.5}}'
                )
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            raise AssertionError(f"unexpected gh command: {cmd}")

        fetch = make_gh_coverage_fetch(config, runner=fake_runner)
        result = fetch()

        assert result is not None
        run_id, head_sha, cov_text = result
        assert run_id == "42"
        assert head_sha == "deadbeef"
        assert json.loads(cov_text)["totals"]["percent_covered"] == 91.5
        # The download must target the latest *successful* run, not run 41.
        download_cmd = next(c for c in calls if c[:3] == ["gh", "run", "download"])
        assert "42" in download_cmd

    def test_coverage_fetch_returns_none_when_no_successful_runs(
        self, config: HydraFlowConfig
    ) -> None:
        from service_registry import make_gh_coverage_fetch

        def fake_runner(cmd, *, cwd):
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=(
                    '[{"databaseId": 1, "headSha": "x", '
                    '"status": "completed", "conclusion": "failure"}]'
                ),
                stderr="",
            )

        fetch = make_gh_coverage_fetch(config, runner=fake_runner)
        assert fetch() is None

    def test_coverage_fetch_returns_none_on_nonzero_exit(
        self, config: HydraFlowConfig
    ) -> None:
        from service_registry import make_gh_coverage_fetch

        def fake_runner(cmd, *, cwd):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

        fetch = make_gh_coverage_fetch(config, runner=fake_runner)
        assert fetch() is None

    def test_merged_pr_lister_maps_file_objects_to_path_strings(
        self, config: HydraFlowConfig
    ) -> None:
        """The load-bearing mapping: gh returns files as [{"path": ...}],
        AttributionResolver expects a flat list[str] of paths."""
        from service_registry import make_gh_merged_pr_lister

        prs_json = (
            '[{"number": 7, "files": [{"path": "src/foo.py"}, '
            '{"path": "tests/test_foo.py"}], "mergedAt": "2026-07-01T00:00:00Z"}]'
        )

        def fake_runner(cmd, *, cwd):
            return subprocess.CompletedProcess(cmd, 0, stdout=prs_json, stderr="")

        lister = make_gh_merged_pr_lister(config, runner=fake_runner)
        result = lister("2026-06-01T00:00:00Z")

        assert result == [
            {
                "number": 7,
                "files": ["src/foo.py", "tests/test_foo.py"],
                "merged_at": "2026-07-01T00:00:00Z",
            }
        ]

    def test_merged_pr_lister_passes_since_into_search_query(
        self, config: HydraFlowConfig
    ) -> None:
        from service_registry import make_gh_merged_pr_lister

        captured = {}

        def fake_runner(cmd, *, cwd):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")

        lister = make_gh_merged_pr_lister(config, runner=fake_runner)
        lister("2026-06-15T00:00:00Z")

        search_arg = captured["cmd"][captured["cmd"].index("--search") + 1]
        assert "2026-06-15T00:00:00Z" in search_arg

    def test_merged_pr_lister_returns_empty_on_nonzero_exit(
        self, config: HydraFlowConfig
    ) -> None:
        from service_registry import make_gh_merged_pr_lister

        def fake_runner(cmd, *, cwd):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

        lister = make_gh_merged_pr_lister(config, runner=fake_runner)
        assert lister("2026-06-01T00:00:00Z") == []

    def test_open_pr_exists_true_and_probes_the_head_branch(
        self, config: HydraFlowConfig
    ) -> None:
        from service_registry import make_gh_open_pr_exists

        captured = {}

        def fake_runner(cmd, *, cwd):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(
                cmd, 0, stdout='[{"number": 42}]', stderr=""
            )

        probe = make_gh_open_pr_exists(config, runner=fake_runner)
        assert probe("auto-tighten/coverage-77.0") is True
        assert "--head" in captured["cmd"]
        assert "auto-tighten/coverage-77.0" in captured["cmd"]

    def test_open_pr_exists_false_when_none_listed(
        self, config: HydraFlowConfig
    ) -> None:
        from service_registry import make_gh_open_pr_exists

        def fake_runner(cmd, *, cwd):
            return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")

        probe = make_gh_open_pr_exists(config, runner=fake_runner)
        assert probe("auto-tighten/coverage-77.0") is False

    def test_open_pr_exists_fails_open_on_nonzero_exit(
        self, config: HydraFlowConfig
    ) -> None:
        # A gh error must not block a legitimate tightening: fail open (False).
        from service_registry import make_gh_open_pr_exists

        def fake_runner(cmd, *, cwd):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

        probe = make_gh_open_pr_exists(config, runner=fake_runner)
        assert probe("auto-tighten/coverage-77.0") is False


class TestFitnessIssueFetcher:
    """``_make_fitness_issue_fetcher`` reads via list_all_issues/list_all_prs (#11418)."""

    async def test_maps_issues_and_prs_to_issue_records(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from service_registry import _make_fitness_issue_fetcher

        prs = MagicMock()
        prs.list_all_issues = AsyncMock(
            return_value=[
                {
                    "number": 1,
                    "state": "OPEN",
                    "labels": [{"name": "bug"}],
                    "createdAt": "2026-01-01T00:00:00Z",
                    "closedAt": None,
                }
            ]
        )
        prs.list_all_prs = AsyncMock(
            return_value=[
                {
                    "number": 2,
                    "state": "MERGED",
                    "labels": [],
                    "createdAt": "2026-01-02T00:00:00Z",
                    "closedAt": "2026-01-03T00:00:00Z",
                    "mergedAt": "2026-01-03T00:00:00Z",
                }
            ]
        )

        fetcher = _make_fitness_issue_fetcher(prs)
        records = await fetcher()

        prs.list_all_issues.assert_awaited_once_with(state="all", limit=1000)
        prs.list_all_prs.assert_awaited_once_with(state="all", limit=1000)
        assert len(records) == 2
        issue_record = next(r for r in records if r.number == 1)
        assert issue_record.is_pr is False
        assert issue_record.labels == ["bug"]
        assert issue_record.state == "open"
        assert issue_record.merged is False
        pr_record = next(r for r in records if r.number == 2)
        assert pr_record.is_pr is True
        assert pr_record.state == "merged"
        assert pr_record.merged is True

    async def test_empty_reads_produce_no_records(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from service_registry import _make_fitness_issue_fetcher

        prs = MagicMock()
        prs.list_all_issues = AsyncMock(return_value=[])
        prs.list_all_prs = AsyncMock(return_value=[])

        fetcher = _make_fitness_issue_fetcher(prs)
        assert await fetcher() == []
