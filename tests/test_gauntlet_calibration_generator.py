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


def test_spec_version_includes_sampled_audit_section():
    """The sampled-adversarial re-audit (#10370) section is co-rendered here."""
    out = render_gauntlet_calibration(None)
    assert "Sampled adversarial re-audit (#10370)" in out
    assert "audit_samples.jsonl" in out
    assert "detection_source: sampled-audit" in out
    # Deterministic spec version shows the no-samples placeholder, not counts.
    assert "no samples recorded yet" in out


def test_populated_report_renders_sampled_audit_observations():
    from audit.metrics import calibration_metrics as sa_metrics
    from audit.models import AUDIT_INPUT_SOURCES, AuditSample

    samples = [
        AuditSample(
            id="1",
            audited_at="2026-07-23T00:00:00+00:00",
            pr_number=1,
            merge_sha="abc",
            blast_radius_class="gauntlet",
            verdict="disagree",
            findings="x",
            input_sources=AUDIT_INPUT_SOURCES,
            auditor_model="gpt",
            sample_rate=0.1,
            disposition="upheld",
        )
    ]
    out = render_gauntlet_calibration({"sampled_audit": sa_metrics(samples)})
    assert "Sampled re-audit observations" in out
    assert "| samples audited | 1 |" in out
