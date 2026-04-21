"""Tests for plugin_skill_registry.skills_for_phase."""

from __future__ import annotations

import pytest

from plugin_skill_registry import PHASE_NAMES, PluginSkill, skills_for_phase


def _make_skills() -> list[PluginSkill]:
    return [
        PluginSkill(
            plugin="superpowers", name="test-driven-development", description="TDD"
        ),
        PluginSkill(
            plugin="superpowers", name="systematic-debugging", description="Debug"
        ),
        PluginSkill(plugin="code-review", name="code-review", description="Review"),
    ]


def test_phase_names_are_frozen():
    assert (
        frozenset({"triage", "discover", "shape", "planner", "agent", "reviewer"})
        == PHASE_NAMES
    )


def test_intersection_returns_only_whitelisted():
    phase_skills = {"agent": ["superpowers:test-driven-development"]}
    out = skills_for_phase("agent", _make_skills(), phase_skills)
    assert [s.qualified_name for s in out] == ["superpowers:test-driven-development"]


def test_preserves_whitelist_order_not_discovery_order():
    phase_skills = {
        "agent": [
            "code-review:code-review",
            "superpowers:test-driven-development",
        ]
    }
    out = skills_for_phase("agent", _make_skills(), phase_skills)
    assert [s.qualified_name for s in out] == [
        "code-review:code-review",
        "superpowers:test-driven-development",
    ]


def test_missing_from_discovery_silently_omitted():
    phase_skills = {
        "agent": [
            "superpowers:test-driven-development",
            "nonexistent:skill",
        ]
    }
    out = skills_for_phase("agent", _make_skills(), phase_skills)
    assert [s.qualified_name for s in out] == ["superpowers:test-driven-development"]


def test_empty_whitelist_returns_empty_list():
    out = skills_for_phase("triage", _make_skills(), {"triage": []})
    assert out == []


def test_missing_phase_key_returns_empty_list():
    # Phase is valid but config omits it → empty, don't crash.
    out = skills_for_phase("agent", _make_skills(), {})
    assert out == []


def test_unknown_phase_name_raises():
    with pytest.raises(ValueError, match="unknown phase"):
        skills_for_phase("bogus", _make_skills(), {"bogus": []})
