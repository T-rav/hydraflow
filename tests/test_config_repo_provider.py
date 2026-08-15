"""Config surface for per-repo model/harness selection (#11211)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from config import HydraFlowConfig


def _cfg(tmp_path: Path, **over: object) -> HydraFlowConfig:
    return HydraFlowConfig(
        repo_root=tmp_path,
        workspace_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
        **over,
    )


def test_repo_provider_defaults_claude(tmp_path: Path) -> None:
    assert _cfg(tmp_path).repo_provider == "claude"


def test_repo_model_defaults_empty(tmp_path: Path) -> None:
    assert _cfg(tmp_path).repo_model == ""


def test_repo_provider_accepts_zai(tmp_path: Path) -> None:
    assert _cfg(tmp_path, repo_provider="zai").repo_provider == "zai"


def test_repo_provider_rejects_unknown_value(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _cfg(tmp_path, repo_provider="openrouter")


def test_repo_model_must_be_glm_when_set(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _cfg(tmp_path, repo_model="claude-opus-4-8")


def test_repo_model_glm_value_accepted(tmp_path: Path) -> None:
    assert _cfg(tmp_path, repo_model="glm-5.2").repo_model == "glm-5.2"


def test_repo_model_empty_string_is_valid(tmp_path: Path) -> None:
    # Empty is the "unset — fall back to credit_failover_model" sentinel, not
    # a validation error, unlike a real non-glm model string.
    assert _cfg(tmp_path, repo_model="").repo_model == ""
