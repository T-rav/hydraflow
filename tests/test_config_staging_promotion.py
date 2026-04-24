"""Tests for dx/hydraflow/config.py — staging/RC promotion config fields."""

from __future__ import annotations

from pathlib import Path

import pytest

# conftest.py already inserts the hydraflow package directory into sys.path
from config import HydraFlowConfig


def _make_cfg(tmp_path: Path) -> HydraFlowConfig:
    """Build a minimal HydraFlowConfig for env-override exercise in tests."""
    return HydraFlowConfig(
        repo_root=tmp_path,
        workspace_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
    )


class TestStagingPromotionConfig:
    def test_staging_branch_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HYDRAFLOW_STAGING_BRANCH", raising=False)
        cfg = _make_cfg(tmp_path)
        assert cfg.staging_branch == "staging"

    def test_staging_branch_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_STAGING_BRANCH", "integration")
        cfg = _make_cfg(tmp_path)
        assert cfg.staging_branch == "integration"

    def test_staging_enabled_defaults_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HYDRAFLOW_STAGING_ENABLED", raising=False)
        cfg = _make_cfg(tmp_path)
        assert cfg.staging_enabled is False

    def test_staging_enabled_env_true(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_STAGING_ENABLED", "true")
        cfg = _make_cfg(tmp_path)
        assert cfg.staging_enabled is True

    def test_rc_cadence_hours_defaults_to_4(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HYDRAFLOW_RC_CADENCE_HOURS", raising=False)
        cfg = _make_cfg(tmp_path)
        assert cfg.rc_cadence_hours == 4

    def test_rc_cadence_hours_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_RC_CADENCE_HOURS", "8")
        cfg = _make_cfg(tmp_path)
        assert cfg.rc_cadence_hours == 8

    def test_rc_branch_prefix_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HYDRAFLOW_RC_BRANCH_PREFIX", raising=False)
        cfg = _make_cfg(tmp_path)
        assert cfg.rc_branch_prefix == "rc/"

    def test_staging_promotion_interval_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HYDRAFLOW_STAGING_PROMOTION_INTERVAL", raising=False)
        cfg = _make_cfg(tmp_path)
        assert cfg.staging_promotion_interval == 300

    def test_staging_promotion_interval_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_STAGING_PROMOTION_INTERVAL", "120")
        cfg = _make_cfg(tmp_path)
        assert cfg.staging_promotion_interval == 120

    def test_staging_rc_retention_days_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HYDRAFLOW_STAGING_RC_RETENTION_DAYS", raising=False)
        cfg = _make_cfg(tmp_path)
        assert cfg.staging_rc_retention_days == 7

    def test_staging_rc_retention_days_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_STAGING_RC_RETENTION_DAYS", "14")
        cfg = _make_cfg(tmp_path)
        assert cfg.staging_rc_retention_days == 14

    def test_base_branch_returns_staging_when_enabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_STAGING_ENABLED", "true")
        cfg = _make_cfg(tmp_path)
        assert cfg.base_branch() == "staging"

    def test_base_branch_returns_main_when_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_STAGING_ENABLED", "false")
        cfg = _make_cfg(tmp_path)
        assert cfg.base_branch() == "main"

    def test_staging_bisect_config_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HYDRAFLOW_STAGING_BISECT_INTERVAL", raising=False)
        monkeypatch.delenv(
            "HYDRAFLOW_STAGING_BISECT_RUNTIME_CAP_SECONDS", raising=False
        )
        monkeypatch.delenv("HYDRAFLOW_STAGING_BISECT_WATCHDOG_RC_CYCLES", raising=False)
        cfg = _make_cfg(tmp_path)
        assert cfg.staging_bisect_interval == 600
        assert cfg.staging_bisect_runtime_cap_seconds == 2700
        assert cfg.staging_bisect_watchdog_rc_cycles == 2

    def test_staging_bisect_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_STAGING_BISECT_INTERVAL", "300")
        monkeypatch.setenv("HYDRAFLOW_STAGING_BISECT_RUNTIME_CAP_SECONDS", "600")
        monkeypatch.setenv("HYDRAFLOW_STAGING_BISECT_WATCHDOG_RC_CYCLES", "4")
        cfg = _make_cfg(tmp_path)
        assert cfg.staging_bisect_interval == 300
        assert cfg.staging_bisect_runtime_cap_seconds == 600
        assert cfg.staging_bisect_watchdog_rc_cycles == 4
