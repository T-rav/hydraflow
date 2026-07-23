"""Regression pins for #9597: the regression-rot detector's two verdicts.

Before #9597, a RED xfail pin whose issue was closed (false-close rot) or
whose issue sat open past the staleness window (orphaned-RED) produced no
signal anywhere. These pins assert the behavior suite keeps both verdict
rows collected — renaming or deleting either silently drops the coverage.
"""

from __future__ import annotations

from pathlib import Path

_SCAN_TESTS = Path(__file__).resolve().parent.parent / "test_regression_rot_scan.py"


def test_rot_verdict_suite_present_and_pinned() -> None:
    source = _SCAN_TESTS.read_text(encoding="utf-8")
    assert "false_close" in source
    assert "orphaned" in source
