"""Regression (#9757): closing a decompose replacement epic cascades to its
parent, and recurses up the parent_epic chain for N-level convergence.

E1 (#2) has children [#3, #4]; #4 is done. #3 was decomposed into replacement
epic E2 (#5, children [#6, #7]) with parent_epic=2, superseded_issue=3. When
#6/#7 complete, E2 auto-closes → propagation marks #3 done in E1 → E1 closes.
Depth-3 adds E3 (#8) replacing a child of E2 to prove the chain recurses.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from epic import EpicManager
from models import EpicState
from tests.helpers import ConfigFactory, make_tracker


def _manager(tmp_path: Path):
    config = ConfigFactory.create(epic_label=["hydraflow-epic"])
    state = make_tracker(tmp_path)
    prs = AsyncMock()
    fetcher = AsyncMock()
    fetcher.fetch_issues_by_labels = AsyncMock(return_value=[])
    fetcher.fetch_issue_by_number = AsyncMock(return_value=None)  # → direct close path
    bus = AsyncMock()
    manager = EpicManager(config, state, prs, fetcher, bus)
    return manager, state


@pytest.mark.asyncio
async def test_replacement_epic_close_cascades_to_parent(tmp_path: Path):
    manager, state = _manager(tmp_path)
    # E1: children [3, 4]; #4 already completed.
    state.upsert_epic_state(
        EpicState(epic_number=2, child_issues=[3, 4], completed_children=[4])
    )
    # E2: replacement of #3 (a child of E1), children [6, 7].
    state.upsert_epic_state(
        EpicState(epic_number=5, child_issues=[6, 7], parent_epic=2, superseded_issue=3)
    )

    await manager.on_child_completed(5, 6)
    await manager.on_child_completed(5, 7)  # E2 all done → closes → cascades

    assert state.get_epic_state(5).closed is True
    assert state.get_epic_state(2).closed is True  # root converged, not prematurely


@pytest.mark.asyncio
async def test_cascade_recurses_three_levels(tmp_path: Path):
    manager, state = _manager(tmp_path)
    # E1 (#2) child [3] (only child) — #3 decomposed into E2.
    state.upsert_epic_state(EpicState(epic_number=2, child_issues=[3]))
    # E2 (#5) child [6] — #6 decomposed into E3. E2 replaces #3 under E1.
    state.upsert_epic_state(
        EpicState(epic_number=5, child_issues=[6], parent_epic=2, superseded_issue=3)
    )
    # E3 (#8) children [9, 10] — replaces #6 under E2.
    state.upsert_epic_state(
        EpicState(
            epic_number=8, child_issues=[9, 10], parent_epic=5, superseded_issue=6
        )
    )

    await manager.on_child_completed(8, 9)
    await manager.on_child_completed(8, 10)  # E3 closes → E2 → E1

    assert state.get_epic_state(8).closed is True
    assert state.get_epic_state(5).closed is True
    assert state.get_epic_state(2).closed is True


@pytest.mark.asyncio
async def test_propagation_fires_from_checker_success_close_path(tmp_path: Path):
    """`_propagate_epic_close` is hooked into BOTH of `_try_auto_close`'s close
    paths. The other tests exercise the direct-close path (checker returns None);
    this one forces the checker-SUCCESS path (close_specific_epic → True) so that
    site is covered too."""
    manager, state = _manager(tmp_path)
    # Force the checker-success branch: close_specific_epic returns True.
    manager._checker.close_specific_epic = AsyncMock(return_value=True)
    state.upsert_epic_state(
        EpicState(epic_number=2, child_issues=[3, 4], completed_children=[4])
    )
    state.upsert_epic_state(
        EpicState(epic_number=5, child_issues=[6, 7], parent_epic=2, superseded_issue=3)
    )

    await manager.on_child_completed(5, 6)
    await manager.on_child_completed(5, 7)  # E2 closes via checker-success → cascades

    assert state.get_epic_state(5).closed is True
    assert state.get_epic_state(2).closed is True
