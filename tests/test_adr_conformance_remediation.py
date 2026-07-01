from datetime import datetime

from adr_conformance import AdrConformance, CheckOutcome, ConformanceKind
from adr_conformance_remediation import RemediationAction, classify_remediation

TS = datetime(2026, 6, 30)


def _conf(outcome):
    return AdrConformance(
        adr_id="ADR-0049",
        kind=ConformanceKind.ENFORCED,
        outcome=outcome,
        checks=[],
        timestamp=TS,
    )


def test_pass_needs_no_remediation():
    d = classify_remediation(_conf(CheckOutcome.PASS), rename_match=None, attempts=0)
    assert d.action is RemediationAction.NONE


def test_unresolved_with_rename_repoints():
    d = classify_remediation(
        _conf(CheckOutcome.UNRESOLVED),
        rename_match="pytest:tests/new.py::test_y",
        attempts=0,
    )
    assert d.action is RemediationAction.REPOINT
    assert "tests/new.py" in d.reason


def test_unresolved_without_match_files_issue():
    d = classify_remediation(
        _conf(CheckOutcome.UNRESOLVED), rename_match=None, attempts=0
    )
    assert d.action is RemediationAction.FILE_ISSUE


def test_fail_escalates_past_budget():
    assert (
        classify_remediation(
            _conf(CheckOutcome.FAIL), rename_match=None, attempts=2
        ).action
        is RemediationAction.FILE_ISSUE
    )
    assert (
        classify_remediation(
            _conf(CheckOutcome.FAIL), rename_match=None, attempts=3
        ).action
        is RemediationAction.ESCALATE
    )
