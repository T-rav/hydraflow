# tests/test_adr_conformance_evaluate.py
from datetime import datetime

from adr_conformance import CheckOutcome, ConformanceKind, evaluate_adrs
from adr_index import ADR, Check
from mockworld.fakes import FakeConformanceRunner

TS = datetime(2026, 6, 30)


def _adr(num, enforcement, checks=(), status="Accepted"):
    return ADR(
        number=num,
        title="X",
        status=status,
        summary="",
        enforcement=enforcement,
        enforced_by=checks,
    )


def test_enforced_passes_when_all_checks_pass(tmp_path):
    (tmp_path / "Makefile").write_text("arch-check:\n\techo hi\n")
    chk = Check("make", "arch-check", "make:arch-check")
    runner = FakeConformanceRunner({"make:arch-check": CheckOutcome.PASS})
    [res] = evaluate_adrs(
        [_adr(1, "enforced", (chk,))], runner, repo_root=tmp_path, timestamp=TS
    )
    assert res.outcome is CheckOutcome.PASS


def test_unresolved_check_is_not_run(tmp_path):
    chk = Check("make", "ghost", "make:ghost")  # no Makefile target
    runner = FakeConformanceRunner({})
    [res] = evaluate_adrs(
        [_adr(1, "enforced", (chk,))], runner, repo_root=tmp_path, timestamp=TS
    )
    assert res.outcome is CheckOutcome.UNRESOLVED
    assert runner.calls == []  # short-circuited, never executed


def test_decision_of_record_is_skipped_and_manual_is_manual(tmp_path):
    runner = FakeConformanceRunner({})
    results = evaluate_adrs(
        [
            _adr(1, "decision-of-record"),
            _adr(2, "manual", (Check("prose", "review", "review"),)),
        ],
        runner,
        repo_root=tmp_path,
        timestamp=TS,
    )
    assert results[0].outcome is CheckOutcome.SKIPPED
    assert results[0].kind is ConformanceKind.DECISION_OF_RECORD
    assert results[1].outcome is CheckOutcome.MANUAL
