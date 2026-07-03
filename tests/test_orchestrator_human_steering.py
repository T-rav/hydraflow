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
