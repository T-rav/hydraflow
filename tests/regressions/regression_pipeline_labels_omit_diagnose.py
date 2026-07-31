"""Regression: pipeline-stage cleanup must include the diagnose + parked stages.

``HydraFlowConfig.all_pipeline_labels`` drives ``PRManager.swap_pipeline_labels``
(src/pr_manager.py), which adds the new stage label then strips every OTHER
label in ``all_pipeline_labels``. ``diagnose_label`` ("hydraflow-diagnose") and
``parked_label`` ("hydraflow-parked") were omitted, so a diagnosed/parked issue
never had those cleared on transition — the labels accumulated and jammed the
pipeline. Self-diagnosed on #10785: the diagnose label survived the ready swap,
so the issue carried hitl + diagnose + escalation labels at once and could not
re-enter the pipeline clean.
"""

from __future__ import annotations

from config import HydraFlowConfig


def test_all_pipeline_labels_includes_diagnose_and_parked() -> None:
    cfg = HydraFlowConfig()
    labels = cfg.all_pipeline_labels
    for stage in cfg.diagnose_label + cfg.parked_label:
        assert stage in labels, (
            f"{stage!r} missing from all_pipeline_labels — swap_pipeline_labels "
            f"will never clear it on a stage transition, jamming the pipeline"
        )


def test_all_pipeline_labels_still_covers_the_known_stages() -> None:
    """Guard the rest of the set so the fix doesn't drop an existing stage."""
    cfg = HydraFlowConfig()
    labels = set(cfg.all_pipeline_labels)
    for group in (
        cfg.find_label,
        cfg.planner_label,
        cfg.ready_label,
        cfg.review_label,
        cfg.hitl_label,
        cfg.fixed_label,
        cfg.verify_label,
        cfg.in_progress_label,
    ):
        for lbl in group:
            assert lbl in labels, f"{lbl!r} dropped from all_pipeline_labels"
    assert "human-required" in labels
