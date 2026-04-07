"""Tests for the RetrospectiveLoop background worker."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


class TestRetrospectiveIntervalConfig:
    def test_default_interval(self) -> None:
        from config import HydraFlowConfig

        cfg = HydraFlowConfig()
        assert cfg.retrospective_interval == 1800

    def test_rejects_below_minimum(self) -> None:
        from config import HydraFlowConfig

        with pytest.raises(ValidationError):
            HydraFlowConfig(retrospective_interval=10)

    def test_accepts_valid_value(self) -> None:
        from config import HydraFlowConfig

        cfg = HydraFlowConfig(retrospective_interval=3600)
        assert cfg.retrospective_interval == 3600
