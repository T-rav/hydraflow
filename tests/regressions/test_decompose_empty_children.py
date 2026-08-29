"""Regression: IssueDecomposer must not silently drop the source issue.

Two code-review findings on the decompose-to-converge terminal (ADR-0105):

1. If *every* child ``create_issue`` fails, the old code still registered an
   empty epic, closed the source issue, and marked it ``decomposed`` — on the
   stall path this superseded the ``human-required`` escalation, losing the
   work and paging no one. The source must stay open for HITL instead.
2. The ``decomposed`` idempotency marker was written LAST (after the fallible
   ``post_comment``/``close_issue`` gh calls), so a failure there left the
   source un-marked and open — the next tick re-ran the ensemble and created a
   DUPLICATE epic + children. The marker must be set before those side-effects.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from issue_decomposer import IssueDecomposer
from models import EpicDecompResult, NewIssueSpec
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory, make_tracker


def _make_decomposer(tmp_path: Path):
    """IssueDecomposer with an AsyncMock ``prs`` (so create/close calls are
    scriptable) and a real StateTracker (so mark/get_issue_status are real)."""
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    prs = AsyncMock()
    epic_manager = MagicMock()
    epic_manager.register_epic = AsyncMock()
    state = make_tracker(tmp_path)
    return IssueDecomposer(prs, epic_manager, state, config), prs, epic_manager, state


def _two_child_result() -> EpicDecompResult:
    return EpicDecompResult(
        should_decompose=True,
        epic_title="Epic: Big Work",
        epic_body="## Sub-issues",
        children=[
            NewIssueSpec(title="Child 1", body="Do 1"),
            NewIssueSpec(title="Child 2", body="Do 2"),
        ],
        reasoning="Too complex for one pass",
    )


@pytest.mark.asyncio
async def test_all_children_fail_keeps_source_open_for_hitl(tmp_path: Path) -> None:
    decomposer, prs, epic_manager, state = _make_decomposer(tmp_path)
    # Epic issue creates OK (500); BOTH child create_issue calls fail (return 0).
    prs.create_issue = AsyncMock(side_effect=[500, 0, 0])

    source = TaskFactory.create(id=42)
    epic_number = await decomposer.create_epic_from_result(
        source_task=source, result=_two_child_result()
    )

    # Nothing was superseded: no epic registered, SOURCE stays open and
    # unmarked — it falls through to human-required. The just-created epic
    # itself is closed loudly rather than left as orphan litter (#9855:
    # 23 childless epics in one day when child labels broke repo-wide).
    assert epic_number is None
    epic_manager.register_epic.assert_not_awaited()
    prs.close_issue.assert_awaited_once_with(500)  # the orphan epic, NOT #42
    assert state.get_issue_status(42) != "decomposed"


@pytest.mark.asyncio
async def test_decomposed_marker_set_before_fallible_close(tmp_path: Path) -> None:
    decomposer, prs, _epic_manager, state = _make_decomposer(tmp_path)
    prs.create_issue = AsyncMock(side_effect=[500, 101, 102])  # epic + 2 children OK
    prs.close_issue = AsyncMock(side_effect=RuntimeError("gh transient failure"))

    source = TaskFactory.create(id=42)
    with pytest.raises(RuntimeError):
        await decomposer.create_epic_from_result(
            source_task=source, result=_two_child_result()
        )

    # The marker was written BEFORE close_issue, so a retry sees "decomposed"
    # and does not create a duplicate epic — despite the close failing.
    assert state.get_issue_status(42) == "decomposed"
