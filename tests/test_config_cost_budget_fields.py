"""Tests for daily_cost_budget_usd / issue_cost_alert_usd config fields.

Spec: §4.11 point 6 — cost-budget alerts.
"""

from __future__ import annotations

import pytest

from config import HydraFlowConfig


def test_defaults_are_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HYDRAFLOW_DAILY_COST_BUDGET_USD", raising=False)
    monkeypatch.delenv("HYDRAFLOW_ISSUE_COST_ALERT_USD", raising=False)
    cfg = HydraFlowConfig()
    assert cfg.daily_cost_budget_usd is None
    assert cfg.issue_cost_alert_usd is None


def test_env_override_parses_float(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYDRAFLOW_DAILY_COST_BUDGET_USD", "5.0")
    monkeypatch.setenv("HYDRAFLOW_ISSUE_COST_ALERT_USD", "1.25")
    cfg = HydraFlowConfig()
    assert cfg.daily_cost_budget_usd == pytest.approx(5.0)
    assert cfg.issue_cost_alert_usd == pytest.approx(1.25)


def test_env_override_empty_string_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYDRAFLOW_DAILY_COST_BUDGET_USD", "")
    monkeypatch.delenv("HYDRAFLOW_ISSUE_COST_ALERT_USD", raising=False)
    cfg = HydraFlowConfig()
    assert cfg.daily_cost_budget_usd is None


def test_env_override_invalid_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYDRAFLOW_ISSUE_COST_ALERT_USD", "not-a-number")
    monkeypatch.delenv("HYDRAFLOW_DAILY_COST_BUDGET_USD", raising=False)
    cfg = HydraFlowConfig()
    assert cfg.issue_cost_alert_usd is None


def test_negative_value_rejected() -> None:
    """Pydantic ge=0.0 should reject a negative direct assignment."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        HydraFlowConfig(daily_cost_budget_usd=-1.0)
