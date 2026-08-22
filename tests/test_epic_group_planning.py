"""Tests for epic group planning — grouping, gap review, and iteration capping."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from events import EventBus
from issue_store import STAGE_READY, IssueStore
from mockworld.fakes import FakeGitHub
from mockworld.fakes.fake_issue_store import FakeIssueStore
from models import EpicGapReview
from plan_phase import PlanPhase
from state import StateTracker
from tests.conftest import PlanResultFactory, TaskFactory

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from models import Task


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_epic_child(
    *,
    id: int,
    title: str = "Child issue",
    epic_number: int | None = None,
    body: str = "",
) -> Task:
    """Create a Task that looks like an epic child."""
    tags = ["hydraflow-epic-child", "hydraflow-plan"]
    if epic_number and not body:
        body = f"Parent Epic #{epic_number}\n\nDo something."
    meta: dict = {}
    if epic_number:
        meta["epic_number"] = epic_number
    return TaskFactory.create(id=id, title=title, body=body, tags=tags, metadata=meta)


def _make_phase(
    config: HydraFlowConfig,
) -> tuple[PlanPhase, AsyncMock, AsyncMock, IssueStore, asyncio.Event]:
    """Build a PlanPhase with mock dependencies.

    Returns (phase, planners_mock, prs_mock, store, stop_event).
    """
    state = StateTracker(config.state_file)
    bus = EventBus()
    fetcher = AsyncMock()
    store = IssueStore(config, fetcher, bus)
    planners = AsyncMock()
    prs = AsyncMock()
    prs.post_comment = AsyncMock()
    prs.remove_label = AsyncMock()
    prs.add_labels = AsyncMock()
    prs.swap_pipeline_labels = AsyncMock()
    prs.transition = AsyncMock()
    prs.get_issue_state = AsyncMock(return_value="OPEN")
    prs.get_issue_labels = AsyncMock(return_value=["hydraflow-plan"])
    prs.create_task = AsyncMock(return_value=99)
    prs.close_task = AsyncMock()
    stop_event = asyncio.Event()
    phase = PlanPhase(config, state, store, planners, prs, bus, stop_event)
    return phase, planners, prs, store, stop_event


# ---------------------------------------------------------------------------
# _group_by_epic tests
# ---------------------------------------------------------------------------


class TestGroupByEpic:
    def test_separates_children_from_standalone(self, config: HydraFlowConfig) -> None:
        phase, *_ = _make_phase(config)
        standalone = TaskFactory.create(id=1, tags=["hydraflow-plan"])
        child_a = _make_epic_child(id=2, epic_number=100)
        child_b = _make_epic_child(id=3, epic_number=100)

        epic_groups, standalones = phase._group_by_epic([standalone, child_a, child_b])

        assert standalones == [standalone]
        assert 100 in epic_groups
        assert [c.id for c in epic_groups[100]] == [2, 3]

    def test_resolves_parent_from_body(self, config: HydraFlowConfig) -> None:
        phase, *_ = _make_phase(config)
        child = TaskFactory.create(
            id=5,
            tags=["hydraflow-epic-child"],
            body="Parent Epic #200\n\nDetails here.",
        )

        epic_groups, standalones = phase._group_by_epic([child])

        assert standalones == []
        assert 200 in epic_groups
        assert epic_groups[200][0].id == 5

    def test_standalone_on_missing_parent(self, config: HydraFlowConfig) -> None:
        """Epic child with no resolvable parent goes to standalone."""
        phase, *_ = _make_phase(config)
        orphan = TaskFactory.create(
            id=7,
            tags=["hydraflow-epic-child"],
            body="No parent reference here.",
        )

        epic_groups, standalones = phase._group_by_epic([orphan])

        assert standalones == [orphan]
        assert epic_groups == {}

    def test_multiple_epics_grouped_separately(self, config: HydraFlowConfig) -> None:
        phase, *_ = _make_phase(config)
        child_a = _make_epic_child(id=10, epic_number=100)
        child_b = _make_epic_child(id=11, epic_number=200)
        child_c = _make_epic_child(id=12, epic_number=100)

        epic_groups, standalones = phase._group_by_epic([child_a, child_b, child_c])

        assert standalones == []
        assert sorted(epic_groups.keys()) == [100, 200]
        assert [c.id for c in epic_groups[100]] == [10, 12]
        assert [c.id for c in epic_groups[200]] == [11]


# ---------------------------------------------------------------------------
# _parse_gap_review tests
# ---------------------------------------------------------------------------


class TestParseGapReview:
    def test_full_parse(self) -> None:
        transcript = (
            "GAP_REVIEW_START\n"
            "## Findings\n"
            "Issue #10 and #11 both modify config.py.\n\n"
            "## Re-plan Required\n"
            "#10\n#11\n\n"
            "## Guidance\n"
            "Coordinate config.py changes to avoid conflicts.\n"
            "GAP_REVIEW_END\n"
        )
        review = PlanPhase._parse_gap_review(transcript, epic_number=50)

        assert review.epic_number == 50
        assert "config.py" in review.findings
        assert review.replan_issues == [10, 11]
        assert "Coordinate" in review.guidance

    def test_duplicate_replan_numbers_are_deduplicated_in_order(self) -> None:
        transcript = (
            "GAP_REVIEW_START\n"
            "## Findings\nRepeated child.\n\n"
            "## Re-plan Required\n#10\n#10, then #11 and #10 again\n\n"
            "## Guidance\nReconcile once per child.\n"
            "GAP_REVIEW_END\n"
        )

        review = PlanPhase._parse_gap_review(transcript, epic_number=50)

        assert review.replan_issues == [10, 11]

    def test_no_replan_needed(self) -> None:
        transcript = (
            "GAP_REVIEW_START\n"
            "## Findings\n"
            "Plans are coherent.\n\n"
            "## Re-plan Required\n"
            "None\n\n"
            "## Guidance\n"
            "No changes needed.\n"
            "GAP_REVIEW_END\n"
        )
        review = PlanPhase._parse_gap_review(transcript, epic_number=50)

        assert review.replan_issues == []
        assert review.findings == "Plans are coherent."

    def test_no_markers(self) -> None:
        review = PlanPhase._parse_gap_review("no markers here", epic_number=1)
        assert review.epic_number == 1
        assert review.findings == ""
        assert review.replan_issues == []


# ---------------------------------------------------------------------------
# _plan_epic_group tests
# ---------------------------------------------------------------------------


class TestPlanEpicGroup:
    @pytest.mark.asyncio
    async def test_runs_gap_review(self, config: HydraFlowConfig) -> None:
        """When >=2 children succeed, gap review should run."""
        phase, planners, prs, store, _stop = _make_phase(config)
        children = [
            _make_epic_child(id=10, title="Child A", epic_number=100),
            _make_epic_child(id=11, title="Child B", epic_number=100),
        ]

        # Both plans succeed
        planners.plan = AsyncMock(
            side_effect=[
                PlanResultFactory.create(
                    issue_number=10, success=True, plan="Plan A", use_defaults=True
                ),
                PlanResultFactory.create(
                    issue_number=11, success=True, plan="Plan B", use_defaults=True
                ),
            ]
        )

        # Gap review returns coherent (no replan needed)
        planners.run_gap_review = AsyncMock(
            return_value=(
                "GAP_REVIEW_START\n"
                "## Findings\nAll good.\n\n"
                "## Re-plan Required\nNone\n\n"
                "## Guidance\nNone needed.\n"
                "GAP_REVIEW_END\n"
            )
        )

        semaphore = asyncio.Semaphore(2)
        results = await phase._plan_epic_group(100, children, semaphore)

        assert len(results) == 2
        planners.run_gap_review.assert_awaited_once()
        # No comment on epic since no re-plan needed
        gap_review_comments = [
            c for c in prs.post_comment.call_args_list if c.args[0] == 100
        ]
        assert len(gap_review_comments) == 0

    @pytest.mark.asyncio
    async def test_gap_review_receives_child_issue_labels(
        self, config: HydraFlowConfig
    ) -> None:
        """run_gap_review gets the union of the reviewed children's labels.

        The gap-review prompt embeds every successful child's plan, so the
        CH-6 prompt gate must see a ``data-class:<class>`` elevation label
        carried by ANY of those children (#9734 review finding 1).
        """
        phase, planners, prs, store, _stop = _make_phase(config)
        children = [
            _make_epic_child(id=10, title="Child A", epic_number=100),
            _make_epic_child(id=11, title="Child B", epic_number=100),
        ]
        children[0].tags.append("data-class:regulated-phi")

        planners.plan = AsyncMock(
            side_effect=[
                PlanResultFactory.create(
                    issue_number=10, success=True, plan="Plan A", use_defaults=True
                ),
                PlanResultFactory.create(
                    issue_number=11, success=True, plan="Plan B", use_defaults=True
                ),
            ]
        )
        planners.run_gap_review = AsyncMock(
            return_value=(
                "GAP_REVIEW_START\n"
                "## Findings\nAll good.\n\n"
                "## Re-plan Required\nNone\n\n"
                "## Guidance\nNone needed.\n"
                "GAP_REVIEW_END\n"
            )
        )

        semaphore = asyncio.Semaphore(2)
        await phase._plan_epic_group(100, children, semaphore)

        labels = planners.run_gap_review.await_args.kwargs["issue_labels"]
        assert "data-class:regulated-phi" in labels

    @pytest.mark.asyncio
    async def test_replans_flagged_issues(self, config: HydraFlowConfig) -> None:
        """Gap review flags an issue for re-planning."""
        phase, planners, prs, store, _stop = _make_phase(config)
        children = [
            _make_epic_child(id=10, title="Child A", epic_number=100),
            _make_epic_child(id=11, title="Child B", epic_number=100),
        ]

        call_count = 0

        async def _plan_side_effect(task, worker_id=0, **kwargs):
            nonlocal call_count
            call_count += 1
            return PlanResultFactory.create(
                issue_number=task.id,
                success=True,
                plan=f"Plan for #{task.id} v{call_count}",
                use_defaults=True,
            )

        planners.plan = AsyncMock(side_effect=_plan_side_effect)

        # First gap review: flag #10 for replan; second: all good
        review_calls = 0

        async def _gap_review(*_args, **_kwargs) -> str:
            nonlocal review_calls
            review_calls += 1
            if review_calls == 1:
                # A genuine replan candidate must still be locally queued in
                # PLAN after the provider's awaited review.
                store.enqueue_transition(children[0], "plan")
                return (
                    "GAP_REVIEW_START\n"
                    "## Findings\nConflict in #10.\n\n"
                    "## Re-plan Required\n#10\n\n"
                    "## Guidance\nFix the conflict.\n"
                    "GAP_REVIEW_END\n"
                )
            return (
                "GAP_REVIEW_START\n"
                "## Findings\nAll resolved.\n\n"
                "## Re-plan Required\nNone\n\n"
                "## Guidance\nNone.\n"
                "GAP_REVIEW_END\n"
            )

        planners.run_gap_review = AsyncMock(side_effect=_gap_review)

        semaphore = asyncio.Semaphore(2)
        results = await phase._plan_epic_group(100, children, semaphore)

        assert len(results) == 2
        # Gap review was called twice
        assert planners.run_gap_review.await_count == 2
        assert planners.plan.await_count == 3
        prs.get_issue_state.assert_awaited_once_with(10)
        prs.get_issue_labels.assert_awaited_once_with(10)
        # Comment posted on epic for the first iteration
        gap_comments = [c for c in prs.post_comment.call_args_list if c.args[0] == 100]
        assert len(gap_comments) >= 1
        assert "Iteration 1" in gap_comments[0].args[1]

    @pytest.mark.asyncio
    async def test_skips_replan_after_implement_claims_child(
        self, config: HydraFlowConfig
    ) -> None:
        """The #11464 stale snapshot cannot replace implement ownership."""
        phase, planners, _prs, store, _stop = _make_phase(config)
        children = [
            _make_epic_child(id=10, title="Child A", epic_number=100),
            _make_epic_child(id=11, title="Child B", epic_number=100),
        ]
        planners.plan = AsyncMock(
            side_effect=lambda task, worker_id=0, **kwargs: PlanResultFactory.create(
                issue_number=task.id,
                success=True,
                plan=f"Plan for #{task.id}",
                use_defaults=True,
            )
        )

        async def _gap_review(*_args, **_kwargs) -> str:
            store.mark_active(10, "implement")
            return (
                "GAP_REVIEW_START\n"
                "## Findings\nStale conflict.\n\n"
                "## Re-plan Required\n#10\n\n"
                "## Guidance\nRe-plan the stale child.\n"
                "GAP_REVIEW_END\n"
            )

        planners.run_gap_review = AsyncMock(side_effect=_gap_review)

        await phase._plan_epic_group(100, children, asyncio.Semaphore(2))

        assert planners.plan.await_count == 2
        planners.run_gap_review.assert_awaited_once()
        # The store canonicalizes the phase name to its stage (#11551): the
        # implement owner is preserved and shows under READY.
        assert store.get_active_issues() == {10: STAGE_READY}

    @pytest.mark.asyncio
    async def test_post_read_local_claim_prevents_stale_replan(
        self, config: HydraFlowConfig
    ) -> None:
        """An implement claim during GitHub reads wins the synchronous CAS."""
        phase, planners, prs, store, _stop = _make_phase(config)
        children = [
            _make_epic_child(id=10, title="Child A", epic_number=100),
            _make_epic_child(id=11, title="Child B", epic_number=100),
        ]
        planners.plan = AsyncMock(
            side_effect=lambda task, worker_id=0, **kwargs: PlanResultFactory.create(
                issue_number=task.id,
                success=True,
                plan=f"Plan for #{task.id}",
                use_defaults=True,
            )
        )

        async def _gap_review(*_args, **_kwargs) -> str:
            store.enqueue_transition(children[0], "plan")
            return (
                "GAP_REVIEW_START\n"
                "## Findings\nRace.\n\n"
                "## Re-plan Required\n#10\n\n"
                "## Guidance\nRetry.\n"
                "GAP_REVIEW_END\n"
            )

        async def _advance_during_read(_issue_number: int) -> list[str]:
            store.enqueue_transition(children[0], "ready")
            claimed = store.get_implementable(2)
            assert {task.id for task in claimed} == {10, 11}
            store.release_in_flight({11}, expected_stage="ready")
            store.mark_active(10, "implement")
            return ["hydraflow-plan"]

        planners.run_gap_review = AsyncMock(side_effect=_gap_review)
        prs.get_issue_labels.side_effect = _advance_during_read

        await phase._plan_epic_group(100, children, asyncio.Semaphore(2))

        assert planners.plan.await_count == 2
        # The store canonicalizes the phase name to its stage (#11551): the
        # implement owner is preserved and shows under READY.
        assert store.get_active_issues() == {10: STAGE_READY}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("live_state", "live_labels"),
        [
            ("OPEN", ["hydraflow-ready"]),
            ("OPEN", ["hydraflow-plan", "hydraflow-in-progress"]),
            ("OPEN", ["hydraflow-plan", "hydraflow-hitl"]),
            ("OPEN", ["hydraflow-plan", "hydraflow-parked"]),
            ("OPEN", ["hydraflow-plan", "hydraflow-fixed"]),
            ("OPEN", ["hydraflow-plan", "hydraflow-verify"]),
            ("CLOSED", ["hydraflow-plan"]),
        ],
        ids=["ready", "in-progress", "hitl", "parked", "fixed", "verify", "closed"],
    )
    async def test_live_state_matrix_fails_closed(
        self,
        config: HydraFlowConfig,
        live_state: str,
        live_labels: list[str],
    ) -> None:
        phase, planners, prs, store, _stop = _make_phase(config)
        children = [
            _make_epic_child(id=10, title="Child A", epic_number=100),
            _make_epic_child(id=11, title="Child B", epic_number=100),
        ]
        planners.plan = AsyncMock(
            side_effect=lambda task, worker_id=0, **kwargs: PlanResultFactory.create(
                issue_number=task.id,
                success=True,
                plan=f"Plan for #{task.id}",
                use_defaults=True,
            )
        )

        async def _gap_review(*_args, **_kwargs) -> str:
            store.enqueue_transition(children[0], "plan")
            return (
                "GAP_REVIEW_START\n"
                "## Findings\nStale stage.\n\n"
                "## Re-plan Required\n#10\n\n"
                "## Guidance\nRetry.\n"
                "GAP_REVIEW_END\n"
            )

        planners.run_gap_review = AsyncMock(side_effect=_gap_review)
        prs.get_issue_state.return_value = live_state
        prs.get_issue_labels.return_value = live_labels

        await phase._plan_epic_group(100, children, asyncio.Semaphore(2))

        assert planners.plan.await_count == 2
        planners.run_gap_review.assert_awaited_once()
        assert [task.id for task in store.get_plannable(1)] == [10]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("failed_read", ["state", "labels"])
    async def test_live_read_failure_fails_closed(
        self, config: HydraFlowConfig, failed_read: str
    ) -> None:
        phase, planners, prs, store, _stop = _make_phase(config)
        children = [
            _make_epic_child(id=10, title="Child A", epic_number=100),
            _make_epic_child(id=11, title="Child B", epic_number=100),
        ]
        planners.plan = AsyncMock(
            side_effect=lambda task, worker_id=0, **kwargs: PlanResultFactory.create(
                issue_number=task.id,
                success=True,
                plan=f"Plan for #{task.id}",
                use_defaults=True,
            )
        )

        async def _gap_review(*_args, **_kwargs) -> str:
            store.enqueue_transition(children[0], "plan")
            return (
                "GAP_REVIEW_START\n"
                "## Findings\nUnreadable live state.\n\n"
                "## Re-plan Required\n#10\n\n"
                "## Guidance\nRetry.\n"
                "GAP_REVIEW_END\n"
            )

        planners.run_gap_review = AsyncMock(side_effect=_gap_review)
        getattr(prs, f"get_issue_{failed_read}").side_effect = RuntimeError("offline")

        await phase._plan_epic_group(100, children, asyncio.Semaphore(2))

        assert planners.plan.await_count == 2
        planners.run_gap_review.assert_awaited_once()
        assert [task.id for task in store.get_plannable(1)] == [10]

    @pytest.mark.asyncio
    async def test_caps_iterations(self, config: HydraFlowConfig) -> None:
        """Re-plan loop should not exceed max iterations."""
        # Override config to limit to 1 iteration
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            repo_root=config.repo_root,
            workspace_base=config.workspace_base,
            state_file=config.state_file,
        )
        # Override the iteration limit
        object.__setattr__(cfg, "epic_gap_review_max_iterations", 1)

        phase, planners, prs, store, _stop = _make_phase(cfg)
        children = [
            _make_epic_child(id=10, title="Child A", epic_number=100),
            _make_epic_child(id=11, title="Child B", epic_number=100),
        ]

        planners.plan = AsyncMock(
            side_effect=lambda task, worker_id=0, **kwargs: PlanResultFactory.create(
                issue_number=task.id,
                success=True,
                plan=f"Plan for #{task.id}",
                use_defaults=True,
            )
        )

        # Always flag for replan (should stop after 1 iteration)
        planners.run_gap_review = AsyncMock(
            return_value=(
                "GAP_REVIEW_START\n"
                "## Findings\nPersistent conflict.\n\n"
                "## Re-plan Required\n#10\n\n"
                "## Guidance\nKeep trying.\n"
                "GAP_REVIEW_END\n"
            )
        )

        semaphore = asyncio.Semaphore(2)
        results = await phase._plan_epic_group(100, children, semaphore)

        assert len(results) == 2
        # Should only call gap review once (capped at 1)
        assert planners.run_gap_review.await_count == 1

    @pytest.mark.asyncio
    async def test_skips_review_under_2_plans(self, config: HydraFlowConfig) -> None:
        """With fewer than 2 successful plans, skip gap review entirely."""
        phase, planners, prs, store, _stop = _make_phase(config)
        children = [
            _make_epic_child(id=10, title="Child A", epic_number=100),
            _make_epic_child(id=11, title="Child B", epic_number=100),
        ]

        # Only one plan succeeds
        planners.plan = AsyncMock(
            side_effect=[
                PlanResultFactory.create(
                    issue_number=10, success=True, plan="Plan A", use_defaults=True
                ),
                PlanResultFactory.create(
                    issue_number=11, success=False, error="oops", use_defaults=True
                ),
            ]
        )

        semaphore = asyncio.Semaphore(2)
        results = await phase._plan_epic_group(100, children, semaphore)

        assert len(results) == 2
        planners.run_gap_review.assert_not_awaited()


# ---------------------------------------------------------------------------
# _post_gap_review_comment tests
# ---------------------------------------------------------------------------


class TestGapReviewComment:
    @pytest.mark.asyncio
    async def test_posts_comment_on_epic(self, config: HydraFlowConfig) -> None:
        phase, _planners, prs, _store, _stop = _make_phase(config)
        review = EpicGapReview(
            epic_number=100,
            findings="Found overlap in config.py",
            replan_issues=[10, 11],
            guidance="Split the config changes",
        )
        await phase._post_gap_review_comment(100, review, iteration=1)

        prs.post_comment.assert_awaited_once()
        call = prs.post_comment.call_args
        assert call.args[0] == 100
        body = call.args[1]
        assert "Iteration 1" in body
        assert "#10, #11" in body
        assert "Split the config changes" in body


# ---------------------------------------------------------------------------
# Pipeline snapshot epic metadata tests
# ---------------------------------------------------------------------------


class TestPipelineSnapshotIncludesEpicFields:
    def test_snapshot_includes_epic_fields_for_child(
        self, config: HydraFlowConfig
    ) -> None:
        bus = EventBus()
        fetcher = AsyncMock()
        store = IssueStore(config, fetcher, bus)

        child = _make_epic_child(id=42, epic_number=100)
        # Simulate queued state
        store._queues["plan"].append(child)
        store._queue_members["plan"].add(42)

        snapshot = store._snapshot_queued()
        entries = snapshot.get("plan", [])
        assert len(entries) == 1
        entry = entries[0]
        assert entry["is_epic_child"] is True
        assert entry["epic_number"] == 100

    def test_snapshot_excludes_epic_fields_for_standalone(
        self, config: HydraFlowConfig
    ) -> None:
        bus = EventBus()
        fetcher = AsyncMock()
        store = IssueStore(config, fetcher, bus)

        standalone = TaskFactory.create(id=43, tags=["hydraflow-plan"])
        store._queues["plan"].append(standalone)
        store._queue_members["plan"].add(43)

        snapshot = store._snapshot_queued()
        entries = snapshot.get("plan", [])
        assert len(entries) == 1
        entry = entries[0]
        assert "is_epic_child" not in entry
        assert "epic_number" not in entry

    def test_snapshot_active_includes_epic_fields(
        self, config: HydraFlowConfig
    ) -> None:
        bus = EventBus()
        fetcher = AsyncMock()
        store = IssueStore(config, fetcher, bus)

        child = _make_epic_child(id=44, epic_number=200)
        store._issue_cache[44] = child
        store._active[44] = "plan"

        snapshot = store._snapshot_active()
        entries = snapshot.get("plan", [])
        assert len(entries) == 1
        assert entries[0]["is_epic_child"] is True
        assert entries[0]["epic_number"] == 200

    def test_snapshot_hitl_includes_epic_fields(self, config: HydraFlowConfig) -> None:
        bus = EventBus()
        fetcher = AsyncMock()
        store = IssueStore(config, fetcher, bus)

        child = _make_epic_child(id=45, epic_number=300)
        store._issue_cache[45] = child
        store._hitl_numbers.add(45)

        hitl_list = store._snapshot_hitl()
        assert len(hitl_list) == 1
        assert hitl_list[0]["is_epic_child"] is True
        assert hitl_list[0]["epic_number"] == 300


# ---------------------------------------------------------------------------
# plan_issues integration with epic groups
# ---------------------------------------------------------------------------


class TestPlanIssuesMixedEpicAndStandalone:
    @pytest.mark.asyncio
    async def test_fake_store_read_failure_does_not_reoffer_epic_forever(
        self, config: HydraFlowConfig
    ) -> None:
        """MockWorld mirrors real dequeue retention on a fail-closed replan."""
        object.__setattr__(config, "epic_group_planning", True)
        bus = EventBus()
        github = FakeGitHub()
        github.add_issue(
            10,
            "Child A",
            "Parent Epic #100\n\nDo something.",
            labels=["hydraflow-epic-child", "hydraflow-plan"],
        )
        github.add_issue(
            11,
            "Child B",
            "Parent Epic #100\n\nDo something else.",
            labels=["hydraflow-epic-child", "hydraflow-plan"],
        )
        store = FakeIssueStore(github=github, event_bus=bus)
        planners = AsyncMock()
        prs = AsyncMock()
        prs.transition = AsyncMock()
        prs.post_comment = AsyncMock()
        prs.create_task = AsyncMock(return_value=99)
        prs.get_issue_state = AsyncMock(side_effect=RuntimeError("offline"))
        prs.get_issue_labels = AsyncMock(return_value=["hydraflow-plan"])
        phase = PlanPhase(
            config,
            StateTracker(config.state_file),
            store,
            planners,
            prs,
            bus,
            asyncio.Event(),
        )
        planner_ids: list[int] = []

        async def _plan(task, worker_id=0, **_kwargs):
            planner_ids.append(task.id)
            return PlanResultFactory.create(
                issue_number=task.id,
                success=True,
                plan=f"Plan for #{task.id}",
                use_defaults=True,
            )

        async def _gap_review(*_args, **_kwargs) -> str:
            task = store.get_cached(10)
            assert task is not None
            store.enqueue_transition(task, "plan")
            return (
                "GAP_REVIEW_START\n"
                "## Findings\nUnreadable child.\n\n"
                "## Re-plan Required\n#10\n\n"
                "## Guidance\nRetry.\n"
                "GAP_REVIEW_END\n"
            )

        planners.plan = AsyncMock(side_effect=_plan)
        planners.run_gap_review = AsyncMock(side_effect=_gap_review)

        results = await asyncio.wait_for(phase.plan_issues(), timeout=1)

        assert [result.issue_number for result in results] == [10, 11]
        assert planner_ids == [10, 11]
        assert store.get_plannable(1) == []

    @pytest.mark.asyncio
    async def test_invalid_epic_replan_cannot_fall_through_to_standalone_pool(
        self, config: HydraFlowConfig
    ) -> None:
        """A skipped #11464-style replan stays skipped for this whole cycle."""
        object.__setattr__(config, "epic_group_planning", True)
        phase, planners, prs, store, _stop = _make_phase(config)
        children = [
            _make_epic_child(id=10, title="Child A", epic_number=100),
            _make_epic_child(id=11, title="Child B", epic_number=100),
        ]
        store._route_issues(children)
        planner_ids: list[int] = []

        async def _plan(task, worker_id=0, **_kwargs):
            planner_ids.append(task.id)
            return PlanResultFactory.create(
                issue_number=task.id,
                success=True,
                plan=f"Plan for #{task.id}",
                use_defaults=True,
            )

        async def _gap_review(*_args, **_kwargs) -> str:
            # Reproduce the stale local PLAN entry that previously escaped the
            # epic guard through plan_issues' standalone refill pool.
            store.enqueue_transition(children[0], "plan")
            return (
                "GAP_REVIEW_START\n"
                "## Findings\nStale child.\n\n"
                "## Re-plan Required\n#10\n\n"
                "## Guidance\nRetry.\n"
                "GAP_REVIEW_END\n"
            )

        planners.plan = AsyncMock(side_effect=_plan)
        planners.run_gap_review = AsyncMock(side_effect=_gap_review)
        prs.get_issue_labels.return_value = ["hydraflow-ready"]

        results = await phase.plan_issues()

        assert [result.issue_number for result in results] == [10, 11]
        assert planner_ids == [10, 11]
        planners.run_gap_review.assert_awaited_once()
        assert store.get_plannable(1) == []

    @pytest.mark.asyncio
    async def test_plans_both_groups(self, config: HydraFlowConfig) -> None:
        """plan_issues should handle both standalone and epic children."""
        object.__setattr__(config, "epic_group_planning", True)
        phase, planners, prs, store, _stop = _make_phase(config)

        standalone = TaskFactory.create(id=1, tags=["hydraflow-plan"])
        child_a = _make_epic_child(id=2, epic_number=100)
        child_b = _make_epic_child(id=3, epic_number=100)

        # First call: epic batch drain gets all 3 (standalone re-queued internally)
        # Second call: standalone pool picks up the re-queued standalone
        _calls = [[standalone, child_a, child_b], [standalone], []]
        store.get_plannable = lambda _max_count: _calls.pop(0) if _calls else []

        planners.plan = AsyncMock(
            side_effect=lambda task, worker_id=0, **kwargs: PlanResultFactory.create(
                issue_number=task.id,
                success=True,
                plan=f"Plan for #{task.id}",
                use_defaults=True,
            )
        )
        # Gap review returns coherent
        planners.run_gap_review = AsyncMock(
            return_value=(
                "GAP_REVIEW_START\n"
                "## Findings\nAll good.\n\n"
                "## Re-plan Required\nNone\n\n"
                "## Guidance\nNone.\n"
                "GAP_REVIEW_END\n"
            )
        )

        results = await phase.plan_issues()

        assert len(results) == 3
        issue_numbers = {r.issue_number for r in results}
        assert issue_numbers == {1, 2, 3}
        # Epic children should have epic_number set
        epic_results = [r for r in results if r.epic_number == 100]
        assert len(epic_results) == 2

    @pytest.mark.asyncio
    async def test_epic_cleanup_preserves_downstream_ready_claim(
        self, config: HydraFlowConfig
    ) -> None:
        """Group cleanup releases only its PLAN reservation, not implement's."""
        object.__setattr__(config, "epic_group_planning", True)
        object.__setattr__(config, "epic_gap_review_max_iterations", 0)
        phase, planners, _prs, store, _stop = _make_phase(config)
        children = [
            _make_epic_child(id=2, epic_number=100),
            _make_epic_child(id=3, epic_number=100),
        ]
        store._route_issues(children)
        planners.plan = AsyncMock(
            side_effect=lambda task, worker_id=0, **kwargs: PlanResultFactory.create(
                issue_number=task.id,
                success=True,
                plan=f"Plan for #{task.id}",
                use_defaults=True,
            )
        )
        epic_manager = AsyncMock()
        dequeued = False

        async def _dequeue_ready(*_args, **_kwargs) -> None:
            nonlocal dequeued
            if not dequeued:
                dequeued = True
                assert [task.id for task in store.get_implementable(1)] == [2]

        epic_manager.on_child_planned.side_effect = _dequeue_ready
        phase._epic_manager = epic_manager

        await phase.plan_issues()

        assert store.get_worker_held_issues() == {2: "ready"}

    @pytest.mark.asyncio
    async def test_disabled_epic_group_planning(self, config: HydraFlowConfig) -> None:
        """When epic_group_planning is False, all issues are standalone."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            repo_root=config.repo_root,
            workspace_base=config.workspace_base,
            state_file=config.state_file,
        )
        # epic_group_planning defaults to False in ConfigFactory

        phase, planners, prs, store, _stop = _make_phase(cfg)

        child_a = _make_epic_child(id=2, epic_number=100)
        child_b = _make_epic_child(id=3, epic_number=100)

        _items = [[child_a], [child_b], []]
        store.get_plannable = lambda _max_count: _items.pop(0) if _items else []

        planners.plan = AsyncMock(
            side_effect=lambda task, worker_id=0, **kwargs: PlanResultFactory.create(
                issue_number=task.id,
                success=True,
                plan=f"Plan for #{task.id}",
                use_defaults=True,
            )
        )

        results = await phase.plan_issues()

        assert len(results) == 2
        # Gap review should never be called
        planners.run_gap_review.assert_not_called()
        # Epic number should NOT be set (planned as standalone)
        assert all(r.epic_number == 0 for r in results)
