# tests/test_prompt_fitness.py
"""Ratcheting floors for the prompt-layer fitness scorecard (ADR-0116 §5).

The completeness ratchet is a gate; this is the measure. Every floor below is
pinned at the value measured on 2026-07-30 and may only move in the improving
direction. A change that worsens any of them fails here, which is what makes
the contract a contract rather than a report nobody reads.

The floors are deliberately unflattering. 96% of scored prompts are High
severity and registry coverage is 30%; pinning the current state stops the drift
that produced it and makes every improvement visible as a floor that moves.

**These are FORM measures.** Per ADR-0116 §6 a rising score is not a quality
claim until the outcome pairing lands, which is why
:func:`prompt_fitness.fitness_summary` carries ``outcome_paired`` and why
:func:`test_form_score_is_not_a_quality_claim` asserts it stays false until
that work is done.
"""

from __future__ import annotations

import pytest

from prompt_fitness import CRITERIA, fitness_summary

# Measured 2026-07-30. Lower the ceilings / raise the floor as prompts improve;
# never the reverse. Raising a ceiling is the defect this file exists to catch.
_MIN_REGISTRY_COVERAGE = 0.30
_MAX_GRANDFATHERED = 30
_MAX_HIGH_SEVERITY_SHARE = 0.96
_MAX_CRITERION_FAIL_RATE: dict[int, float] = {
    1: 0.72,  # leads with the request
    2: 0.24,  # specific over vague
    3: 0.88,  # XML tag structure — the near-universal failure
    4: 0.40,  # examples present
    5: 0.00,  # output contract stated — already clean, must stay clean
    6: 0.08,  # long-context placement
    7: 0.44,  # chain-of-thought scaffold
    8: 0.84,  # edge cases named
}


@pytest.fixture(scope="module")
def fitness():
    return fitness_summary()


def test_registry_coverage_does_not_regress(fitness) -> None:
    assert fitness.registry_coverage >= _MIN_REGISTRY_COVERAGE, (
        f"registry coverage fell to {fitness.registry_coverage:.2%} "
        f"(floor {_MIN_REGISTRY_COVERAGE:.2%}): "
        f"{fitness.registered_modules}/{fitness.discovered_modules} modules. "
        "A new prompt builder was added without a PROMPT_REGISTRY entry."
    )


def test_grandfathered_count_does_not_grow(fitness) -> None:
    assert fitness.grandfathered <= _MAX_GRANDFATHERED, (
        f"_GRANDFATHERED grew to {fitness.grandfathered} (pinned at "
        f"{_MAX_GRANDFATHERED}). Register the builder instead of exempting it."
    )


def test_high_severity_share_does_not_worsen(fitness) -> None:
    assert fitness.high_severity_share <= _MAX_HIGH_SEVERITY_SHARE, (
        f"High-severity share rose to {fitness.high_severity_share:.2%} "
        f"(ceiling {_MAX_HIGH_SEVERITY_SHARE:.2%}). "
        f"Counts: {fitness.severity_counts}."
    )


@pytest.mark.parametrize("criterion", sorted(_MAX_CRITERION_FAIL_RATE))
def test_criterion_fail_rate_does_not_worsen(fitness, criterion: int) -> None:
    ceiling = _MAX_CRITERION_FAIL_RATE[criterion]
    actual = fitness.criterion_fail_rates.get(criterion, 0.0)
    assert actual <= ceiling, (
        f"criterion {criterion} ({CRITERIA[criterion]}) fail rate rose to "
        f"{actual:.2%} (ceiling {ceiling:.2%}). Fix the prompt or record a "
        "decision before raising the ceiling."
    )


def test_every_registered_prompt_actually_scores(fitness) -> None:
    """A fixture that no longer renders drops silently out of the score."""
    assert fitness.scored_prompts >= 25, (
        f"only {fitness.scored_prompts} prompts scored (expected >= 25). A "
        "fixture stopped rendering, so its prompt is now unmeasured — that is "
        "a coverage regression wearing a passing test."
    )


def test_form_score_is_not_a_quality_claim(fitness) -> None:
    """ADR-0116 §6: the rubric measures form, so it needs its outcome pair.

    This asserts the flag exists and is honest. When the outcome join lands,
    flip the expectation and pass ``outcome_paired=True`` from the caller —
    deliberately a test change, so nobody can quietly start treating a form
    score as evidence of quality.
    """
    assert fitness.outcome_paired is False, (
        "outcome_paired is True but the outcome join has not landed. If it "
        "has, update this test and ADR-0116 §6 together."
    )
