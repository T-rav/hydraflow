"""`_decide_charter` agrees with `compute_charter_drift` (#11862).

The OPA pilot was rejected as an ENGINE (#11750, `docs/proposals/opa-pilot-findings.md`)
— that verdict stands and nothing here re-opens it. What was not yet in
production is the *capability* it exercised: the seam deciding more than ADRs.
This pins the charter arm to the existing pure reference implementation.

**Why a parity test rather than a shared helper.** `compute_charter_drift` stays
the reference; the caretaker keeps filing from its current path this cycle. If
`_decide_charter` simply called it, the two would agree by construction and the
test would say nothing. They agree here because the collector emits the finding
CLASS and the engine re-derives fatality from `NON_FATAL_FINDING_CLASSES` — two
routes to one verdict, which is the property ADR-0143 Ruling 4 asks for and the
same shape as the ADR enforcement parity test.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from charter import CharterDriftReport, CharterFinding
from charter_model import (
    FINDING_ACTOR_WITHOUT_LOOP,
    FINDING_LOOP_WITHOUT_ACTOR,
    FINDING_MISSING_ARTIFACT,
    FINDING_MISSING_STANDARD,
    FINDING_UNKNOWN_LAYER,
    FINDING_UNKNOWN_STANDARD,
)
from policy.facts import STANDARD_CHARTER, collect_charter_facts
from policy.models import DecisionStatus
from policy.python_engine import PythonDecisionEngine

_NOW = datetime(2026, 9, 1, tzinfo=UTC)


class _GovernsAll:
    def governs(self, standard: str) -> bool:  # noqa: ARG002 - stub
        return True


def _finding(cls: str, suffix: str = "x") -> CharterFinding:
    return CharterFinding(
        check_id=f"{cls}:{suffix}", finding_class=cls, detail="detail"
    )


def _decide(report: CharterDriftReport):
    facts = collect_charter_facts(report, observed_at=_NOW)
    return PythonDecisionEngine().decide(facts, charter=_GovernsAll())[0]


_CASES = [
    ("clean", CharterDriftReport(repo="o/r")),
    ("no-charter", CharterDriftReport(repo="o/r", has_charter=False)),
    (
        "fatal-standard",
        CharterDriftReport(repo="o/r", findings=(_finding(FINDING_MISSING_STANDARD),)),
    ),
    (
        "fatal-artifact",
        CharterDriftReport(repo="o/r", findings=(_finding(FINDING_MISSING_ARTIFACT),)),
    ),
    (
        "fatal-loop-binding",
        CharterDriftReport(
            repo="o/r", findings=(_finding(FINDING_LOOP_WITHOUT_ACTOR),)
        ),
    ),
    (
        "tolerated-unknown-standard",
        CharterDriftReport(repo="o/r", findings=(_finding(FINDING_UNKNOWN_STANDARD),)),
    ),
    (
        "tolerated-unknown-layer",
        CharterDriftReport(repo="o/r", findings=(_finding(FINDING_UNKNOWN_LAYER),)),
    ),
    (
        "advisory-actor-without-loop",
        CharterDriftReport(
            repo="o/r", findings=(_finding(FINDING_ACTOR_WITHOUT_LOOP),)
        ),
    ),
    (
        "mixed",
        CharterDriftReport(
            repo="o/r",
            findings=(
                _finding(FINDING_MISSING_STANDARD),
                _finding(FINDING_UNKNOWN_LAYER),
            ),
        ),
    ),
]


@pytest.mark.parametrize(("name", "report"), _CASES, ids=[name for name, _ in _CASES])
def test_blocking_matches_the_reference_implementations_clean(
    name: str, report: CharterDriftReport
) -> None:
    """The one invariant that must hold: blocking iff the report is not clean.

    `clean` is the reference's own word for "no FATAL drift". If the engine
    ever blocks where the caretaker would not — or passes where it would file
    — the two halves of the seam have drifted and the decision surface is
    lying about the repo.
    """
    decision = _decide(report)

    if not report.has_charter:
        assert decision.status is DecisionStatus.EXEMPT
        assert decision.blocking is False
        return

    assert decision.blocking is (not report.clean), (
        f"{name}: engine blocking={decision.blocking} but the reference says "
        f"clean={report.clean}"
    )


@pytest.mark.parametrize(("name", "report"), _CASES, ids=[name for name, _ in _CASES])
def test_every_case_produces_exactly_one_decision(
    name: str, report: CharterDriftReport
) -> None:
    """One subject, one verdict. A report that fanned out per finding would
    make the rendered page count repos wrong."""
    facts = collect_charter_facts(report, observed_at=_NOW)
    decisions = PythonDecisionEngine().decide(facts, charter=_GovernsAll())
    assert len(decisions) == 1, name
    assert decisions[0].standard == STANDARD_CHARTER


def test_an_ungoverned_repo_is_exempt_not_compliant() -> None:
    """EXEMPT and COMPLIANT must stay different answers.

    A repo with no charter did not SATISFY the contract — it was never subject
    to it. Collapsing the two would make any "compliant" count a lie, which is
    the distinction the four statuses exist to preserve (ADR-0143 Ruling 4).
    """
    decision = _decide(CharterDriftReport(repo="o/r", has_charter=False))
    assert decision.status is DecisionStatus.EXEMPT
    assert decision.status is not DecisionStatus.COMPLIANT


def test_the_collector_emits_no_verdict() -> None:
    """A Fact is an observation; the verdict belongs to the engine.

    If the collector emitted `fatal: true` the parity test above would be
    tautological — both sides would read one helper's output rather than reach
    the same conclusion by different routes.
    """
    report = CharterDriftReport(
        repo="o/r", findings=(_finding(FINDING_MISSING_STANDARD),)
    )
    facts = collect_charter_facts(report, observed_at=_NOW)
    values = {str(f.value) for f in facts}

    assert FINDING_MISSING_STANDARD in values, "the finding class must be recorded"
    assert not any(str(f.key) in {"fatal", "blocking", "clean"} for f in facts), (
        f"the collector emitted a verdict: {[f.key for f in facts]}"
    )


def test_has_charter_is_emitted_even_when_clean() -> None:
    """An empty fact list cannot distinguish "governed and clean" from
    "ungoverned", and those are different answers."""
    facts = collect_charter_facts(CharterDriftReport(repo="o/r"), observed_at=_NOW)
    assert any(f.key == "has_charter" for f in facts)
