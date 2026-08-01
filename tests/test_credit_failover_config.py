"""Config surface for credit-failover to GLM (#10844)."""

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


def test_credit_failover_enabled_defaults_on(tmp_path: Path) -> None:
    assert _cfg(tmp_path).credit_failover_enabled is True


def test_credit_failover_model_defaults_glm(tmp_path: Path) -> None:
    assert _cfg(tmp_path).credit_failover_model == "glm-5.2"


def test_credit_failover_cooldown_defaults_15(tmp_path: Path) -> None:
    assert _cfg(tmp_path).credit_failover_cooldown_minutes == 15


def test_credit_failover_model_must_be_glm(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _cfg(tmp_path, credit_failover_model="claude-opus-4-8")


def test_credit_failover_cooldown_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _cfg(tmp_path, credit_failover_cooldown_minutes=0)


def test_credit_failover_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HYDRAFLOW_CREDIT_FAILOVER_ENABLED", "false")
    assert _cfg(tmp_path).credit_failover_enabled is False
