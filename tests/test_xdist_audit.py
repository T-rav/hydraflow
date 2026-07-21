"""Tests for the xdist-isolation audit (scripts/xdist_audit.py)."""

from __future__ import annotations

from pathlib import Path

from scripts.xdist_audit import (
    build_report,
    classify_xdist_unsafe,
    failed_ids,
    parse_outcomes,
    render_summary,
    run_audit,
)


def _junit(cases: dict[str, bool]) -> bytes:
    """Build a JUnit XML doc; ``cases`` maps test_id → failed?."""
    parts = ["<testsuite>"]
    for test_id, failed in cases.items():
        cls, _, name = test_id.rpartition(".")
        body = "<failure message='boom'/>" if failed else ""
        parts.append(f'<testcase classname="{cls}" name="{name}">{body}</testcase>')
    parts.append("</testsuite>")
    return "".join(parts).encode()


def test_parse_outcomes_maps_pass_and_fail() -> None:
    outcomes = parse_outcomes(_junit({"m.test_a": False, "m.test_b": True}))
    assert outcomes == {"m.test_a": "pass", "m.test_b": "fail"}


def test_parse_outcomes_sticky_fail_across_reruns() -> None:
    # A rerun plugin can emit the same id twice; once failed, stays failed.
    xml = (
        b"<testsuite>"
        b'<testcase classname="m" name="test_x"><failure message="x"/></testcase>'
        b'<testcase classname="m" name="test_x"></testcase>'
        b"</testsuite>"
    )
    assert parse_outcomes(xml)["m.test_x"] == "fail"


def test_failed_ids_sorted() -> None:
    outcomes = {"m.b": "fail", "m.a": "fail", "m.c": "pass"}
    assert failed_ids(outcomes) == ["m.a", "m.b"]


def test_classify_flags_fail_parallel_pass_serial() -> None:
    parallel = {"m.leaky": "fail", "m.ok": "pass", "m.broken": "fail"}
    serial = {"m.leaky": "pass", "m.broken": "fail"}
    # leaky: fail-parallel + pass-serial → xdist-unsafe.
    # broken: fail in both → a real bug, NOT xdist-unsafe.
    assert classify_xdist_unsafe(parallel, serial) == ["m.leaky"]


def test_classify_requires_serial_pass_evidence() -> None:
    # A parallel failure with no serial verdict is NOT classified.
    parallel = {"m.leaky": "fail"}
    assert classify_xdist_unsafe(parallel, serial={}) == []


def test_classify_empty_when_no_parallel_failures() -> None:
    assert classify_xdist_unsafe({"m.a": "pass"}, {"m.a": "pass"}) == []


def test_build_report_shape() -> None:
    report = build_report({"m.leaky": "fail", "m.ok": "pass"}, {"m.leaky": "pass"})
    assert report["xdist_unsafe"] == ["m.leaky"]
    assert report["parallel_failures"] == ["m.leaky"]
    assert report["counts"] == {
        "parallel_total": 2,
        "parallel_failures": 1,
        "xdist_unsafe": 1,
    }


def test_render_summary_clean() -> None:
    report = build_report({"m.a": "pass"}, {})
    summary = render_summary(report)
    assert "No xdist-unsafe tests found" in summary


def test_render_summary_lists_unsafe() -> None:
    report = build_report({"m.leaky": "fail"}, {"m.leaky": "pass"})
    summary = render_summary(report)
    assert "`m.leaky`" in summary
    assert "PYTEST_SERIAL_PATHS" in summary


def test_run_audit_orchestrates_two_phases(monkeypatch, tmp_path: Path) -> None:
    """run_audit runs parallel, then serial-rechecks only the failures."""
    calls: list[list[str]] = []

    def fake_run(args: list[str]) -> None:
        calls.append(args)
        # Locate the --junitxml path and write a fixture for that phase.
        junit = Path(
            next(a.split("=", 1)[1] for a in args if a.startswith("--junitxml="))
        )
        if "-n" in args:  # parallel phase: two fail, one pass
            junit.write_bytes(
                _junit({"m.leaky": True, "m.broken": True, "m.ok": False})
            )
        else:  # serial recheck of the two failures: leaky recovers, broken stays
            junit.write_bytes(_junit({"m.leaky": False, "m.broken": True}))

    monkeypatch.setattr("scripts.xdist_audit._run_pytest", fake_run)
    report = run_audit("tests/", ["tests/regressions"], tmp_path)

    assert report["xdist_unsafe"] == ["m.leaky"]
    assert report["parallel_failures"] == ["m.broken", "m.leaky"]
    # Serial recheck targeted exactly the parallel failures.
    serial_call = calls[1]
    assert "m.leaky" in serial_call and "m.broken" in serial_call
    assert "no:xdist" in serial_call


def test_run_audit_skips_serial_when_no_failures(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str]) -> None:
        calls.append(args)
        junit = Path(
            next(a.split("=", 1)[1] for a in args if a.startswith("--junitxml="))
        )
        junit.write_bytes(_junit({"m.ok": False}))

    monkeypatch.setattr("scripts.xdist_audit._run_pytest", fake_run)
    report = run_audit("tests/", [], tmp_path)

    assert report["xdist_unsafe"] == []
    assert len(calls) == 1  # no serial recheck phase
