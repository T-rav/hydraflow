"""Unit tests for the pure regression-rot scan/classify engine (#9597).

Covers filename -> issue-number parsing, xfail-RED marker detection, the
blocked-on exemption annotation, and the classification matrix (closed+red,
open+stale, open+fresh -> none) that P10.6 requires as a regression test.
"""

from __future__ import annotations

from pathlib import Path

from regression_rot_scan import (
    RegressionRotFile,
    RegressionRotFinding,
    build_rollup_body,
    classify_regression_rot,
    parse_issue_numbers,
    scan_regression_dir,
)


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


HELD_BACK_BODY = (
    "import pytest\n\n"
    "@pytest.mark.xfail(reason='Regression for issue #9836 — fix not yet "
    "landed', strict=False)\n"
    "def test_thing():\n"
    "    assert False\n"
)

HELD_BACK_MULTILINE_BODY = (
    "import pytest\n\n"
    "@pytest.mark.xfail(\n"
    "    reason='Regression for issue #6408 — fix not yet landed', "
    "strict=False\n"
    ")\n"
    "def test_thing():\n"
    "    assert False\n"
)

GREEN_BODY = "def test_thing():\n    assert True\n"

BLOCKED_BODY = "# hydraflow-regression-rot: blocked-on #9080\n" + HELD_BACK_BODY


class TestParseIssueNumbers:
    def test_single_test_prefix(self) -> None:
        assert parse_issue_numbers("test_issue_9836") == [9836]

    def test_multi_number_slug(self) -> None:
        assert parse_issue_numbers("test_issue_9419_9421_adr_drift") == [
            9419,
            9421,
        ]

    def test_legacy_regression_prefix(self) -> None:
        assert parse_issue_numbers("regression_issue_6709") == [6709]

    def test_descriptive_name_yields_empty(self) -> None:
        assert parse_issue_numbers("test_async_subprocess_timeouts") == []

    def test_slug_suffix_after_number(self) -> None:
        assert parse_issue_numbers("test_issue_9351_ci_sentinel_contract") == [9351]


class TestScanRegressionDir:
    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        assert scan_regression_dir(tmp_path / "nope") == []

    def test_held_back_marker_detected(self, tmp_path: Path) -> None:
        _write(tmp_path, "test_issue_9836.py", HELD_BACK_BODY)
        files = scan_regression_dir(tmp_path)
        assert len(files) == 1
        assert files[0].issue_numbers == (9836,)
        assert files[0].is_xfail_red is True
        assert files[0].blocked_on is None

    def test_multiline_xfail_marker_detected(self, tmp_path: Path) -> None:
        _write(tmp_path, "regression_issue_6408.py", HELD_BACK_MULTILINE_BODY)
        files = scan_regression_dir(tmp_path)
        assert files[0].is_xfail_red is True

    def test_green_test_is_not_held_back(self, tmp_path: Path) -> None:
        _write(tmp_path, "test_issue_1234.py", GREEN_BODY)
        files = scan_regression_dir(tmp_path)
        assert files[0].is_xfail_red is False

    def test_blocked_annotation_parsed(self, tmp_path: Path) -> None:
        _write(tmp_path, "test_issue_9415.py", BLOCKED_BODY)
        files = scan_regression_dir(tmp_path)
        assert files[0].blocked_on == 9080

    def test_pycache_and_init_skipped(self, tmp_path: Path) -> None:
        _write(tmp_path, "__init__.py", "")
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        (pycache / "test_issue_1.cpython-311.pyc").write_text("junk")
        files = scan_regression_dir(tmp_path)
        assert files == []

    def test_descriptive_file_has_no_issue_numbers(self, tmp_path: Path) -> None:
        _write(tmp_path, "test_async_subprocess_timeouts.py", GREEN_BODY)
        files = scan_regression_dir(tmp_path)
        assert files[0].issue_numbers == ()


def _file(
    issue_numbers: tuple[int, ...],
    *,
    is_xfail_red: bool = True,
    blocked_on: int | None = None,
    name: str = "test_issue_1.py",
) -> RegressionRotFile:
    return RegressionRotFile(
        path=Path(name),
        issue_numbers=issue_numbers,
        is_xfail_red=is_xfail_red,
        blocked_on=blocked_on,
    )


class TestClassifyRegressionRot:
    def test_closed_and_red_is_false_close_rot(self) -> None:
        files = [_file((100,))]
        findings = classify_regression_rot(
            files,
            issue_states={100: "COMPLETED"},
            ages_days={},
            stale_days=14,
        )
        assert len(findings) == 1
        assert findings[0].issue_number == 100
        assert findings[0].kind == "false_close"

    def test_not_planned_close_is_also_false_close_rot(self) -> None:
        files = [_file((101,))]
        findings = classify_regression_rot(
            files,
            issue_states={101: "NOT_PLANNED"},
            ages_days={},
            stale_days=14,
        )
        assert findings[0].kind == "false_close"

    def test_open_and_stale_is_orphaned_red(self) -> None:
        files = [_file((200,))]
        findings = classify_regression_rot(
            files,
            issue_states={200: "OPEN"},
            ages_days={200: 30},
            stale_days=14,
        )
        assert len(findings) == 1
        assert findings[0].issue_number == 200
        assert findings[0].kind == "orphaned_red"

    def test_open_and_fresh_yields_no_finding(self) -> None:
        files = [_file((300,))]
        findings = classify_regression_rot(
            files,
            issue_states={300: "OPEN"},
            ages_days={300: 2},
            stale_days=14,
        )
        assert findings == []

    def test_open_exactly_at_threshold_is_not_yet_orphaned(self) -> None:
        files = [_file((301,))]
        findings = classify_regression_rot(
            files,
            issue_states={301: "OPEN"},
            ages_days={301: 14},
            stale_days=14,
        )
        assert findings == []

    def test_green_file_never_classified(self) -> None:
        files = [_file((400,), is_xfail_red=False)]
        findings = classify_regression_rot(
            files,
            issue_states={400: "COMPLETED"},
            ages_days={},
            stale_days=14,
        )
        assert findings == []

    def test_blocked_annotation_exempts_even_when_open_and_stale(self) -> None:
        files = [_file((500,), blocked_on=9080)]
        findings = classify_regression_rot(
            files,
            issue_states={500: "OPEN"},
            ages_days={500: 999},
            stale_days=14,
        )
        assert findings == []

    def test_blocked_annotation_exempts_false_close_too(self) -> None:
        files = [_file((501,), blocked_on=9080)]
        findings = classify_regression_rot(
            files,
            issue_states={501: "COMPLETED"},
            ages_days={},
            stale_days=14,
        )
        assert findings == []

    def test_unknown_state_yields_no_finding(self) -> None:
        files = [_file((600,))]
        findings = classify_regression_rot(
            files,
            issue_states={600: "UNKNOWN"},
            ages_days={},
            stale_days=14,
        )
        assert findings == []

    def test_no_issue_numbers_never_classified(self) -> None:
        files = [_file(())]
        findings = classify_regression_rot(
            files,
            issue_states={},
            ages_days={},
            stale_days=14,
        )
        assert findings == []

    def test_multiple_files_same_issue_are_grouped(self) -> None:
        files = [
            _file((700,), name="test_issue_700_a.py"),
            _file((700,), name="test_issue_700_b.py"),
        ]
        findings = classify_regression_rot(
            files,
            issue_states={700: "COMPLETED"},
            ages_days={},
            stale_days=14,
        )
        assert len(findings) == 1
        assert set(findings[0].paths) == {"test_issue_700_a.py", "test_issue_700_b.py"}


class TestBuildRollupBody:
    def test_empty_findings_says_none_currently_both_sections(self) -> None:
        body = build_rollup_body([])
        assert body.count("None currently.") == 2

    def test_false_close_finding_listed_under_its_section(self) -> None:
        finding = RegressionRotFinding(
            issue_number=100, kind="false_close", paths=("tests/regressions/a.py",)
        )
        body = build_rollup_body([finding])
        false_close_section, _, orphaned_section = body.partition("## Orphaned-RED")
        assert "#100" in false_close_section
        assert "#100" not in orphaned_section

    def test_orphaned_finding_listed_under_its_section(self) -> None:
        finding = RegressionRotFinding(
            issue_number=200, kind="orphaned_red", paths=("tests/regressions/b.py",)
        )
        body = build_rollup_body([finding])
        false_close_section, _, orphaned_section = body.partition("## Orphaned-RED")
        assert "#200" not in false_close_section
        assert "#200" in orphaned_section

    def test_ordering_is_deterministic_by_issue_number(self) -> None:
        findings = [
            RegressionRotFinding(issue_number=300, kind="false_close", paths=("c.py",)),
            RegressionRotFinding(issue_number=100, kind="false_close", paths=("a.py",)),
        ]
        body = build_rollup_body(findings)
        assert body.index("#100") < body.index("#300")
