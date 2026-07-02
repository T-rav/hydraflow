"""StateTracker disturbance-dampener attempt-counter tests."""

from __future__ import annotations

from pathlib import Path

from tests.helpers import make_tracker


def test_attempts_bump_and_persist(tmp_path: Path) -> None:
    tracker = make_tracker(tmp_path)
    key = "disturbance:suppressions:src/a.py"
    assert tracker.get_disturbance_dampener_attempts(key) == 0
    assert tracker.bump_disturbance_dampener_attempts(key) == 1
    assert tracker.bump_disturbance_dampener_attempts(key) == 2

    reloaded = make_tracker(tmp_path)
    reloaded.load()
    assert reloaded.get_disturbance_dampener_attempts(key) == 2
    reloaded.clear_disturbance_dampener_attempts(key)
    assert reloaded.get_disturbance_dampener_attempts(key) == 0
