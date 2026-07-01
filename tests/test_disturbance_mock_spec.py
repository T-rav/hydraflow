"""Unit tests for the mock-spec detector adapter."""

from __future__ import annotations

from pathlib import Path

from disturbance.detectors.mock_spec import MockSpecDetector


def test_adapts_mock_without_spec_to_finding(tmp_path: Path) -> None:
    t = tmp_path / "tests"
    t.mkdir()
    # A Port-typed var assigned a bare AsyncMock() -> a mock-spec violation.
    (t / "test_thing.py").write_text(
        "from unittest.mock import AsyncMock\n"
        "from some_module import PRPort\n"
        "def test_x():\n"
        "    client: PRPort = AsyncMock()\n",
        encoding="utf-8",
    )
    findings = MockSpecDetector(globs=("tests/**/test_*.py",)).detect(tmp_path)
    assert findings, "expected at least one mock-spec finding"
    assert all(f.dimension == "mock_spec" for f in findings)
    assert all(f.signature == "tests/test_thing.py::mock_spec" for f in findings)


def test_skips_synthetic_fixture_dirs(tmp_path: Path) -> None:
    fx = tmp_path / "tests" / "_mock_spec_fixtures"
    fx.mkdir(parents=True)
    (fx / "test_bad.py").write_text(
        "from unittest.mock import AsyncMock\n"
        "from some_module import PRPort\n"
        "def test_x():\n"
        "    client: PRPort = AsyncMock()\n",
        encoding="utf-8",
    )
    assert MockSpecDetector(globs=("tests/**/test_*.py",)).detect(tmp_path) == []
