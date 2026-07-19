"""Unit tests for the suppression-count detector."""

from __future__ import annotations

from pathlib import Path

from disturbance.detectors.suppressions import SuppressionsDetector


def _write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def test_detects_type_ignore_and_noqa_with_codes(tmp_path: Path) -> None:
    _write(
        tmp_path, "src/a.py", "x = 1  # type: ignore[assignment]\ny = 2  # noqa: E501\n"
    )
    findings = SuppressionsDetector().detect(tmp_path)
    sigs = sorted(f.signature for f in findings)
    assert sigs == ["src/a.py::noqa:E501", "src/a.py::type-ignore[assignment]"]
    assert all(f.dimension == "suppressions" for f in findings)


def test_counts_multiple_same_code_in_file(tmp_path: Path) -> None:
    _write(tmp_path, "src/a.py", "a = 1  # type: ignore\nb = 2  # type: ignore\n")
    findings = SuppressionsDetector().detect(tmp_path)
    assert [f.signature for f in findings] == [
        "src/a.py::type-ignore",
        "src/a.py::type-ignore",
    ]


def test_signature_is_line_number_independent(tmp_path: Path) -> None:
    _write(tmp_path, "src/a.py", "a = 1  # noqa\n")
    before = SuppressionsDetector().detect(tmp_path)[0].signature
    _write(tmp_path, "src/a.py", "\n\n\na = 1  # noqa\n")  # shifted down 3 lines
    after = SuppressionsDetector().detect(tmp_path)[0].signature
    assert before == after == "src/a.py::noqa"


def test_clean_file_yields_nothing(tmp_path: Path) -> None:
    _write(tmp_path, "src/a.py", "x = 1\n")
    assert SuppressionsDetector().detect(tmp_path) == []


def test_ignores_suppression_inside_string_literal(tmp_path: Path) -> None:
    _write(tmp_path, "src/a.py", 'x = "# type: ignore[foo]"\ny = 1  # noqa: E501\n')
    findings = SuppressionsDetector().detect(tmp_path)
    # Only the real trailing comment counts; the string literal is ignored.
    assert [f.signature for f in findings] == ["src/a.py::noqa:E501"]


def test_multi_code_noqa_keeps_all_codes(tmp_path: Path) -> None:
    _write(tmp_path, "src/a.py", "x = call()  # noqa: S603, S607\n")
    findings = SuppressionsDetector().detect(tmp_path)
    assert [f.signature for f in findings] == ["src/a.py::noqa:S603,S607"]
