"""Tests for issue_state.py — the single owner of the closed-issue vocabulary.

Regression pin for #11458: the set of ``PRPort.get_issue_state`` values that
mean "closed" used to be written out independently in four places
(regression_rot_scan, gate_health_loop, epic, workspace_gc_loop), and they
disagreed on whether the raw REST ``CLOSED`` value belongs. These tests pin
the one owned predicate so a future vocabulary change has exactly one site
to edit.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from issue_state import RESOLVED_ISSUE_STATES, issue_state_is_resolved


@pytest.mark.parametrize("state", ["COMPLETED", "NOT_PLANNED"])
def test_terminal_states_read_as_resolved(state: str) -> None:
    assert issue_state_is_resolved(state) is True


@pytest.mark.parametrize(
    "state",
    ["OPEN", "UNKNOWN", "", "REOPENED", "garbage"],
)
def test_non_terminal_states_read_as_unresolved(state: str) -> None:
    assert issue_state_is_resolved(state) is False


def test_raw_closed_is_not_resolved() -> None:
    """Raw REST ``CLOSED`` never escapes ``PRPort.get_issue_state``.

    ``PRManager.get_issue_state`` maps ``CLOSED`` to its ``stateReason``
    (``COMPLETED`` / ``NOT_PLANNED`` / ``""``) before returning, so ``CLOSED``
    is deliberately absent from the vocabulary — the two historical call
    sites that included it were defending an unreachable value.
    """
    assert issue_state_is_resolved("CLOSED") is False


def test_input_is_coerced_to_uppercase() -> None:
    assert issue_state_is_resolved("completed") is True
    assert issue_state_is_resolved("Not_Planned") is True


def test_non_string_input_fails_open() -> None:
    """A garbage read (unconfigured ``AsyncMock`` port yields a ``MagicMock``)
    must read as not-resolved, never crash — so a state re-check built on the
    predicate never blocks or files on a broken read."""
    assert issue_state_is_resolved(None) is False
    assert issue_state_is_resolved(MagicMock()) is False


def test_vocabulary_is_exactly_completed_and_not_planned() -> None:
    assert frozenset({"COMPLETED", "NOT_PLANNED"}) == RESOLVED_ISSUE_STATES


def test_predicate_is_reexported_from_phase_utils() -> None:
    """#11457's pins patch imports the predicate from ``phase_utils`` by name;
    the re-export must keep that import surface resolving to the same owner."""
    from phase_utils import issue_state_is_resolved as via_phase_utils

    assert via_phase_utils is issue_state_is_resolved
