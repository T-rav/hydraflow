"""Issue #10657: PATCH /api/control/config silently reverts a combo-covered
model/tool edit to the ``HYDRAFLOW_*`` env value.

``_ENV_COMBO_OVERRIDES`` was the only ``_ENV_*`` table whose loop did not guard
on "the field is still at its declared default / was not explicitly supplied".
Every other override table applies the env value only when the operator did NOT
supply one; the combo loop applied it unconditionally. Because
``patch_config`` re-validates through ``HydraFlowConfig.model_validate(...)``
(which re-runs the combo loop) and reads the value back off the validated
model, a matching env var silently clobbered the operator's edit — the UI
showed a green ``live`` badge for a change that never took effect.

Expected precedence: an explicitly supplied value (CLI kwarg, config file, or
PATCH) beats the matching ``HYDRAFLOW_*`` env var.
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from config import HydraFlowConfig
from tests.helpers import find_endpoint, make_dashboard_router


def test_explicit_review_model_kwarg_beats_combo_env() -> None:
    """The issue's exact repro: with HYDRAFLOW_REVIEW=claude:sonnet in the
    environment, an explicit ``review_model="opus"`` must win, not revert to
    the env's ``sonnet``."""
    with patch.dict(os.environ, {"HYDRAFLOW_REVIEW": "claude:sonnet"}, clear=False):
        cfg = HydraFlowConfig(review_model="opus")
        assert cfg.review_model == "opus"


def test_explicit_model_kwarg_beats_implement_combo_env() -> None:
    """A second combo field (HYDRAFLOW_IMPLEMENT -> model) exercises the same
    precedence: explicit ``model`` beats the env-declared model."""
    with patch.dict(
        os.environ, {"HYDRAFLOW_IMPLEMENT": "codex:gpt-5-codex"}, clear=False
    ):
        cfg = HydraFlowConfig(implementation_tool="codex", model="gpt-5-nano")
        assert cfg.model == "gpt-5-nano"
        assert cfg.implementation_tool == "codex"


def test_combo_env_still_applies_when_no_explicit_value() -> None:
    """Guard-rail: the fix must NOT disable env overrides for the pure-env
    case. With no explicit kwarg, the env value still wins."""
    with patch.dict(os.environ, {"HYDRAFLOW_REVIEW": "claude:sonnet"}, clear=False):
        cfg = HydraFlowConfig()
        assert cfg.review_tool == "claude"
        assert cfg.review_model == "sonnet"


@pytest.mark.asyncio
async def test_patch_config_edit_beats_env_for_combo_field(
    config, event_bus, state, tmp_path
) -> None:
    """The operator-facing symptom: PATCH /api/control/config editing a
    combo-covered field WITH its env var set returns the edited value, not the
    env value."""
    router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
    patch_config = find_endpoint(router, "/api/control/config")
    assert patch_config is not None

    with patch.dict(os.environ, {"HYDRAFLOW_REVIEW": "claude:sonnet"}, clear=False):
        response = await patch_config({"review_model": "opus"})

    data = json.loads(response.body)
    assert data["status"] == "ok"
    assert data["updated"]["review_model"] == "opus"
    assert config.review_model == "opus"
