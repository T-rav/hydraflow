# tests/test_prompt_fitness.py
"""Ratcheting floors for the prompt-layer fitness scorecard (ADR-0116 §5).

The completeness ratchet is a gate; this is the measure. Every floor below is
pinned at the value measured on 2026-07-30 and may only move in the improving
direction. A change that worsens any of them fails here, which is what makes
the contract a contract rather than a report nobody reads.

The floors are deliberately unflattering. Registry coverage is now 100% — every
prompt builder in ``src/`` is registered, rendered and scored — but 94.9% of
those 65 prompts are still High severity. Pinning that state stops the drift
that produced it and makes every improvement visible as a floor that moves.

Coverage reaching 100% is the *end of the counting*, not the end of the work:
the fleet's rubric scores are now measured honestly rather than partially.

**These are FORM measures.** Per ADR-0116 §6 a rising score is not a quality
claim until the outcome pairing lands, which is why
:func:`prompt_fitness.fitness_summary` carries ``outcome_paired`` and why
:func:`test_form_score_is_not_a_quality_claim` asserts it stays false until
that work is done.
"""

from __future__ import annotations

import pytest

from prompt_fitness import (
    CRITERIA,
    PROMPT_BASELINE,
    baseline_criterion_fail_rates,
    baseline_high_severity_share,
    fitness_summary,
    per_prompt_scores,
    placeholder_leaks,
    prompt_placeholder_leaks,
    prompt_regressions,
)

# Coverage floor and allowlist ceiling are still pinned constants: they measure
# the size of the gap, which only ever improves deliberately.
_MIN_REGISTRY_COVERAGE = 1.0
_MAX_GRANDFATHERED = 0

# The fleet aggregates are NOT pinned constants any more. A hand-pinned ceiling
# is unstable under coverage changes — registering a newly-measured bad prompt
# raises every average even though nothing regressed, so the only way to keep the
# number green is to raise it, which is indistinguishable from covering up a real
# regression. They are derived from PROMPT_BASELINE instead, so the expectation
# moves only when a baseline entry is added or tightened, and the binding check
# for regression is per-prompt (below).


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


@pytest.mark.parametrize("criterion", sorted(CRITERIA))
def test_criterion_fail_rate_matches_baseline(fitness, criterion: int) -> None:
    """Aggregates must equal what the per-prompt baselines imply.

    Not "<= a ceiling": exact agreement. A drift in either direction means the
    baselines and the measured corpus disagree, which is the state where a
    regression can hide behind an aggregate that still looks acceptable.
    """
    expected = baseline_criterion_fail_rates()[criterion]
    actual = fitness.criterion_fail_rates.get(criterion, 0.0)
    assert actual == pytest.approx(expected, abs=0.001), (
        f"criterion {criterion} ({CRITERIA[criterion]}) fail rate is "
        f"{actual:.2%}, but PROMPT_BASELINE implies {expected:.2%}. Either a "
        "prompt changed without its baseline being updated, or the baseline is "
        "stale. Per-prompt detail is in test_no_prompt_gains_a_failing_criterion."
    )


def test_high_severity_share_matches_baseline(fitness) -> None:
    expected = baseline_high_severity_share()
    assert fitness.high_severity_share == pytest.approx(expected, abs=0.001), (
        f"High-severity share is {fitness.high_severity_share:.2%}, but "
        f"PROMPT_BASELINE implies {expected:.2%}. Counts: "
        f"{fitness.severity_counts}."
    )


def test_every_registered_prompt_actually_scores(fitness) -> None:
    """A fixture that no longer renders drops silently out of the score.

    Derived from the baseline, not a hand-pinned floor. It was pinned at
    ``>= 37`` while 59 prompts actually scored, so 22 could stop rendering
    before it tripped — a floor written the same day it was already stale.
    """
    assert fitness.scored_prompts >= len(PROMPT_BASELINE), (
        f"only {fitness.scored_prompts} prompts scored, but PROMPT_BASELINE "
        f"pins {len(PROMPT_BASELINE)}. A fixture stopped rendering, so its "
        "prompt is now unmeasured — a coverage regression wearing a passing "
        "test."
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


# --------------------------------------------------------------------------
# Per-prompt setpoints (ADR-0116 §5). The floors above are fleet aggregates and
# mask per-prompt regression: one prompt can degrade while another improves and
# the mean never moves. These bind each prompt to its own past, which is what
# makes editing a prompt behave like editing tested code.
# --------------------------------------------------------------------------


def test_no_prompt_gains_a_failing_criterion() -> None:
    regressions = [r for r in prompt_regressions() if not r.unrenderable]
    assert not regressions, "\n".join(
        [
            "Prompt(s) gained a failing criterion against their baseline:",
            *(
                f"  - {r.prompt}: now also fails "
                f"{sorted(r.new_fails)} "
                f"({', '.join(CRITERIA[c] for c in sorted(r.new_fails))})"
                for r in regressions
            ),
            "",
            "A prompt may only shed failures. If the change is intended, fix the",
            "prompt; if the baseline is genuinely wrong, update PROMPT_BASELINE",
            "in src/prompt_fitness.py in the same commit and say why.",
        ]
    )


def test_no_prompt_stops_rendering() -> None:
    """A fixture that breaks drops the prompt from scoring — an invisible loss."""
    broken = [r.prompt for r in prompt_regressions() if r.unrenderable]
    assert not broken, (
        f"Prompt(s) in PROMPT_BASELINE no longer render: {broken}. Their "
        "fixtures broke, so they are now unmeasured — a coverage regression "
        "wearing a passing test."
    )


def test_baseline_covers_every_scored_prompt() -> None:
    """A scored prompt absent from the baseline is unpinned and free to rot."""
    unpinned = sorted(set(per_prompt_scores()) - set(PROMPT_BASELINE))
    assert not unpinned, (
        f"Scored prompts with no PROMPT_BASELINE entry: {unpinned}. Add them "
        "with their current failing criteria so they are pinned against their "
        "own past."
    )


def test_baseline_is_not_looser_than_reality() -> None:
    """Guards the baseline itself: stale entries silently widen the allowance."""
    current = per_prompt_scores()
    stale = {
        name: sorted(baseline - current[name])
        for name, baseline in PROMPT_BASELINE.items()
        if name in current and (baseline - current[name])
    }
    assert not stale, (
        "PROMPT_BASELINE allows failures these prompts no longer have: "
        f"{stale}. Tighten the baseline in the same commit that improved them, "
        "or the win is given back silently the next time they regress."
    )


# --------------------------------------------------------------------------
# Unformatted-placeholder leak — a correctness bug the ADR-0087 rubric is
# blind to. See the note above ``placeholder_leaks`` in src/prompt_fitness.py.
# --------------------------------------------------------------------------


def test_no_prompt_leaks_an_unformatted_placeholder() -> None:
    leaks = prompt_placeholder_leaks()
    assert not leaks, (
        "Prompts shipping a literal str.format placeholder to the model: "
        + "; ".join(f"{name} leaks {sorted(v)}" for name, v in sorted(leaks.items()))
        + ". A shared fragment was interpolated into an f-string without "
        ".format(...). Format it at the call site."
    )


def test_placeholder_detector_catches_the_bug_it_was_written_for() -> None:
    """Guards the detector: if it stops firing, the gate is decoration.

    The exact defect found on 2026-07-30 — MEMORY_SUGGESTION_PROMPT
    interpolated unformatted by shape_runner and discover_runner.
    """
    from runner_constants import MEMORY_SUGGESTION_PROMPT  # noqa: PLC0415

    assert "context" in placeholder_leaks(MEMORY_SUGGESTION_PROMPT), (
        "placeholder_leaks no longer detects an unformatted {context} in "
        "MEMORY_SUGGESTION_PROMPT, the defect it was written to catch"
    )


def test_placeholder_detector_ignores_braces_in_code() -> None:
    """Code legitimately contains braces; only prose leaks are bugs."""
    assert not placeholder_leaks("Use `### P{N} — Name` for phase headings")
    assert not placeholder_leaks('```python\nraise E(f"{key}: {attempts}")\n```')
    assert not placeholder_leaks('+        grouped[f"{year}-W{week:02d}"].append(r)')
    assert placeholder_leaks("This {context} may have surfaced knowledge")
