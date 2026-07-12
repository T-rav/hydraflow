"""Decomposition depth + fan-out cap config field defaults (decompose-to-converge)."""

from __future__ import annotations

from config import HydraFlowConfig


def test_decomposition_knob_defaults() -> None:
    c = HydraFlowConfig()
    assert c.max_decomposition_depth == 2
    assert c.max_total_decomposition_children == 8


def test_env_override(monkeypatch) -> None:
    monkeypatch.setenv("HYDRAFLOW_MAX_DECOMPOSITION_DEPTH", "3")
    assert HydraFlowConfig().max_decomposition_depth == 3
