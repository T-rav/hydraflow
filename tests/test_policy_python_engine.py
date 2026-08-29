"""``PythonDecisionEngine`` unit contract (#11749).

Two things get proved here that the live-corpus parity test in
``tests/architecture/test_policy_adr_enforcement_parity.py`` cannot:

1. **The arms the live corpus never reaches.** Today every Accepted ADR is
   either ``REAL`` or exempt, so a parity test over the real repo exercises two
   of the four statuses. The synthetic fact sets below reach all four.
2. **Fail-closed behaviour on thin evidence.** A collector that drops a fact
   must redden, not silently default — dropping ``resolved`` alone would turn a
   paid-off debt back into a grandfathered one.

The conformance half is checked as an exhaustive equivalence against
``classify_remediation``: every ``CheckOutcome`` x rename-present/absent x an
attempts range spanning the escalation threshold. The loop's behaviour changed
only in which object carries the action, and this is what says so.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from adr_conformance import AdrConformance, CheckOutcome, ConformanceKind
from adr_conformance_remediation import RemediationAction, classify_remediation
from policy.facts import (
    COLLECTED_STANDARDS,
    STANDARD_ADR_CONFORMANCE,
    STANDARD_ADR_ENFORCEMENT,
    conformance_facts,
)
from policy.models import Charter, DecisionEngine, DecisionStatus, Fact
from policy.python_engine import (
    MissingFactError,
    PythonDecisionEngine,
    UnsupportedStandardError,
)

OBSERVED_AT = datetime(2026, 8, 28, 9, 30, tzinfo=UTC)


def _enforcement_facts(
    subject: str,
    *,
    enforcement_class: str,
    in_baseline_snapshot: bool = False,
    resolved: bool = False,
    exempt: bool = False,
    drop: str | None = None,
) -> list[Fact]:
    observations: dict[str, bool | str] = {
        "enforcement_class": enforcement_class,
        "in_baseline_snapshot": in_baseline_snapshot,
        "resolved": resolved,
        "exempt": exempt,
    }
    if drop is not None:
        observations.pop(drop)
    return [
        Fact(
            standard=STANDARD_ADR_ENFORCEMENT,
            subject=subject,
            key=key,
            value=value,
            observed_at=OBSERVED_AT,
            source="test",
        )
        for key, value in observations.items()
    ]


def _conformance(outcome: CheckOutcome) -> AdrConformance:
    return AdrConformance(
        adr_id="ADR-0100",
        kind=ConformanceKind.ENFORCED,
        outcome=outcome,
        checks=[],
        timestamp=OBSERVED_AT,
    )


def _decide_one(facts: list[Fact], charter: Charter | None = None):
    decisions = PythonDecisionEngine().decide(facts, charter)
    assert len(decisions) == 1
    return decisions[0]


# ---------------------------------------------------------------------------
# The protocol binding
# ---------------------------------------------------------------------------


def test_the_reference_engine_satisfies_the_decision_engine_protocol() -> None:
    """The protocol is the seam #11750's OPA engine plugs into; if the
    reference implementation does not satisfy it, it is decoration."""
    assert isinstance(PythonDecisionEngine(), DecisionEngine)


def test_the_reference_engine_judges_every_standard_the_collectors_emit() -> None:
    """Pinned in both directions against ``COLLECTED_STANDARDS``.

    A collector that emits a standard the engine has no ruleset for is an
    ``UnsupportedStandardError`` in production — the loop would crash mid-tick
    rather than file. A standard the engine judges but nothing collects for is
    a ruleset with no evidence behind it. Neither is allowed to appear
    silently, so the sample fact sets below are asserted to cover the collector
    constant exactly, and each one is asserted to reach a decision.
    """
    minimal_facts = {
        STANDARD_ADR_ENFORCEMENT: _enforcement_facts(
            "ADR-0100", enforcement_class="REAL"
        ),
        STANDARD_ADR_CONFORMANCE: conformance_facts(
            _conformance(CheckOutcome.PASS),
            rename_match=None,
            attempts=0,
            max_attempts=3,
            observed_at=OBSERVED_AT,
        ),
    }

    assert set(minimal_facts) == set(COLLECTED_STANDARDS)
    for standard, facts in minimal_facts.items():
        decisions = PythonDecisionEngine().decide(facts)
        assert [d.standard for d in decisions] == [standard]


# ---------------------------------------------------------------------------
# adr_enforcement — all four statuses
# ---------------------------------------------------------------------------


def test_real_enforcement_is_compliant_and_not_blocking() -> None:
    decision = _decide_one(_enforcement_facts("ADR-0100", enforcement_class="REAL"))

    assert decision.status is DecisionStatus.COMPLIANT
    assert decision.blocking is False
    assert decision.remediation is RemediationAction.NONE


def test_weak_debt_with_no_lane_is_violated_and_blocking() -> None:
    decision = _decide_one(_enforcement_facts("ADR-0777", enforcement_class="WEAK"))

    assert decision.status is DecisionStatus.VIOLATED
    assert decision.blocking is True
    assert decision.remediation is RemediationAction.FILE_ISSUE


def test_missing_debt_with_no_lane_is_violated_and_blocking() -> None:
    decision = _decide_one(_enforcement_facts("ADR-0778", enforcement_class="MISSING"))

    assert decision.status is DecisionStatus.VIOLATED
    assert decision.blocking is True


def test_allow_listed_debt_is_exempt_and_not_blocking() -> None:
    decision = _decide_one(
        _enforcement_facts("ADR-0025", enforcement_class="WEAK", exempt=True)
    )

    assert decision.status is DecisionStatus.EXEMPT
    assert decision.blocking is False
    assert decision.remediation is RemediationAction.NONE


def test_unresolved_baseline_debt_is_grandfathered_and_not_blocking() -> None:
    decision = _decide_one(
        _enforcement_facts(
            "ADR-0091", enforcement_class="MISSING", in_baseline_snapshot=True
        )
    )

    assert decision.status is DecisionStatus.GRANDFATHERED
    assert decision.blocking is False


def test_baseline_debt_claimed_resolved_is_violated_again_when_it_regresses() -> None:
    """``resolved`` leaves the grandfathered set — a regression is a violation,
    not a free ride back onto the baseline."""
    decision = _decide_one(
        _enforcement_facts(
            "ADR-0091",
            enforcement_class="MISSING",
            in_baseline_snapshot=True,
            resolved=True,
        )
    )

    assert decision.status is DecisionStatus.VIOLATED
    assert decision.blocking is True


def test_exemption_takes_precedence_over_the_baseline_lane() -> None:
    """``live_grandfathered`` subtracts the exemption set, so an ADR in both
    lanes is exempt, never grandfathered."""
    decision = _decide_one(
        _enforcement_facts(
            "ADR-0025",
            enforcement_class="WEAK",
            in_baseline_snapshot=True,
            exempt=True,
        )
    )

    assert decision.status is DecisionStatus.EXEMPT


def test_a_real_adr_still_in_the_baseline_is_compliant_not_grandfathered() -> None:
    """Class is read first: paying the debt makes the ADR compliant even before
    its id is moved into ``resolved``."""
    decision = _decide_one(
        _enforcement_facts(
            "ADR-0091", enforcement_class="REAL", in_baseline_snapshot=True
        )
    )

    assert decision.status is DecisionStatus.COMPLIANT


def test_decision_carries_the_facts_it_was_made_from() -> None:
    facts = _enforcement_facts("ADR-0777", enforcement_class="WEAK")

    decision = _decide_one(facts)

    assert {f.key for f in decision.facts} == {
        "enforcement_class",
        "in_baseline_snapshot",
        "resolved",
        "exempt",
    }


# ---------------------------------------------------------------------------
# Fail-closed
# ---------------------------------------------------------------------------


def test_a_dropped_resolved_fact_raises_rather_than_defaulting() -> None:
    """Defaulting ``resolved`` to False would silently re-grandfather a debt
    that had been paid — the exact "consolidation widens a gate" shape."""
    facts = _enforcement_facts(
        "ADR-0091",
        enforcement_class="MISSING",
        in_baseline_snapshot=True,
        resolved=True,
        drop="resolved",
    )

    with pytest.raises(MissingFactError, match="resolved"):
        PythonDecisionEngine().decide(facts)


def test_a_dropped_enforcement_class_fact_raises() -> None:
    facts = _enforcement_facts(
        "ADR-0777", enforcement_class="WEAK", drop="enforcement_class"
    )

    with pytest.raises(MissingFactError, match="enforcement_class"):
        PythonDecisionEngine().decide(facts)


def test_an_unknown_standard_refuses_rather_than_returning_silence() -> None:
    facts = [
        Fact(
            standard="rails",
            subject="src/foo.py",
            key="drift",
            value=True,
            observed_at=OBSERVED_AT,
            source="test",
        )
    ]

    with pytest.raises(UnsupportedStandardError, match="rails"):
        PythonDecisionEngine().decide(facts)


# ---------------------------------------------------------------------------
# Charter selection + ordering
# ---------------------------------------------------------------------------


def test_charter_excludes_standards_it_does_not_place_in_force() -> None:
    facts = _enforcement_facts("ADR-0777", enforcement_class="WEAK")

    assert PythonDecisionEngine().decide(facts, Charter.for_standards("rails")) == []


def test_decisions_are_ordered_by_standard_then_subject_regardless_of_fact_order() -> (
    None
):
    """A replay from ``facts.jsonl`` must not depend on write order."""
    facts = [
        *_enforcement_facts("ADR-0300", enforcement_class="REAL"),
        *_enforcement_facts("ADR-0100", enforcement_class="REAL"),
        *_enforcement_facts("ADR-0200", enforcement_class="REAL"),
    ]

    subjects = [d.subject for d in PythonDecisionEngine().decide(facts)]

    assert subjects == ["ADR-0100", "ADR-0200", "ADR-0300"]


# ---------------------------------------------------------------------------
# adr_conformance — exhaustive equivalence with classify_remediation
# ---------------------------------------------------------------------------


def test_conformance_decisions_match_classify_remediation_over_every_input() -> None:
    """Exhaustive over ``CheckOutcome`` x rename x attempts around the budget.

    Not a sample: the loop dispatches on ``decision.remediation``, so any input
    where the engine and ``classify_remediation`` disagree is an input where
    the migration changed behaviour.
    """
    engine = PythonDecisionEngine()
    charter = Charter.for_standards(STANDARD_ADR_CONFORMANCE)
    checked = 0

    for outcome in CheckOutcome:
        for rename_match in (None, "tests/test_new.py::test_renamed"):
            for attempts in range(0, 6):
                conf = _conformance(outcome)
                expected = classify_remediation(
                    conf,
                    rename_match=rename_match,
                    attempts=attempts,
                    max_attempts=3,
                )
                facts = conformance_facts(
                    conf,
                    rename_match=rename_match,
                    attempts=attempts,
                    max_attempts=3,
                    observed_at=OBSERVED_AT,
                )
                decision = engine.decide(facts, charter)[0]

                assert decision.remediation is expected.action, (
                    f"{outcome} rename={rename_match!r} attempts={attempts}: "
                    f"engine said {decision.remediation}, classify_remediation "
                    f"said {expected.action}"
                )
                assert decision.reason == expected.reason
                assert decision.blocking is (
                    expected.action is not RemediationAction.NONE
                )
                checked += 1

    assert checked == len(CheckOutcome) * 2 * 6


def test_a_missing_rename_fact_is_not_the_same_as_an_empty_one() -> None:
    """``rename_match`` is omitted when absent; an empty string would be a
    detected rename to nowhere and must not route to REPOINT either."""
    conf = _conformance(CheckOutcome.UNRESOLVED)

    facts = conformance_facts(
        conf, rename_match=None, attempts=0, max_attempts=3, observed_at=OBSERVED_AT
    )

    assert "rename_match" not in {f.key for f in facts}
    decision = PythonDecisionEngine().decide(facts)[0]
    assert decision.remediation is RemediationAction.FILE_ISSUE
