"""Tests for IssueDecomposer — extracted epic create/link/register plumbing.

Behavior-preserving extraction from ``TriagePhase._maybe_decompose``
(ADR-0105 decompose-to-converge, task 2). The intake-decomposition tests in
``tests/test_epic_decomposition.py::TestMaybeDecompose`` are pinned and must
stay green unchanged; these tests cover the new ``IssueDecomposer`` surface
directly.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from issue_decomposer import IssueDecomposer
from mockworld.fakes.fake_github import FakeGitHub
from models import EpicDecompResult, EpicState, NewIssueSpec
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory, make_tracker


def _make_decomposer(tmp_path: Path):
    """Build an IssueDecomposer with a real FakeGitHub + StateTracker.

    ``epic_manager`` is a MagicMock (per the brief) since EpicManager's own
    persistence behavior is out of scope here — only that IssueDecomposer
    calls it correctly.
    """
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    prs = FakeGitHub()
    epic_manager = MagicMock()
    epic_manager.register_epic = AsyncMock()
    state = make_tracker(tmp_path)
    decomposer = IssueDecomposer(prs, epic_manager, state, config)
    return decomposer, prs, epic_manager, state, config


def _two_child_result(**overrides: object) -> EpicDecompResult:
    defaults: dict[str, object] = {
        "should_decompose": True,
        "epic_title": "Epic: Big Work",
        "epic_body": "## Sub-issues",
        "children": [
            NewIssueSpec(title="Child 1", body="Do 1"),
            NewIssueSpec(title="Child 2", body="Do 2"),
        ],
        "reasoning": "Too complex for one pass",
    }
    defaults.update(overrides)
    return EpicDecompResult(**defaults)  # type: ignore[arg-type]


class TestCreateEpicFromResult:
    @pytest.mark.asyncio
    async def test_creates_epic_and_children_and_registers(
        self, tmp_path: Path
    ) -> None:
        decomposer, prs, epic_manager, state, config = _make_decomposer(tmp_path)
        prs.add_issue(10, "Source issue", "Original body")
        source_task = TaskFactory.create(id=10)
        result = _two_child_result()

        epic_number = await decomposer.create_epic_from_result(
            source_task=source_task, result=result
        )

        assert epic_number is not None

        epic_issue = prs.issue(epic_number)
        assert epic_issue.title == "Epic: Big Work"
        assert epic_issue.body == "## Sub-issues"
        assert epic_issue.labels == config.epic_label

        child_1 = prs.issue(epic_number + 1)
        child_2 = prs.issue(epic_number + 2)
        assert child_1.title == "Child 1"
        assert child_1.labels == [config.epic_child_label[0], config.find_label[0]]
        assert f"Parent Epic #{epic_number}" in child_1.body
        assert child_2.title == "Child 2"
        assert child_2.labels == [config.epic_child_label[0], config.find_label[0]]
        assert f"Parent Epic #{epic_number}" in child_2.body

        epic_manager.register_epic.assert_called_once_with(
            epic_number,
            "Epic: Big Work",
            [epic_number + 1, epic_number + 2],
            auto_decomposed=True,
        )

        # Source issue closed with a link to the new epic.
        source_issue = prs.issue(10)
        assert source_issue.state == "closed"
        assert any(f"epic #{epic_number}" in c for c in source_issue.comments)
        assert state.to_dict()["processed_issues"]["10"] == "decomposed"

    @pytest.mark.asyncio
    async def test_should_decompose_false_returns_none_no_create_issue_calls(
        self, tmp_path: Path
    ) -> None:
        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        prs = AsyncMock()
        epic_manager = MagicMock()
        epic_manager.register_epic = AsyncMock()
        state = make_tracker(tmp_path)
        decomposer = IssueDecomposer(prs, epic_manager, state, config)
        source_task = TaskFactory.create(id=10)
        result = EpicDecompResult(should_decompose=False, reasoning="Not appropriate")

        epic_number = await decomposer.create_epic_from_result(
            source_task=source_task, result=result
        )

        assert epic_number is None
        prs.create_issue.assert_not_called()
        prs.close_issue.assert_not_called()
        epic_manager.register_epic.assert_not_called()

    @pytest.mark.asyncio
    async def test_stall_context_embedded_in_every_child_body(
        self, tmp_path: Path
    ) -> None:
        decomposer, prs, _epic_manager, _state, _config = _make_decomposer(tmp_path)
        prs.add_issue(10, "Source issue", "Original body")
        source_task = TaskFactory.create(id=10)
        result = _two_child_result()

        epic_number = await decomposer.create_epic_from_result(
            source_task=source_task,
            result=result,
            stall_context="Parent #7 stalled on flaky CI in payment module",
        )

        assert epic_number is not None
        child_1 = prs.issue(epic_number + 1)
        child_2 = prs.issue(epic_number + 2)
        assert "Parent #7 stalled on flaky CI in payment module" in child_1.body
        assert "Parent #7 stalled on flaky CI in payment module" in child_2.body

    @pytest.mark.asyncio
    async def test_depth_lands_on_epic_state_decomposition_depth(
        self, tmp_path: Path
    ) -> None:
        decomposer, prs, epic_manager, state, _config = _make_decomposer(tmp_path)
        prs.add_issue(10, "Source issue", "Original body")
        source_task = TaskFactory.create(id=10)
        result = _two_child_result()

        # A real EpicManager.register_epic upserts an EpicState; simulate
        # that side effect since epic_manager here is a MagicMock.
        async def _register_epic(
            epic_number: int,
            title: str,
            children: list[int],
            *,
            auto_decomposed: bool = False,
        ) -> None:
            state.upsert_epic_state(
                EpicState(
                    epic_number=epic_number,
                    title=title,
                    child_issues=children,
                    auto_decomposed=auto_decomposed,
                )
            )

        epic_manager.register_epic.side_effect = _register_epic

        epic_number = await decomposer.create_epic_from_result(
            source_task=source_task, result=result, depth=2
        )

        assert epic_number is not None
        epic_state = state.get_epic_state(epic_number)
        assert epic_state is not None
        assert epic_state.decomposition_depth == 2

    @pytest.mark.asyncio
    async def test_depth_zero_is_default_and_does_not_touch_epic_state(
        self, tmp_path: Path
    ) -> None:
        """The intake path always calls with depth=0 — must stay a no-op."""
        decomposer, prs, epic_manager, state, _config = _make_decomposer(tmp_path)
        prs.add_issue(10, "Source issue", "Original body")
        source_task = TaskFactory.create(id=10)
        result = _two_child_result()

        epic_number = await decomposer.create_epic_from_result(
            source_task=source_task, result=result, depth=0
        )

        assert epic_number is not None
        # register_epic is mocked (doesn't really persist), so with depth=0
        # IssueDecomposer must not attempt to read/write epic state at all.
        assert state.get_epic_state(epic_number) is None

    @pytest.mark.asyncio
    async def test_epic_creation_failure_returns_none(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        prs = AsyncMock()
        prs.create_issue = AsyncMock(return_value=0)
        epic_manager = MagicMock()
        epic_manager.register_epic = AsyncMock()
        state = make_tracker(tmp_path)
        decomposer = IssueDecomposer(prs, epic_manager, state, config)
        source_task = TaskFactory.create(id=10)
        result = _two_child_result()

        epic_number = await decomposer.create_epic_from_result(
            source_task=source_task, result=result
        )

        assert epic_number is None
        epic_manager.register_epic.assert_not_called()
        prs.close_issue.assert_not_called()
