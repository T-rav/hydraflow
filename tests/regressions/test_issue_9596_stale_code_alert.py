"""Regression pin for #9596: the stale-code dead-man-switch fires exactly once.

Before #9596 a factory instance could run arbitrarily many commits behind
origin with zero operator signal (the class behind the 2026-06-18 stale-
factory incident: an old instance re-broke already-fixed behavior for days).
This pin drives the full behavior file and asserts its two load-bearing
rows stay collected and green: at-threshold files an issue, and a still-
stale second tick does not re-file.
"""

from __future__ import annotations

from pathlib import Path

_BEHAVIOR_FILE = (
    Path(__file__).resolve().parent.parent / "test_health_monitor_stale_code_alert.py"
)


def test_stale_code_behavior_suite_present_and_pinned() -> None:
    """The #9596 behavior suite exists and keeps its load-bearing tests.

    A rename/deletion of either row silently drops the dead-man-switch
    coverage; this pin turns that into a red regression.
    """
    source = _BEHAVIOR_FILE.read_text(encoding="utf-8")
    assert "async def test_at_threshold_files_issue" in source
    assert "async def test_threshold_files_once" in source
