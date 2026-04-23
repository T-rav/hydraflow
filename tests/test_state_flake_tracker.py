"""Tests for FlakeTrackerStateMixin."""

from __future__ import annotations

from pathlib import Path

from state import StateTracker


def _tracker(tmp_path: Path) -> StateTracker:
    return StateTracker(state_file=tmp_path / "state.json")


def test_set_and_get_flake_counts(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    st.set_flake_counts({"tests/foo.py::test_bar": 4})
    assert st.get_flake_counts() == {"tests/foo.py::test_bar": 4}


def test_inc_flake_attempts_is_monotonic(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    assert st.get_flake_attempts("tests/foo.py::test_bar") == 0
    st.inc_flake_attempts("tests/foo.py::test_bar")
    st.inc_flake_attempts("tests/foo.py::test_bar")
    assert st.get_flake_attempts("tests/foo.py::test_bar") == 2


def test_clear_flake_attempts(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    st.inc_flake_attempts("tests/foo.py::test_bar")
    st.clear_flake_attempts("tests/foo.py::test_bar")
    assert st.get_flake_attempts("tests/foo.py::test_bar") == 0
