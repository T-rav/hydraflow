"""Tests for ``orchestrator_hitl`` — the operator-facing HITL façade.

Every verb on this mixin is a thin, deliberate delegation to the single
``HITLController`` the orchestrator owns: the dashboard talks to the
orchestrator, never to the controller. The delegation is the contract (a verb
that grew its own local state would silently fork HITL truth), so these tests
pin the routing, the argument order, and the read-through of the three
backward-compatible accessors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from orchestrator import HydraFlowOrchestrator

if TYPE_CHECKING:
    from config import HydraFlowConfig


@pytest.fixture
def orch_with_stub_controller(
    config: HydraFlowConfig,
) -> tuple[HydraFlowOrchestrator, MagicMock]:
    """An orchestrator whose HITLController is replaced by a recording stub."""
    orch = HydraFlowOrchestrator(config)
    ctrl = MagicMock()
    orch._hitl_ctrl = ctrl
    return orch, ctrl


class TestHITLVerbsDelegate:
    """Each dashboard verb forwards to ``HITLController`` unchanged."""

    def test_provide_human_input_forwards_issue_and_answer(
        self, orch_with_stub_controller: tuple[HydraFlowOrchestrator, MagicMock]
    ) -> None:
        orch, ctrl = orch_with_stub_controller

        orch.provide_human_input(42, "use the second option")

        ctrl.provide_human_input.assert_called_once_with(42, "use the second option")

    def test_submit_hitl_correction_maps_to_submit_correction(
        self, orch_with_stub_controller: tuple[HydraFlowOrchestrator, MagicMock]
    ) -> None:
        orch, ctrl = orch_with_stub_controller

        orch.submit_hitl_correction(7, "retry with the smaller diff")

        ctrl.submit_correction.assert_called_once_with(7, "retry with the smaller diff")

    def test_get_hitl_status_returns_controller_status(
        self, orch_with_stub_controller: tuple[HydraFlowOrchestrator, MagicMock]
    ) -> None:
        orch, ctrl = orch_with_stub_controller
        ctrl.get_status.return_value = "awaiting_human"

        assert orch.get_hitl_status(7) == "awaiting_human"
        ctrl.get_status.assert_called_once_with(7)

    def test_skip_hitl_issue_maps_to_skip_issue(
        self, orch_with_stub_controller: tuple[HydraFlowOrchestrator, MagicMock]
    ) -> None:
        orch, ctrl = orch_with_stub_controller

        orch.skip_hitl_issue(7)

        ctrl.skip_issue.assert_called_once_with(7)


class TestHITLAccessorsReadThrough:
    """The three accessors expose controller state, never a private copy."""

    def test_human_input_requests_is_the_controller_mapping(
        self, orch_with_stub_controller: tuple[HydraFlowOrchestrator, MagicMock]
    ) -> None:
        orch, ctrl = orch_with_stub_controller
        ctrl.human_input_requests = {9: "which base branch?"}

        assert orch.human_input_requests == {9: "which base branch?"}

    def test_active_hitl_issues_is_the_controller_set(
        self, orch_with_stub_controller: tuple[HydraFlowOrchestrator, MagicMock]
    ) -> None:
        orch, ctrl = orch_with_stub_controller
        ctrl.active_hitl_issues = {9, 11}

        assert orch._active_hitl_issues == {9, 11}

    def test_hitl_corrections_is_the_controller_mapping(
        self, orch_with_stub_controller: tuple[HydraFlowOrchestrator, MagicMock]
    ) -> None:
        orch, ctrl = orch_with_stub_controller
        ctrl.hitl_corrections = {9: "narrow the scope"}

        assert orch._hitl_corrections == {9: "narrow the scope"}
