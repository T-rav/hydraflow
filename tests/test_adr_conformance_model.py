from datetime import datetime

from adr_conformance import (
    AdrConformance,
    CheckOutcome,
    CheckResult,
    ConformanceKind,
    classify_enforcement,
)


def test_classify_enforcement_known_and_unknown():
    assert classify_enforcement("enforced") is ConformanceKind.ENFORCED
    assert classify_enforcement("decision-of-record") is ConformanceKind.DECISION_OF_RECORD
    assert classify_enforcement("garbage") is None


def test_adrconformance_roundtrips():
    c = AdrConformance(
        adr_id="ADR-0049",
        kind=ConformanceKind.ENFORCED,
        outcome=CheckOutcome.PASS,
        checks=[CheckResult(check="pytest:tests/t.py::t", outcome=CheckOutcome.PASS, duration_s=1.2)],
        timestamp=datetime(2026, 6, 30, 12, 0, 0),
    )
    assert AdrConformance.model_validate_json(c.model_dump_json()) == c
