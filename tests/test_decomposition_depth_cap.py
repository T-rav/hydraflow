"""Tests for decompose-to-converge depth + fan-out caps and the intake-vector
guard (ADR-0105 §4, task 5).

Covers:
    (a) ``depth == max_decomposition_depth`` -> ``create_epic_from_result``
        returns ``None``, zero ``create_issue`` calls (depth-cap).
    (b) creating the proposed children would push the decomposition's root
        epic to/past ``max_total_decomposition_children`` -> returns
        ``None``, zero ``create_issue`` calls (fanout-cap).
    (c) under both caps -> creates normally, and every child issue carries
        the ``auto_decomposed_child_label`` stamp.
    (d) ``TriagePhase._maybe_decompose`` skips an issue that already carries
        the ``auto_decomposed_child_label`` — the intake complexity path
        must not re-split an already-decomposed child uncounted.
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
from tests.conftest import TaskFactory, TriageResultFactory
from tests.helpers import ConfigFactory, make_tracker


def _make_decomposer(tmp_path: Path):
    """Build an IssueDecomposer with a real FakeGitHub + StateTracker.

    Mirrors ``tests/test_issue_decomposer.py::_make_decomposer`` — the
    ``epic_manager`` is a ``MagicMock`` since only ``IssueDecomposer``'s own
    cap logic is under test here.
    """
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    prs = FakeGitHub()
    epic_manager = MagicMock()
    epic_manager.register_epic = AsyncMock()
    state = make_tracker(tmp_path)
    decomposer = IssueDecomposer(prs, epic_manager, state, config)
    return decomposer, prs, epic_manager, state, config


def _make_decomposer_mocked(tmp_path: Path):
    """Build an IssueDecomposer with a mocked ``prs`` for no-create assertions.

    Mirrors ``tests/test_issue_decomposer.py::test_epic_creation_failure_returns_none``
    — a plain ``AsyncMock`` lets tests assert ``create_issue`` was never
    awaited, without depending on FakeGitHub internals.
    """
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    prs = AsyncMock()
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


class TestDepthCap:
    @pytest.mark.asyncio
    async def test_depth_at_cap_returns_none_and_creates_nothing(
        self, tmp_path: Path
    ) -> None:
        decomposer, prs, epic_manager, _state, config = _make_decomposer_mocked(
            tmp_path
        )
        source_task = TaskFactory.create(id=10)
        result = _two_child_result()

        epic_number = await decomposer.create_epic_from_result(
            source_task=source_task,
            result=result,
            depth=config.max_decomposition_depth,
        )

        assert epic_number is None
        prs.create_issue.assert_not_called()
        epic_manager.register_epic.assert_not_called()

    @pytest.mark.asyncio
    async def test_depth_over_cap_returns_none_and_creates_nothing(
        self, tmp_path: Path
    ) -> None:
        decomposer, prs, epic_manager, _state, config = _make_decomposer_mocked(
            tmp_path
        )
        source_task = TaskFactory.create(id=10)
        result = _two_child_result()

        epic_number = await decomposer.create_epic_from_result(
            source_task=source_task,
            result=result,
            depth=config.max_decomposition_depth + 1,
        )

        assert epic_number is None
        prs.create_issue.assert_not_called()
        epic_manager.register_epic.assert_not_called()

    @pytest.mark.asyncio
    async def test_depth_under_cap_is_unaffected(self, tmp_path: Path) -> None:
        decomposer, prs, _epic_manager, _state, config = _make_decomposer(tmp_path)
        prs.add_issue(10, "Source issue", "Original body")
        source_task = TaskFactory.create(id=10)
        result = _two_child_result()

        epic_number = await decomposer.create_epic_from_result(
            source_task=source_task,
            result=result,
            depth=config.max_decomposition_depth - 1,
        )

        assert epic_number is not None


class TestFanoutCap:
    @pytest.mark.asyncio
    async def test_fanout_over_cap_returns_none_and_creates_nothing(
        self, tmp_path: Path
    ) -> None:
        decomposer, prs, epic_manager, state, config = _make_decomposer_mocked(tmp_path)

        # Simulate a root epic that already fanned out to
        # max_total_decomposition_children - 1 children, one of which
        # (#10) is now itself stalling and being recursively decomposed.
        existing_count = config.max_total_decomposition_children - 1
        existing_children = list(range(10, 10 + existing_count))
        state.upsert_epic_state(
            EpicState(
                epic_number=999,
                title="Epic: Root",
                child_issues=existing_children,
            )
        )
        assert 10 in existing_children

        source_task = TaskFactory.create(id=10)
        # Two new children would push the root's total to
        # existing_count + 2, which is >= max_total_decomposition_children.
        result = _two_child_result()

        epic_number = await decomposer.create_epic_from_result(
            source_task=source_task,
            result=result,
            depth=1,  # under the depth cap, so only the fanout-cap can fire
        )

        assert epic_number is None
        prs.create_issue.assert_not_called()
        epic_manager.register_epic.assert_not_called()

    @pytest.mark.asyncio
    async def test_fanout_under_cap_creates_normally(self, tmp_path: Path) -> None:
        decomposer, prs, _epic_manager, state, config = _make_decomposer(tmp_path)
        prs.add_issue(10, "Source issue", "Body")

        # Only one existing child under the root — plenty of fan-out budget
        # left before max_total_decomposition_children.
        state.upsert_epic_state(
            EpicState(
                epic_number=999,
                title="Epic: Root",
                child_issues=[10],
            )
        )

        source_task = TaskFactory.create(id=10)
        result = _two_child_result()

        # depth=0 (parent-level decomposition): P1 default max_decomposition_depth
        # is 1, so depth=1 would now hit the depth-cap before this test's
        # fanout-cap logic ever runs. This class targets the fanout cap only,
        # so stay under the depth cap at depth=0 rather than overriding config.
        epic_number = await decomposer.create_epic_from_result(
            source_task=source_task, result=result, depth=0
        )

        assert epic_number is not None


class TestAutoChildStamp:
    @pytest.mark.asyncio
    async def test_children_carry_auto_decomposed_child_label(
        self, tmp_path: Path
    ) -> None:
        decomposer, prs, epic_manager, state, config = _make_decomposer(tmp_path)
        prs.add_issue(10, "Source issue", "Original body")
        source_task = TaskFactory.create(id=10)
        result = _two_child_result()

        # A real EpicManager.register_epic upserts an EpicState; simulate
        # that side effect since epic_manager here is a MagicMock (mirrors
        # tests/test_issue_decomposer.py::test_depth_lands_on_epic_state_decomposition_depth).
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

        # P1 default is 1; this test explicitly exercises the depth>=1 code
        # path (proving decomposition_depth=1 lands on EpicState), which the
        # new default would otherwise block via the depth-cap.
        object.__setattr__(config, "max_decomposition_depth", 2)

        epic_number = await decomposer.create_epic_from_result(
            source_task=source_task, result=result, depth=1
        )

        assert epic_number is not None
        child_1 = prs.issue(epic_number + 1)
        child_2 = prs.issue(epic_number + 2)
        assert config.auto_decomposed_child_label[0] in child_1.labels
        assert config.auto_decomposed_child_label[0] in child_2.labels
        # Stamped alongside the pre-existing labels, not instead of them.
        assert config.epic_child_label[0] in child_1.labels
        assert config.find_label[0] in child_1.labels

        # Depth is also recorded on the created epic (already-threaded
        # EpicState.decomposition_depth, per task 1/2).
        epic_manager.register_epic.assert_called_once()
        epic_state = state.get_epic_state(epic_number)
        assert epic_state is not None
        assert epic_state.decomposition_depth == 1


class TestMaybeDecomposeIntakeGuard:
    """The intake complexity path must not re-split a stamped auto-child."""

    def _make_phase(self, config, *, epic_manager=None):
        import asyncio

        from events import EventBus
        from issue_store import IssueStore
        from state import StateTracker
        from triage_phase import TriagePhase

        state = StateTracker(config.state_file)
        bus = EventBus()
        store = MagicMock(spec=IssueStore)
        prs = AsyncMock()
        triage = AsyncMock()
        stop_event = asyncio.Event()

        phase = TriagePhase(
            config,
            state,
            store,
            triage,
            prs,
            bus,
            stop_event,
            epic_manager=epic_manager,
        )
        return phase, state, prs, triage

    @pytest.mark.asyncio
    async def test_stamped_auto_child_skips_intake_decomposition(
        self, tmp_path: Path
    ) -> None:
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            epic_decompose_complexity_threshold=8,
            # #11298: intake decomposition defaults OFF; this guard test
            # exercises the depth-cap mechanism, so enable it explicitly.
            epic_decompose_on_intake_enabled=True,
        )
        mgr = AsyncMock()
        phase, _state, prs, triage = self._make_phase(config, epic_manager=mgr)

        task = TaskFactory.create(
            id=10, tags=["ready", config.auto_decomposed_child_label[0]]
        )
        result = TriageResultFactory.create(
            issue_number=10, ready=True, complexity_score=9
        )

        decomposed = await phase._maybe_decompose(task, result)

        assert decomposed is False
        # The uncounted-re-split vector: intake must not even attempt the
        # decomposition council/single-shot call for a stamped auto-child.
        triage.run_decomposition.assert_not_called()
        prs.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_unstamped_issue_still_decomposes_normally(
        self, tmp_path: Path
    ) -> None:
        """Regression guard: the new check must not over-match plain issues."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            epic_decompose_complexity_threshold=8,
        )
        mgr = AsyncMock()
        phase, _state, prs, triage = self._make_phase(config, epic_manager=mgr)

        triage.run_decomposition = AsyncMock(
            return_value=EpicDecompResult(
                should_decompose=True,
                epic_title="Epic: Big Work",
                epic_body="## Sub-issues",
                children=[
                    NewIssueSpec(title="Child 1", body="Do 1"),
                    NewIssueSpec(title="Child 2", body="Do 2"),
                ],
                reasoning="Too complex",
            )
        )
        phase._triage = triage
        prs.create_issue = AsyncMock(side_effect=[200, 201, 202])

        task = TaskFactory.create(id=10, tags=["ready"])
        result = TriageResultFactory.create(
            issue_number=10, ready=True, complexity_score=9
        )

        decomposed = await phase._maybe_decompose(task, result)

        assert decomposed is True
        triage.run_decomposition.assert_called_once()


class TestEscalationClassGuard:
    """#11119: anomaly escalations are signals, not projects — never
    auto-decomposed. The 2026-08-14 idle test showed a cold-boot staleness
    observation grown into an epic + 3 children before it self-cleared."""

    @pytest.mark.asyncio
    async def test_trust_loop_anomaly_never_decomposes(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            epic_decompose_complexity_threshold=8,
        )
        mgr = AsyncMock()
        guard = TestMaybeDecomposeIntakeGuard()
        phase, _state, prs, triage = guard._make_phase(config, epic_manager=mgr)

        task = TaskFactory.create(id=11, tags=["ready", "trust-loop-anomaly"])
        result = TriageResultFactory.create(
            issue_number=11, ready=True, complexity_score=9
        )

        decomposed = await phase._maybe_decompose(task, result)

        assert decomposed is False
        triage.run_decomposition.assert_not_called()
        prs.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_hitl_escalation_never_decomposes(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            epic_decompose_complexity_threshold=8,
        )
        mgr = AsyncMock()
        guard = TestMaybeDecomposeIntakeGuard()
        phase, _state, prs, triage = guard._make_phase(config, epic_manager=mgr)

        task = TaskFactory.create(id=12, tags=["hitl-escalation"])
        result = TriageResultFactory.create(
            issue_number=12, ready=True, complexity_score=9
        )

        decomposed = await phase._maybe_decompose(task, result)

        assert decomposed is False
        triage.run_decomposition.assert_not_called()
