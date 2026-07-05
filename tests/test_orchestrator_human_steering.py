"""Orchestrator actuator seam for continuous human-on-the-loop steering (Task 6).

`HydraFlowOrchestrator._apply_human_steering` enacts the pure decision from
`human_steering.apply_steering` for each active issue: pause -> skip
scheduling, abort -> park at the recoverable HITL label, redo -> re-enqueue
to the named phase with the redo counter persisted. Guarded end-to-end by
`config.human_steering_enabled` (dark by default).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from human_steering_loop import HumanSteeringLoop
from models import SteeringState
from orchestrator import HydraFlowOrchestrator
from tests.conftest import TaskFactory

if TYPE_CHECKING:
    from config import HydraFlowConfig


class TestHumanSteeringDisabled:
    @pytest.mark.asyncio
    async def test_noop_when_feature_disabled(self, config: HydraFlowConfig) -> None:
        """Default-off: no active-issue enumeration, no label swaps."""
        config.human_steering_enabled = False
        orch = HydraFlowOrchestrator(config)
        orch._svc.store.get_active_issues = MagicMock()  # type: ignore[method-assign]
        orch._svc.prs.swap_pipeline_labels = AsyncMock()  # type: ignore[method-assign]

        await orch._apply_human_steering()

        orch._svc.store.get_active_issues.assert_not_called()
        orch._svc.prs.swap_pipeline_labels.assert_not_awaited()


class TestHumanSteeringSkip:
    @pytest.mark.asyncio
    async def test_paused_issue_is_not_parked_or_reenqueued(
        self, config: HydraFlowConfig
    ) -> None:
        config.human_steering_enabled = True
        orch = HydraFlowOrchestrator(config)
        orch._svc.store.get_active_issues = lambda: {5: "ready"}  # type: ignore[method-assign]
        orch._svc.prs.swap_pipeline_labels = AsyncMock()  # type: ignore[method-assign]
        orch._svc.store.enqueue_transition = MagicMock()  # type: ignore[method-assign]
        orch._state.set_human_steering("5", SteeringState(flow="paused"))

        await orch._apply_human_steering()

        orch._svc.prs.swap_pipeline_labels.assert_not_awaited()
        orch._svc.store.enqueue_transition.assert_not_called()


class TestHumanSteeringAbort:
    @pytest.mark.asyncio
    async def test_abort_swaps_to_hitl_label(self, config: HydraFlowConfig) -> None:
        config.human_steering_enabled = True
        orch = HydraFlowOrchestrator(config)
        orch._svc.store.get_active_issues = lambda: {7: "ready"}  # type: ignore[method-assign]
        orch._svc.prs.swap_pipeline_labels = AsyncMock()  # type: ignore[method-assign]
        orch._state.set_human_steering("7", SteeringState(flow="abort"))

        await orch._apply_human_steering()

        orch._svc.prs.swap_pipeline_labels.assert_awaited_once_with(
            7, config.hitl_label[0]
        )

    @pytest.mark.asyncio
    async def test_abort_escalates_with_operator_abort_origin(
        self, config: HydraFlowConfig
    ) -> None:
        """`/abort` records a distinct HITL origin so operator aborts are
        distinguishable from failure-driven escalations on the dashboard."""
        config.human_steering_enabled = True
        orch = HydraFlowOrchestrator(config)
        orch._svc.store.get_active_issues = lambda: {7: "ready"}  # type: ignore[method-assign]
        orch._svc.prs.swap_pipeline_labels = AsyncMock()  # type: ignore[method-assign]
        orch._state.set_human_steering("7", SteeringState(flow="abort"))

        await orch._apply_human_steering()

        orch._svc.prs.swap_pipeline_labels.assert_awaited_once_with(
            7, config.hitl_label[0]
        )
        assert orch._state.get_hitl_origin(7) == "operator-abort"
        assert orch._state.get_hitl_cause(7) == "/abort steering directive"

    @pytest.mark.asyncio
    async def test_reabort_is_idempotent(self, config: HydraFlowConfig) -> None:
        """A second `/abort` on an issue already parked with operator-abort
        origin must not double-count the lifetime HITL escalation counter."""
        config.human_steering_enabled = True
        orch = HydraFlowOrchestrator(config)
        orch._svc.store.get_active_issues = lambda: {7: "ready"}  # type: ignore[method-assign]
        orch._svc.prs.swap_pipeline_labels = AsyncMock()  # type: ignore[method-assign]
        orch._state.set_human_steering("7", SteeringState(flow="abort"))

        await orch._apply_human_steering()
        before = orch._state.get_lifetime_stats().total_hitl_escalations

        # Simulate a second /abort directive arriving on the same
        # already-operator-aborted issue.
        orch._state.set_human_steering("7", SteeringState(flow="abort"))
        orch._svc.prs.swap_pipeline_labels.reset_mock()

        await orch._apply_human_steering()

        orch._svc.prs.swap_pipeline_labels.assert_not_awaited()
        after = orch._state.get_lifetime_stats().total_hitl_escalations
        assert after == before


class TestHumanSteeringRedo:
    @pytest.mark.asyncio
    async def test_redo_valid_phase_reenqueues_and_persists_count(
        self, config: HydraFlowConfig
    ) -> None:
        config.human_steering_enabled = True
        orch = HydraFlowOrchestrator(config)
        task = TaskFactory.create(id=9)
        orch._svc.store.get_active_issues = lambda: {9: "ready"}  # type: ignore[method-assign]
        orch._svc.store.get_cached = lambda _n: task  # type: ignore[method-assign]
        orch._svc.store.enqueue_transition = MagicMock()  # type: ignore[method-assign]
        orch._state.set_human_steering(
            "9", SteeringState(redo_phase="plan", redo_count=0)
        )

        await orch._apply_human_steering()

        orch._svc.store.enqueue_transition.assert_called_once_with(task, "plan")
        persisted = orch._state.get_human_steering("9")
        assert persisted.redo_phase is None
        assert persisted.redo_count == 1

    @pytest.mark.asyncio
    async def test_redo_over_cap_is_dropped(self, config: HydraFlowConfig) -> None:
        config.human_steering_enabled = True
        orch = HydraFlowOrchestrator(config)
        orch._svc.store.get_active_issues = lambda: {11: "ready"}  # type: ignore[method-assign]
        orch._svc.store.enqueue_transition = MagicMock()  # type: ignore[method-assign]
        orch._state.set_human_steering(
            "11",
            SteeringState(
                redo_phase="plan", redo_count=config.human_steering_max_redos
            ),
        )

        await orch._apply_human_steering()

        orch._svc.store.enqueue_transition.assert_not_called()

    @pytest.mark.asyncio
    async def test_redo_invalid_phase_is_dropped(self, config: HydraFlowConfig) -> None:
        config.human_steering_enabled = True
        orch = HydraFlowOrchestrator(config)
        orch._svc.store.get_active_issues = lambda: {13: "ready"}  # type: ignore[method-assign]
        orch._svc.store.enqueue_transition = MagicMock()  # type: ignore[method-assign]
        orch._state.set_human_steering("13", SteeringState(redo_phase="bogus"))

        await orch._apply_human_steering()

        orch._svc.store.enqueue_transition.assert_not_called()

    @pytest.mark.asyncio
    async def test_redo_dashboard_name_resolves_and_reenqueues(
        self, config: HydraFlowConfig
    ) -> None:
        """A dashboard-facing token ('implement') resolves to the internal
        phase ('ready') and is enacted — no operator feedback needed."""
        config.human_steering_enabled = True
        orch = HydraFlowOrchestrator(config)
        task = TaskFactory.create(id=21)
        orch._svc.store.get_active_issues = lambda: {21: "shape"}  # type: ignore[method-assign]
        orch._svc.store.get_cached = lambda _n: task  # type: ignore[method-assign]
        orch._svc.store.enqueue_transition = MagicMock()  # type: ignore[method-assign]
        orch._svc.prs.post_comment = AsyncMock()  # type: ignore[method-assign]
        orch._state.set_human_steering(
            "21", SteeringState(redo_phase="implement", redo_count=0)
        )

        await orch._apply_human_steering()

        orch._svc.store.enqueue_transition.assert_called_once_with(task, "ready")
        orch._svc.prs.post_comment.assert_not_awaited()
        persisted = orch._state.get_human_steering("21")
        assert persisted.redo_phase is None
        assert persisted.redo_count == 1

    @pytest.mark.asyncio
    async def test_redo_unknown_token_posts_operator_feedback_once(
        self, config: HydraFlowConfig
    ) -> None:
        config.human_steering_enabled = True
        orch = HydraFlowOrchestrator(config)
        orch._svc.store.get_active_issues = lambda: {17: "ready"}  # type: ignore[method-assign]
        orch._svc.store.enqueue_transition = MagicMock()  # type: ignore[method-assign]
        orch._svc.prs.post_comment = AsyncMock()  # type: ignore[method-assign]
        orch._state.set_human_steering("17", SteeringState(redo_phase="bogus"))

        await orch._apply_human_steering()

        orch._svc.store.enqueue_transition.assert_not_called()
        orch._svc.prs.post_comment.assert_awaited_once()
        args, _ = orch._svc.prs.post_comment.await_args
        assert args[0] == 17
        assert "bogus" in args[1]
        assert "unknown phase" in args[1]

        # Freshness gate: redo_phase is now cleared, so a second tick must
        # not re-post feedback for the same (stale) directive.
        orch._svc.prs.post_comment.reset_mock()
        await orch._apply_human_steering()
        orch._svc.prs.post_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_redo_cap_reached_posts_operator_feedback(
        self, config: HydraFlowConfig
    ) -> None:
        config.human_steering_enabled = True
        orch = HydraFlowOrchestrator(config)
        orch._svc.store.get_active_issues = lambda: {19: "ready"}  # type: ignore[method-assign]
        orch._svc.store.enqueue_transition = MagicMock()  # type: ignore[method-assign]
        orch._svc.prs.post_comment = AsyncMock()  # type: ignore[method-assign]
        orch._state.set_human_steering(
            "19",
            SteeringState(
                redo_phase="implement", redo_count=config.human_steering_max_redos
            ),
        )

        await orch._apply_human_steering()

        orch._svc.store.enqueue_transition.assert_not_called()
        orch._svc.prs.post_comment.assert_awaited_once()
        args, _ = orch._svc.prs.post_comment.await_args
        assert args[0] == 19
        assert "redo cap reached" in args[1]


class TestHumanSteeringGuidanceFold:
    @pytest.mark.asyncio
    async def test_implementer_prompt_includes_fenced_guidance(
        self, config: HydraFlowConfig
    ) -> None:
        """End-to-end: guidance persisted via steering state reaches the
        implementer's prompt, fenced as untrusted (ADR-0092)."""
        from implement_phase import ImplementPhase  # noqa: PLC0415

        config.human_steering_enabled = True
        orch = HydraFlowOrchestrator(config)
        orch._state.set_human_steering(
            "42", SteeringState(guidance="focus on the retry path")
        )
        issue = TaskFactory.create(id=42)

        implementer: ImplementPhase = orch._svc.implementer
        captured: dict[str, object] = {}

        async def _fake_run(task, worktree_path, branch, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            from models import WorkerResult

            return WorkerResult(issue_number=task.id, branch=branch, success=True)

        implementer._agents.run = _fake_run  # type: ignore[method-assign]
        implementer._setup_worktree_and_branch = AsyncMock(  # type: ignore[method-assign]
            return_value=config.workspace_base / "issue-42"
        )
        implementer._store.enrich_with_comments = AsyncMock(return_value=issue)  # type: ignore[method-assign]

        await implementer._run_implementation(issue, "agent/issue-42", 0, "")

        assert captured.get("human_guidance") == "focus on the retry path"


class TestHumanSteeringEnabledPathEndToEnd:
    """Sensor -> actuator, wired together, at the (now-default) enabled config.

    Unlike the per-behavior tests above (which set `human_steering_enabled =
    True` directly on the config and drive the actuator with a hand-built
    `SteeringState`), this test drives the real `HumanSteeringLoop` sensor
    against an authorized comment and asserts the state it *writes* is what
    the orchestrator actuator then *acts on*. It exercises the authorization
    choke point (`parse_directives`) and the sensor/actuator wiring together,
    so it fails if either the default flip or the allowlist plumbing regresses.
    """

    @pytest.mark.asyncio
    async def test_authorized_pause_is_sensed_and_actuated_as_skip(
        self, config: HydraFlowConfig
    ) -> None:
        # human_steering_enabled is left at its config default (now True) —
        # this is the point of the enabled-path test.
        assert config.human_steering_enabled is True
        config.human_steering_authorized_users = ["ops-operator"]
        orch = HydraFlowOrchestrator(config)
        orch._svc.store.get_active_issues = lambda: {23: "ready"}  # type: ignore[method-assign]
        orch._svc.prs.swap_pipeline_labels = AsyncMock()  # type: ignore[method-assign]
        orch._svc.store.enqueue_transition = MagicMock()  # type: ignore[method-assign]
        orch._svc.prs.list_issue_comments = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                {
                    "user": {"login": "ops-operator"},
                    "body": "/pause",
                    "created_at": "2026-07-04T10:00:00Z",
                },
            ]
        )

        sensor = HumanSteeringLoop(
            config=config,
            state=orch._state,
            prs=orch._svc.prs,
            deps=MagicMock(),
            active_issues_cb=orch._svc.store.get_active_issues,
        )
        sensor._enabled_cb = lambda _name: True  # kill-switch open

        sense_result = await sensor._do_work()
        assert sense_result["status"] == "ok"
        assert sense_result["updated"] == 1
        assert orch._state.get_human_steering("23").flow == "paused"

        await orch._apply_human_steering()

        orch._svc.prs.swap_pipeline_labels.assert_not_awaited()
        orch._svc.store.enqueue_transition.assert_not_called()

    @pytest.mark.asyncio
    async def test_unauthorized_pause_is_dropped_at_the_sensor(
        self, config: HydraFlowConfig
    ) -> None:
        """Empty allowlist ⇒ honor nobody: the same `/pause` comment from a
        login absent from `human_steering_authorized_users` never reaches
        SteeringState, so the actuator sees a running issue and proceeds."""
        assert config.human_steering_enabled is True
        assert config.human_steering_authorized_users == []
        orch = HydraFlowOrchestrator(config)
        orch._svc.store.get_active_issues = lambda: {24: "ready"}  # type: ignore[method-assign]
        orch._svc.prs.swap_pipeline_labels = AsyncMock()  # type: ignore[method-assign]
        orch._svc.prs.list_issue_comments = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                {
                    "user": {"login": "random-passerby"},
                    "body": "/pause",
                    "created_at": "2026-07-04T10:00:00Z",
                },
            ]
        )

        sensor = HumanSteeringLoop(
            config=config,
            state=orch._state,
            prs=orch._svc.prs,
            deps=MagicMock(),
            active_issues_cb=orch._svc.store.get_active_issues,
        )
        sensor._enabled_cb = lambda _name: True

        await sensor._do_work()

        assert orch._state.get_human_steering("24").flow == "running"
