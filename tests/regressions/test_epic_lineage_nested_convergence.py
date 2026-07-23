"""Regression (#9757): epic-to-epic lineage for nested decompose-to-converge.

`EpicState` gains `parent_epic`/`superseded_issue` so a decomposed child's
replacement epic is linked back to the child (and its parent epic), letting the
rollup converge nested (depth >= 2) decompositions correctly.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from issue_decomposer import IssueDecomposer
from mockworld.fakes.fake_github import FakeGitHub
from models import EpicDecompResult, EpicState, NewIssueSpec
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory, make_tracker

# --- Task 1: EpicState lineage fields ---


def test_epicstate_lineage_defaults_none():
    e = EpicState(epic_number=5)
    assert e.parent_epic is None
    assert e.superseded_issue is None


def test_epicstate_lineage_roundtrips():
    e = EpicState(epic_number=5, parent_epic=2, superseded_issue=3)
    reloaded = EpicState.model_validate(e.model_dump())
    assert reloaded.parent_epic == 2
    assert reloaded.superseded_issue == 3


# --- Task 2: get_replacement_epic ---


def test_get_replacement_epic(tmp_path: Path):
    state = make_tracker(tmp_path)
    state.upsert_epic_state(EpicState(epic_number=5, superseded_issue=3, parent_epic=2))
    state.upsert_epic_state(EpicState(epic_number=9, superseded_issue=None))
    assert state.get_replacement_epic(3).epic_number == 5
    assert state.get_replacement_epic(999) is None


# --- Task 4: IssueDecomposer stamps lineage ---


def _decomposer(tmp_path):
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    prs = FakeGitHub()
    state = make_tracker(tmp_path)

    # The real EpicManager.register_epic persists an EpicState; the decomposer
    # then reads it back to stamp lineage. Mirror that so the stamp has a state
    # to write to.
    async def _register(epic_num, title, children, auto_decomposed=False):
        state.upsert_epic_state(
            EpicState(epic_number=epic_num, title=title, child_issues=list(children))
        )

    epic_manager = MagicMock()
    epic_manager.register_epic = AsyncMock(side_effect=_register)
    return IssueDecomposer(prs, epic_manager, state, config), state


def _result():
    return EpicDecompResult(
        should_decompose=True,
        epic_title="Epic: split",
        epic_body="## Sub",
        children=[NewIssueSpec(title="A", body="a"), NewIssueSpec(title="B", body="b")],
        reasoning="too broad",
    )


@pytest.mark.asyncio
async def test_stamps_lineage_when_source_is_epic_child(tmp_path):
    decomposer, state = _decomposer(tmp_path)
    # Source issue #3 is a child of an existing epic E1 (#2).
    state.upsert_epic_state(EpicState(epic_number=2, child_issues=[3, 4]))
    e2 = await decomposer.create_epic_from_result(
        source_task=TaskFactory.create(id=3),
        result=_result(),
    )
    replacement = state.get_epic_state(e2)
    assert replacement.parent_epic == 2
    assert replacement.superseded_issue == 3


@pytest.mark.asyncio
async def test_no_lineage_for_top_level_source(tmp_path):
    decomposer, state = _decomposer(tmp_path)
    e2 = await decomposer.create_epic_from_result(
        source_task=TaskFactory.create(id=42),
        result=_result(),
    )
    replacement = state.get_epic_state(e2)
    assert replacement.parent_epic is None
    assert replacement.superseded_issue is None
