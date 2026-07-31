"""Regression for #10940: the ADR Check grammar recognizes a typed ``script:`` kind.

Before this, ``parse_enforced_by`` typed only ``pytest:`` and ``make:`` lines;
every other line — including ``script:scripts/foo.py`` — became a ``prose``
check, so ``classify_adr_enforcement`` scored an ADR enforced by an executable
repo script as WEAK. Now ``script:`` parses to a typed check and
``resolve_check`` resolves it iff the script file exists.
"""

from __future__ import annotations

from pathlib import Path

from adr_conformance import resolve_check
from adr_index import parse_enforced_by


def test_script_line_parses_as_typed_check() -> None:
    (check,) = parse_enforced_by("script:scripts/audit_prompts.py")
    assert check.kind == "script"
    assert check.target == "scripts/audit_prompts.py"


def test_script_check_resolves_when_file_exists(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "audit_prompts.py").write_text("# a real script\n")

    (check,) = parse_enforced_by("script:scripts/audit_prompts.py")

    assert resolve_check(check, tmp_path) is True


def test_script_check_unresolved_when_file_missing(tmp_path: Path) -> None:
    (check,) = parse_enforced_by("script:scripts/does_not_exist.py")

    assert resolve_check(check, tmp_path) is False
