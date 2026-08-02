"""Unit tests for the ADR enforcement-debt classifier + assertion-strength
heuristic (issue #10411).

Two pure signals layered on ADR-0100's parser/resolver, never forking it:

* ``classify_adr_enforcement`` → REAL / WEAK / MISSING (the debt lens).
* ``check_is_tautological`` → does a *resolving* pytest check actually assert,
  or is it a green-but-hollow guard?

The final block pins the mechanism against LIVE ADRs so a parser/resolver
regression that silently reclassifies a real enforcement is caught here.
"""

from __future__ import annotations

from pathlib import Path

from adr_conformance import (
    EnforcementClass,
    adr_is_unattributed,
    check_is_tautological,
    check_is_unattributed,
    classify_adr_enforcement,
    has_real_enforcement,
)
from adr_index import ADR, Check, scan_adr_directory

REPO = Path(__file__).resolve().parent.parent
ADR_DIR = REPO / "docs" / "adr"


def _pytest(target: str) -> Check:
    return Check(kind="pytest", target=target, raw=f"pytest:{target}")


def _adr(number: int, enforcement: str, checks: tuple[Check, ...]) -> ADR:
    return ADR(
        number=number,
        title="synthetic",
        status="Accepted",
        summary="",
        enforcement=enforcement,
        enforced_by=checks,
    )


# --------------------------------------------------------------------------
# check_is_tautological — the assertion-strength heuristic
# --------------------------------------------------------------------------


def _write(tmp_path: Path, rel: str, body: str) -> None:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def test_bare_assert_is_not_tautological(tmp_path: Path):
    _write(tmp_path, "tests/t.py", "def test_x():\n    assert 1 == 1\n")
    assert not check_is_tautological(_pytest("tests/t.py::test_x"), tmp_path)


def test_import_only_test_is_tautological(tmp_path: Path):
    _write(
        tmp_path, "tests/t.py", "import os\n\n\ndef test_x():\n    import os  # noop\n"
    )
    assert check_is_tautological(_pytest("tests/t.py::test_x"), tmp_path)


def test_mock_assert_call_counts_as_asserting(tmp_path: Path):
    _write(
        tmp_path,
        "tests/t.py",
        "def test_x(mock):\n    mock.foo()\n    mock.assert_called_once()\n",
    )
    assert not check_is_tautological(_pytest("tests/t.py::test_x"), tmp_path)


def test_helper_idiom_call_counts_as_asserting(tmp_path: Path):
    # A test that delegates its assertion to a `verify_*` helper must NOT be
    # mis-flagged weak — the heuristic is biased toward STRONG.
    _write(tmp_path, "tests/t.py", "def test_x():\n    verify_invariant(thing)\n")
    assert not check_is_tautological(_pytest("tests/t.py::test_x"), tmp_path)


def test_pytest_raises_context_counts_as_asserting(tmp_path: Path):
    _write(
        tmp_path,
        "tests/t.py",
        "import pytest\n\n\ndef test_x():\n    with pytest.raises(ValueError):\n        boom()\n",
    )
    assert not check_is_tautological(_pytest("tests/t.py::test_x"), tmp_path)


def test_class_method_scoped_to_the_named_class(tmp_path: Path):
    _write(
        tmp_path,
        "tests/t.py",
        "class TestA:\n    def test_x(self):\n        pass\n\n"
        "class TestB:\n    def test_x(self):\n        assert True\n",
    )
    # The hollow one is TestA.test_x, NOT TestB.test_x (same method name).
    assert check_is_tautological(_pytest("tests/t.py::TestA::test_x"), tmp_path)
    assert not check_is_tautological(_pytest("tests/t.py::TestB::test_x"), tmp_path)


def test_module_only_citation_scans_whole_module(tmp_path: Path):
    _write(
        tmp_path,
        "tests/t.py",
        "def test_a():\n    pass\n\n\ndef test_b():\n    assert 2 == 2\n",
    )
    # Any assert anywhere in the module makes a module-only citation strong.
    assert not check_is_tautological(_pytest("tests/t.py"), tmp_path)


def test_unresolvable_and_nonpytest_are_never_tautological(tmp_path: Path):
    assert not check_is_tautological(_pytest("tests/missing.py::test_x"), tmp_path)
    assert not check_is_tautological(
        Check(kind="make", target="trust-contracts", raw="make:trust-contracts"),
        tmp_path,
    )
    assert not check_is_tautological(
        Check(kind="prose", target="review checklist", raw="review checklist"),
        tmp_path,
    )


# --------------------------------------------------------------------------
# classify_adr_enforcement / has_real_enforcement
# --------------------------------------------------------------------------


def test_no_enforced_by_is_missing(tmp_path: Path):
    adr = _adr(1, "decision-of-record", ())
    assert classify_adr_enforcement(adr, tmp_path) is EnforcementClass.MISSING
    assert not has_real_enforcement(adr, tmp_path)


def test_manual_prose_is_weak(tmp_path: Path):
    adr = _adr(
        2, "manual", (Check(kind="prose", target="review checklist", raw="review"),)
    )
    assert classify_adr_enforcement(adr, tmp_path) is EnforcementClass.WEAK


def test_enforced_with_resolving_check_is_real(tmp_path: Path):
    _write(tmp_path, "tests/t.py", "def test_x():\n    assert True\n")
    adr = _adr(3, "enforced", (_pytest("tests/t.py::test_x"),))
    assert classify_adr_enforcement(adr, tmp_path) is EnforcementClass.REAL
    assert has_real_enforcement(adr, tmp_path)


def test_enforced_but_unresolvable_is_weak(tmp_path: Path):
    adr = _adr(4, "enforced", (_pytest("tests/missing.py::test_x"),))
    assert classify_adr_enforcement(adr, tmp_path) is EnforcementClass.WEAK
    assert not has_real_enforcement(adr, tmp_path)


def test_tautology_does_not_downgrade_real(tmp_path: Path):
    # A resolving-but-hollow check still counts as REAL for the debt lens —
    # tautology is advisory, never a hard downgrade (coordinator constraint).
    _write(tmp_path, "tests/t.py", "def test_x():\n    import os  # no assert\n")
    adr = _adr(5, "enforced", (_pytest("tests/t.py::test_x"),))
    assert classify_adr_enforcement(adr, tmp_path) is EnforcementClass.REAL
    assert check_is_tautological(adr.enforced_by[0], tmp_path)


def test_mutating_make_check_is_not_real(tmp_path: Path):
    (tmp_path / "Makefile").write_text("arch-regen:\n\techo regen\n")
    adr = _adr(
        6, "enforced", (Check(kind="make", target="arch-regen", raw="make:arch-regen"),)
    )
    assert not has_real_enforcement(adr, tmp_path)
    assert classify_adr_enforcement(adr, tmp_path) is EnforcementClass.WEAK


# --------------------------------------------------------------------------
# Live exemplars — prove the mechanism end-to-end on real ADRs
# --------------------------------------------------------------------------


def _live() -> dict[int, ADR]:
    return {a.number: a for a in scan_adr_directory(ADR_DIR) if a.status == "Accepted"}


def test_exemplar_adrs_classify_real():
    """Named ADRs with genuine, resolving enforcement must be REAL — this is
    the proof the resolver works on live data, not just synthetic fixtures."""
    live = _live()
    # 0001 five-loops (arch-check test), 0002 label state machine, 0047 trust
    # contracts (make: + pytest:), 0100 the conformance ratchet itself.
    for number in (1, 2, 47, 100):
        adr = live[number]
        assert classify_adr_enforcement(adr, REPO) is EnforcementClass.REAL, (
            f"ADR-{number:04d} should classify REAL; got "
            f"{classify_adr_enforcement(adr, REPO)} (enforcement={adr.enforcement})"
        )


def test_no_accepted_adr_classifies_missing():
    # ADR-0027 (single-definition rule), the former MISSING exemplar, was the
    # only Accepted ADR classifying MISSING (#10867) — decided enforce over
    # retire and backed with a resolving check (ADR-0003, an earlier exemplar,
    # is now Superseded by ADR-0112 — clone-local isolation, #10623). The
    # corpus now carries zero MISSING debt; this pins that outcome so a future
    # ADR landing without any Enforced-by declaration regresses here instead
    # of silently drifting back into debt.
    live = _live()
    missing = sorted(
        number
        for number, adr in live.items()
        if classify_adr_enforcement(adr, REPO) is EnforcementClass.MISSING
    )
    assert not missing, f"Accepted ADRs classifying MISSING (should be none): {missing}"


def test_exemplar_manual_is_weak():
    # ADR-0051 (iterative production-readiness review) is genuinely process-only:
    # manual with a prose workflow pointer, not a runnable check. (ADR-0042, the
    # former exemplar, now carries a real asserting ruleset check — #10623.)
    assert classify_adr_enforcement(_live()[51], REPO) is EnforcementClass.WEAK


# --------------------------------------------------------------------------
# check_is_unattributed / adr_is_unattributed — the relatedness signal (#10861)
# REAL only means "names a file that exists"; attribution asks whether that file
# names the ADR. Advisory, mirroring check_is_tautological: never folded into
# REAL (see test_attribution_never_moves_classification below).
# --------------------------------------------------------------------------


def test_resolving_pytest_that_never_mentions_the_adr_is_unattributed(tmp_path: Path):
    _write(tmp_path, "tests/t.py", "def test_x():\n    assert True\n")
    check = _pytest("tests/t.py::test_x")
    assert check_is_unattributed(check, 116, tmp_path)


def test_explicit_and_bare_and_path_forms_each_attribute(tmp_path: Path):
    check = _pytest("tests/t.py::test_x")
    for body in (
        '"""Enforces ADR-0116."""\ndef test_x():\n    assert True\n',
        '"""See ADR 116 for why."""\ndef test_x():\n    assert True\n',
        '"""Guards ADR-116."""\ndef test_x():\n    assert True\n',
        "# ratchet for 0116\ndef test_x():\n    assert True\n",
        "# see docs/adr/0116-prompts.md\ndef test_x():\n    assert True\n",
    ):
        _write(tmp_path, "tests/t.py", body)
        assert not check_is_unattributed(check, 116, tmp_path), body


def test_substring_number_does_not_attribute(tmp_path: Path):
    # 10116 contains "0116" but must NOT attribute ADR-0116 (no word boundary),
    # nor must ADR-1163 attribute ADR-116.
    _write(
        tmp_path,
        "tests/t.py",
        "# unrelated ids 10116 and ADR-1163\ndef test_x():\n    assert True\n",
    )
    assert check_is_unattributed(_pytest("tests/t.py::test_x"), 116, tmp_path)


def test_make_and_unresolvable_checks_are_never_unattributed(tmp_path: Path):
    make = Check(kind="make", target="trust-contracts", raw="make:trust-contracts")
    prose = Check(kind="prose", target="review checklist", raw="review checklist")
    assert not check_is_unattributed(make, 116, tmp_path)
    assert not check_is_unattributed(prose, 116, tmp_path)
    # a pytest target whose file is missing is unresolvable -> never reported
    assert not check_is_unattributed(_pytest("tests/missing.py::test_x"), 116, tmp_path)


def test_adr_pointing_at_an_unrelated_but_real_file_is_unattributed(tmp_path: Path):
    # The exact #10861 shape: a resolving check that does not relate to the ADR.
    _write(tmp_path, "tests/test_prompt_fitness.py", "def test_x():\n    assert True\n")
    adr = _adr(130, "enforced", (_pytest("tests/test_prompt_fitness.py::test_x"),))
    assert has_real_enforcement(adr, tmp_path)  # still REAL — classification unmoved
    assert adr_is_unattributed(adr, tmp_path)


def test_adr_pointing_at_a_file_that_names_it_is_attributed(tmp_path: Path):
    _write(
        tmp_path,
        "tests/t.py",
        '"""Enforces ADR-0130."""\ndef test_x():\n    assert True\n',
    )
    adr = _adr(130, "enforced", (_pytest("tests/t.py::test_x"),))
    assert has_real_enforcement(adr, tmp_path)
    assert not adr_is_unattributed(adr, tmp_path)


def test_adr_attributed_if_any_sibling_check_names_it(tmp_path: Path):
    # Two resolving pytest checks; only one names the ADR. That is enough.
    _write(tmp_path, "tests/a.py", "def test_x():\n    assert True\n")
    _write(tmp_path, "tests/b.py", '"""ADR-0130."""\ndef test_y():\n    assert True\n')
    adr = _adr(
        130,
        "enforced",
        (_pytest("tests/a.py::test_x"), _pytest("tests/b.py::test_y")),
    )
    assert not adr_is_unattributed(adr, tmp_path)


def test_attribution_never_moves_classification(tmp_path: Path):
    # The load-bearing invariant of the whole fix: an unattributed ADR is still
    # REAL. Attribution is advisory and must not touch classify/has_real.
    _write(tmp_path, "tests/t.py", "def test_x():\n    assert True\n")
    adr = _adr(130, "enforced", (_pytest("tests/t.py::test_x"),))
    assert adr_is_unattributed(adr, tmp_path)
    assert classify_adr_enforcement(adr, tmp_path) is EnforcementClass.REAL
    assert has_real_enforcement(adr, tmp_path)
