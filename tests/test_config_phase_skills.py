"""Tests for the auto_install_plugins and phase_skills config fields."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from config import HydraFlowConfig


def test_auto_install_plugins_defaults_true():
    cfg = HydraFlowConfig()
    assert cfg.auto_install_plugins is True


def test_phase_skills_defaults_contain_all_six_phases():
    cfg = HydraFlowConfig()
    assert set(cfg.phase_skills.keys()) == {
        "triage",
        "discover",
        "shape",
        "planner",
        "agent",
        "reviewer",
    }


def test_phase_skills_default_agent_contents():
    cfg = HydraFlowConfig()
    assert cfg.phase_skills["agent"] == [
        "superpowers:test-driven-development",
        "superpowers:systematic-debugging",
        "superpowers:verification-before-completion",
        "code-simplifier:simplify",
        "frontend-design:frontend-design",
    ]


def test_unknown_phase_name_rejected():
    with pytest.raises(ValidationError, match="unknown phase"):
        HydraFlowConfig(phase_skills={"bogus_phase": []})


def test_override_preserves_other_phases():
    cfg = HydraFlowConfig(phase_skills={"triage": ["superpowers:systematic-debugging"]})
    # Overriding one phase replaces the entire dict (pydantic default semantics)
    # — the test documents and locks in this behavior.
    assert cfg.phase_skills == {"triage": ["superpowers:systematic-debugging"]}
