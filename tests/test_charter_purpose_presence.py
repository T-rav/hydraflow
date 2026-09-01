"""`missing-purpose` — is intent STATED? (#11856, ADR-0143 Amendment 2026-09-01)

ADR-0143 Ruling 3 left Purpose unchecked and required a ruling before any check
was added. The operator ruled on 2026-08-31: presence and shape are checkable
without pretending to read intent, goal referential integrity goes through the
policy seam, and semantic conformance stays refused.

This covers the drift half. It is deliberately the weakest possible reading —
a charter that STATES a purpose passes, however unserved that purpose is.
"""

from __future__ import annotations

import pytest

from charter import (
    FINDING_LEGACY_RAILS_MANIFEST,
    FINDING_MISSING_PURPOSE,
    FINDING_UNKNOWN_STANDARD,
    NON_FATAL_FINDING_CLASSES,
    Articles,
    Artifacts,
    Charter,
    CharterFinding,
    ObservedRepo,
    Purpose,
    compute_charter_drift,
)

_STANDARDS = ("adr_enforcement",)
_ARTIFACTS = ("docs/adr",)


def _charter(purpose: Purpose) -> Charter:
    """A charter that is otherwise complete, so only Purpose can be at fault."""
    return Charter(
        purpose=purpose,
        articles=Articles(standards=_STANDARDS, assurance="internal"),
        artifacts=Artifacts(required=_ARTIFACTS),
    )


def _observed() -> ObservedRepo:
    return ObservedRepo(
        present_standards=frozenset(_STANDARDS),
        present_artifacts=frozenset(_ARTIFACTS),
        known_standards=frozenset(_STANDARDS),
    )


def _purpose_findings(charter: Charter) -> list[str]:
    report = compute_charter_drift(charter, _observed(), repo="o/r")
    return [
        f.check_id
        for f in report.findings
        if f.finding_class == FINDING_MISSING_PURPOSE
    ]


class TestAStatedPurposePasses:
    def test_a_complete_purpose_is_not_drift(self) -> None:
        charter = _charter(Purpose(product="a factory", goals=("lights_off",)))

        assert _purpose_findings(charter) == []

    def test_an_unserved_purpose_is_still_a_stated_one(self) -> None:
        # The check reads presence, never merit. A goal no code pursues is a
        # matter for goal referential integrity in the policy seam; this layer
        # has no opinion, and asserting otherwise here would be the semantic
        # conformance ADR-0143 refused.
        charter = _charter(Purpose(product="x", goals=("a_goal_nothing_serves",)))

        assert _purpose_findings(charter) == []


class TestAnUnstatedPurposeIsDrift:
    def test_a_charter_stating_no_product_is_drift(self) -> None:
        charter = _charter(Purpose(product="", goals=("lights_off",)))

        assert _purpose_findings(charter) == [f"{FINDING_MISSING_PURPOSE}:product"]

    def test_a_whitespace_only_product_is_not_a_statement(self) -> None:
        charter = _charter(Purpose(product="   \n\t ", goals=("lights_off",)))

        assert _purpose_findings(charter) == [f"{FINDING_MISSING_PURPOSE}:product"]

    def test_a_charter_naming_no_goals_is_drift(self) -> None:
        charter = _charter(Purpose(product="a factory", goals=()))

        assert _purpose_findings(charter) == [f"{FINDING_MISSING_PURPOSE}:goals"]

    def test_the_two_halves_are_reported_separately(self) -> None:
        # One finding saying "purpose is wrong" would leave the caretaker's
        # issue naming WHICH only in prose. They are different mistakes.
        charter = _charter(Purpose())

        assert _purpose_findings(charter) == [
            f"{FINDING_MISSING_PURPOSE}:product",
            f"{FINDING_MISSING_PURPOSE}:goals",
        ]


class TestTheLegacyFormatIsNotAskedForWhatItCannotExpress:
    """A `rails.yaml` predates the Purpose layer and has nowhere to put one.

    Demanding a purpose from an un-migrated repo would make it fatally drifted
    over a key its format cannot express — turning ADR-0121's deliberately
    non-fatal `legacy-rails-manifest` tolerance into a hard failure by the side
    door. Migration to `charter.yaml` is what surfaces the requirement, and it
    is already its own reported finding.
    """

    def test_a_legacy_manifest_is_not_asked_for_a_purpose(self) -> None:
        legacy = Charter(
            purpose=Purpose(),
            articles=Articles(standards=_STANDARDS, assurance="internal"),
            artifacts=Artifacts(required=_ARTIFACTS),
            load_findings=(
                CharterFinding(
                    check_id=f"{FINDING_LEGACY_RAILS_MANIFEST}:rails.yaml",
                    finding_class=FINDING_LEGACY_RAILS_MANIFEST,
                    detail="loaded from a legacy rails.yaml",
                ),
            ),
        )

        assert _purpose_findings(legacy) == []

    def test_a_modern_charter_carrying_other_load_findings_is_still_asked(
        self,
    ) -> None:
        # The decoy. Exempting on "has any load finding" rather than on the
        # legacy class would silently excuse every charter that reported
        # anything at load time.
        noisy = Charter(
            purpose=Purpose(),
            articles=Articles(standards=_STANDARDS, assurance="internal"),
            artifacts=Artifacts(required=_ARTIFACTS),
            load_findings=(
                CharterFinding(
                    check_id=f"{FINDING_UNKNOWN_STANDARD}:soc2_ready",
                    finding_class=FINDING_UNKNOWN_STANDARD,
                    detail="neither carried nor shipped",
                ),
            ),
        )

        assert _purpose_findings(noisy) == [
            f"{FINDING_MISSING_PURPOSE}:product",
            f"{FINDING_MISSING_PURPOSE}:goals",
        ]


class TestItIsFatalOnPurpose:
    def test_missing_purpose_is_not_tolerated(self) -> None:
        """Fatal by sequence, not severity.

        Goal referential integrity resolves goal ids against the Articles. With
        no goals it gets an empty subject list, and a check with an empty
        subject list passes silently and reads as coverage. Tolerating an
        unstated purpose would let the stronger check disable itself quietly.
        """
        assert FINDING_MISSING_PURPOSE not in NON_FATAL_FINDING_CLASSES

    def test_a_charter_with_no_purpose_reports_fatal_findings(self) -> None:
        report = compute_charter_drift(_charter(Purpose()), _observed(), repo="o/r")

        assert [f.check_id for f in report.fatal_findings] == [
            f"{FINDING_MISSING_PURPOSE}:product",
            f"{FINDING_MISSING_PURPOSE}:goals",
        ]


class TestTheRepoObeysItsOwnRule:
    def test_this_repos_charter_states_a_purpose(self) -> None:
        """The check would be theatre if the repo declaring it failed it."""
        from pathlib import Path

        from charter import load_charter

        charter = load_charter(Path(__file__).resolve().parents[1])

        assert charter.purpose.product.strip()
        assert charter.purpose.goals


@pytest.mark.parametrize(
    "surface",
    [
        pytest.param("src/charter_model.py", id="purpose-docstring"),
        pytest.param("charter.yaml", id="charter-comment"),
    ],
)
def test_no_surface_still_claims_nothing_reads_purpose(surface: str) -> None:
    """ADR-0053: the claim was true when written and is now false.

    A vocabulary that says one thing in three places and corrects it in one is
    the drift the term campaign exists to prevent. `declares_nothing_checkable`
    is the third surface; its rationale is asserted by its own docstring test.
    """
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / surface).read_text(encoding="utf-8")

    assert "no drift check reads it" not in text
