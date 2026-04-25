"""Spec §7 line 1612 — unit tests for the two product-phase evaluator skills.

The deeper unit tests live in:
- ``tests/test_discover_completeness_skill.py``
- ``tests/test_shape_coherence_skill.py``

This file provides the spec-named entry-point: high-level wiring + smoke
tests that prove both skills are registered, callable, and surface a
verdict the runners can act on. Adding a third evaluator? Add a row
here too — that gives the §7 audit a single place to verify the set is
complete without grepping the registry.
"""

from __future__ import annotations

import pytest


def test_discover_completeness_skill_registered() -> None:
    """The Discover phase's evaluator skill must be in the registry so
    the runner can dispatch it."""
    from skill_registry import BUILTIN_SKILLS

    names = {s.name for s in BUILTIN_SKILLS}
    assert "discover-completeness" in names, (
        "discover-completeness skill missing from BUILTIN_SKILLS — "
        "DiscoverRunner.run_turn cannot dispatch the evaluator"
    )


def test_shape_coherence_skill_registered() -> None:
    """The Shape phase's evaluator skill must be in the registry."""
    from skill_registry import BUILTIN_SKILLS

    names = {s.name for s in BUILTIN_SKILLS}
    assert "shape-coherence" in names, (
        "shape-coherence skill missing from BUILTIN_SKILLS — "
        "ShapeRunner.run_turn cannot dispatch the evaluator"
    )


@pytest.mark.parametrize(
    "skill_name",
    ["discover-completeness", "shape-coherence"],
)
def test_evaluator_skill_has_prompt_builder(skill_name: str) -> None:
    """Both evaluator skills must have a callable prompt_builder; missing
    it would mean the LLM gets no rubric and returns garbage."""
    from skill_registry import BUILTIN_SKILLS

    skill = next((s for s in BUILTIN_SKILLS if s.name == skill_name), None)
    assert skill is not None, f"skill {skill_name!r} not found"
    assert callable(skill.prompt_builder), (
        f"skill {skill_name!r} has no callable prompt_builder"
    )


@pytest.mark.parametrize(
    "skill_name",
    ["discover-completeness", "shape-coherence"],
)
def test_evaluator_skill_has_result_parser(skill_name: str) -> None:
    """Result parser must be callable; without it the runner can't read
    the verdict back from the LLM response."""
    from skill_registry import BUILTIN_SKILLS

    skill = next((s for s in BUILTIN_SKILLS if s.name == skill_name), None)
    assert skill is not None, f"skill {skill_name!r} not found"
    assert callable(skill.result_parser), (
        f"skill {skill_name!r} has no callable result_parser"
    )
