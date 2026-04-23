"""Tests for WikiRotDetectorLoop config fields (spec §4.9)."""

from __future__ import annotations

import pytest

from config import HydraFlowConfig


def test_wiki_rot_detector_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HYDRAFLOW_WIKI_ROT_DETECTOR_INTERVAL", raising=False)
    cfg = HydraFlowConfig()
    assert cfg.wiki_rot_detector_interval == 604800


def test_wiki_rot_detector_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYDRAFLOW_WIKI_ROT_DETECTOR_INTERVAL", "86400")
    cfg = HydraFlowConfig()
    assert cfg.wiki_rot_detector_interval == 86400


def test_wiki_rot_detector_interval_bounds() -> None:
    with pytest.raises(ValueError):
        HydraFlowConfig(wiki_rot_detector_interval=30)  # below 86400 minimum
    with pytest.raises(ValueError):
        HydraFlowConfig(wiki_rot_detector_interval=10_000_000)  # above 2_592_000 max
