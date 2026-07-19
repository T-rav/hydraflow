"""EpicState.decomposition_depth default (decompose-to-converge)."""

from __future__ import annotations

from models import EpicState


def test_decomposition_depth_defaults_to_zero() -> None:
    state = EpicState(epic_number=100, child_issues=[1, 2])
    assert state.decomposition_depth == 0


def test_decomposition_depth_accepts_explicit_value() -> None:
    state = EpicState(epic_number=100, child_issues=[1, 2], decomposition_depth=1)
    assert state.decomposition_depth == 1
