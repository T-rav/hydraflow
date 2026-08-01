"""Issue #9717: env-combo role model clobbered by the group cascade.

``_apply_env_overrides`` sets combo env vars via ``object.__setattr__``,
which bypasses ``__pydantic_fields_set__``; ``_apply_profile_overrides``
then sees the field as non-explicit and — when the env-set value equals the
field default — the BACKGROUND/SYSTEM cascade silently overwrites the
operator's explicit per-role choice.
"""

from __future__ import annotations

import os
from unittest.mock import patch

from config import HydraFlowConfig


def test_explicit_report_issue_combo_survives_background_cascade() -> None:
    """The original report: HYDRAFLOW_REPORT_ISSUE=claude:opus (== defaults)
    + HYDRAFLOW_BACKGROUND=claude:sonnet must keep report_issue on opus."""
    with patch.dict(
        os.environ,
        {
            "HYDRAFLOW_REPORT_ISSUE": "claude:opus",
            "HYDRAFLOW_BACKGROUND": "claude:sonnet",
        },
        clear=False,
    ):
        cfg = HydraFlowConfig()
        assert cfg.report_issue_tool == "claude"
        assert cfg.report_issue_model == "opus"
        # The cascade must still reach roles WITHOUT an explicit combo.
        assert cfg.adr_review_model == "sonnet"


def test_explicit_planner_combo_survives_system_cascade() -> None:
    """Same class under the SYSTEM cascade: planner_model default is opus."""
    with patch.dict(
        os.environ,
        {
            "HYDRAFLOW_PLANNER": "claude:opus",
            "HYDRAFLOW_SYSTEM": "claude:sonnet",
        },
        clear=False,
    ):
        cfg = HydraFlowConfig()
        assert cfg.planner_tool == "claude"
        assert cfg.planner_model == "opus"
        # Non-explicit system-family roles still cascade.
        assert cfg.review_model == "sonnet"


def test_combo_env_fields_registered_as_explicit() -> None:
    """Combo-set fields must land in __pydantic_fields_set__ — that is the
    signal _apply_profile_overrides uses to respect operator choices."""
    with patch.dict(os.environ, {"HYDRAFLOW_REPORT_ISSUE": "claude:opus"}, clear=False):
        cfg = HydraFlowConfig()
        assert "report_issue_tool" in cfg.__pydantic_fields_set__
        assert "report_issue_model" in cfg.__pydantic_fields_set__
