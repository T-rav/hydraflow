# tests/test_adr_index_conformance_parse.py
from pathlib import Path

from adr_index import Check, parse_adr_file, parse_enforced_by


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "0099-x.md"
    p.write_text(body)
    return p


def test_parses_enforced_kind_and_typed_checks(tmp_path):
    adr = parse_adr_file(
        _write(
            tmp_path,
            (
                "# ADR-0099: X\n\n**Status:** Accepted\n"
                "**Enforcement:** enforced\n"
                "**Enforced by:** pytest:tests/test_x.py::test_y\n"
                "make:arch-check\n\n## Context\n\nc\n"
            ),
        )
    )
    assert adr.enforcement == "enforced"
    assert adr.enforced_by == (
        Check(
            kind="pytest",
            target="tests/test_x.py::test_y",
            raw="pytest:tests/test_x.py::test_y",
        ),
        Check(kind="make", target="arch-check", raw="make:arch-check"),
    )


def test_decision_of_record_has_no_checks(tmp_path):
    adr = parse_adr_file(
        _write(
            tmp_path,
            (
                "# ADR-0099: X\n\n**Status:** Accepted\n"
                "**Enforcement:** decision-of-record\n\n## Context\n\nc\n"
            ),
        )
    )
    assert adr.enforcement == "decision-of-record"
    assert adr.enforced_by == ()


def test_missing_enforcement_normalizes_to_unknown(tmp_path):
    adr = parse_adr_file(
        _write(tmp_path, "# ADR-0099: X\n\n**Status:** Accepted\n\n## Context\n\nc\n")
    )
    assert adr.enforcement == "unknown"


def test_enforced_by_stops_at_next_bullet_not_just_blank_line(tmp_path):
    """Regression: **Enforced by:** followed immediately (no blank line) by
    a sibling frontmatter bullet like `- **Spec:**` must NOT swallow that
    bullet into the Enforced-by capture. Real ADR frontmatter is often a
    single bullet list with no blank lines between fields:

        - **Enforced by:** pytest:tests/x.py::t
        - **Spec:** foo

    Before the fix, the greedy capture ran until the next blank line or
    `**Field:**`/`##` heading — but `- **Spec:**` is a bullet, not a
    top-level `**Field:**` line, so it wasn't recognized as a stop point
    and got absorbed into the Enforced-by block.
    """
    adr = parse_adr_file(
        _write(
            tmp_path,
            (
                "# ADR-0099: X\n\n**Status:** Accepted\n"
                "**Enforcement:** enforced\n"
                "- **Enforced by:** pytest:tests/x.py::t\n"
                "- **Spec:** foo\n\n## Context\n\nc\n"
            ),
        )
    )
    assert adr.enforced_by == (
        Check(kind="pytest", target="tests/x.py::t", raw="pytest:tests/x.py::t"),
    )


def test_manual_prose_is_one_check_per_line_not_comma_split():
    # commas inside manual prose must NOT fragment
    checks = parse_enforced_by("branch protection review, per PR checklist\n")
    assert len(checks) == 1
    assert checks[0].kind == "make" or checks[0].raw.startswith("branch")
    # prose (no recognized prefix) -> single raw entry, target == raw, kind sentinel
    assert checks[0].raw == "branch protection review, per PR checklist"
