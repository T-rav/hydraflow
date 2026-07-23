"""Unit tests for the gauntlet-calibration report generator (#10371)."""

from __future__ import annotations

import judge_independence as ji
from arch.generators.gauntlet_calibration import render_gauntlet_calibration


def test_spec_version_is_deterministic_and_self_describing():
    a = render_gauntlet_calibration(None)
    b = render_gauntlet_calibration(None)
    assert a == b  # deterministic — no runtime data baked in
    assert "Disagreement by family" in a
    assert "Fail-closed for self-modification" in a
    assert "no observations recorded yet" in a


def test_populated_report_renders_disagreement_by_family():
    metrics = {
        "classed_verdicts": 3,
        "independent_verdicts": 2,
        "pct_independent": 66.7,
        "fail_open_total": 5,
        "fail_open_ucl": 4.2,
        "fail_open_rate_breached": True,
        "independence_unavailable_total": 1,
        "disagreement_by_family": {"openai": {"verdicts": 2, "dissents": 1}},
    }
    out = render_gauntlet_calibration(metrics)
    assert "| openai | 2 | 1 |" in out
    assert "66.7" in out
    assert "| fail-open rate breached | True |" in out


def test_generator_consumes_calibration_metrics_shape():
    # Wiring check: the metrics dict the module produces renders without error.
    out = render_gauntlet_calibration(ji.calibration_metrics([]))
    assert "Gauntlet Calibration" in out
