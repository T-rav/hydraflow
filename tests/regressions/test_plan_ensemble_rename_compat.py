"""Regression: the "Council" -> "Ensemble" rename must not orphan persisted state.

The adversarial planning ensemble (``PlanCouncil`` / ``DecompositionCouncil``
and friends) was renamed to ``PlanEnsemble`` / ``DecompositionEnsemble`` so
"Council" carries exactly one meaning in this repo — the ``agents/council/``
governance layer — per ADR-0053 (ubiquitous language as a living artifact).

Three of the renamed names had already escaped the process boundary before the
rename, so the OLD spelling must keep being *read* even though only the new one
is ever *written*:

1. ``Concern.raised_in_stage`` — persisted inside ``AdversarialState`` in the
   state file. An issue mid-plan across the rename still carries
   ``plan_council_risk_skeptic``; if that stopped matching
   ``DESIGN_DECISION_STAGES`` its CRITICAL design-gate findings would silently
   stop qualifying and the issue would march to ``ready`` (the exact #10659
   failure mode, reintroduced by a rename).
2. ``hydraflow-council-review`` — a GitHub label, which lives on issues in a
   remote repo, not in this tree. ``review_phase`` must keep skipping it.
3. ``phase_scripts["shape_council"]`` — a MockWorld seed JSON key. Seed files
   are authored outside this repo; ``sandbox_main`` silently *ignores* unknown
   phase names, so an un-canonicalized legacy key would degrade to a no-op
   rather than fail loudly.

Each assertion below is the mutation guard for one compat pin: delete the pin
and exactly one of these reddens.
"""

from __future__ import annotations

from datetime import UTC, datetime

from adversarial_labels import LABELS_ADVERSARIAL_TRANSIENT
from mockworld.seed import MockWorldSeed
from pending_concerns import (
    DESIGN_DECISION_STAGES,
    Concern,
    is_design_decision_concern,
)


def _concern(stage: str) -> Concern:
    return Concern(
        id="PLAN-RISK_SKEPTIC-001",
        raised_in_phase="plan",
        raised_in_stage=stage,
        severity="CRITICAL",
        concern="the motivating assumption is unverified",
        raised_at=datetime.now(UTC),
        must_address_by="planner",
    )


class TestLegacyStageString:
    """Pin 1: ``plan_council_risk_skeptic`` stays a design-gate stage."""

    def test_current_stage_string_is_a_design_decision(self) -> None:
        assert is_design_decision_concern(_concern("plan_ensemble_risk_skeptic"))

    def test_legacy_stage_string_is_still_a_design_decision(self) -> None:
        """A concern persisted before the rename must still gate on a human."""
        assert is_design_decision_concern(_concern("plan_council_risk_skeptic"))

    def test_both_spellings_are_in_the_stage_set(self) -> None:
        assert {
            "plan_ensemble_risk_skeptic",
            "plan_council_risk_skeptic",
        } <= DESIGN_DECISION_STAGES

    def test_an_unrelated_stage_is_not_a_design_decision(self) -> None:
        """The set is not just "everything" — the guard has to discriminate."""
        assert not is_design_decision_concern(_concern("plan_ensemble_builder"))


class TestLegacyTransientLabel:
    """Pin 2: the pre-rename label stays recognised so review_phase skips it."""

    def test_current_label_is_recognised(self) -> None:
        assert "hydraflow-ensemble-review" in LABELS_ADVERSARIAL_TRANSIENT

    def test_legacy_label_is_still_recognised(self) -> None:
        assert "hydraflow-council-review" in LABELS_ADVERSARIAL_TRANSIENT


class TestLegacySeedPhaseKey:
    """Pin 3: a pre-rename seed key canonicalizes instead of silently no-opping."""

    def test_current_phase_key_round_trips(self) -> None:
        seed = MockWorldSeed.from_json(
            '{"phase_scripts": {"shape_ensemble": {"3": {"1": "split"}}}}'
        )

        assert seed.phase_scripts["shape_ensemble"] == {3: {1: "split"}}

    def test_legacy_phase_key_is_canonicalized_to_the_new_name(self) -> None:
        """``sandbox_main`` dispatches on the canonical name only."""
        seed = MockWorldSeed.from_json(
            '{"phase_scripts": {"shape_council": {"3": {"1": "split"}}}}'
        )

        assert "shape_council" not in seed.phase_scripts
        assert seed.phase_scripts["shape_ensemble"] == {3: {1: "split"}}

    def test_legacy_key_gets_the_round_number_int_coercion_too(self) -> None:
        """The int-coercion branch keys off the CANONICAL name, not the raw one."""
        seed = MockWorldSeed.from_json(
            '{"phase_scripts": {"shape_council": {"7": {"2": "consensus"}}}}'
        )

        rounds = seed.phase_scripts["shape_ensemble"][7]
        assert all(isinstance(rk, int) for rk in rounds)
